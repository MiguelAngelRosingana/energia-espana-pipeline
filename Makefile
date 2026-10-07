PY ?= python

.PHONY: install db init run calidad resumen test live lint export reset

install:
	$(PY) -m pip install -r requirements-dev.txt

db:  ## PostgreSQL local (puerto 5433) con las bases energia y energia_test
	docker compose up -d

init:
	$(PY) -m energia init-db

run:  ## Carga incremental (la primera vez, desde ENERGIA_FECHA_INICIO)
	$(PY) -m energia run

calidad:
	$(PY) -m energia calidad

resumen:
	$(PY) -m energia resumen

export:
	$(PY) -m energia exportar --destino export

test:
	$(PY) -m pytest -q

live:  ## Tests contra la API real
	$(PY) -m pytest -m live -q

lint:
	$(PY) -m ruff check .

reset:  ## Borra los esquemas de la base de datos principal
	docker compose down -v
