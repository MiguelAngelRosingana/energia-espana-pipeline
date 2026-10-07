-- Paso 3: hechos. Primero se CLASIFICA cada fila del lote frente a lo ya cargado
-- (nueva / modificada / igual) y después solo se escriben las nuevas y las modificadas.
-- Así los contadores son explícitos y no dependen de ningún detalle interno de PostgreSQL.

-- ---- Generación por tecnología -------------------------------------------------------
UPDATE stg.generacion g
SET accion = c.accion
FROM (
    SELECT s.sistema, s.serie_id, s.fecha,
           CASE WHEN f.fecha_id IS NULL THEN 'nueva'
                WHEN (f.mwh, f.porcentaje_reportado) IS DISTINCT FROM (s.mwh, s.porcentaje)
                     THEN 'modificada'
                ELSE 'igual' END AS accion
    FROM stg.generacion s
    JOIN dwh.dim_sistema d ON d.codigo = s.sistema
    LEFT JOIN dwh.fact_generacion f
           ON f.fecha_id = to_char(s.fecha, 'YYYYMMDD')::integer
          AND f.sistema_id = d.sistema_id
          AND f.tecnologia_id = s.serie_id
    WHERE s.serie_tipo IN ('Renovable', 'No-Renovable')
) c
WHERE g.sistema = c.sistema AND g.serie_id = c.serie_id AND g.fecha = c.fecha;

INSERT INTO dwh.fact_generacion (fecha_id, sistema_id, tecnologia_id, mwh, porcentaje_reportado)
SELECT to_char(g.fecha, 'YYYYMMDD')::integer, d.sistema_id, g.serie_id, g.mwh, g.porcentaje
FROM stg.generacion g
JOIN dwh.dim_sistema d ON d.codigo = g.sistema
WHERE g.accion IN ('nueva', 'modificada')
ON CONFLICT (fecha_id, sistema_id, tecnologia_id) DO UPDATE
SET mwh = EXCLUDED.mwh,
    porcentaje_reportado = EXCLUDED.porcentaje_reportado,
    actualizado_en = now();

-- ---- Total de generación que reporta la fuente ---------------------------------------
UPDATE stg.generacion g
SET accion = c.accion
FROM (
    SELECT s.sistema, s.serie_id, s.fecha,
           CASE WHEN f.fecha_id IS NULL THEN 'nueva'
                WHEN f.mwh_total IS DISTINCT FROM s.mwh THEN 'modificada'
                ELSE 'igual' END AS accion
    FROM stg.generacion s
    JOIN dwh.dim_sistema d ON d.codigo = s.sistema
    LEFT JOIN dwh.fact_generacion_total f
           ON f.fecha_id = to_char(s.fecha, 'YYYYMMDD')::integer
          AND f.sistema_id = d.sistema_id
    WHERE s.serie_tipo = 'total'
) c
WHERE g.sistema = c.sistema AND g.serie_id = c.serie_id AND g.fecha = c.fecha;

INSERT INTO dwh.fact_generacion_total (fecha_id, sistema_id, mwh_total)
SELECT to_char(g.fecha, 'YYYYMMDD')::integer, d.sistema_id, g.mwh
FROM stg.generacion g
JOIN dwh.dim_sistema d ON d.codigo = g.sistema
WHERE g.serie_tipo = 'total' AND g.accion IN ('nueva', 'modificada')
ON CONFLICT (fecha_id, sistema_id) DO UPDATE
SET mwh_total = EXCLUDED.mwh_total,
    actualizado_en = now();

-- ---- Demanda -------------------------------------------------------------------------
UPDATE stg.demanda g
SET accion = c.accion
FROM (
    SELECT s.sistema, s.fecha,
           CASE WHEN f.fecha_id IS NULL THEN 'nueva'
                WHEN f.mwh IS DISTINCT FROM s.mwh THEN 'modificada'
                ELSE 'igual' END AS accion
    FROM stg.demanda s
    JOIN dwh.dim_sistema d ON d.codigo = s.sistema
    LEFT JOIN dwh.fact_demanda f
           ON f.fecha_id = to_char(s.fecha, 'YYYYMMDD')::integer
          AND f.sistema_id = d.sistema_id
) c
WHERE g.sistema = c.sistema AND g.fecha = c.fecha;

INSERT INTO dwh.fact_demanda (fecha_id, sistema_id, mwh)
SELECT to_char(g.fecha, 'YYYYMMDD')::integer, d.sistema_id, g.mwh
FROM stg.demanda g
JOIN dwh.dim_sistema d ON d.codigo = g.sistema
WHERE g.accion IN ('nueva', 'modificada')
ON CONFLICT (fecha_id, sistema_id) DO UPDATE
SET mwh = EXCLUDED.mwh,
    actualizado_en = now();

-- ---- Referencia nacional (solo para conciliar; no cuenta como hecho) -----------------
INSERT INTO dwh.ref_nacional (fecha_id, serie_id, serie_titulo, mwh)
SELECT to_char(fecha, 'YYYYMMDD')::integer,
       CASE WHEN serie_tipo = 'total' THEN 0 ELSE serie_id END,
       serie_titulo,
       mwh
FROM stg.generacion
WHERE sistema = 'nacional'
ON CONFLICT (fecha_id, serie_id) DO UPDATE
SET mwh = EXCLUDED.mwh,
    serie_titulo = EXCLUDED.serie_titulo,
    actualizado_en = now()
WHERE dwh.ref_nacional.mwh IS DISTINCT FROM EXCLUDED.mwh;
