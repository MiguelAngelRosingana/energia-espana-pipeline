-- ======================= dwh: modelo en estrella =======================
-- Dos tablas de hechos (generación y demanda) que comparten dimensiones conformadas
-- (fecha y sistema eléctrico). Grano:
--   fact_generacion       : un día x un sistema eléctrico x una tecnología
--   fact_generacion_total : un día x un sistema eléctrico (total que reporta la fuente)
--   fact_demanda          : un día x un sistema eléctrico

CREATE TABLE IF NOT EXISTS dwh.dim_fecha (
    fecha_id         integer PRIMARY KEY,          -- AAAAMMDD
    fecha            date NOT NULL UNIQUE,
    anio             smallint NOT NULL,
    trimestre        smallint NOT NULL,
    mes              smallint NOT NULL,
    anio_mes         char(7) NOT NULL,             -- AAAA-MM
    nombre_mes       text NOT NULL,
    dia              smallint NOT NULL,
    dia_semana       smallint NOT NULL,            -- 1 = lunes ... 7 = domingo (ISO)
    nombre_dia       text NOT NULL,
    es_fin_de_semana boolean NOT NULL
);

-- Los cinco sistemas eléctricos que publica la fuente. El id es el de la propia API.
CREATE TABLE IF NOT EXISTS dwh.dim_sistema (
    sistema_id    smallint PRIMARY KEY,
    codigo        text NOT NULL UNIQUE,
    nombre        text NOT NULL,
    es_peninsular boolean NOT NULL
);
INSERT INTO dwh.dim_sistema (sistema_id, codigo, nombre, es_peninsular) VALUES
    (8741, 'peninsular', 'Península', true),
    (8742, 'canarias',   'Canarias',  false),
    (8743, 'baleares',   'Baleares',  false),
    (8744, 'ceuta',      'Ceuta',     false),
    (8745, 'melilla',    'Melilla',   false)
ON CONFLICT (sistema_id) DO NOTHING;

-- Tecnologías de generación. El id es el de la serie en la API.
-- `familia` es una agrupación propia (no oficial) para simplificar los informes.
CREATE TABLE IF NOT EXISTS dwh.dim_tecnologia (
    tecnologia_id integer PRIMARY KEY,
    nombre        text NOT NULL,
    tipo          text NOT NULL CHECK (tipo IN ('Renovable', 'No-Renovable')),
    es_renovable  boolean NOT NULL,
    familia       text NOT NULL
);

CREATE TABLE IF NOT EXISTS dwh.fact_generacion (
    fecha_id             integer  NOT NULL REFERENCES dwh.dim_fecha (fecha_id),
    sistema_id           smallint NOT NULL REFERENCES dwh.dim_sistema (sistema_id),
    tecnologia_id        integer  NOT NULL REFERENCES dwh.dim_tecnologia (tecnologia_id),
    -- Generación NETA: puede ser ligeramente negativa (se ha observado en Carbón, mín. -94,5 MWh).
    mwh                  numeric(14, 3) NOT NULL,
    porcentaje_reportado numeric(9, 6),
    cargado_en           timestamptz NOT NULL DEFAULT now(),
    actualizado_en       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (fecha_id, sistema_id, tecnologia_id)
);
CREATE INDEX IF NOT EXISTS ix_fact_generacion_tecnologia ON dwh.fact_generacion (tecnologia_id);
CREATE INDEX IF NOT EXISTS ix_fact_generacion_sistema ON dwh.fact_generacion (sistema_id);

CREATE TABLE IF NOT EXISTS dwh.fact_generacion_total (
    fecha_id       integer  NOT NULL REFERENCES dwh.dim_fecha (fecha_id),
    sistema_id     smallint NOT NULL REFERENCES dwh.dim_sistema (sistema_id),
    mwh_total      numeric(14, 3) NOT NULL CHECK (mwh_total >= 0),
    cargado_en     timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (fecha_id, sistema_id)
);

CREATE TABLE IF NOT EXISTS dwh.fact_demanda (
    fecha_id       integer  NOT NULL REFERENCES dwh.dim_fecha (fecha_id),
    sistema_id     smallint NOT NULL REFERENCES dwh.dim_sistema (sistema_id),
    mwh            numeric(14, 3) NOT NULL CHECK (mwh > 0),
    cargado_en     timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (fecha_id, sistema_id)
);

-- Referencia para CONCILIAR: lo que publica la fuente a nivel nacional. No es un hecho de
-- análisis (no se mezcla con los cinco sistemas); solo sirve para comprobar que estos suman el
-- nacional, aunque en una ejecución solo haya cambiado uno de ellos.
CREATE TABLE IF NOT EXISTS dwh.ref_nacional (
    fecha_id       integer NOT NULL REFERENCES dwh.dim_fecha (fecha_id),
    serie_id       integer NOT NULL,          -- id de la tecnología; 0 = total
    serie_titulo   text NOT NULL,
    mwh            numeric(14, 3) NOT NULL,
    actualizado_en timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (fecha_id, serie_id)
);

-- ======================= stg: staging del lote =======================
-- UNLOGGED: no escribe en el WAL. Se vacía y se rellena en cada ejecución, así que
-- perderla en una caída no importa (se reconstruye desde raw).
CREATE UNLOGGED TABLE IF NOT EXISTS stg.generacion (
    sistema      text NOT NULL,
    serie_id     integer NOT NULL,
    serie_titulo text NOT NULL,
    serie_tipo   text NOT NULL,            -- Renovable | No-Renovable | total
    fecha        date NOT NULL,
    mwh          numeric(14, 3) NOT NULL,
    porcentaje   numeric(9, 6),
    respuesta_id bigint NOT NULL,
    accion       text,                     -- nueva | modificada | igual
    PRIMARY KEY (sistema, serie_id, fecha)
);
CREATE UNLOGGED TABLE IF NOT EXISTS stg.demanda (
    sistema      text NOT NULL,
    fecha        date NOT NULL,
    mwh          numeric(14, 3) NOT NULL,
    respuesta_id bigint NOT NULL,
    accion       text,
    PRIMARY KEY (sistema, fecha)
);
