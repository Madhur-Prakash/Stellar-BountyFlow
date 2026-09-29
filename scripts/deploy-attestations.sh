#!/usr/bin/env bash
# Build and deploy the BountyFlow attestations Soroban contract to Stellar Testnet.
# Mirrors scripts/deploy-attestations.ps1.
#
# Usage:
#   scripts/deploy-attestations.sh   # build + deploy + write contracts/deployments/attestations-testnet.json
#
# The attester key lives only in the root .env (STELLAR_ATTESTER_SECRET). When it is missing, a new keypair is
# generated into .env and funded with Friendbot. ATTESTATION_CONTRACT_ID is written to .env after the deploy.
#
# Environment overrides:
#   STELLAR_SOURCE_ACCOUNT   deployer identity name   (default: bountyflow-deployer)
#   STELLAR_NETWORK          network name             (default: testnet)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONTRACTS_DIR="$ROOT_DIR/contracts"
BACKEND_DIR="$ROOT_DIR/backend"
DEPLOY_DIR="$CONTRACTS_DIR/deployments"
ENV_FILE="$ROOT_DIR/.env"
WASM="$CONTRACTS_DIR/target/wasm32v1-none/release/attestations.wasm"

NETWORK="${STELLAR_NETWORK:-testnet}"
SOURCE="${STELLAR_SOURCE_ACCOUNT:-bountyflow-deployer}"
OUT_JSON="$DEPLOY_DIR/attestations-$NETWORK.json"

# BountyFlow's own STELLAR_NETWORK_PASSPHRASE (from a sourced .env) would make the CLI ignore --network.
unset STELLAR_NETWORK_PASSPHRASE STELLAR_RPC_URL

log() { printf '==> %s\n' "$*" >&2; }
strip_cr() { tr -d '\r'; }

command -v stellar >/dev/null 2>&1 || { echo "stellar CLI not found in PATH" >&2; exit 1; }
command -v uv >/dev/null 2>&1 || { echo "uv not found in PATH (used to derive the attester address)" >&2; exit 1; }

STDERR_LOG="$(mktemp)"
trap 'rm -f "$STDERR_LOG"' EXIT

# Run a stellar command from contracts/ (the CLI also reads a .env in its working directory), retrying once on
# failure. Its stderr is mirrored to ours and kept in $STDERR_LOG; its stdout is returned.
run_logged() {
  local out
  if ! out="$(cd "$CONTRACTS_DIR" && "$@" 2>"$STDERR_LOG")"; then
    cat "$STDERR_LOG" >&2
    log "command failed, retrying once in 5s: $*"
    sleep 5
    if ! out="$(cd "$CONTRACTS_DIR" && "$@" 2>"$STDERR_LOG")"; then
      cat "$STDERR_LOG" >&2
      return 1
    fi
  fi
  cat "$STDERR_LOG" >&2
  printf '%s\n' "$out"
}

tx_hash_from() {
  { grep -oiE 'tx/[0-9a-f]{64}|transaction hash is [0-9a-f]{64}' "$1" || true; } \
    | { grep -oiE '[0-9a-f]{64}' || true; } | head -n1
}

read_env() { [ -f "$ENV_FILE" ] && { grep -E "^$1=" "$ENV_FILE" | head -n1 | cut -d= -f2- | strip_cr; } || true; }

write_env() {
  local key="$1" value="$2" tmp
  tmp="$(mktemp)"
  if [ -f "$ENV_FILE" ] && grep -qE "^$key=" "$ENV_FILE"; then
    awk -v k="$key" -v v="$value" 'BEGIN { FS = OFS = "=" } $1 == k { print k "=" v; next } { print }' "$ENV_FILE" >"$tmp"
  else
    { [ -f "$ENV_FILE" ] && cat "$ENV_FILE"; printf '%s=%s\n' "$key" "$value"; } >"$tmp"
  fi
  mv "$tmp" "$ENV_FILE"
}

py() { (cd "$BACKEND_DIR" && uv run --quiet python -c "$1"); }

# 1. Build ------------------------------------------------------------------
log "building contract wasm (stellar contract build --package attestations, optimized)"
(cd "$CONTRACTS_DIR" && stellar contract build --package attestations)
[ -f "$WASM" ] || { echo "wasm not found at $WASM" >&2; exit 1; }

# 2. Deployer ----------------------------------------------------------------
if stellar keys address "$SOURCE" >/dev/null 2>&1; then
  stellar keys fund "$SOURCE" --network "$NETWORK" >/dev/null 2>&1 || true
else
  log "generating + funding identity '$SOURCE' on $NETWORK"
  run_logged stellar keys generate "$SOURCE" --network "$NETWORK" --fund >/dev/null
fi
DEPLOYER_ADDRESS="$(stellar keys address "$SOURCE" | strip_cr)"
log "deployer: $DEPLOYER_ADDRESS"

# 3. Attester (secret stays in .env) ------------------------------------------
ATTESTER_SECRET="$(read_env STELLAR_ATTESTER_SECRET)"
if [ -z "$ATTESTER_SECRET" ]; then
  log "STELLAR_ATTESTER_SECRET is not set: generating an attester keypair into .env"
  ATTESTER_SECRET="$(py 'from stellar_sdk import Keypair; print(Keypair.random().secret)' | strip_cr)"
  write_env STELLAR_ATTESTER_SECRET "$ATTESTER_SECRET"
fi
# The secret goes through stdin, never on a command line.
ATTESTER_ADDRESS="$(printf '%s' "$ATTESTER_SECRET" \
  | py 'import sys; from stellar_sdk import Keypair; print(Keypair.from_secret(sys.stdin.read().strip()).public_key)' \
  | strip_cr)"
case "$ATTESTER_ADDRESS" in G*) ;; *) echo "STELLAR_ATTESTER_SECRET in .env is not a valid Stellar secret key" >&2; exit 1 ;; esac
log "attester: $ATTESTER_ADDRESS"
if [ "$NETWORK" = "testnet" ]; then
  curl -fsS -m 60 "https://friendbot.stellar.org/?addr=$ATTESTER_ADDRESS" >/dev/null 2>&1 \
    && log "attester funded with Friendbot" || log "attester already funded (or Friendbot unavailable)"
fi

# 4. Upload + deploy ---------------------------------------------------------
log "uploading wasm"
WASM_HASH="$(run_logged stellar contract upload --wasm "$WASM" --source-account "$SOURCE" --network "$NETWORK" | tail -n1 | strip_cr)"
UPLOAD_TX="$(tx_hash_from "$STDERR_LOG")"
log "wasm hash: $WASM_HASH"

log "deploying contract (constructor: attester)"
CONTRACT_ID="$(run_logged stellar contract deploy --wasm-hash "$WASM_HASH" --source-account "$SOURCE" \
  --network "$NETWORK" --alias attestations -- --attester "$ATTESTER_ADDRESS" | tail -n1 | strip_cr)"
DEPLOY_TX="$(tx_hash_from "$STDERR_LOG")"
case "$CONTRACT_ID" in C*) ;; *) echo "unexpected deploy output: $CONTRACT_ID" >&2; exit 1 ;; esac
log "contract id: $CONTRACT_ID (deploy tx: $DEPLOY_TX)"

# 5. Sanity check -----------------------------------------------------------
view() {
  run_logged stellar contract invoke --id "$CONTRACT_ID" --source-account "$SOURCE" --network "$NETWORK" \
    --send no -- "$1" | tail -n1 | strip_cr | tr -d '"'
}
VERSION="$(view version)"
ONCHAIN_ATTESTER="$(view attester)"
TOTAL="$(view total)"
log "on-chain version(): $VERSION, attester(): $ONCHAIN_ATTESTER, total(): $TOTAL"
[ "$ONCHAIN_ATTESTER" = "$ATTESTER_ADDRESS" ] || { echo "attester() does not match the configured attester" >&2; exit 1; }

# 6. Record ------------------------------------------------------------------
write_env ATTESTATION_CONTRACT_ID "$CONTRACT_ID"
mkdir -p "$DEPLOY_DIR"
if [ -n "$UPLOAD_TX" ]; then UPLOAD_JSON="\"$UPLOAD_TX\""; else UPLOAD_JSON="null"; fi
cat >"$OUT_JSON" <<JSON
{
  "network": "$NETWORK",
  "contract_id": "$CONTRACT_ID",
  "attester_address": "$ATTESTER_ADDRESS",
  "wasm_hash": "$WASM_HASH",
  "upload_tx": $UPLOAD_JSON,
  "deploy_tx": "$DEPLOY_TX",
  "deployed_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "deployer_address": "$DEPLOYER_ADDRESS",
  "contract_version": $VERSION,
  "explorer_url": "https://stellar.expert/explorer/$NETWORK/contract/$CONTRACT_ID",
  "smoke_test": { "version": $VERSION, "attester": "$ONCHAIN_ATTESTER", "total": $TOTAL }
}
JSON
log "wrote $OUT_JSON"
cat "$OUT_JSON"
