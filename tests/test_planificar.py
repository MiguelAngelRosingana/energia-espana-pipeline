from datetime import date

import pytest

from energia.calidad import cargar_controles
from energia.db import SQL_DIR
from energia.pipeline import planificar
from energia.redata import claves_por_defecto

INICIO = date(2023, 1, 1)
CLAVES = [("generacion", "peninsular"), ("demanda", "canarias")]


def test_sin_marca_de_agua_se_parte_de_la_fecha_de_inicio():
    plan = planificar({}, CLAVES, hasta=date(2023, 1, 31), desde=None, solape_dias=7,
                      fecha_inicio=INICIO)
    assert {(p.dataset, p.sistema, p.desde, p.hasta) for p in plan} == {
        ("generacion", "peninsular", INICIO, date(2023, 1, 31)),
        ("demanda", "canarias", INICIO, date(2023, 1, 31)),
    }


def test_con_marca_de_agua_se_vuelven_a_pedir_los_ultimos_dias():
    marcas = {("generacion", "peninsular"): date(2026, 10, 5)}
    plan = planificar(marcas, CLAVES[:1], hasta=date(2026, 10, 6), desde=None, solape_dias=7,
                      fecha_inicio=INICIO)
    # solape de 7 días contando la propia marca: 5 oct y los 6 anteriores
    assert plan[0].desde == date(2026, 9, 29) and plan[0].hasta == date(2026, 10, 6)


def test_solape_de_un_dia_parte_de_la_propia_marca():
    marcas = {("generacion", "peninsular"): date(2026, 10, 5)}
    plan = planificar(marcas, CLAVES[:1], date(2026, 10, 6), None, 1, INICIO)
    assert plan[0].desde == date(2026, 10, 5)


def test_cada_clave_usa_su_propia_marca():
    marcas = {("generacion", "peninsular"): date(2026, 10, 5)}  # demanda/canarias no tiene marca
    plan = planificar(marcas, CLAVES, date(2026, 10, 6), None, 3, INICIO)
    desdes = {}
    for p in plan:  # con varios tramos, el primero es el de menor fecha
        desdes[(p.dataset, p.sistema)] = min(p.desde, desdes.get((p.dataset, p.sistema), p.desde))
    assert desdes[("generacion", "peninsular")] == date(2026, 10, 3)
    assert desdes[("demanda", "canarias")] == INICIO


def test_desde_explicito_manda_sobre_la_marca():
    marcas = {("generacion", "peninsular"): date(2026, 10, 5)}
    plan = planificar(marcas, CLAVES[:1], date(2026, 10, 6), date(2026, 1, 1), 7, INICIO)
    assert plan[0].desde == date(2026, 1, 1)


def test_un_rango_largo_se_trocea_a_lo_que_admite_la_api():
    plan = planificar({}, CLAVES[:1], hasta=date(2024, 12, 31), desde=None, solape_dias=7,
                      fecha_inicio=INICIO)
    assert len(plan) == 3  # 731 días = 365 + 365 + 1
    assert plan[0].desde == INICIO and plan[-1].hasta == date(2024, 12, 31)
    assert all((p.hasta - p.desde).days + 1 <= 365 for p in plan)


def test_si_la_marca_esta_por_delante_de_hasta_no_hay_nada_que_pedir():
    marcas = {("generacion", "peninsular"): date(2026, 12, 31)}
    assert planificar(marcas, CLAVES[:1], date(2026, 10, 1), None, 1, INICIO) == []


def test_el_solape_debe_ser_positivo():
    with pytest.raises(ValueError):
        planificar({}, CLAVES, date(2026, 1, 1), None, 0, INICIO)


def test_las_claves_por_defecto_son_seis_de_generacion_y_cinco_de_demanda():
    claves = claves_por_defecto()
    assert len([c for c in claves if c[0] == "generacion"]) == 6  # 5 sistemas + nacional
    assert len([c for c in claves if c[0] == "demanda"]) == 5
    assert ("demanda", "nacional") not in claves


# ------------------------------------------------------------------ SQL y controles (estático)


def test_los_controles_declaran_alcance_y_severidad_validos():
    controles = cargar_controles()
    assert len(controles) >= 10
    assert {c.alcance for c in controles} == {"lote", "modelo"}
    assert {c.severidad for c in controles} == {"error", "aviso"}
    assert len({c.nombre for c in controles}) == len(controles)


def test_hay_controles_que_bloquean_y_otros_que_solo_avisan():
    por_nombre = {c.nombre: c.severidad for c in cargar_controles()}
    assert por_nombre["suma_sistemas_igual_nacional"] == "error"
    assert por_nombre["total_igual_suma_tecnologias"] == "error"
    assert por_nombre["huecos_de_fechas"] == "aviso"  # completitud: avisa, no bloquea
    assert por_nombre["frescura"] == "aviso"


def test_los_ficheros_sql_no_contienen_signos_de_porcentaje():
    """psycopg2 interpreta % como marcador de parámetros: mejor que no aparezca en el SQL."""
    for fichero in SQL_DIR.rglob("*.sql"):
        assert "%" not in fichero.read_text(encoding="utf-8"), fichero.name
