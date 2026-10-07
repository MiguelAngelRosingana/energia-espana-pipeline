-- control: huecos_de_fechas
-- alcance: modelo
-- severidad: aviso
-- descripcion: No puede faltar ningún día entre el primero y el último cargados de cada sistema. Un hueco falsearía los acumulados mensuales.
WITH rango AS (
    SELECT f.sistema_id, min(d.fecha) AS primera, max(d.fecha) AS ultima
    FROM dwh.fact_generacion_total f
    JOIN dwh.dim_fecha d ON d.fecha_id = f.fecha_id
    GROUP BY f.sistema_id
)
SELECT s.codigo AS sistema, dia::date AS fecha_faltante
FROM rango r
JOIN dwh.dim_sistema s ON s.sistema_id = r.sistema_id
CROSS JOIN LATERAL generate_series(r.primera, r.ultima, interval '1 day') AS dia
LEFT JOIN dwh.fact_generacion_total t
       ON t.sistema_id = r.sistema_id
      AND t.fecha_id = to_char(dia, 'YYYYMMDD')::integer
WHERE t.fecha_id IS NULL
ORDER BY 1, 2
