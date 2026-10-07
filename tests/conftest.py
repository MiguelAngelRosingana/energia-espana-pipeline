import os

import pytest
from sqlalchemy import text

from energia.db import aplicar_esquema, crear_engine


@pytest.fixture(scope="session")
def engine_test():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Falta TEST_DATABASE_URL (los tests de integración la necesitan)")
    engine = crear_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture()
def db(engine_test):
    """Base de datos limpia con el esquema aplicado. ATENCIÓN: borra raw, stg, dwh y etl."""
    with engine_test.begin() as conn:
        for esquema in ("raw", "stg", "dwh", "etl"):
            conn.execute(text(f"DROP SCHEMA IF EXISTS {esquema} CASCADE"))
    aplicar_esquema(engine_test)
    return engine_test
