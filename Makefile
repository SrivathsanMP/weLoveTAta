.PHONY: build up down seed test isolation-test logs

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

seed:
	docker compose run --rm --no-deps ingest

test:
	python tests/test_queries.py

isolation-test:
	sh tests/test_isolation.sh

logs:
	docker compose logs -f --tail=100