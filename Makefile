.PHONY: help

help:
	@echo "Usage:"
	@echo "  make ui                 Run the Streamlit UI"
	@echo "  make worker             Run the Temporal worker"
	@echo "  make refresh            Trigger universe refresh workflow"
	@echo "  make up                 Start all services in Docker"
	@echo "  make down               Stop all Docker services"
	@echo "  make logs               View Docker logs"
	@echo "  make test               Run tests"
	@echo "  make cov                Run tests with coverage"
	@echo "  make check              Lint code with Ruff"
	@echo "  make format             Format code with Ruff"
	@echo "  make allci              Run all CI steps"

# Application
ui:
	uv run streamlit run src/trade_analyzer/ui/app.py

worker:
	uv run python -m trade_analyzer.workers.universe_worker

refresh:
	uv run python -m trade_analyzer.workers.start_workflow

# Docker
up:
	docker-compose up -d --build

down:
	docker-compose down

logs:
	docker-compose logs -f

# CI
test:
	uv run pytest tests/

cov:
	uv run pytest --cov=src/trade_analyzer tests/ --cov-report=term-missing

check:
	uv run ruff check src/

format:
	uv run ruff format src/

allci:
	$(MAKE) check
	$(MAKE) format
	$(MAKE) cov
