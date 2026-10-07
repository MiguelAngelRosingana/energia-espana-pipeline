-- Paso 2: dimensiones. Solo se añade lo que aparece en el lote.

-- Calendario. Los nombres de mes y día se generan en español sin depender del idioma
-- del servidor (lc_time).
INSERT INTO dwh.dim_fecha
    (fecha_id, fecha, anio, trimestre, mes, anio_mes, nombre_mes, dia, dia_semana,
     nombre_dia, es_fin_de_semana)
SELECT to_char(f.fecha, 'YYYYMMDD')::integer,
       f.fecha,
       extract(year FROM f.fecha)::smallint,
       extract(quarter FROM f.fecha)::smallint,
       extract(month FROM f.fecha)::smallint,
       to_char(f.fecha, 'YYYY-MM'),
       (ARRAY['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
              'septiembre', 'octubre', 'noviembre', 'diciembre'])[extract(month FROM f.fecha)::int],
       extract(day FROM f.fecha)::smallint,
       extract(isodow FROM f.fecha)::smallint,
       (ARRAY['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado',
              'domingo'])[extract(isodow FROM f.fecha)::int],
       extract(isodow FROM f.fecha) IN (6, 7)
FROM (SELECT fecha FROM stg.generacion UNION SELECT fecha FROM stg.demanda) f
ON CONFLICT (fecha_id) DO NOTHING;

-- Tecnologías. Se excluye la serie "total" (no es una tecnología) y el sistema "nacional"
-- (solo sirve para comprobar que cuadra con la suma de los sistemas).
-- La familia es una agrupación propia, no oficial.
INSERT INTO dwh.dim_tecnologia (tecnologia_id, nombre, tipo, es_renovable, familia)
SELECT DISTINCT ON (serie_id)
       serie_id,
       serie_titulo,
       serie_tipo,
       serie_tipo = 'Renovable',
       CASE
           WHEN serie_titulo IN ('Eólica', 'Hidroeólica')                  THEN 'Eólica'
           WHEN serie_titulo IN ('Solar fotovoltaica', 'Solar térmica')    THEN 'Solar'
           WHEN serie_titulo = 'Hidráulica'                                THEN 'Hidráulica'
           WHEN serie_titulo = 'Nuclear'                                   THEN 'Nuclear'
           WHEN serie_titulo IN ('Ciclo combinado', 'Turbina de gas')      THEN 'Gas'
           WHEN serie_titulo = 'Carbón'                                    THEN 'Carbón'
           WHEN serie_titulo = 'Cogeneración'                              THEN 'Cogeneración'
           ELSE 'Otras'
       END
FROM stg.generacion
WHERE sistema <> 'nacional'
  AND serie_tipo IN ('Renovable', 'No-Renovable')
ORDER BY serie_id, fecha DESC
ON CONFLICT (tecnologia_id) DO UPDATE
SET nombre = EXCLUDED.nombre,
    tipo = EXCLUDED.tipo,
    es_renovable = EXCLUDED.es_renovable,
    familia = EXCLUDED.familia
WHERE (dwh.dim_tecnologia.nombre, dwh.dim_tecnologia.tipo, dwh.dim_tecnologia.familia)
      IS DISTINCT FROM (EXCLUDED.nombre, EXCLUDED.tipo, EXCLUDED.familia);
