# BountyFlow bounty_escrow contract tasks. Run from contracts/bounty_escrow.
WASM := ../target/wasm32v1-none/release/bounty_escrow.wasm

# soroban-sdk 28 builds a contract wasm only through stellar-cli v25.2.0+ (`stellar contract build`, which shakes the
# contract spec); a plain `cargo build --target wasm32v1-none` fails in soroban-sdk's build script. Native builds
# (`cargo test`, `cargo clippy`) do not need the CLI. CI pins the Stellar CLI version listed in contracts/README.md.
STELLAR_CLI_MIN := 25.2.0
STELLAR_CLI_INSTALL := https://developers.stellar.org/docs/build/smart-contracts/getting-started/setup\#install-the-stellar-cli

.PHONY: all build build-raw test fmt fmt-check clippy optimize clean check-stellar-cli

all: fmt clippy test build

# Optimized release wasm via the Stellar CLI (optimization is on by default in CLI 27).
build: check-stellar-cli
	stellar contract build
	@ls -l $(WASM)

# Unoptimized release wasm (skips the wasm-opt pass). soroban-sdk 28 still requires the Stellar CLI for this.
build-raw: check-stellar-cli
	stellar contract build --optimize=false
	@ls -l $(WASM)

test:
	cargo test

fmt:
	cargo fmt --all

fmt-check:
	cargo fmt --all --check

clippy:
	cargo clippy --all-targets -- -D warnings

# `stellar contract optimize` is deprecated in CLI 27 in favour of `build --optimize`.
optimize: check-stellar-cli
	stellar contract build --optimize

# Fails with a clear message when the Stellar CLI is missing or older than STELLAR_CLI_MIN.
check-stellar-cli:
	@command -v stellar >/dev/null 2>&1 || { \
	  echo "error: stellar-cli not found in PATH. soroban-sdk 28 contracts are built with 'stellar contract build'" >&2; \
	  echo "       from stellar-cli v$(STELLAR_CLI_MIN)+ (contracts/README.md lists the version CI uses)." >&2; \
	  echo "       Install: $(STELLAR_CLI_INSTALL)" >&2; \
	  exit 1; }
	@v=$$(stellar --version 2>/dev/null | awk 'NR == 1 { print $$2 }'); \
	  if ! awk -v have="$$v" -v need="$(STELLAR_CLI_MIN)" 'BEGIN { split(have, h, "."); split(need, n, "."); \
	      for (i = 1; i <= 3; i++) { if (h[i] + 0 > n[i] + 0) exit 0; if (h[i] + 0 < n[i] + 0) exit 1 } exit 0 }'; then \
	    echo "error: stellar-cli $${v:-(unknown version)} is too old. soroban-sdk 28 needs stellar-cli v$(STELLAR_CLI_MIN)+" >&2; \
	    echo "       to build a contract. Upgrade: $(STELLAR_CLI_INSTALL)" >&2; \
	    exit 1; \
	  fi

clean:
	cargo clean
