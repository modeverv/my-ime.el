HOST ?= 127.0.0.1
PORT ?= 8765
COMPOSE ?= docker compose
PYTHON ?= $(if $(filter windows,$(RUNTIME_OS)),python,python3)
UNAME_S := $(shell uname -s 2>/dev/null || echo Windows_NT)
UNAME_M := $(shell uname -m 2>/dev/null || echo $(PROCESSOR_ARCHITECTURE))
RUNTIME_OS := $(if $(filter Darwin,$(UNAME_S)),darwin,$(if $(filter Linux,$(UNAME_S)),linux,$(if $(filter Windows_NT,$(UNAME_S)),windows,$(if $(findstring MINGW,$(UNAME_S)),windows,$(if $(findstring MSYS,$(UNAME_S)),windows,unsupported)))))
RUNTIME_ARCH := $(if $(filter arm64 aarch64,$(UNAME_M)),arm64,$(if $(filter x86_64 amd64,$(UNAME_M)),x86_64,$(UNAME_M)))
RUNTIME_NAME := my-ime-kkc-runtime-$(RUNTIME_OS)-$(RUNTIME_ARCH)
RUNTIME_REPO ?= https://raw.githubusercontent.com/modeverv/my-ime-kkc-runtime/main
RUNTIME_DIR ?= .deps/kkc-runtime
RUNTIME_CURRENT := $(RUNTIME_DIR)/current
RUNTIME_TARBALL := $(RUNTIME_DIR)/$(RUNTIME_NAME).tar.gz
RUNTIME_SHA256 := $(RUNTIME_TARBALL).sha256
EXE_SUFFIX := $(if $(filter windows,$(RUNTIME_OS)),.exe,)
PATH_SEP := $(if $(filter windows,$(RUNTIME_OS)),;,:)
KKC_BIN := $(abspath $(RUNTIME_CURRENT))/bin/kkc$(EXE_SUFFIX)
KKC_DATA_PATH := $(abspath $(RUNTIME_CURRENT))/lib/libkkc$(PATH_SEP)$(abspath $(RUNTIME_CURRENT))/share/libkkc

.PHONY: deps run stdio test smoke stdio-smoke docker-build docker-up docker-down docker-logs docker-smoke

deps:
	@test "$(RUNTIME_OS)" != unsupported || (echo "unsupported runtime OS: $(UNAME_S)" >&2; exit 1)
	$(PYTHON) scripts/install-kkc-runtime.py --runtime-dir $(RUNTIME_DIR) --repo $(RUNTIME_REPO)
	$(MAKE) stdio-smoke

run:
	$(PYTHON) -m server.app --host $(HOST) --port $(PORT)

stdio:
	MY_IME_KKC_COMMAND="$(KKC_BIN)" \
	MY_IME_KKC_DATA_PATH="$(KKC_DATA_PATH)" \
	$(PYTHON) -m server.stdio_app

test:
	$(PYTHON) -m unittest discover -s tests -v

smoke:
	curl -s http://$(HOST):$(PORT)/health
	curl -s -X POST http://$(HOST):$(PORT)/convert \
		-H 'Content-Type: application/json' \
		-d '{"text":";;global state;;gayoikannjiniikeru."}'

stdio-smoke:
	@test -x "$(KKC_BIN)" || (echo "missing runtime; run make deps" >&2; exit 1)
	printf '%s\n' '{"id":1,"method":"convert","text":"watashinonamaeha nakanodesu"}' | \
	  MY_IME_KKC_COMMAND="$(KKC_BIN)" \
	  MY_IME_KKC_DATA_PATH="$(KKC_DATA_PATH)" \
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
