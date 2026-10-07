"""Tests de integración: PostgreSQL real + respuestas reales de la API (fixtures)."""
from datetime import date

import pytest
from sqlalchemy import text

from energia.db import aplicar_esquema
from energia.pipeline import ejecutar, reprocesar
from energia.redata import SISTEMAS
from tests.falso import ClienteFalso, cargar_fixture, contar_puntos, fecha_de

pytestmark = pytest.mark.integracion

DESDE, HASTA = date(2026, 9, 28), date(2026, 10, 5)
HOY = date(2026, 10, 6)  # con hoy = 6 oct, "hasta" por defecto es el 5 oct


def correr(db, cliente=None, **kw):
    kw.setdefault("hoy", HOY)
    kw.setdefault("desde", DESDE)
    kw.setdefault("solape_dias", 7)
    return ejecutar(db, cliente or ClienteFalso(), **kw)


def uno(db, sql, **params):
    with db.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


def filas(db, sql, **params):
    with db.connect() as conn:
        return conn.execute(text(sql), params).all()


def cuentas(db):
    return {
        t: uno(db, f"SELECT count(*) FROM dwh.{t}")
        for t in ("fact_generacion", "fact_generacion_total", "fact_demanda", "dim_fecha")
    }


# ------------------------------------------------------------------ primera carga


def test_la_primera_carga_trae_exactamente_lo_que_hay_en_la_fuente(db):
    r = correr(db)
    assert r.estado == "ok", r.error

    tecnologias = contar_puntos("generacion", SISTEMAS, DESDE, HASTA, sin_totales=True)
    totales = len(SISTEMAS) * 8
    esperado = {
        "fact_generacion": tecnologias,
        "fact_generacion_total": totales,
        "fact_demanda": contar_puntos("demanda", SISTEMAS, DESDE, HASTA),
        "dim_fecha": 8,
    }
    assert cuentas(db) == esperado
    assert r.hechos_nuevos == tecnologias + totales + esperado["fact_demanda"]
    assert r.hechos_modificados == 0 and r.hechos_iguales == 0
    assert r.respuestas_nuevas == 11 and r.respuestas_repetidas == 0


def test_una_serie_que_no_reporta_un_dia_no_se_rellena_con_ceros(db):
    """Turbina de vapor (Península) no aparece todos los días en los datos reales."""
    correr(db)
    serie = next(s for s in cargar_fixture("generacion_peninsular.json")["included"]
                 if s["attributes"]["title"] == "Turbina de vapor")
    dias_con_dato = {fecha_de(v) for v in serie["attributes"]["values"]}
    assert 0 < len(dias_con_dato) < 8, "el fixture ya no ilustra el caso"

    en_bd = uno(db, """
        SELECT count(*) FROM dwh.fact_generacion f
        JOIN dwh.dim_tecnologia t USING (tecnologia_id)
        JOIN dwh.dim_sistema s USING (sistema_id)
        WHERE t.nombre = 'Turbina de vapor' AND s.codigo = 'peninsular'""")
    assert en_bd == len(dias_con_dato)
    # y una tecnología que ese sistema nunca reporta no tiene ninguna fila
    assert uno(db, """
        SELECT count(*) FROM dwh.fact_generacion f
        JOIN dwh.dim_tecnologia t USING (tecnologia_id)
        JOIN dwh.dim_sistema s USING (sistema_id)
        WHERE t.nombre = 'Nuclear' AND s.codigo = 'canarias'""") == 0


def test_el_nacional_solo_se_usa_para_comprobar_y_no_entra_al_modelo(db):
    correr(db)
    assert uno(db, "SELECT count(*) FROM dwh.dim_sistema WHERE codigo = 'nacional'") == 0
    assert uno(db, "SELECT count(*) FROM raw.respuestas WHERE sistema = 'nacional'") == 1
    # el total de la Península más el de las islas es el nacional, así que no se cuenta dos veces
    nacional = next(s for s in cargar_fixture("generacion_nacional.json")["included"]
                    if s["attributes"]["type"] == "total")["attributes"]["values"]
    suma_nacional = sum(v["value"] for v in nacional if DESDE <= fecha_de(v) <= HASTA)
    assert float(uno(db, "SELECT sum(mwh_total) FROM dwh.fact_generacion_total")) == pytest.approx(
        suma_nacional, abs=0.5)


def test_las_dimensiones_se_rellenan_con_su_clasificacion(db):
    correr(db)
    with db.connect() as conn:
        familias = dict(conn.execute(text("SELECT nombre, familia FROM dwh.dim_tecnologia")).all())
        renovable = dict(
            conn.execute(text("SELECT nombre, es_renovable FROM dwh.dim_tecnologia")).all()
        )
    assert familias["Eólica"] == "Eólica" and familias["Ciclo combinado"] == "Gas"
    assert renovable["Solar fotovoltaica"] is True and renovable["Nuclear"] is False
    assert "Generación total" not in familias  # el total no es una tecnología
    dias = uno(db, "SELECT dia_semana FROM dwh.dim_fecha WHERE fecha = '2026-10-05'")
    assert dias == 1  # lunes
    assert uno(db, "SELECT nombre_mes FROM dwh.dim_fecha WHERE fecha = '2026-10-05'") == "octubre"


def test_los_negativos_pequenos_se_cargan_y_se_avisan_pero_no_bloquean(db):
    r = correr(db)
    assert r.estado == "ok"
    minimo = float(uno(db, "SELECT min(mwh) FROM dwh.fact_generacion"))
    assert minimo < 0, "los datos reales de esa semana incluyen carbón neto negativo"
    aviso = next(c for c in r.controles if c.control == "negativos_menores")
    assert aviso.estado == "fallo" and aviso.severidad == "aviso" and aviso.filas > 0


# ------------------------------------------------------------------ idempotencia y revisiones


def test_ejecutar_dos_veces_lo_mismo_no_cambia_nada(db):
    correr(db)
    antes = cuentas(db)
    raw_antes = uno(db, "SELECT count(*) FROM raw.respuestas")
    suma_antes = uno(db, "SELECT sum(mwh) FROM dwh.fact_generacion")

    r = correr(db)
    assert r.estado == "ok"
    assert r.respuestas_nuevas == 0 and r.respuestas_repetidas == 11
    assert r.hechos_nuevos == r.hechos_modificados == 0
    assert cuentas(db) == antes
    assert uno(db, "SELECT count(*) FROM raw.respuestas") == raw_antes
    assert uno(db, "SELECT sum(mwh) FROM dwh.fact_generacion") == suma_antes


def _revision_coherente(dataset, sistema, payload, *, dia=date(2026, 10, 2), delta=100.0):
    """Simula que la fuente revisa la eólica de un día: sube el dato de la tecnología y el total,
    en la Península y en el nacional (así siguen cuadrando todas las sumas)."""
    if dataset != "generacion" or sistema not in ("peninsular", "nacional"):
        return
    for serie in payload["included"]:
        titulo, tipo = serie["attributes"]["title"], serie["attributes"]["type"]
        if titulo == "Eólica" or tipo == "total":
            for v in serie["attributes"]["values"]:
                if fecha_de(v) == dia:
                    v["value"] = round(v["value"] + delta, 2)


def test_una_revision_de_la_fuente_actualiza_el_hecho_y_conserva_la_version_anterior(db):
    correr(db)
    antes = float(uno(db, """
        SELECT f.mwh FROM dwh.fact_generacion f
        JOIN dwh.dim_tecnologia t USING (tecnologia_id)
        JOIN dwh.dim_sistema s USING (sistema_id)
        JOIN dwh.dim_fecha d USING (fecha_id)
        WHERE t.nombre = 'Eólica' AND s.codigo = 'peninsular' AND d.fecha = '2026-10-02'"""))

    r = correr(db, ClienteFalso(ajuste=_revision_coherente))
    assert r.estado == "ok", r.error
    assert r.hechos_modificados == 2  # la eólica de ese día y el total de ese día
    assert r.hechos_nuevos == 0
    assert r.respuestas_nuevas == 2  # solo cambian las dos respuestas revisadas (Pen. y nacional)

    despues = float(uno(db, """
        SELECT f.mwh FROM dwh.fact_generacion f
        JOIN dwh.dim_tecnologia t USING (tecnologia_id)
        JOIN dwh.dim_sistema s USING (sistema_id)
        JOIN dwh.dim_fecha d USING (fecha_id)
        WHERE t.nombre = 'Eólica' AND s.codigo = 'peninsular' AND d.fecha = '2026-10-02'"""))
    assert despues == pytest.approx(antes + 100.0)
    # raw conserva las dos versiones de la respuesta de la Península
    assert uno(db, "SELECT count(*) FROM raw.respuestas "
                   "WHERE dataset = 'generacion' AND sistema = 'peninsular'") == 2
    assert uno(db, """SELECT count(*) FROM dwh.fact_generacion
                      WHERE actualizado_en > cargado_en""") == 1


# ------------------------------------------------------------------ incremental


def test_la_marca_de_agua_avanza_y_la_ventana_de_solape_se_relee(db):
    cliente1 = ClienteFalso()
    r1 = correr(db, cliente1, hasta=date(2026, 9, 30))
    assert r1.estado == "ok"
    sql_marcas = "SELECT dataset, sistema, ultima_fecha FROM etl.marcas_agua"
    marcas = {(d, s): f for d, s, f in filas(db, sql_marcas)}
    assert len(marcas) == 11 and set(marcas.values()) == {date(2026, 9, 30)}
    por_dia = cuentas(db)["fact_demanda"] // 3  # 3 días cargados (28, 29 y 30)

    # segunda ejecución SIN --desde: parte de la marca menos el solape (2 días)
    cliente2 = ClienteFalso()
    r2 = ejecutar(db, cliente2, hoy=date(2026, 10, 3), hasta=date(2026, 10, 2), solape_dias=2)
    assert r2.estado == "ok", r2.error
    assert {c[2] for c in cliente2.llamadas} == {date(2026, 9, 29)}  # 30 sep menos 1 día
    assert {c[3] for c in cliente2.llamadas} == {date(2026, 10, 2)}
    assert cuentas(db)["dim_fecha"] == 5  # 28 sep .. 2 oct
    assert r2.hechos_iguales > 0, "el solape debe re-leer días ya cargados sin duplicarlos"
    assert r2.hechos_nuevos > 0
    assert cuentas(db)["fact_demanda"] == por_dia * 5
    marcas2 = {s for (_, s, f) in filas(db, sql_marcas) if f == date(2026, 10, 2)}
    assert len(marcas2) == 6  # los 6 sistemas (incl. nacional) en 2 oct


def test_el_dia_en_curso_no_se_pide_por_defecto(db):
    cliente = ClienteFalso()
    ejecutar(db, cliente, hoy=date(2026, 10, 3), desde=date(2026, 9, 28))
    assert {c[3] for c in cliente.llamadas} == {date(2026, 10, 2)}  # ayer, no hoy


# ------------------------------------------------------------------ rarezas de la API real


def test_los_puntos_fuera_de_rango_se_descartan_y_se_avisan(db):
    r = correr(db, ClienteFalso(extras_dia_siguiente=True))
    assert r.estado == "ok", r.error
    assert uno(db, "SELECT max(fecha) FROM dwh.dim_fecha") == HASTA  # nada de después del fin
    aviso = next(c for c in r.controles if c.control == "puntos_fuera_de_rango")
    assert aviso.estado == "fallo" and aviso.filas > 0 and aviso.severidad == "aviso"
    # y los hechos son exactamente los mismos que sin el extra
    assert cuentas(db)["fact_demanda"] == contar_puntos("demanda", SISTEMAS, DESDE, HASTA)


def test_el_cambio_de_hora_no_desplaza_ni_duplica_dias(db):
    cliente = ClienteFalso(nombres={("generacion", "peninsular"):
                                    "generacion_peninsular_cambio_de_hora.json"})
    r = ejecutar(db, cliente, hoy=date(2026, 4, 2), desde=date(2026, 3, 26), hasta=date(2026, 4, 1),
                 claves=[("generacion", "peninsular")])
    assert r.estado == "ok", r.error
    with db.connect() as conn:
        fechas = [f for (f,) in conn.execute(text("SELECT fecha FROM dwh.dim_fecha ORDER BY 1"))]
        por_dia = dict(conn.execute(text(
            "SELECT d.fecha, count(*) FROM dwh.fact_generacion f "
            "JOIN dwh.dim_fecha d USING (fecha_id) GROUP BY 1")).all())
    assert [f.isoformat() for f in fechas] == [
        "2026-03-26", "2026-03-27", "2026-03-28", "2026-03-29",
        "2026-03-30", "2026-03-31", "2026-04-01"]
    assert len(set(por_dia.values())) == 1, "cada día debe tener las mismas tecnologías"


# ------------------------------------------------------------------ calidad: el freno


def _corromper_nacional(dataset, sistema, payload):
    """El nacional deja de ser la suma de los sistemas: la fuente sería incoherente."""
    if (dataset, sistema) != ("generacion", "nacional"):
        return
    for serie in payload["included"]:
        if serie["attributes"]["title"] == "Eólica":
            serie["attributes"]["values"][0]["value"] += 500


def test_un_control_de_error_deshace_todo_y_deja_las_respuestas_en_cuarentena(db):
    r = correr(db, ClienteFalso(ajuste=_corromper_nacional))
    assert r.estado == "error"
    assert "suma_sistemas_igual_nacional" in r.error
    # el modelo queda exactamente como estaba: vacío
    assert cuentas(db) == {"fact_generacion": 0, "fact_generacion_total": 0,
                           "fact_demanda": 0, "dim_fecha": 0}
    assert uno(db, "SELECT count(*) FROM etl.marcas_agua") == 0
    # lo descargado no se pierde: está en raw, en cuarentena y con el motivo
    assert uno(db, "SELECT count(*) FROM raw.respuestas WHERE estado = 'cuarentena'") == 11
    assert "suma_sistemas_igual_nacional" in uno(db, "SELECT motivo FROM raw.respuestas LIMIT 1")
    assert r.en_cuarentena == 11
    # y la evidencia del fallo queda registrada, aunque la transacción se deshiciera
    fallo = filas(db, "SELECT estado, severidad, filas_afectadas FROM etl.resultados_calidad "
                      "WHERE run_id = :r AND control = 'suma_sistemas_igual_nacional'", r=r.run_id)
    assert [tuple(x) for x in fallo] == [("fallo", "error", 1)]
    assert uno(db, "SELECT estado FROM etl.ejecuciones WHERE run_id = :r", r=r.run_id) == "error"


def test_tras_un_fallo_de_calidad_la_siguiente_ejecucion_se_recupera(db):
    malo = correr(db, ClienteFalso(ajuste=_corromper_nacional))
    assert malo.estado == "error"
    bueno = correr(db)  # la fuente ya devuelve datos coherentes
    assert bueno.estado == "ok", bueno.error
    # las 10 respuestas buenas que arrastró la cuarentena se reencolan y se procesan
    assert bueno.respuestas_reencoladas == 10 and bueno.respuestas_nuevas == 1
    assert cuentas(db)["fact_demanda"] == 40
    # lo que estaba en cuarentena sigue ahí hasta que alguien lo reprocese o lo descarte
    assert uno(db, "SELECT count(*) FROM raw.respuestas WHERE estado = 'cuarentena'") == 1


def test_reprocesar_devuelve_la_cuarentena_a_pendiente(db):
    correr(db, ClienteFalso(ajuste=_corromper_nacional))
    assert reprocesar(db) == 11
    assert uno(db, "SELECT count(*) FROM raw.respuestas WHERE estado = 'pendiente'") == 11


def test_un_fallo_de_la_fuente_a_mitad_no_pierde_lo_descargado(db):
    class ClienteQueFalla(ClienteFalso):
        def obtener(self, dataset, sistema, desde, hasta):
            if len(self.llamadas) == 6:
                raise RuntimeError("la fuente se cayó")
            return super().obtener(dataset, sistema, desde, hasta)

    r = correr(db, ClienteQueFalla())
    assert r.estado == "error" and "se cayó" in r.error
    assert uno(db, "SELECT count(*) FROM raw.respuestas") == 6
    assert cuentas(db)["fact_generacion"] == 0  # no se transformó nada a medias
    # la siguiente ejecución aprovecha lo ya descargado y completa el resto
    ok = correr(db)
    assert ok.estado == "ok" and ok.respuestas_repetidas == 6 and ok.respuestas_nuevas == 5


def test_el_contrato_de_la_api_roto_hace_fallar_la_ejecucion_con_un_mensaje_claro(db):
    def romper(dataset, sistema, payload):
        payload.pop("included")

    class ClienteSinValidar(ClienteFalso):
        def obtener(self, dataset, sistema, desde, hasta):
            # el cliente real valida; aquí simulamos que lo hace y detecta el cambio
            from energia.redata import ErrorRespuesta
            raise ErrorRespuesta("La respuesta no tiene la lista 'included' esperada")

    r = correr(db, ClienteSinValidar())
    assert r.estado == "error" and "included" in r.error


# ------------------------------------------------------------------ modelo y vistas


def test_el_esquema_se_puede_aplicar_varias_veces(db):
    assert aplicar_esquema(db) == aplicar_esquema(db)
    assert uno(db, "SELECT count(*) FROM dwh.dim_sistema") == 5


def test_las_claves_foraneas_impiden_hechos_huerfanos(db):
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError), db.begin() as conn:
        conn.execute(text("INSERT INTO dwh.fact_demanda (fecha_id, sistema_id, mwh) "
                          "VALUES (20260101, 8741, 1000)"))


def test_la_vista_de_balance_cuadra_con_las_tablas_de_hechos(db):
    correr(db)
    with db.connect() as conn:
        v = conn.execute(text("""
            SELECT generacion_total_mwh, generacion_renovable_mwh, porcentaje_renovable, demanda_mwh
            FROM dwh.v_balance_diario
            WHERE sistema = 'peninsular' AND fecha = '2026-10-05'""")).one()
    pen = cargar_fixture("generacion_peninsular.json")
    ult = {s["attributes"]["title"]: next(x for x in s["attributes"]["values"]
                                          if fecha_de(x) == date(2026, 10, 5))
           for s in pen["included"]}
    tipos = {s["attributes"]["title"]: s["attributes"]["type"] for s in pen["included"]}
    esperado_ren = sum(p["value"] for t, p in ult.items() if tipos[t] == "Renovable")
    assert float(v.generacion_total_mwh) == pytest.approx(ult["Generación total"]["value"])
    assert float(v.generacion_renovable_mwh) == pytest.approx(esperado_ren)
    total = ult["Generación total"]["value"]
    assert float(v.porcentaje_renovable) == pytest.approx(esperado_ren / total)
    assert 0 < float(v.porcentaje_renovable) < 1 and float(v.demanda_mwh) > 0


def test_el_porcentaje_mensual_pondera_por_produccion_y_no_promedia_porcentajes(db):
    correr(db)
    with db.connect() as conn:
        mensual = float(conn.execute(text(
            "SELECT porcentaje_renovable FROM dwh.v_balance_mensual "
            "WHERE sistema = 'peninsular' AND anio_mes = '2026-10'")).scalar_one())
        diarios = [float(x) for (x,) in conn.execute(text(
            "SELECT porcentaje_renovable FROM dwh.v_balance_diario "
            "WHERE sistema = 'peninsular' AND anio_mes = '2026-10'"))]
        suma_ren, suma_tot = conn.execute(text(
            "SELECT sum(generacion_renovable_mwh), sum(generacion_total_mwh) "
            "FROM dwh.v_balance_diario "
            "WHERE sistema = 'peninsular' AND anio_mes = '2026-10'")).one()
    assert mensual == pytest.approx(float(suma_ren) / float(suma_tot))
    media_simple = sum(diarios) / len(diarios)
    assert mensual != pytest.approx(media_simple, abs=1e-9)  # no es la media de los diarios


def test_el_detalle_trae_los_porcentajes_calculados(db):
    correr(db)
    with db.connect() as conn:
        suma = conn.execute(text(
            "SELECT sum(porcentaje_del_total) FROM dwh.v_generacion_detalle "
            "WHERE sistema = 'canarias' AND fecha = '2026-10-05'")).scalar_one()
    assert float(suma) == pytest.approx(1.0, abs=1e-6)


def test_exportar_escribe_un_csv_por_tabla_con_las_filas_de_la_base(db, tmp_path):
    from energia.exportar import TABLAS, exportar
    correr(db)
    filas = exportar(db, tmp_path)
    assert set(filas) == {t.split(".")[1] for t in TABLAS}
    assert filas["fact_demanda"] == 40 and filas["dim_sistema"] == 5
    lineas = (tmp_path / "fact_demanda.csv").read_text(encoding="utf-8").splitlines()
    assert lineas[0] == "fecha_id,sistema_id,mwh,cargado_en,actualizado_en"
    assert len(lineas) == 41


def test_los_controles_de_modelo_detectan_huecos_y_retraso(db):
    """Se cargan dos días no consecutivos: debe avisar del hueco y de la falta de frescura."""
    correr(db, hasta=date(2026, 9, 28))
    correr(db, hasta=date(2026, 10, 1), desde=date(2026, 10, 1), hoy=date(2026, 10, 20))
    from energia.calidad import cargar_controles, ejecutar_controles
    with db.connect() as conn:
        res = {r.control: r for r in ejecutar_controles(conn, cargar_controles(),
                                                        date(2026, 10, 20), alcance="modelo")}
    assert res["huecos_de_fechas"].estado == "fallo"
    assert res["huecos_de_fechas"].filas == 5 * 2  # 29 y 30 sep, en los 5 sistemas
    assert res["frescura"].estado == "fallo" and res["frescura"].filas == 5
