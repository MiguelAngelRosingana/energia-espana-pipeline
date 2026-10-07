"""Exportación del modelo a CSV, para cargarlo en Power BI u otra herramienta sin PostgreSQL."""
from pathlib import Path

from sqlalchemy import Engine

TABLAS = (
    "dwh.dim_fecha",
    "dwh.dim_sistema",
    "dwh.dim_tecnologia",
    "dwh.fact_generacion",
    "dwh.fact_generacion_total",
    "dwh.fact_demanda",
    "dwh.v_generacion_detalle",
    "dwh.v_balance_diario",
    "dwh.v_balance_mensual",
)


def exportar(engine: Engine, destino: Path) -> dict[str, int]:
    """Escribe un CSV (UTF-8, cabecera, comas) por tabla o vista. Devuelve filas por fichero."""
    destino.mkdir(parents=True, exist_ok=True)
    filas = {}
    conexion = engine.raw_connection()
    try:
        cursor = conexion.cursor()
        for tabla in TABLAS:
            nombre = tabla.split(".", 1)[1]
            with open(destino / f"{nombre}.csv", "wb") as f:
                cursor.copy_expert(
                    f"COPY (SELECT * FROM {tabla} ORDER BY 1, 2) "
                    "TO STDOUT WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')",
                    f,
                )
            filas[nombre] = cursor.rowcount
    finally:
        conexion.close()
    return filas
