-- control: total_igual_suma_tecnologias
-- alcance: lote
-- severidad: error
-- descripcion: En cada día y sistema, el total que reporta la fuente debe ser igual a la suma de sus tecnologías (tolerancia 0,05 MWh). Si falta el total o falta una tecnología, no cuadra.
SELECT sistema,
       fecha,
       coalesce(max(mwh) FILTER (WHERE serie_tipo = 'total'), 0)  AS total_reportado,
       coalesce(sum(mwh) FILTER (WHERE serie_tipo <> 'total'), 0) AS suma_tecnologias
FROM stg.generacion
GROUP BY sistema, fecha
HAVING abs(coalesce(max(mwh) FILTER (WHERE serie_tipo = 'total'), 0)
         - coalesce(sum(mwh) FILTER (WHERE serie_tipo <> 'total'), 0)) > 0.05
