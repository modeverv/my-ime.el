HOST ?= 127.0.0.1
PORT ?= 8765
COMPOSE ?= docker compose

.PHONY: run test smoke docker-build docker-up docker-down docker-logs docker-smoke

run:
	python -m server.app --host $(HOST) --port $(PORT)

test:
	python -m unittest discover -s tests -v

smoke:
	curl -s http://$(HOST):$(PORT)/health
	curl -s -X POST http://$(HOST):$(PORT)/convert \
		-H 'Content-Type: application/json' \
		-d '{"text":";;global state;;gayoikannjiniikeru."}'

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
