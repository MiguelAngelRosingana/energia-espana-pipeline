"""Pruebas contra la API REAL de Red Eléctrica. Se excluyen por defecto (`pytest -m live`).

Las ejecuta cada día el workflow programado: comprueban que la fuente sigue cumpliendo las
premisas en las que se apoya el pipeline. Si alguna falla, la fuente ha cambiado.
"""
from datetime import date, timedelta

import pytest
import requests

from energia.redata import MAX_DIAS_POR_LLAMADA, SISTEMAS, ClienteRedata, validar_estructura

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def ventana():
    hasta = date.today() - timedelta(days=3)
    return hasta - timedelta(days=6), hasta


def _por_dia(payload):
    dias = {}
    for serie in payload["included"]:
        total = serie["attributes"]["type"] == "total"
        for v in serie["attributes"]["values"]:
            d = dias.setdefault(v["datetime"][:10], {"total": None, "suma": 0.0})
            if total:
                d["total"] = v["value"]
            else:
                d["suma"] += v["value"]
    return dias


def test_el_contrato_de_generacion_y_la_suma_de_tecnologias_se_mantienen(ventana):
    cliente = ClienteRedata()
    for sistema in ("peninsular", "canarias", "nacional"):
        r = cliente.obtener("generacion", sistema, *ventana)
        validar_estructura(r.payload)
        dias = _por_dia(r.payload)
        assert len(dias) >= 6, f"{sistema}: faltan días"
        for dia, d in dias.items():
            assert d["total"] is not None, f"{sistema} {dia}: sin total"
            assert abs(d["total"] - d["suma"]) < 0.05, f"{sistema} {dia}: el total no cuadra"


def test_la_suma_de_los_sistemas_sigue_siendo_el_nacional(ventana):
    cliente = ClienteRedata()
    suma = 0.0
    for sistema in SISTEMAS:
        for serie in cliente.obtener("generacion", sistema, *ventana).payload["included"]:
            if serie["attributes"]["type"] == "total":
                suma += sum(v["value"] for v in serie["attributes"]["values"])
    nacional = sum(
        v["value"]
        for serie in cliente.obtener("generacion", "nacional", *ventana).payload["included"]
        if serie["attributes"]["type"] == "total"
        for v in serie["attributes"]["values"]
    )
    assert abs(suma - nacional) < 0.5


def test_la_demanda_existe_y_es_positiva_en_los_cinco_sistemas(ventana):
    cliente = ClienteRedata()
    for sistema in SISTEMAS:
        series = cliente.obtener("demanda", sistema, *ventana).payload["included"]
        valores = [v["value"] for s in series for v in s["attributes"]["values"]]
        assert len(valores) >= 6 and all(v > 0 for v in valores), sistema


def test_la_api_sigue_rechazando_rangos_de_mas_de_un_ano():
    """Premisa del troceado: rangos claramente largos dan 400. Medido: 367 días OK, 369 días 400.
    El pipeline trocea en 365 días, así que solo falla si la API pasa a admitir rangos mucho
    mayores (entonces se podría relajar el troceado)."""
    hasta = date.today() - timedelta(days=3)
    desde = hasta - timedelta(days=MAX_DIAS_POR_LLAMADA + 35)
    r = requests.get(
        "https://apidatos.ree.es/es/datos/generacion/estructura-generacion",
        params={"start_date": f"{desde}T00:00", "end_date": f"{hasta}T23:59", "time_trunc": "day"},
        timeout=60,
    )
    assert r.status_code == 400
