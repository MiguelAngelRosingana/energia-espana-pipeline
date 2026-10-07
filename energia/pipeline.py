"""Orquestación del pipeline: planificar -> extraer -> aterrizar (raw) -> transformar (SQL).

Flujo de una ejecución:

1. Se abre una fila en ``etl.ejecuciones``.
2. **Planificar**: para cada (conjunto de datos, sistema) se decide qué días pedir. Con marca de
   agua se parte de ``marca - solape + 1``: se vuelven a pedir los últimos días por si la fuente
   los ha revisado. Sin marca de agua, desde la fecha de inicio configurada.
3. **Extraer y aterrizar**: cada respuesta se guarda tal cual en ``raw.respuestas`` y se confirma
   de inmediato. Si algo falla después, lo descargado no se pierde.
4. **Transformar** (UNA transacción): JSON -> staging -> dimensiones -> hechos -> controles de
   calidad -> marcas de agua -> raw marcado como procesado. Si un control de severidad ``error``
   falla, se deshace todo: el modelo queda exactamente como estaba.
5. Se cierra la ejecución y se guardan los resultados de calidad (en otra transacción, para que
   el rollback no borre la evidencia de por qué falló).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import Engine, text

from energia import config
from energia.calidad import (
    CalidadError,
    ResultadoControl,
    cargar_controles,
    ejecutar_controles,
    hay_errores,
)
from energia.db import SQL_DIR, leer_sql
from energia.redata import ClienteRedata, Respuesta, claves_por_defecto, trocear

log = logging.getLogger(__name__)

TRANSFORMACIONES = SQL_DIR / "transformaciones"
# Los pasos 10-30 construyen el lote; el 40 (marcas de agua) solo se ejecuta si los controles pasan.
_PASOS_CARGA = ("10_staging.sql", "20_dimensiones.sql", "30_hechos.sql")
_PASO_MARCAS = "40_marcas_agua.sql"


@dataclass(frozen=True)
class Peticion:
    dataset: str
    sistema: str
    desde: date
    hasta: date


@dataclass
class Resultado:
    run_id: int
    estado: str = "en_curso"
    desde: date | None = None
    hasta: date | None = None
    respuestas_nuevas: int = 0
    respuestas_repetidas: int = 0
    respuestas_reencoladas: int = 0
    filas_stg: int = 0
    hechos_nuevos: int = 0
    hechos_modificados: int = 0
    hechos_iguales: int = 0
    en_cuarentena: int = 0
    controles: list[ResultadoControl] = field(default_factory=list)
    error: str | None = None


# ------------------------------------------------------------------ planificación

def leer_marcas(engine: Engine) -> dict[tuple[str, str], date]:
    with engine.connect() as conn:
        filas = conn.execute(text("SELECT dataset, sistema, ultima_fecha FROM etl.marcas_agua"))
        return {(f.dataset, f.sistema): f.ultima_fecha for f in filas}


def planificar(
    marcas: dict[tuple[str, str], date],
    claves: list[tuple[str, str]],
    hasta: date,
    desde: date | None,
    solape_dias: int,
    fecha_inicio: date,
) -> list[Peticion]:
    """Decide qué rango pedir para cada (dataset, sistema), troceado a lo que admite la API."""
    if solape_dias < 1:
        raise ValueError("solape_dias debe ser al menos 1")
    peticiones = []
    for dataset, sistema in claves:
        if desde is not None:
            inicio = desde
        elif (dataset, sistema) in marcas:
            inicio = marcas[(dataset, sistema)] - timedelta(days=solape_dias - 1)
        else:
            inicio = fecha_inicio
        peticiones += [Peticion(dataset, sistema, a, b) for a, b in trocear(inicio, hasta)]
    return peticiones


# ------------------------------------------------------------------ ejecución

def ejecutar(
    engine: Engine,
    cliente: ClienteRedata,
    *,
    hoy: date | None = None,
    desde: date | None = None,
    hasta: date | None = None,
    solape_dias: int | None = None,
    fecha_inicio: date | None = None,
    claves: list[tuple[str, str]] | None = None,
) -> Resultado:
    hoy = hoy or date.today()
    # Por defecto no se carga el día en curso: la fuente puede tenerlo incompleto o provisional.
    hasta = hasta or hoy - timedelta(days=1)
    solape_dias = solape_dias or config.solape_dias_defecto()
    fecha_inicio = fecha_inicio or config.fecha_inicio_defecto()
    claves = claves or claves_por_defecto()

    res = Resultado(run_id=_abrir_ejecucion(engine, desde, hasta, solape_dias), hasta=hasta)
    try:
        plan = planificar(leer_marcas(engine), claves, hasta, desde, solape_dias, fecha_inicio)
        res.desde = min((p.desde for p in plan), default=None)
        log.info("Ejecución %d: %d peticiones (%s .. %s)", res.run_id, len(plan), res.desde, hasta)

        for p in plan:
            respuesta = cliente.obtener(p.dataset, p.sistema, p.desde, p.hasta)
            resultado = _aterrizar(engine, res.run_id, respuesta)
            if resultado == "nueva":
                res.respuestas_nuevas += 1
            elif resultado == "reencolada":
                res.respuestas_reencoladas += 1
            else:
                res.respuestas_repetidas += 1

        _transformar(engine, res, hoy)
        res.estado = "ok"
    except CalidadError as e:
        res.estado, res.error, res.controles = "error", str(e), e.resultados
        _poner_en_cuarentena(engine, str(e))
        log.error("%s", e)
    except Exception as e:  # noqa: BLE001 - se registra y se relanza como resultado de la ejecución
        res.estado, res.error = "error", f"{type(e).__name__}: {e}"
        log.exception("Ejecución %d fallida", res.run_id)

    res.en_cuarentena = _contar_cuarentena(engine)
    _cerrar_ejecucion(engine, res)
    return res


def _abrir_ejecucion(engine: Engine, desde: date | None, hasta: date, solape: int) -> int:
    with engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO etl.ejecuciones (desde, hasta, solape_dias) "
                "VALUES (:desde, :hasta, :solape) RETURNING run_id"
            ),
            {"desde": desde, "hasta": hasta, "solape": solape},
        ).scalar_one()


def _aterrizar(engine: Engine, run_id: int, r: Respuesta) -> str:
    """Guarda la respuesta en raw. Devuelve 'nueva', 'repetida' o 'reencolada'.

    Una respuesta idéntica a otra ya guardada es 'repetida' (carga idempotente) y no se procesa
    de nuevo. Si la idéntica estaba en cuarentena, se 'reencola': un lote que falló arrastra a
    la cuarentena también respuestas buenas, y si la fuente vuelve a enviar lo mismo hay que
    darles otra oportunidad (si siguen mal, los controles las volverán a frenar).
    """
    with engine.begin() as conn:
        fila = conn.execute(
            text(
                "INSERT INTO raw.respuestas "
                "(run_id, dataset, sistema, desde, hasta, estado_http, huella, payload) "
                "VALUES (:run_id, :dataset, :sistema, :desde, :hasta, :http, :huella, "
                "CAST(:payload AS jsonb)) "
                "ON CONFLICT (dataset, sistema, desde, hasta, huella) DO NOTHING RETURNING id"
            ),
            {
                "run_id": run_id, "dataset": r.dataset, "sistema": r.sistema,
                "desde": r.desde, "hasta": r.hasta, "http": r.estado_http, "huella": r.huella,
                "payload": json.dumps(r.payload, ensure_ascii=False),
            },
        ).first()
        if fila is not None:
            return "nueva"
        reencolada = conn.execute(
            text(
                "UPDATE raw.respuestas SET estado = 'pendiente', motivo = NULL, run_id = :run_id "
                "WHERE dataset = :dataset AND sistema = :sistema AND desde = :desde "
                "AND hasta = :hasta AND huella = :huella AND estado = 'cuarentena' RETURNING id"
            ),
            {"run_id": run_id, "dataset": r.dataset, "sistema": r.sistema, "desde": r.desde,
             "hasta": r.hasta, "huella": r.huella},
        ).first()
    return "reencolada" if reencolada is not None else "repetida"


def _transformar(engine: Engine, res: Resultado, hoy: date) -> None:
    """Transformación y carga en UNA transacción: o entra todo el lote o no entra nada."""
    controles = cargar_controles()
    with engine.begin() as conn:
        for nombre in _PASOS_CARGA:
            conn.execute(text(leer_sql(TRANSFORMACIONES / nombre)))

        res.controles = ejecutar_controles(conn, controles, hoy)
        if hay_errores(res.controles):
            raise CalidadError(res.controles)  # al salir del bloque se hace ROLLBACK

        conn.execute(text(leer_sql(TRANSFORMACIONES / _PASO_MARCAS)))
        conn.execute(
            text(
                "UPDATE raw.respuestas SET estado = 'procesada', procesada_en = now() "
                "WHERE estado = 'pendiente'"
            )
        )
        res.filas_stg = conn.execute(
            text("SELECT (SELECT count(*) FROM stg.generacion) "
                 "+ (SELECT count(*) FROM stg.demanda)")
        ).scalar_one()
        acciones = dict(
            conn.execute(
                text(
                    "SELECT accion, count(*) FROM ("
                    "  SELECT accion FROM stg.generacion WHERE accion IS NOT NULL"
                    "  UNION ALL SELECT accion FROM stg.demanda WHERE accion IS NOT NULL"
                    ") t GROUP BY accion"
                )
            ).all()
        )
    res.hechos_nuevos = acciones.get("nueva", 0)
    res.hechos_modificados = acciones.get("modificada", 0)
    res.hechos_iguales = acciones.get("igual", 0)


def _poner_en_cuarentena(engine: Engine, motivo: str) -> None:
    """Las respuestas del lote fallido no se reintentan solas: quedan visibles en cuarentena."""
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE raw.respuestas SET estado = 'cuarentena', motivo = :m "
                 "WHERE estado = 'pendiente'"),
            {"m": motivo[:500]},
        )


def _contar_cuarentena(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM raw.respuestas WHERE estado = 'cuarentena'")
        ).scalar_one()


def _cerrar_ejecucion(engine: Engine, res: Resultado) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE etl.ejecuciones SET estado = :estado, finalizado_en = now(), "
                "desde = :desde, hasta = :hasta, respuestas_nuevas = :rn, "
                "respuestas_repetidas = :rr, respuestas_reencoladas = :re, "
                "filas_stg = :fs, hechos_nuevos = :hn, "
                "hechos_modificados = :hm, hechos_iguales = :hi, error = :error "
                "WHERE run_id = :run_id"
            ),
            {
                "estado": res.estado, "desde": res.desde, "hasta": res.hasta,
                "rn": res.respuestas_nuevas, "rr": res.respuestas_repetidas,
                "re": res.respuestas_reencoladas,
                "fs": res.filas_stg, "hn": res.hechos_nuevos, "hm": res.hechos_modificados,
                "hi": res.hechos_iguales, "error": res.error, "run_id": res.run_id,
            },
        )
        for c in res.controles:
            conn.execute(
                text(
                    "INSERT INTO etl.resultados_calidad "
                    "(run_id, control, alcance, severidad, estado, filas_afectadas, ejemplos) "
                    "VALUES (:run_id, :control, :alcance, :sev, :estado, :filas, "
                    "CAST(:ejemplos AS jsonb))"
                ),
                {
                    "run_id": res.run_id, "control": c.control, "alcance": c.alcance,
                    "sev": c.severidad, "estado": c.estado, "filas": c.filas,
                    "ejemplos": json.dumps(c.ejemplos, ensure_ascii=False, default=str),
                },
            )


def reprocesar(engine: Engine) -> int:
    """Devuelve las respuestas en cuarentena a 'pendiente' (para la siguiente ejecución)."""
    with engine.begin() as conn:
        return conn.execute(
            text("UPDATE raw.respuestas SET estado = 'pendiente', motivo = NULL "
                 "WHERE estado = 'cuarentena'")
        ).rowcount
