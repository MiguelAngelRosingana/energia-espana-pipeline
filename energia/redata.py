"""Cliente de la API REData de Red Eléctrica (https://www.ree.es/es/apidatos).

Las decisiones de este módulo se apoyan en pruebas contra la API real (octubre de 2026):

* Con ``time_trunc=day`` la API acepta rangos de hasta algo más de un año (200 con 367 días,
  HTTP 400 desde 369). El pipeline se queda por debajo, en 365 días por llamada, para no
  depender de ese margen exacto.
* Los errores de petición (rango demasiado largo, fechas invertidas o con formato inválido)
  devuelven siempre el mismo 400 con el mensaje «Los datos solicitados no están disponibles en
  este momento. Inténtelo de nuevo más tarde», aunque el problema NO sea transitorio. Por eso un
  400 no se reintenta: repetirlo daría exactamente lo mismo. Solo se reintentan los errores de
  red, los 429 y los 5xx.
* La respuesta incluye metadatos (``last-update``) que cambian cada día aunque los datos no
  cambien. La huella que se usa para no guardar dos veces lo mismo se calcula solo sobre los datos.
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass
from datetime import date, timedelta

import requests

log = logging.getLogger(__name__)

MAX_DIAS_POR_LLAMADA = 365

# Identificadores de los sistemas eléctricos en la API.
SISTEMAS_GEO = {
    "peninsular": 8741,
    "canarias": 8742,
    "baleares": 8743,
    "ceuta": 8744,
    "melilla": 8745,
}
SISTEMAS = tuple(SISTEMAS_GEO)
NACIONAL = "nacional"  # solo para generación: se usa para comprobar que cuadra con los sistemas

DATASETS = {
    "generacion": "generacion/estructura-generacion",
    "demanda": "demanda/evolucion",
}


def claves_por_defecto() -> list[tuple[str, str]]:
    """Pares (conjunto de datos, sistema) que carga el pipeline."""
    return [("generacion", s) for s in (*SISTEMAS, NACIONAL)] + [("demanda", s) for s in SISTEMAS]


class ErrorRedata(Exception):
    """Error al obtener datos de REData."""


class ErrorPeticion(ErrorRedata):
    """La API rechazó la petición (4xx). No se reintenta."""


class ErrorServicio(ErrorRedata):
    """La API no respondió bien tras varios reintentos (red, 429 o 5xx)."""


class ErrorRespuesta(ErrorRedata):
    """La API respondió 200 pero con una estructura inesperada (cambio de contrato)."""


@dataclass(frozen=True)
class Respuesta:
    dataset: str
    sistema: str
    desde: date
    hasta: date
    estado_http: int
    payload: dict
    huella: str


def trocear(
    desde: date, hasta: date, max_dias: int = MAX_DIAS_POR_LLAMADA
) -> list[tuple[date, date]]:
    """Divide [desde, hasta] (ambos incluidos) en tramos de como máximo ``max_dias`` días."""
    tramos = []
    inicio = desde
    while inicio <= hasta:
        fin = min(inicio + timedelta(days=max_dias - 1), hasta)
        tramos.append((inicio, fin))
        inicio = fin + timedelta(days=1)
    return tramos


def huella_contenido(payload: dict) -> str:
    """SHA-256 de los datos (series y valores), sin los metadatos que cambian a diario."""
    series = []
    for serie in payload.get("included", []):
        atributos = serie.get("attributes", {})
        valores = [
            (v.get("datetime"), v.get("value"), v.get("percentage"))
            for v in atributos.get("values", [])
        ]
        series.append(
            (str(serie.get("id")), atributos.get("title"), atributos.get("type"), valores)
        )
    series.sort(key=lambda s: s[0])
    texto = json.dumps(series, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def validar_estructura(payload: object) -> None:
    """Comprueba el contrato mínimo que el resto del pipeline da por supuesto."""
    if not isinstance(payload, dict) or not isinstance(payload.get("included"), list):
        raise ErrorRespuesta("La respuesta no tiene la lista 'included' esperada")
    for serie in payload["included"]:
        atributos = serie.get("attributes") if isinstance(serie, dict) else None
        if not isinstance(atributos, dict) or "title" not in atributos:
            raise ErrorRespuesta("Una serie no tiene 'attributes.title'")
        if not isinstance(atributos.get("values"), list):
            raise ErrorRespuesta(f"La serie {atributos['title']!r} no tiene 'values'")
        for v in atributos["values"]:
            if not isinstance(v, dict) or "datetime" not in v or "value" not in v:
                raise ErrorRespuesta(f"Un valor de {atributos['title']!r} no tiene datetime/value")


class ClienteRedata:
    def __init__(
        self,
        base_url: str = "https://apidatos.ree.es/es/datos",
        sesion: requests.Session | None = None,
        reintentos: int = 3,
        espera_base: float = 1.0,
        timeout: tuple[float, float] = (10, 40),
        pausa: float = 0.2,
        dormir=time.sleep,
    ):
        self.base_url = base_url.rstrip("/")
        self.sesion = sesion or requests.Session()
        self.reintentos = reintentos
        self.espera_base = espera_base
        self.timeout = timeout
        self.pausa = pausa
        self.dormir = dormir

    def obtener(self, dataset: str, sistema: str, desde: date, hasta: date) -> Respuesta:
        if dataset not in DATASETS:
            raise ValueError(f"Conjunto de datos desconocido: {dataset}")
        if sistema != NACIONAL and sistema not in SISTEMAS_GEO:
            raise ValueError(f"Sistema desconocido: {sistema}")
        if hasta < desde:
            raise ValueError("'hasta' no puede ser anterior a 'desde'")
        if (hasta - desde).days + 1 > MAX_DIAS_POR_LLAMADA:
            raise ValueError(f"Rango de más de {MAX_DIAS_POR_LLAMADA} días: usa trocear()")

        params = {
            "start_date": f"{desde.isoformat()}T00:00",
            "end_date": f"{hasta.isoformat()}T23:59",
            "time_trunc": "day",
        }
        if sistema != NACIONAL:
            params.update(
                geo_trunc="electric_system", geo_limit=sistema, geo_ids=str(SISTEMAS_GEO[sistema])
            )
        url = f"{self.base_url}/{DATASETS[dataset]}"
        cabeceras = {
            "Accept": "application/json",
            "User-Agent": "energia-espana-pipeline/0.1 (proyecto de portfolio)",
        }

        ultimo_error = "sin intentos"
        for intento in range(1, self.reintentos + 1):
            try:
                r = self.sesion.get(url, params=params, headers=cabeceras, timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as e:
                ultimo_error = f"{type(e).__name__}: {e}"
            else:
                if r.status_code == 200:
                    try:
                        payload = r.json()
                    except ValueError as e:
                        raise ErrorRespuesta(f"La respuesta no es JSON: {e}") from e
                    validar_estructura(payload)
                    self.dormir(self.pausa)
                    return Respuesta(
                        dataset, sistema, desde, hasta, r.status_code, payload,
                        huella_contenido(payload),
                    )
                if r.status_code == 429 or r.status_code >= 500:
                    ultimo_error = f"HTTP {r.status_code}"
                else:
                    raise ErrorPeticion(
                        f"HTTP {r.status_code} en {dataset}/{sistema} {desde}..{hasta}: "
                        f"{r.text[:200]}"
                    )
            if intento < self.reintentos:
                espera = self.espera_base * 2 ** (intento - 1) + random.uniform(0, 0.25)
                log.warning(
                    "Intento %d/%d fallido (%s). Reintento en %.1f s",
                    intento, self.reintentos, ultimo_error, espera,
                )
                self.dormir(espera)
        raise ErrorServicio(
            f"{dataset}/{sistema} {desde}..{hasta}: sin respuesta válida tras "
            f"{self.reintentos} intentos ({ultimo_error})"
        )
