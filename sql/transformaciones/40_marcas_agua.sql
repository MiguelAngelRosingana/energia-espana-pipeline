-- Paso 4: avanzar las marcas de agua hasta el último día que REALMENTE llegó en el lote
-- (no hasta el día que se pidió: si la fuente no devolvió un día, la marca no lo salta).
-- GREATEST evita que una carga con un rango antiguo haga retroceder la marca.
INSERT INTO etl.marcas_agua (dataset, sistema, ultima_fecha)
SELECT 'generacion', sistema, max(fecha) FROM stg.generacion GROUP BY sistema
UNION ALL
SELECT 'demanda', sistema, max(fecha) FROM stg.demanda GROUP BY sistema
ON CONFLICT (dataset, sistema) DO UPDATE
SET ultima_fecha = GREATEST(etl.marcas_agua.ultima_fecha, EXCLUDED.ultima_fecha),
    actualizada_en = now();
