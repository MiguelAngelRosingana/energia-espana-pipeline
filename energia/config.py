"""Configuración leída de variables de entorno (nunca credenciales en el código)."""
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("Falta DATABASE_URL. Copia .env.example a .env y ajústalo.")
    return url


def fecha_inicio_defecto() -> date:
    """Primer día que se carga cuando todavía no hay marca de agua."""
    return date.fromisoformat(os.environ.get("ENERGIA_FECHA_INICIO", "2023-01-01"))


def solape_dias_defecto() -> int:
    return int(os.environ.get("ENERGIA_SOLAPE_DIAS", "7"))


def redata_base_url() -> str:
    return os.environ.get("REDATA_BASE_URL", "https://apidatos.ree.es/es/datos")
