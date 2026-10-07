"""Controles de calidad de datos.

Cada control es un fichero SQL de ``sql/calidad`` que devuelve las filas que lo INCUMPLEN
(vacío = correcto). La cabecera del fichero declara su alcance y su severidad:

* ``lote``   : se ejecuta sobre el lote que se está cargando (staging), antes de confirmar.
* ``modelo`` : se ejecuta sobre el almacén completo (huecos, frescura, coherencia).
* ``error``  : si falla, la transacción se deshace y NADA de ese lote llega al modelo.
* ``aviso``  : se registra y se muestra, pero no bloquea la carga.

Criterio: se bloquea ante INCOHERENCIAS dentro de los datos (sumas que no cuadran, negativos,
filas perdidas) y solo se avisa de problemas de COMPLETITUD o FRESCURA, que dependen de la
fuente y bloquearían el pipeline entero para siempre si la fuente no se corrige.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy import Connection, text

from energia.db import SQL_DIR, leer_sql

CARPETA = SQL_DIR / "calidad"
_CABECERA = re.compile(r"^--\s*(control|alcance|severidad|descripcion):\s*(.+)$")


@dataclass(frozen=True)
class Control:
    nombre: str
    alcance: str
    severidad: str
    descripcion: str
    sql: str


@dataclass
class ResultadoControl:
    control: str
    alcance: str
    severidad: str
    estado: str  # ok | fallo
    filas: int = 0
    ejemplos: list = field(default_factory=list)


class CalidadError(Exception):
    """Falló al menos un control de severidad 'error'."""

    def __init__(self, resultados: list[ResultadoControl]):
        fallidos = [r for r in resultados if r.estado == "fallo" and r.severidad == "error"]
        detalle = ", ".join(f"{r.control} ({r.filas} filas)" for r in fallidos)
        super().__init__(f"Controles de calidad fallidos: {detalle}")
        self.resultados = resultados


def cargar_controles(carpeta: Path = CARPETA) -> list[Control]:
    controles = []
    for fichero in sorted(carpeta.glob("*.sql")):
        contenido = leer_sql(fichero)
        meta = {}
        for linea in contenido.splitlines():
            m = _CABECERA.match(linea.strip())
            if m:
                meta[m.group(1)] = m.group(2).strip()
        faltan = {"control", "alcance", "severidad", "descripcion"} - meta.keys()
        if faltan:
            raise ValueError(f"{fichero.name}: faltan en la cabecera {sorted(faltan)}")
        if meta["alcance"] not in ("lote", "modelo") or meta["severidad"] not in ("error", "aviso"):
            raise ValueError(f"{fichero.name}: alcance o severidad no válidos")
        controles.append(
            Control(meta["control"], meta["alcance"], meta["severidad"], meta["descripcion"],
                    contenido.rstrip().rstrip(";"))
        )
    return controles


def ejecutar_controles(
    conn: Connection,
    controles: list[Control],
    hoy: date,
    alcance: str | None = None,
    max_ejemplos: int = 5,
) -> list[ResultadoControl]:
    resultados = []
    for c in controles:
        if alcance and c.alcance != alcance:
            continue
        params = {"hoy": hoy}
        filas = conn.execute(text(f"SELECT count(*) FROM ({c.sql}) q"), params).scalar_one()
        ejemplos = []
        if filas:
            ejemplos = conn.execute(
                text(
                    "SELECT coalesce(jsonb_agg(to_jsonb(q)), '[]'::jsonb) "
                    f"FROM (SELECT * FROM ({c.sql}) q0 LIMIT {int(max_ejemplos)}) q"
                ),
                params,
            ).scalar_one()
        resultados.append(
            ResultadoControl(c.nombre, c.alcance, c.severidad, "fallo" if filas else "ok",
                             int(filas), ejemplos)
        )
    return resultados


def hay_errores(resultados: list[ResultadoControl]) -> bool:
    return any(r.estado == "fallo" and r.severidad == "error" for r in resultados)
