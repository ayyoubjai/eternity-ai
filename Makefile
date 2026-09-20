CLONE ?= default

.PHONY: init models build run run-live run-headless

init:
	git submodule update --init --recursive

models:
	./scripts/download-models.sh

build:
	docker build --network host -t digital-clone:local .

run:
	./scripts/run-docker.sh --clone "$(CLONE)" --mode offline --style cinematic

run-live:
	./scripts/run-docker.sh --clone "$(CLONE)" --mode live

run-headless:
	CLONE="$(CLONE)" docker compose run --rm digital-clone
