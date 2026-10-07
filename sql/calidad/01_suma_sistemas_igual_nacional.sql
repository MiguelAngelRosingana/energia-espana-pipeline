-- control: suma_sistemas_igual_nacional
-- alcance: lote
-- severidad: error
-- descripcion: Para cada día del lote y cada tecnología (y el total), el dato nacional debe ser igual a la suma de los cinco sistemas eléctricos (tolerancia de redondeo 0,05 MWh). Se compara con lo que hay en el MODELO y no solo con el lote, para que una revisión que afecte a un único sistema no dé falsos errores.
WITH dias AS (
    SELECT DISTINCT to_char(fecha, 'YYYYMMDD')::integer AS fecha_id FROM stg.generacion
),
sistemas AS (
    SELECT fecha_id, tecnologia_id AS serie_id, sum(mwh) AS suma, count(*) AS n_sistemas
    FROM dwh.fact_generacion
    GROUP BY fecha_id, tecnologia_id
    UNION ALL
    SELECT fecha_id, 0, sum(mwh_total), count(*)
    FROM dwh.fact_generacion_total
    GROUP BY fecha_id
)
SELECT d.fecha,
       n.serie_titulo                AS serie,
       n.mwh                         AS nacional,
       coalesce(s.suma, 0)           AS suma_sistemas,
       coalesce(s.n_sistemas, 0)     AS n_sistemas
FROM dwh.ref_nacional n
JOIN dias USING (fecha_id)
JOIN dwh.dim_fecha d USING (fecha_id)
LEFT JOIN sistemas s ON s.fecha_id = n.fecha_id AND s.serie_id = n.serie_id
WHERE abs(n.mwh - coalesce(s.suma, 0)) > 0.05
