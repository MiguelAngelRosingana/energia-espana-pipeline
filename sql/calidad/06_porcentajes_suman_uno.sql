-- control: porcentajes_suman_uno
-- alcance: lote
-- severidad: aviso
-- descripcion: Los porcentajes que reporta la fuente para las tecnologías de un día y sistema deben sumar 1 (tolerancia 0,001).
SELECT sistema,
       fecha,
       sum(porcentaje) AS suma_porcentajes
FROM stg.generacion
WHERE serie_tipo <> 'total'
GROUP BY sistema, fecha
HAVING abs(sum(porcentaje) - 1) > 0.001
