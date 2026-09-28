# BountyFlow bounty_escrow contract tasks. Run from contracts/bounty_escrow.
WASM := ../target/wasm32v1-none/release/bounty_escrow.wasm

.PHONY: all build build-raw test fmt fmt-check clippy optimize clean

all: fmt clippy test build

# Optimized release wasm via the Stellar CLI (optimization is on by default in CLI 27).
build:
	stellar contract build
	@ls -l $(WASM)

# Fallback: plain cargo build, no wasm-opt pass.
build-raw:
	cargo build --target wasm32v1-none --release

test:
	cargo test

fmt:
	cargo fmt --all

fmt-check:
	cargo fmt --all --check

clippy:
	cargo clippy --all-targets -- -D warnings

# `stellar contract optimize` is deprecated in CLI 27 in favour of `build --optimize`.
optimize:
	stellar contract build --optimize

clean:
	cargo clean
