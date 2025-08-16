# Makefile para OraculusBot

.PHONY: help install test test-unit test-integration test-coverage lint format clean

# Variables
PYTHON := uv run python
PYTEST := uv run pytest
BLACK := uv run black
ISORT := uv run isort
FLAKE8 := uv run flake8 --ignore E501,W503

help: ## Mostrar ayuda
	@echo "Comandos disponibles:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

install: ## Instalar dependencias
	uv sync

test: ## Ejecutar todos los tests
	$(PYTEST) -v

test-unit: ## Ejecutar solo tests unitarios
	$(PYTEST) test_oraculus_bot.py -v -m "not integration"

test-integration: ## Ejecutar solo tests de integración
	$(PYTEST) test_integration.py -v -m "integration or not integration"

test-coverage: ## Ejecutar tests con cobertura
	$(PYTEST) --cov=oraculus_bot --cov-report=html --cov-report=term-missing

test-fast: ## Ejecutar tests rápidos (sin integración)
	$(PYTEST) test_oraculus_bot.py -v -x

lint: ## Verificar código con linters
	$(FLAKE8) oraculus_bot.py test_*.py
	$(BLACK) --check oraculus_bot.py test_*.py
	$(ISORT) --check-only oraculus_bot.py test_*.py

format: ## Formatear código
	$(BLACK) oraculus_bot.py test_*.py conftest.py
	$(ISORT) oraculus_bot.py test_*.py conftest.py

clean: ## Limpiar archivos temporales
	rm -rf __pycache__/ .pytest_cache/ .coverage htmlcov/
	rm -rf test_temp/ logs/ *.db *.csv submissions/
	find . -name "*.pyc" -delete
	find . -name "*.pyo" -delete

run: ## Ejecutar el bot
	$(PYTHON) oraculus_bot.py

create-config: ## Crear archivo de configuración de ejemplo
	$(PYTHON) oraculus_bot.py --create-config

# Comandos de desarrollo
dev-setup: install ## Setup completo para desarrollo
	$(PYTHON) oraculus_bot.py --create-config
	@echo "✅ Setup de desarrollo completado"
	@echo "📝 Edita config.json con tus datos de Zulip"
	@echo "📊 Prepara tu archivo master_data.csv"

test-all: lint test test-coverage ## Ejecutar todos los checks y tests

# Comandos de CI/CD
ci: ## Comandos para CI/CD
	$(PYTEST) -v --junitxml=test-results.xml
	$(PYTEST) --cov=oraculus_bot --cov-report=xml