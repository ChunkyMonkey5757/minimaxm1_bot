.PHONY: setup dev run docker-up docker-down logs update

setup:
	python -m pip install --upgrade pip
	pip install -r requirements.txt
	@echo "Copy .env.example -> .env and adjust settings."

dev:
	PAPER_MODE=true python -m src.main

run:
	python -m src.main

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

logs:
	docker compose logs -f

update:
	git pull && docker compose up -d --build
