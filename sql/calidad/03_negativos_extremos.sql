-- control: negativos_extremos
-- alcance: lote
-- severidad: error
-- descripcion: La generación es neta y puede ser ligeramente negativa (en los datos reales hay 5 valores de Carbón entre -50 y -94,5 MWh), pero un valor por debajo de -1000 MWh es un orden de magnitud peor que lo observado y se trata como dato corrupto. La demanda nunca puede ser negativa.
SELECT 'generacion' AS conjunto, sistema, serie_titulo AS serie, fecha, mwh
FROM stg.generacion
WHERE mwh < -1000
UNION ALL
SELECT 'demanda', sistema, 'Demanda', fecha, mwh
FROM stg.demanda
WHERE mwh < 0
