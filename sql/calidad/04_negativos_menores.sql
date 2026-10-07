-- control: negativos_menores
-- alcance: lote
-- severidad: aviso
-- descripcion: Deja constancia de los valores de generación ligeramente negativos (entre 0 y -1000 MWh). No se rechazan porque la fuente publica generación neta, pero conviene verlos.
SELECT sistema, serie_titulo AS serie, fecha, mwh
FROM stg.generacion
WHERE mwh < 0 AND mwh >= -1000
  AND sistema <> 'nacional'
ORDER BY fecha
