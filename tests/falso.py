"""Cliente falso para los tests: sirve respuestas REALES de la API guardadas en tests/fixtures,
recortadas al rango pedido, como haría la API. Así los tests no dependen de la red."""
from __future__ import annotations

import copy
import json
from datetime import date, timedelta
from pathlib import Path

from energia.redata import Respuesta, huella_contenido, validar_estructura

FIXTURES = Path(__file__).parent / "fixtures"
SEMANA = (date(2026, 9, 28), date(2026, 10, 5))  # lo que cubren los fixtures de la semana


def fecha_de(punto: dict) -> date:
    return date.fromisoformat(punto["datetime"][:10])


def cargar_fixture(nombre: str) -> dict:
    return json.loads((FIXTURES / nombre).read_text(encoding="utf-8"))


def desplazar(texto_datetime: str, dias: int) -> str:
    """Suma días al datetime ISO conservando la hora y el desfase."""
    return (date.fromisoformat(texto_datetime[:10]) + timedelta(days=dias)).isoformat() + (
        texto_datetime[10:]
    )


class ClienteFalso:
    def __init__(
        self, ajuste=None, extras_dia_siguiente: bool = False, nombres: dict | None = None
    ):
        """
        ajuste: función (dataset, sistema, payload) que modifica la respuesta (simula revisiones
                o datos corruptos).
        extras_dia_siguiente: añade un punto del día siguiente al fin pedido, como hace la API real.
        nombres: {(dataset, sistema): fichero} para usar otro fixture.
        """
        self.ajuste = ajuste
        self.extras = extras_dia_siguiente
        self.nombres = nombres or {}
        self.llamadas: list[tuple] = []

    def obtener(self, dataset: str, sistema: str, desde: date, hasta: date) -> Respuesta:
        self.llamadas.append((dataset, sistema, desde, hasta))
        payload = copy.deepcopy(
            cargar_fixture(self.nombres.get((dataset, sistema), f"{dataset}_{sistema}.json"))
        )
        for serie in payload["included"]:
            dentro = [v for v in serie["attributes"]["values"] if desde <= fecha_de(v) <= hasta]
            if self.extras and dentro:
                extra = dict(dentro[-1])
                extra["datetime"] = desplazar(extra["datetime"], 1)
                dentro.append(extra)
            serie["attributes"]["values"] = dentro
        if self.ajuste:
            self.ajuste(dataset, sistema, payload)
        validar_estructura(payload)
        return Respuesta(dataset, sistema, desde, hasta, 200, payload, huella_contenido(payload))


def contar_puntos(dataset: str, sistemas, desde: date, hasta: date, *, sin_totales=False) -> int:
    """Cuenta los puntos de los fixtures dentro del rango (cálculo independiente del pipeline)."""
    n = 0
    for sistema in sistemas:
        for serie in cargar_fixture(f"{dataset}_{sistema}.json")["included"]:
            if sin_totales and serie["attributes"]["type"] == "total":
                continue
            n += sum(1 for v in serie["attributes"]["values"] if desde <= fecha_de(v) <= hasta)
    return n
