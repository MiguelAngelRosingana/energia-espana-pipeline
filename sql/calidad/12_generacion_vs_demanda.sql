-- control: generacion_vs_demanda
-- alcance: modelo
-- severidad: aviso
-- descripcion: La generación total de un día y sistema debería estar en el mismo orden de magnitud que su demanda (entre 0,5 y 1,5 veces). Un valor fuera de ese rango suele indicar un dato mal cargado, no una situación real.
SELECT sistema,
       fecha,
       generacion_total_mwh,
       demanda_mwh,
       round(generacion_total_mwh / demanda_mwh, 3) AS razon
FROM dwh.v_balance_diario
WHERE demanda_mwh > 0
  AND (generacion_total_mwh / demanda_mwh < 0.5 OR generacion_total_mwh / demanda_mwh > 1.5)
