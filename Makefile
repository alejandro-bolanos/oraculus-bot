# Makefile para OraculusBot

.PHONY: help install test test-unit test-integration test-fast test-coverage clean lint format check setup-dev

# Variables
UV_RUN := uv run
PYTHON := $(UV_RUN) python
PYTEST := $(UV_RUN) pytest
RUFF := $(UV_RUN) ruff

help: ## Mostrar ayuda
	@echo "Comandos disponibles:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Instalar dependencias
	uv sync

setup-dev: ## Configurar entorno de desarrollo
	uv add --dev pytest pytest-cov pytest-mock ruff mypy
	@echo "Entorno de desarrollo configurado"

test: ## Ejecutar todos los tests
	$(PYTEST) -v --tb=short

test-unit: ## Ejecutar solo tests unitarios
	$(PYTEST) tests/unit/test_oraculus_bot.py -v

test-integration: ## Ejecutar solo tests de integración
	$(PYTEST) tests/integration/test_integration.py -v

test-fast: ## Tests rápidos (unitarios solamente)
	$(PYTEST) tests/unit/test_oraculus_bot.py -x -v

test-coverage: ## Tests con reporte de cobertura
	$(PYTEST) --cov=oraculus_bot --cov-report=html --cov-report=term
	@echo "Reporte de cobertura generado en htmlcov/"

test-watch: ## Ejecutar tests en modo watch (requiere pytest-watch)
	uv add --dev pytest-watch
	uv run ptw --runner "pytest -v"

lint: ## Verificar calidad de código con Ruff
	$(RUFF) check .
	uv run mypy src/oraculus_bot/oraculus_bot.py --ignore-missing-imports

format: ## Formatear código con Ruff
	$(RUFF) format src/oraculus_bot.py test_*.py

format-check: ## Verificar formato sin modificar archivos
	$(RUFF) format --check src/oraculus_bot.py test_*.py

lint-fix: ## Corregir automáticamente problemas de linting
	$(RUFF) check --fix .

clean: ## Limpiar archivos temporales
	rm -rf .pytest_cache/
	rm -rf htmlcov/
	rm -rf __pycache__/
	rm -rf .mypy_cache/
	rm -rf *.pyc
	rm -rf .coverage
	find . -type d -name __pycache__ -delete
	find . -type f -name "*.pyc" -delete
	rm -rf .ruff_cache/

demo-data: ## Crear datos de demostración
	@echo "Creando datos maestros de demostración..."
	$(PYTHON) -c "import pandas as pd; pd.DataFrame({'id': range(1,101), 'clase_binaria': [1 if i%3==0 else 0 for i in range(1,101)], 'dataset': ['public' if i<=30 else 'private' for i in range(1,101)]}).to_csv('master_data_demo.csv', index=False)"
	@echo "Archivo master_data_demo.csv creado"

check: ## Verificación completa (lint + format-check + tests)
	make format-check
	make lint
	make test

check-fix: ## Verificación completa con corrección automática
	make format
	make lint-fix
	make test

# Targets de desarrollo
dev-install: setup-dev ## Instalación completa para desarrollo

dev-test: format lint test-coverage ## Pipeline completo de desarrollo

# Target por defecto
all: clean install test ## Instalación y tests completos