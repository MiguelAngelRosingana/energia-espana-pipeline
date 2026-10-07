-- ======================= vistas para BI (Power BI, SQL, etc.) =======================
-- Son la capa de consumo: ya traen las dimensiones unidas y los porcentajes calculados.

-- Detalle: un día x sistema x tecnología.
CREATE OR REPLACE VIEW dwh.v_generacion_detalle AS
SELECT d.fecha,
       d.anio,
       d.anio_mes,
       d.nombre_mes,
       d.nombre_dia,
       d.es_fin_de_semana,
       s.codigo  AS sistema,
       s.nombre  AS sistema_nombre,
       t.nombre  AS tecnologia,
       t.familia,
       t.tipo,
       t.es_renovable,
       f.mwh,
       f.mwh / NULLIF(tot.mwh_total, 0) AS porcentaje_del_total
FROM dwh.fact_generacion f
JOIN dwh.dim_fecha d       ON d.fecha_id = f.fecha_id
JOIN dwh.dim_sistema s     ON s.sistema_id = f.sistema_id
JOIN dwh.dim_tecnologia t  ON t.tecnologia_id = f.tecnologia_id
JOIN dwh.fact_generacion_total tot
  ON tot.fecha_id = f.fecha_id AND tot.sistema_id = f.sistema_id;

-- Balance diario: generación total y renovable frente a demanda, por sistema.
CREATE OR REPLACE VIEW dwh.v_balance_diario AS
WITH renovable AS (
    SELECT f.fecha_id,
           f.sistema_id,
           sum(f.mwh) FILTER (WHERE t.es_renovable) AS mwh_renovable
    FROM dwh.fact_generacion f
    JOIN dwh.dim_tecnologia t ON t.tecnologia_id = f.tecnologia_id
    GROUP BY f.fecha_id, f.sistema_id
)
SELECT d.fecha,
       d.anio,
       d.anio_mes,
       s.codigo AS sistema,
       s.nombre AS sistema_nombre,
       tot.mwh_total                                    AS generacion_total_mwh,
       coalesce(r.mwh_renovable, 0)                     AS generacion_renovable_mwh,
       coalesce(r.mwh_renovable, 0) / NULLIF(tot.mwh_total, 0) AS porcentaje_renovable,
       dem.mwh                                          AS demanda_mwh,
       tot.mwh_total - dem.mwh                          AS generacion_menos_demanda_mwh
FROM dwh.fact_generacion_total tot
JOIN dwh.dim_fecha d    ON d.fecha_id = tot.fecha_id
JOIN dwh.dim_sistema s  ON s.sistema_id = tot.sistema_id
LEFT JOIN renovable r   ON r.fecha_id = tot.fecha_id AND r.sistema_id = tot.sistema_id
LEFT JOIN dwh.fact_demanda dem
       ON dem.fecha_id = tot.fecha_id AND dem.sistema_id = tot.sistema_id;

-- Balance mensual. El porcentaje renovable es la suma de MWh renovables entre la suma
-- de MWh totales (ponderado por producción), NO la media de los porcentajes diarios.
CREATE OR REPLACE VIEW dwh.v_balance_mensual AS
SELECT anio_mes,
       sistema,
       sistema_nombre,
       count(*)                          AS dias,
       sum(generacion_total_mwh)         AS generacion_total_mwh,
       sum(generacion_renovable_mwh)     AS generacion_renovable_mwh,
       sum(generacion_renovable_mwh) / NULLIF(sum(generacion_total_mwh), 0) AS porcentaje_renovable,
       sum(demanda_mwh)                  AS demanda_mwh
FROM dwh.v_balance_diario
GROUP BY anio_mes, sistema, sistema_nombre;

-- Resumen de las últimas ejecuciones del pipeline.
CREATE OR REPLACE VIEW etl.v_resumen_ejecuciones AS
SELECT run_id,
       estado,
       iniciado_en,
       round(extract(epoch FROM (finalizado_en - iniciado_en))::numeric, 1) AS segundos,
       desde,
       hasta,
       respuestas_nuevas,
       respuestas_repetidas,
       respuestas_reencoladas,
       filas_stg,
       hechos_nuevos,
       hechos_modificados,
       hechos_iguales,
       error
FROM etl.ejecuciones
ORDER BY run_id DESC;
