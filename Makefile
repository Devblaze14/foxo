.PHONY: install run test seed lint fmt docker

install:       ## Install dependencies
	pip install -r requirements.txt

run:           ## Start the API (http://localhost:8000/docs)
	uvicorn app.main:app --reload

test:          ## Run the test suite
	pytest

seed:          ## Populate sample data
	python -m scripts.seed

lint:          ## Lint with ruff
	ruff check .

fmt:           ## Auto-format with ruff
	ruff format .

docker:        ## Run against Postgres via docker compose
	docker compose up --build
