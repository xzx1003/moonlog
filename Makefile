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

.PHONY: bench
bench: build
	python3 scripts/bench_cli.py

GO ?= go
.PHONY: bench-compare
bench-compare:
	moon build benchmarks/compare --target native --release
	$(GO) build -o /tmp/moonlog-go-reference benchmarks/compare/main.go
	python3 benchmarks/compare/run.py --go /tmp/moonlog-go-reference

BENCH_BASELINE ?=
BENCH_CANDIDATE ?= bin/moonlog
BENCH_RUNS ?= 5
BENCH_WARMUPS ?= 1
BENCH_SEED ?= 20261029
BENCH_GATE ?=
BENCH_REG_SIZES ?= 10,100
BENCH_REG_OUTPUT ?= benchmarks/regression/results.json
BENCH_REG_LARGE_OUTPUT ?= benchmarks/regression/results-large.json

.PHONY: bench-regression
bench-regression: build
	@test -n "$(BENCH_BASELINE)" || { echo "set BENCH_BASELINE=/path/to/previous/moonlog" >&2; exit 2; }
	python3 benchmarks/regression/run.py --baseline "$(BENCH_BASELINE)" --candidate "$(BENCH_CANDIDATE)" --sizes "$(BENCH_REG_SIZES)" --runs $(BENCH_RUNS) --warmups $(BENCH_WARMUPS) --seed $(BENCH_SEED) --output "$(BENCH_REG_OUTPUT)" $(BENCH_GATE)

.PHONY: bench-regression-large
bench-regression-large: build
	@test -n "$(BENCH_BASELINE)" || { echo "set BENCH_BASELINE=/path/to/previous/moonlog" >&2; exit 2; }
	python3 benchmarks/regression/run.py --baseline "$(BENCH_BASELINE)" --candidate "$(BENCH_CANDIDATE)" --sizes 1024,5120,10240 --allow-large --runs $(BENCH_RUNS) --warmups $(BENCH_WARMUPS) --seed $(BENCH_SEED) --output "$(BENCH_REG_LARGE_OUTPUT)" $(BENCH_GATE)
