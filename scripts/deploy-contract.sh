#!/usr/bin/env bash
# Build and deploy the BountyFlow bounty_escrow Soroban contract to Stellar Testnet.
#
# Usage:
#   scripts/deploy-contract.sh                    # build + deploy + write contracts/deployments/testnet.json
#   RUN_SMOKE_TEST=1 scripts/deploy-contract.sh   # also run a create_escrow -> get_escrow -> release smoke flow
#
# Environment overrides:
#   STELLAR_SOURCE_ACCOUNT   deployer identity name   (default: bountyflow-deployer)
#   ARBITER_IDENTITY         arbiter identity name    (default: bountyflow-arbiter)
#   SMOKE_REQUESTER          smoke-test requester     (default: bountyflow-smoke-requester)
#   STELLAR_NETWORK          network name             (default: testnet)
#   RUN_SMOKE_TEST           1 to run the smoke flow  (default: 0)
#
# Secrets never leave the local Stellar CLI key store (~/.config/stellar/identity);
# only public data (addresses, ids, hashes) is written to the repo.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONTRACTS_DIR="$ROOT_DIR/contracts"
DEPLOY_DIR="$CONTRACTS_DIR/deployments"
WASM_REL="target/wasm32v1-none/release/bounty_escrow.wasm"

NETWORK="${STELLAR_NETWORK:-testnet}"
SOURCE="${STELLAR_SOURCE_ACCOUNT:-bountyflow-deployer}"
ARBITER="${ARBITER_IDENTITY:-bountyflow-arbiter}"
REQUESTER="${SMOKE_REQUESTER:-bountyflow-smoke-requester}"
RUN_SMOKE_TEST="${RUN_SMOKE_TEST:-0}"
OUT_JSON="$DEPLOY_DIR/$NETWORK.json"

json_str_or_null() { if [ -n "$1" ]; then printf '"%s"' "$1"; else printf 'null'; fi; }
log() { printf '==> %s\n' "$*" >&2; }
strip_cr() { tr -d '\r'; }

command -v stellar >/dev/null 2>&1 || { echo "stellar CLI not found in PATH" >&2; exit 1; }

STDERR_LOG="$(mktemp)"
trap 'rm -f "$STDERR_LOG"' EXIT

# Run a stellar command, retrying once on failure (friendbot / RPC hiccups).
# Its stderr is mirrored to ours and kept in $STDERR_LOG (for tx hash
# extraction); its stdout is returned.
run_logged() {
  local out
  if ! out="$("$@" 2>"$STDERR_LOG")"; then
    cat "$STDERR_LOG" >&2
    log "command failed, retrying once in 5s: $*"
    sleep 5
    if ! out="$("$@" 2>"$STDERR_LOG")"; then
      cat "$STDERR_LOG" >&2
      return 1
    fi
  fi
  cat "$STDERR_LOG" >&2
  printf '%s\n' "$out"
}

# Extract the first 64-hex transaction hash from CLI log output.
tx_hash_from() {
  { grep -oiE 'tx/[0-9a-f]{64}|transaction hash is [0-9a-f]{64}' "$1" || true; } \
    | { grep -oiE '[0-9a-f]{64}' || true; } | head -n1
}

ensure_identity() {
  local name="$1"
  if stellar keys address "$name" >/dev/null 2>&1; then
    log "identity '$name' exists: $(stellar keys address "$name" | strip_cr)"
    # Top up / create on-ledger account if needed; failure (already funded) is fine.
    stellar keys fund "$name" --network "$NETWORK" >/dev/null 2>&1 || true
  else
    log "generating + funding identity '$name' on $NETWORK"
    run_logged stellar keys generate "$name" --network "$NETWORK" --fund >/dev/null
  fi
}

# 1. Build ------------------------------------------------------------------
log "building contract wasm (stellar contract build, optimized)"
(cd "$CONTRACTS_DIR" && stellar contract build --package bounty_escrow)
WASM="$CONTRACTS_DIR/$WASM_REL"
[ -f "$WASM" ] || { echo "wasm not found at $WASM" >&2; exit 1; }
log "wasm: $WASM ($(wc -c <"$WASM" | tr -d ' ') bytes)"

# 2. Identities --------------------------------------------------------------
ensure_identity "$SOURCE"
ensure_identity "$ARBITER"
DEPLOYER_ADDRESS="$(stellar keys address "$SOURCE" | strip_cr)"
ARBITER_ADDRESS="$(stellar keys address "$ARBITER" | strip_cr)"
log "deployer: $DEPLOYER_ADDRESS"
log "arbiter:  $ARBITER_ADDRESS"

# 3. Upload + deploy ---------------------------------------------------------
log "uploading wasm"
WASM_HASH="$(run_logged stellar contract upload --wasm "$WASM" --source-account "$SOURCE" --network "$NETWORK" | tail -n1 | strip_cr)"
UPLOAD_TX="$(tx_hash_from "$STDERR_LOG")"
log "wasm hash: $WASM_HASH (upload tx: ${UPLOAD_TX:-none - wasm already on ledger})"

log "deploying contract"
CONTRACT_ID="$(run_logged stellar contract deploy --wasm-hash "$WASM_HASH" --source-account "$SOURCE" --network "$NETWORK" --alias bounty_escrow | tail -n1 | strip_cr)"
DEPLOY_TX="$(tx_hash_from "$STDERR_LOG")"
case "$CONTRACT_ID" in
  C*) ;;
  *) echo "unexpected deploy output: $CONTRACT_ID" >&2; exit 1 ;;
esac
log "contract id: $CONTRACT_ID (deploy tx: $DEPLOY_TX)"

NATIVE_SAC_ID="$(stellar contract id asset --asset native --network "$NETWORK" | tail -n1 | strip_cr)"
log "native XLM SAC id: $NATIVE_SAC_ID"

# 4. Sanity check (read-only, simulated) ------------------------------------
VERSION="$(stellar contract invoke --id "$CONTRACT_ID" --source-account "$SOURCE" --network "$NETWORK" -- version 2>/dev/null | tail -n1 | strip_cr)"
log "on-chain version(): $VERSION"

DEPLOYED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# 5. Optional smoke flow ----------------------------------------------------
SMOKE_JSON=""
if [ "$RUN_SMOKE_TEST" = "1" ]; then
  ensure_identity "$REQUESTER"
  REQUESTER_ADDRESS="$(stellar keys address "$REQUESTER" | strip_cr)"
  BOUNTY_ID="$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')"
  DEADLINE=$(( $(date -u +%s) + 7 * 24 * 3600 ))
  REWARD=10000000   # 1 XLM (7 decimals) per position

  log "smoke: create_escrow bounty_id=$BOUNTY_ID (1 position, 1 XLM deposit)"
  run_logged stellar contract invoke --id "$CONTRACT_ID" --source-account "$REQUESTER" --network "$NETWORK" -- \
    create_escrow --requester "$REQUESTER_ADDRESS" --bounty_id "$BOUNTY_ID" --token "$NATIVE_SAC_ID" \
    --reward_per_position "$REWARD" --positions 1 --arbiter "$ARBITER_ADDRESS" \
    --deadline "$DEADLINE" --initial_deposit "$REWARD" >/dev/null
  CREATE_TX="$(tx_hash_from "$STDERR_LOG")"
  log "smoke: create_escrow tx $CREATE_TX"

  CREATED_JSON="$(stellar contract invoke --id "$CONTRACT_ID" --source-account "$REQUESTER" --network "$NETWORK" -- \
    get_escrow --bounty_id "$BOUNTY_ID" 2>/dev/null | tail -n1 | strip_cr)"
  log "smoke: get_escrow -> $CREATED_JSON"

  # Pay the single position to the deployer account (any non-requester address works).
  log "smoke: release to $DEPLOYER_ADDRESS"
  RELEASED_JSON="$(run_logged stellar contract invoke --id "$CONTRACT_ID" --source-account "$REQUESTER" --network "$NETWORK" -- \
    release --requester "$REQUESTER_ADDRESS" --bounty_id "$BOUNTY_ID" --contributor "$DEPLOYER_ADDRESS" | tail -n1 | strip_cr)"
  RELEASE_TX="$(tx_hash_from "$STDERR_LOG")"
  log "smoke: release tx $RELEASE_TX"

  SMOKE_JSON="$(cat <<EOF
,
  "smoke_test": {
    "requester_address": "$REQUESTER_ADDRESS",
    "contributor_address": "$DEPLOYER_ADDRESS",
    "bounty_id": "$BOUNTY_ID",
    "reward_per_position": $REWARD,
    "positions": 1,
    "deadline": $DEADLINE,
    "create_escrow_tx": "$CREATE_TX",
    "escrow_after_create": ${CREATED_JSON:-null},
    "release_tx": "$RELEASE_TX",
    "escrow_after_release": ${RELEASED_JSON:-null}
  }
EOF
)"
fi

# 6. Write deployment record ------------------------------------------------
mkdir -p "$DEPLOY_DIR"
cat >"$OUT_JSON" <<EOF
{
  "network": "$NETWORK",
  "contract_id": "$CONTRACT_ID",
  "native_asset_contract_id": "$NATIVE_SAC_ID",
  "arbiter_address": "$ARBITER_ADDRESS",
  "wasm_hash": "$WASM_HASH",
  "upload_tx": $(json_str_or_null "$UPLOAD_TX"),
  "deploy_tx": "$DEPLOY_TX",
  "deployed_at": "$DEPLOYED_AT",
  "deployer_address": "$DEPLOYER_ADDRESS",
  "contract_version": ${VERSION:-null},
  "explorer_url": "https://stellar.expert/explorer/$NETWORK/contract/$CONTRACT_ID"${SMOKE_JSON}
}
EOF
log "wrote $OUT_JSON"
cat "$OUT_JSON"
