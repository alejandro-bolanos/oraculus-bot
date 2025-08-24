# Makefile para OraculusBot

.PHONY: help install test test-unit test-integration test-fast test-coverage clean lint format setup-dev

# Variables
PYTHON := uv run python
PYTEST := uv run pytest
PIP := uv add

help: ## Mostrar ayuda
	@echo "Comandos disponibles:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Instalar dependencias
	uv sync

setup-dev: ## Configurar entorno de desarrollo
	uv add --dev pytest pytest-cov pytest-mock black isort flake8 mypy
	@echo "Entorno de desarrollo configurado"

test: ## Ejecutar todos los tests
	$(PYTEST) -v --tb=short

test-unit: ## Ejecutar solo tests unitarios
	$(PYTEST) test_oraculus_bot.py -v

test-integration: ## Ejecutar solo tests de integración
	$(PYTEST) test_integration.py -v

test-fast: ## Tests rápidos (unitarios solamente)
	$(PYTEST) test_oraculus_bot.py -x -v

test-coverage: ## Tests con reporte de cobertura
	$(PYTEST) --cov=oraculus_bot --cov-report=html --cov-report=term
	@echo "Reporte de cobertura generado en htmlcov/"

test-watch: ## Ejecutar tests en modo watch (requiere pytest-watch)
	uv add --dev pytest-watch
	uv run ptw --runner "pytest -v"

lint: ## Verificar calidad de código
	uv run flake8 oraculus_bot.py test_*.py
	uv run mypy oraculus_bot.py --ignore-missing-imports

format: ## Formatear código
	uv run black oraculus_bot.py test_*.py
	uv run isort oraculus_bot.py test_*.py

clean: ## Limpiar archivos temporales
	rm -rf .pytest_cache/
	rm -rf htmlcov/
	rm -rf __pycache__/
	rm -rf *.pyc
	rm -rf .coverage
	rm -rf logs/
	rm -rf submissions/
	rm -f *.db
	find . -type d -name __pycache__ -delete
	find . -type f -name "*.pyc" -delete

run: ## Ejecutar el bot
	$(PYTHON) oraculus_bot.py

run-config: ## Crear configuración de ejemplo
	$(PYTHON) oraculus_bot.py --create-config

demo-data: ## Crear datos de demostración
	@echo "Creando datos maestros de demostración..."
	$(PYTHON) -c "import pandas as pd; pd.DataFrame({'id': range(1,101), 'clase_binaria': [1 if i%3==0 else 0 for i in range(1,101)], 'dataset': ['public' if i<=30 else 'private' for i in range(1,101)]}).to_csv('master_data_demo.csv', index=False)"
	@echo "Archivo master_data_demo.csv creado"

check: ## Verificación completa (lint + tests)
	make lint
	make test

docker-build: ## Construir imagen Docker
	docker build -t oraculus-bot .

docker-run: ## Ejecutar en Docker
	docker run -it --rm -v $(PWD)/config.json:/app/config.json -v $(PWD)/master_data.csv:/app/master_data.csv oraculus-bot

benchmark: ## Benchmark de rendimiento
	@echo "Ejecutando benchmarks..."
	$(PYTEST) test_integration.py::TestPerformanceAndScalability -v --durations=10

docs: ## Generar documentación
	@echo "Generando documentación..."
	$(PYTHON) -c "from oraculus_bot import OraculusBot; help(OraculusBot)" > docs.txt
	@echo "Documentación generada en docs.txt"

# Targets de desarrollo
dev-install: setup-dev ## Instalación completa para desarrollo

dev-test: format lint test-coverage ## Pipeline completo de desarrollo

# Target por defecto
all: clean install test ## Instalación y tests completos