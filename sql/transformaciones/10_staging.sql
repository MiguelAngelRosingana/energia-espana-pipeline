-- Paso 1: aplanar el JSON de las respuestas pendientes a filas tipadas (ELT: el trabajo
-- pesado lo hace la base de datos con SQL, no Python).
--
-- Detalles:
--  * La fecha de cada punto llega como medianoche local con su desfase (por ejemplo
--    2026-03-29T00:00:00+01:00). Se convierte a hora de Madrid y se trunca a fecha, así los
--    días de cambio de hora no se desplazan ni se duplican.
--  * La ventana PEDIDA manda: la API a veces devuelve puntos de días posteriores al rango
--    solicitado (días en curso, incompletos, solo en algunas series). Se descartan aquí y el
--    control "puntos_fuera_de_rango" deja constancia de cuántos fueron.
--  * Si varias respuestas pendientes traen el mismo (sistema, serie, día), gana la más reciente.
--  * Una serie que no reporta un día simplemente no aporta fila: ausente no es cero.

TRUNCATE stg.generacion, stg.demanda;

INSERT INTO stg.generacion
    (sistema, serie_id, serie_titulo, serie_tipo, fecha, mwh, porcentaje, respuesta_id)
SELECT sistema, serie_id, serie_titulo, serie_tipo, fecha, mwh, porcentaje, respuesta_id
FROM (
    SELECT p.*,
           row_number() OVER (PARTITION BY p.sistema, p.serie_id, p.fecha
                              ORDER BY p.respuesta_id DESC) AS orden
    FROM (
        SELECT r.sistema,
               (s ->> 'id')::integer                 AS serie_id,
               s -> 'attributes' ->> 'title'         AS serie_titulo,
               s -> 'attributes' ->> 'type'          AS serie_tipo,
               ((v ->> 'datetime')::timestamptz AT TIME ZONE 'Europe/Madrid')::date AS fecha,
               (v ->> 'value')::numeric              AS mwh,
               (v ->> 'percentage')::numeric         AS porcentaje,
               r.id                                  AS respuesta_id,
               r.desde,
               r.hasta
        FROM raw.respuestas r
        CROSS JOIN LATERAL jsonb_array_elements(r.payload -> 'included') AS s
        CROSS JOIN LATERAL jsonb_array_elements(s -> 'attributes' -> 'values') AS v
        WHERE r.estado = 'pendiente'
          AND r.dataset = 'generacion'
          AND v ->> 'value' IS NOT NULL
    ) p
    WHERE p.fecha BETWEEN p.desde AND p.hasta
) x
WHERE orden = 1;

INSERT INTO stg.demanda (sistema, fecha, mwh, respuesta_id)
SELECT sistema, fecha, mwh, respuesta_id
FROM (
    SELECT p.*,
           row_number() OVER (PARTITION BY p.sistema, p.fecha
                              ORDER BY p.respuesta_id DESC) AS orden
    FROM (
        SELECT r.sistema,
               ((v ->> 'datetime')::timestamptz AT TIME ZONE 'Europe/Madrid')::date AS fecha,
               (v ->> 'value')::numeric AS mwh,
               r.id AS respuesta_id,
               r.desde,
               r.hasta
        FROM raw.respuestas r
        CROSS JOIN LATERAL jsonb_array_elements(r.payload -> 'included') AS s
        CROSS JOIN LATERAL jsonb_array_elements(s -> 'attributes' -> 'values') AS v
        WHERE r.estado = 'pendiente'
          AND r.dataset = 'demanda'
          AND v ->> 'value' IS NOT NULL
    ) p
    WHERE p.fecha BETWEEN p.desde AND p.hasta
) x
WHERE orden = 1;
