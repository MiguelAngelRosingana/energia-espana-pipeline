"""Guarda respuestas REALES de la API en tests/fixtures para que los tests no dependan de la red.

Uso:  python scripts/capturar_fixtures.py

Captura una semana (2026-09-28 .. 2026-10-05) de los once pares (conjunto, sistema) que carga el
pipeline y, aparte, una semana alrededor del cambio de hora de marzo de 2026 (el día 29 tiene
23 horas) para comprobar que los días no se desplazan.
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from energia.redata import ClienteRedata, claves_por_defecto  # noqa: E402

DESTINO = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
SEMANA = (date(2026, 9, 28), date(2026, 10, 5))
CAMBIO_DE_HORA = (date(2026, 3, 26), date(2026, 4, 1))


def guardar(nombre: str, payload: dict) -> None:
    ruta = DESTINO / nombre
    ruta.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{nombre:<40} {ruta.stat().st_size / 1024:6.1f} KB")


def main() -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)
    cliente = ClienteRedata()
    for dataset, sistema in claves_por_defecto():
        guardar(f"{dataset}_{sistema}.json", cliente.obtener(dataset, sistema, *SEMANA).payload)
    guardar("generacion_peninsular_cambio_de_hora.json",
            cliente.obtener("generacion", "peninsular", *CAMBIO_DE_HORA).payload)


if __name__ == "__main__":
    main()
