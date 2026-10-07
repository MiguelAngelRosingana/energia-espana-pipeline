-- control: demanda_positiva
-- alcance: lote
-- severidad: error
-- descripcion: La demanda de un día completo no puede ser cero.
SELECT sistema, fecha, mwh
FROM stg.demanda
WHERE mwh <= 0
