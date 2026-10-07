"""Conexión a PostgreSQL y aplicación del esquema."""
from pathlib import Path

from sqlalchemy import Engine, create_engine

from energia.config import RAIZ

SQL_DIR = RAIZ / "sql"


def crear_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True)


def leer_sql(ruta: Path) -> str:
    # Siempre UTF-8: los ficheros llevan tildes y en Windows el valor por defecto sería otro.
    return ruta.read_text(encoding="utf-8")


def aplicar_esquema(engine: Engine) -> list[str]:
    """Aplica sql/0*.sql en orden. Todo es idempotente (IF NOT EXISTS / OR REPLACE)."""
    aplicados = []
    with engine.begin() as conn:
        for fichero in sorted(SQL_DIR.glob("0*.sql")):
            conn.exec_driver_sql(leer_sql(fichero))
            aplicados.append(fichero.name)
    return aplicados
