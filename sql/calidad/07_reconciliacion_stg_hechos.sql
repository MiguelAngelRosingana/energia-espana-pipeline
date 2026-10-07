-- control: reconciliacion_stg_hechos
-- alcance: lote
-- severidad: error
-- descripcion: Todo lo que llegó en el lote (tecnologías, totales y demanda de los sistemas) debe existir en las tablas de hechos tras la carga. Si no, se ha perdido algo por el camino.
SELECT 'fact_generacion' AS tabla, g.sistema, g.fecha, g.serie_id::text AS clave
FROM stg.generacion g
JOIN dwh.dim_sistema d ON d.codigo = g.sistema
LEFT JOIN dwh.fact_generacion f
       ON f.fecha_id = to_char(g.fecha, 'YYYYMMDD')::integer
      AND f.sistema_id = d.sistema_id
      AND f.tecnologia_id = g.serie_id
WHERE g.serie_tipo IN ('Renovable', 'No-Renovable')
  AND f.fecha_id IS NULL
UNION ALL
SELECT 'fact_generacion_total', g.sistema, g.fecha, g.serie_id::text
FROM stg.generacion g
JOIN dwh.dim_sistema d ON d.codigo = g.sistema
LEFT JOIN dwh.fact_generacion_total f
       ON f.fecha_id = to_char(g.fecha, 'YYYYMMDD')::integer
      AND f.sistema_id = d.sistema_id
WHERE g.serie_tipo = 'total'
  AND f.fecha_id IS NULL
UNION ALL
SELECT 'fact_demanda', g.sistema, g.fecha, 'demanda'
FROM stg.demanda g
JOIN dwh.dim_sistema d ON d.codigo = g.sistema
LEFT JOIN dwh.fact_demanda f
       ON f.fecha_id = to_char(g.fecha, 'YYYYMMDD')::integer
      AND f.sistema_id = d.sistema_id
WHERE f.fecha_id IS NULL
