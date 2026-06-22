HOST ?= 127.0.0.1
PORT ?= 8765
COMPOSE ?= docker compose
PYTHON ?= python3
UNAME_S := $(shell uname -s)
UNAME_M := $(shell uname -m)
RUNTIME_OS := $(if $(filter Darwin,$(UNAME_S)),darwin,$(if $(filter Linux,$(UNAME_S)),linux,unsupported))
RUNTIME_ARCH := $(if $(filter arm64 aarch64,$(UNAME_M)),arm64,$(if $(filter x86_64 amd64,$(UNAME_M)),x86_64,$(UNAME_M)))
RUNTIME_NAME := my-ime-kkc-runtime-$(RUNTIME_OS)-$(RUNTIME_ARCH)
RUNTIME_REPO ?= https://raw.githubusercontent.com/modeverv/my-ime-kkc-runtime/main
RUNTIME_DIR ?= .deps/kkc-runtime
RUNTIME_CURRENT := $(RUNTIME_DIR)/current
RUNTIME_TARBALL := $(RUNTIME_DIR)/$(RUNTIME_NAME).tar.gz
RUNTIME_SHA256 := $(RUNTIME_TARBALL).sha256
KKC_DATA_PATH := $(abspath $(RUNTIME_CURRENT))/lib/libkkc:$(abspath $(RUNTIME_CURRENT))/share/libkkc

.PHONY: deps run stdio test smoke stdio-smoke docker-build docker-up docker-down docker-logs docker-smoke

deps:
	@test "$(RUNTIME_OS)" != unsupported || (echo "unsupported runtime OS: $(UNAME_S)" >&2; exit 1)
	mkdir -p $(RUNTIME_DIR)
	/usr/bin/curl -fsSL -o $(RUNTIME_TARBALL) $(RUNTIME_REPO)/$(RUNTIME_NAME).tar.gz
	/usr/bin/curl -fsSL -o $(RUNTIME_SHA256) $(RUNTIME_REPO)/$(RUNTIME_NAME).tar.gz.sha256
	cd $(RUNTIME_DIR) && shasum -a 256 -c $(notdir $(RUNTIME_SHA256))
	rm -rf $(RUNTIME_CURRENT)
	mkdir -p $(RUNTIME_CURRENT)
	/usr/bin/tar -xzf $(RUNTIME_TARBALL) -C $(RUNTIME_CURRENT) --strip-components=1
	$(MAKE) stdio-smoke

run:
	$(PYTHON) -m server.app --host $(HOST) --port $(PORT)

stdio:
	MY_IME_KKC_COMMAND=$(abspath $(RUNTIME_CURRENT))/bin/kkc \
	MY_IME_KKC_DATA_PATH=$(KKC_DATA_PATH) \
	$(PYTHON) -m server.stdio_app

test:
	$(PYTHON) -m unittest discover -s tests -v

smoke:
	curl -s http://$(HOST):$(PORT)/health
	curl -s -X POST http://$(HOST):$(PORT)/convert \
		-H 'Content-Type: application/json' \
		-d '{"text":";;global state;;gayoikannjiniikeru."}'

stdio-smoke:
	@test -x $(RUNTIME_CURRENT)/bin/kkc || (echo "missing runtime; run make deps" >&2; exit 1)
	printf '%s\n' '{"id":1,"method":"convert","text":"watashinonamaeha nakanodesu"}' | \
	  MY_IME_KKC_COMMAND=$(abspath $(RUNTIME_CURRENT))/bin/kkc \
	  MY_IME_KKC_DATA_PATH=$(KKC_DATA_PATH) \
	  $(PYTHON) -m server.stdio_app

docker-build:
	$(COMPOSE) build

up:
	PORT=$(PORT) $(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f server

docker-smoke:
	curl -s http://$(HOST):$(PORT)/health
	curl -s -X POST http://$(HOST):$(PORT)/convert \
		-H 'Content-Type: application/json' \
		-d '{"text":";;global state;;gayoikannjiniikeru."}'
