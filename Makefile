.PHONY: build test check integration web-build web-test web-bench web-serve

WEB_BENCH_MB ?= 64

build:
	moon build cmd/main --target native --release
	mkdir -p bin
	cp _build/native/release/build/cmd/main/main.exe bin/moonlog

check:
	moon check --target native --deny-warn
	moon fmt --check

test:
	moon test --target native --deny-warn

integration: build
	python3 scripts/test_cli.py bin/moonlog

web-build:
	moon build web_bridge --target wasm-gc --release
	mkdir -p web/generated
	cp _build/wasm-gc/release/build/web_bridge/web_bridge.wasm web/generated/moonlog_web.wasm

web-test: build web-build
	node scripts/test_web.mjs web/generated/moonlog_web.wasm bin/moonlog

web-bench: web-build
	node scripts/bench_web.mjs web/generated/moonlog_web.wasm $(WEB_BENCH_MB)

web-serve:
	python3 -m http.server 8000
