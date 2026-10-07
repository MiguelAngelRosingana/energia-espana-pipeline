-- control: puntos_fuera_de_rango
-- alcance: lote
-- severidad: aviso
-- descripcion: La API a veces devuelve puntos de días posteriores al rango pedido (días en curso, incompletos). El staging los descarta; este control deja constancia de cuántos llegaron y de qué series.
SELECT r.dataset,
       r.sistema,
       s -> 'attributes' ->> 'title' AS serie,
       ((v ->> 'datetime')::timestamptz AT TIME ZONE 'Europe/Madrid')::date AS fecha,
       r.desde AS pedido_desde,
       r.hasta AS pedido_hasta
FROM raw.respuestas r
CROSS JOIN LATERAL jsonb_array_elements(r.payload -> 'included') AS s
CROSS JOIN LATERAL jsonb_array_elements(s -> 'attributes' -> 'values') AS v
WHERE r.estado = 'pendiente'
  AND ((v ->> 'datetime')::timestamptz AT TIME ZONE 'Europe/Madrid')::date
      NOT BETWEEN r.desde AND r.hasta
