-- control: frescura
-- alcance: modelo
-- severidad: aviso
-- descripcion: El último día cargado de cada sistema no debe tener más de 3 días de antigüedad respecto a la fecha de referencia. Detecta una fuente parada o un pipeline que no se ejecuta.
SELECT s.codigo AS sistema,
       max(d.fecha) AS ultima_fecha,
       (CAST(:hoy AS date) - max(d.fecha)) AS dias_de_retraso
FROM dwh.fact_generacion_total f
JOIN dwh.dim_fecha d ON d.fecha_id = f.fecha_id
JOIN dwh.dim_sistema s ON s.sistema_id = f.sistema_id
GROUP BY s.codigo
HAVING (CAST(:hoy AS date) - max(d.fecha)) > 3
