-- ======================= etl: control del proceso =======================

CREATE TABLE IF NOT EXISTS etl.ejecuciones (
    run_id               bigserial PRIMARY KEY,
    iniciado_en          timestamptz NOT NULL DEFAULT now(),
    finalizado_en        timestamptz,
    estado               text NOT NULL DEFAULT 'en_curso'
                         CHECK (estado IN ('en_curso', 'ok', 'error')),
    desde                date,
    hasta                date,
    solape_dias          integer,
    respuestas_nuevas    integer,
    respuestas_repetidas integer,
    respuestas_reencoladas integer,
    filas_stg            integer,
    hechos_nuevos        integer,
    hechos_modificados   integer,
    hechos_iguales       integer,
    error                text
);

-- Marca de agua: último día cargado con éxito para cada conjunto de datos y sistema.
-- La siguiente ejecución parte de aquí (menos los días de solape).
CREATE TABLE IF NOT EXISTS etl.marcas_agua (
    dataset        text NOT NULL,
    sistema        text NOT NULL,
    ultima_fecha   date NOT NULL,
    actualizada_en timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (dataset, sistema)
);

CREATE TABLE IF NOT EXISTS etl.resultados_calidad (
    id              bigserial PRIMARY KEY,
    run_id          bigint NOT NULL REFERENCES etl.ejecuciones (run_id) ON DELETE CASCADE,
    control         text NOT NULL,
    alcance         text NOT NULL CHECK (alcance IN ('lote', 'modelo')),
    severidad       text NOT NULL CHECK (severidad IN ('error', 'aviso')),
    estado          text NOT NULL CHECK (estado IN ('ok', 'fallo')),
    filas_afectadas integer NOT NULL DEFAULT 0,
    ejemplos        jsonb,
    ejecutado_en    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_resultados_calidad_run ON etl.resultados_calidad (run_id);

-- ======================= raw: respuestas de la API =======================
-- Una fila por respuesta distinta de la API. Se conserva el JSON completo para poder
-- reprocesar sin volver a llamar a la fuente y para auditar qué devolvió y cuándo.
CREATE TABLE IF NOT EXISTS raw.respuestas (
    id            bigserial PRIMARY KEY,
    run_id        bigint REFERENCES etl.ejecuciones (run_id),
    dataset       text NOT NULL,
    sistema       text NOT NULL,
    desde         date NOT NULL,
    hasta         date NOT NULL,
    recibida_en   timestamptz NOT NULL DEFAULT now(),
    estado_http   integer NOT NULL,
    huella        char(64) NOT NULL,     -- SHA-256 de los datos (no de los metadatos)
    payload       jsonb NOT NULL,
    estado        text NOT NULL DEFAULT 'pendiente'
                  CHECK (estado IN ('pendiente', 'procesada', 'cuarentena')),
    motivo        text,
    procesada_en  timestamptz,
    -- La misma petición con los mismos datos no se guarda dos veces (carga idempotente).
    UNIQUE (dataset, sistema, desde, hasta, huella)
);
CREATE INDEX IF NOT EXISTS ix_raw_respuestas_estado ON raw.respuestas (estado);
