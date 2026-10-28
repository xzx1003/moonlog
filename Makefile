.PHONY: build test check integration

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
