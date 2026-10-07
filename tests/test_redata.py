from datetime import date, timedelta

import pytest
import requests

from energia.redata import (
    MAX_DIAS_POR_LLAMADA,
    ClienteRedata,
    ErrorPeticion,
    ErrorRespuesta,
    ErrorServicio,
    huella_contenido,
    trocear,
    validar_estructura,
)
from tests.falso import cargar_fixture

# ----------------------------------------------------------------------------- trocear


def test_un_dia_es_un_solo_tramo():
    assert trocear(date(2026, 1, 1), date(2026, 1, 1)) == [(date(2026, 1, 1), date(2026, 1, 1))]


def test_365_dias_caben_en_una_llamada_y_366_necesitan_dos():
    inicio = date(2025, 1, 1)
    assert len(trocear(inicio, inicio + timedelta(days=364))) == 1
    assert len(trocear(inicio, inicio + timedelta(days=365))) == 2


@pytest.mark.parametrize("dias", [1, 30, 365, 366, 800, 1500])
def test_los_tramos_cubren_el_rango_sin_huecos_ni_solapes(dias):
    desde = date(2023, 1, 1)
    hasta = desde + timedelta(days=dias - 1)
    tramos = trocear(desde, hasta)
    assert tramos[0][0] == desde and tramos[-1][1] == hasta
    for (_, fin), (inicio, _) in zip(tramos, tramos[1:], strict=False):
        assert inicio == fin + timedelta(days=1)
    assert all((b - a).days + 1 <= MAX_DIAS_POR_LLAMADA for a, b in tramos)


def test_un_rango_invertido_no_genera_tramos():
    assert trocear(date(2026, 2, 1), date(2026, 1, 1)) == []


# ----------------------------------------------------------------------------- huella


def test_la_huella_ignora_los_metadatos_que_cambian_cada_dia():
    a = cargar_fixture("generacion_peninsular.json")
    b = cargar_fixture("generacion_peninsular.json")
    for serie in b["included"]:
        serie["attributes"]["last-update"] = "2099-01-01T00:00:00.000+01:00"
    assert huella_contenido(a) == huella_contenido(b)


def test_la_huella_cambia_si_cambia_un_valor():
    a = cargar_fixture("generacion_peninsular.json")
    b = cargar_fixture("generacion_peninsular.json")
    b["included"][0]["attributes"]["values"][0]["value"] += 0.01
    assert huella_contenido(a) != huella_contenido(b)


def test_la_huella_no_depende_del_orden_de_las_series():
    a = cargar_fixture("generacion_peninsular.json")
    b = cargar_fixture("generacion_peninsular.json")
    b["included"].reverse()
    assert huella_contenido(a) == huella_contenido(b)


# ----------------------------------------------------------------------------- contrato


def test_la_estructura_real_es_valida():
    validar_estructura(cargar_fixture("demanda_peninsular.json"))


@pytest.mark.parametrize(
    "malo",
    [
        [],
        {"data": {}},
        {"included": "no es una lista"},
        {"included": [{"attributes": {"values": []}}]},  # sin title
        {"included": [{"attributes": {"title": "X"}}]},  # sin values
        {"included": [{"attributes": {"title": "X", "values": [{"value": 1}]}}]},  # sin datetime
    ],
)
def test_una_estructura_inesperada_se_rechaza(malo):
    with pytest.raises(ErrorRespuesta):
        validar_estructura(malo)


# ----------------------------------------------------------------------------- cliente HTTP


class RespuestaHttp:
    def __init__(self, status=200, payload=None, texto="", json_valido=True):
        self.status_code = status
        self._payload = payload
        self.text = texto
        self._json_valido = json_valido

    def json(self):
        if not self._json_valido:
            raise ValueError("no es JSON")
        return self._payload


class SesionFalsa:
    """Devuelve (o lanza) una cosa por llamada y recuerda con qué parámetros se la llamó."""

    def __init__(self, *eventos):
        self.eventos = list(eventos)
        self.llamadas = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.llamadas.append({"url": url, "params": params, "headers": headers})
        evento = self.eventos.pop(0)
        if isinstance(evento, Exception):
            raise evento
        return evento


def cliente(sesion, **kw):
    esperas = []
    c = ClienteRedata(sesion=sesion, dormir=esperas.append, espera_base=1.0, **kw)
    c.esperas = esperas
    return c


OK = RespuestaHttp(200, cargar_fixture("demanda_peninsular.json"))


def test_peticion_correcta_devuelve_respuesta_con_huella():
    sesion = SesionFalsa(OK)
    r = cliente(sesion).obtener("demanda", "peninsular", date(2026, 9, 28), date(2026, 10, 5))
    assert r.estado_http == 200 and len(r.huella) == 64
    assert r.dataset == "demanda" and r.sistema == "peninsular"


def test_los_parametros_incluyen_el_sistema_electrico_salvo_en_el_nacional():
    sesion = SesionFalsa(OK, OK)
    c = cliente(sesion)
    c.obtener("generacion", "canarias", date(2026, 9, 28), date(2026, 10, 5))
    c.obtener("generacion", "nacional", date(2026, 9, 28), date(2026, 10, 5))
    canarias, nacional = (x["params"] for x in sesion.llamadas)
    assert canarias["geo_ids"] == "8742" and canarias["geo_limit"] == "canarias"
    assert canarias["start_date"] == "2026-09-28T00:00"
    assert canarias["end_date"] == "2026-10-05T23:59"
    assert canarias["time_trunc"] == "day"
    assert "geo_ids" not in nacional
    assert sesion.llamadas[0]["url"].endswith("/generacion/estructura-generacion")


def test_un_400_no_se_reintenta():
    sesion = SesionFalsa(RespuestaHttp(400, texto="Los datos solicitados no están disponibles"))
    c = cliente(sesion)
    with pytest.raises(ErrorPeticion):
        c.obtener("demanda", "peninsular", date(2026, 9, 28), date(2026, 10, 5))
    assert len(sesion.llamadas) == 1 and c.esperas == []


def test_un_500_se_reintenta_con_espera_creciente_y_acaba_funcionando():
    sesion = SesionFalsa(RespuestaHttp(503), RespuestaHttp(502), OK)
    c = cliente(sesion, pausa=0)
    r = c.obtener("demanda", "peninsular", date(2026, 9, 28), date(2026, 10, 5))
    assert r.estado_http == 200 and len(sesion.llamadas) == 3
    esperas = [e for e in c.esperas if e > 0]
    assert len(esperas) == 2 and esperas[0] < esperas[1]  # 1 s y 2 s (más un pequeño jitter)


def test_un_429_tambien_se_reintenta():
    sesion = SesionFalsa(RespuestaHttp(429), OK)
    assert cliente(sesion).obtener("demanda", "peninsular", date(2026, 9, 28), date(2026, 9, 29))


def test_si_la_red_falla_siempre_se_acaba_con_error_de_servicio():
    sesion = SesionFalsa(*[requests.ConnectionError("sin red")] * 3)
    with pytest.raises(ErrorServicio, match="3 intentos"):
        cliente(sesion).obtener("demanda", "peninsular", date(2026, 9, 28), date(2026, 10, 5))
    assert len(sesion.llamadas) == 3


def test_un_timeout_se_reintenta():
    sesion = SesionFalsa(requests.Timeout("lento"), OK)
    assert cliente(sesion).obtener("demanda", "peninsular", date(2026, 9, 28), date(2026, 9, 29))


def test_una_respuesta_que_no_es_json_se_rechaza_sin_reintentar():
    sesion = SesionFalsa(RespuestaHttp(200, json_valido=False))
    with pytest.raises(ErrorRespuesta):
        cliente(sesion).obtener("demanda", "peninsular", date(2026, 9, 28), date(2026, 9, 29))
    assert len(sesion.llamadas) == 1


def test_un_cambio_de_contrato_se_detecta():
    sesion = SesionFalsa(RespuestaHttp(200, {"incluido": []}))
    with pytest.raises(ErrorRespuesta):
        cliente(sesion).obtener("demanda", "peninsular", date(2026, 9, 28), date(2026, 9, 29))


@pytest.mark.parametrize(
    ("dataset", "sistema", "desde", "hasta"),
    [
        ("precios", "peninsular", date(2026, 1, 1), date(2026, 1, 2)),
        ("demanda", "marte", date(2026, 1, 1), date(2026, 1, 2)),
        ("demanda", "peninsular", date(2026, 1, 2), date(2026, 1, 1)),
        ("demanda", "peninsular", date(2025, 1, 1), date(2026, 1, 1)),  # 366 días
    ],
)
def test_los_argumentos_invalidos_se_rechazan_antes_de_llamar(dataset, sistema, desde, hasta):
    sesion = SesionFalsa()
    with pytest.raises(ValueError):
        cliente(sesion).obtener(dataset, sistema, desde, hasta)
    assert sesion.llamadas == []
