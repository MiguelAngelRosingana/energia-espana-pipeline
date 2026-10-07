-- Capas del almacén. Cada esquema tiene una responsabilidad:
--   raw : lo que devolvió la API, tal cual (JSONB), inmutable.
--   stg : staging. Filas ya aplanadas y tipadas del lote que se está procesando.
--   dwh : modelo en estrella (dimensiones, hechos y vistas para BI).
--   etl : control del proceso (ejecuciones, marcas de agua, resultados de calidad).
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS stg;
CREATE SCHEMA IF NOT EXISTS dwh;
CREATE SCHEMA IF NOT EXISTS etl;
