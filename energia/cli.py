"""Línea de comandos: init-db, run, calidad, resumen, exportar y reprocesar."""
from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

from sqlalchemy import text

from energia import config
from energia.calidad import cargar_controles, ejecutar_controles, hay_errores
from energia.db import aplicar_esquema, crear_engine
from energia.exportar import exportar
from energia.pipeline import ejecutar, reprocesar
from energia.redata import ClienteRedata


def _fecha(valor: str) -> date:
    return date.fromisoformat(valor)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="energia", description="Pipeline ELT de energía eléctrica de España"
    )
    sub = p.add_subparsers(dest="comando", required=True)

    sub.add_parser("init-db", help="Crea o actualiza el esquema (es idempotente)")

    r = sub.add_parser("run", help="Extrae, carga y transforma (incremental)")
    r.add_argument("--desde", type=_fecha, help="Fuerza el primer día a pedir (AAAA-MM-DD)")
    r.add_argument("--hasta", type=_fecha, help="Último día a pedir (por defecto, ayer)")
    r.add_argument("--solape-dias", type=int, help="Días que se vuelven a pedir (por defecto 7)")
    r.add_argument("--hoy", type=_fecha, help="Fecha de referencia (solo para pruebas)")

    c = sub.add_parser("calidad", help="Ejecuta los controles de calidad del modelo")
    c.add_argument("--hoy", type=_fecha, help="Fecha de referencia para la frescura")

    sub.add_parser("resumen", help="Últimas ejecuciones, marcas de agua y controles")

    e = sub.add_parser("exportar", help="Exporta el modelo a CSV")
    e.add_argument("--destino", type=Path, default=Path("export"))

    sub.add_parser("reprocesar", help="Devuelve a 'pendiente' las respuestas en cuarentena")
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    args = _parser().parse_args(argv)
    engine = crear_engine(config.database_url())

    if args.comando == "init-db":
        for nombre in aplicar_esquema(engine):
            print(f"Aplicado {nombre}")
        return 0

    if args.comando == "run":
        cliente = ClienteRedata(config.redata_base_url())
        r = ejecutar(
            engine, cliente, hoy=args.hoy, desde=args.desde, hasta=args.hasta,
            solape_dias=args.solape_dias,
        )
        print(
            f"run {r.run_id}: {r.estado} | {r.desde} .. {r.hasta} | respuestas nuevas "
            f"{r.respuestas_nuevas}, repetidas {r.respuestas_repetidas}, reencoladas "
            f"{r.respuestas_reencoladas} | filas en staging "
            f"{r.filas_stg} | hechos: {r.hechos_nuevos} nuevos, {r.hechos_modificados} "
            f"modificados, {r.hechos_iguales} sin cambios"
        )
        for c in r.controles:
            if c.estado == "fallo":
                print(f"  [{c.severidad.upper()}] {c.control}: {c.filas} filas, "
                      f"p. ej. {c.ejemplos[:2]}")
        if r.en_cuarentena:
            print(f"  ATENCIÓN: {r.en_cuarentena} respuestas en cuarentena (ver raw.respuestas)")
        if r.error:
            print(f"  ERROR: {r.error}")
        return 0 if r.estado == "ok" else 1

    if args.comando == "calidad":
        with engine.connect() as conn:
            resultados = ejecutar_controles(
                conn, cargar_controles(), args.hoy or date.today(), alcance="modelo"
            )
        for r in resultados:
            marca = "OK   " if r.estado == "ok" else r.severidad.upper().ljust(5)
            print(f"{marca} {r.control:<28} filas afectadas: {r.filas}")
            if r.estado == "fallo":
                print(f"      ejemplos: {r.ejemplos[:3]}")
        return 1 if hay_errores(resultados) else 0

    if args.comando == "resumen":
        _resumen(engine)
        return 0

    if args.comando == "exportar":
        for nombre, filas in exportar(engine, args.destino).items():
            print(f"{nombre + '.csv':<30} {filas:>8} filas")
        return 0

    if args.comando == "reprocesar":
        print(f"{reprocesar(engine)} respuestas devueltas a 'pendiente'")
        return 0
    return 2


def _resumen(engine) -> None:
    with engine.connect() as conn:
        print("== Últimas ejecuciones ==")
        print(f"{'run':>4} {'estado':<7} {'desde':<10} {'hasta':<10} {'resp.nuevas':>11} "
              f"{'nuevos':>7} {'modif.':>6} {'iguales':>8} {'seg':>6}")
        for f in conn.execute(text("SELECT * FROM etl.v_resumen_ejecuciones LIMIT 10")).mappings():
            print(f"{f['run_id']:>4} {f['estado']:<7} {f['desde']!s:<10} {f['hasta']!s:<10} "
                  f"{f['respuestas_nuevas'] or 0:>11} {f['hechos_nuevos'] or 0:>7} "
                  f"{f['hechos_modificados'] or 0:>6} {f['hechos_iguales'] or 0:>8} "
                  f"{f['segundos'] or 0:>6}")
        print("\n== Marcas de agua ==")
        for f in conn.execute(
            text("SELECT dataset, sistema, ultima_fecha FROM etl.marcas_agua ORDER BY 1, 2")
        ):
            print(f"{f.dataset:<11} {f.sistema:<11} {f.ultima_fecha}")
        print("\n== Controles de la última ejecución ==")
        for f in conn.execute(
            text(
                "SELECT control, severidad, estado, filas_afectadas FROM etl.resultados_calidad "
                "WHERE run_id = (SELECT max(run_id) FROM etl.resultados_calidad) ORDER BY id"
            )
        ):
            print(f"{f.estado:<6} {f.severidad:<6} {f.control:<32} {f.filas_afectadas}")
