# Power BI sobre el modelo de energía

Guía para construir el informe encima del modelo en estrella de este proyecto (proyecto 3 del
flujo Python → SQL → Power BI). El `.pbix` se construye en Power BI Desktop; aquí está todo lo
que hace falta para no empezar de cero.

## 1. Conexión

**Opción A — PostgreSQL (la realista, la que enseñas en entrevista).**
Obtener datos → *Base de datos PostgreSQL* → servidor `localhost:5433`, base de datos `energia`,
modo **Importar**. Necesita el conector Npgsql instalado (Power BI lo avisa si falta).

**Opción B — CSV (sin base de datos, para que cualquiera pueda abrir el informe).**
`python -m energia exportar --destino export` genera un CSV por tabla. Obtener datos → *Texto/CSV*
(UTF-8, delimitador coma). Úsala para publicar el `.pbix` en el repositorio con datos de ejemplo.

Carga **las tablas** (`dim_*` y `fact_*`), no las vistas, para que el modelo sea una estrella de
verdad:

| Tabla | Filas aprox. |
|---|---|
| `dwh.dim_fecha` | 1.375 |
| `dwh.dim_sistema` | 5 |
| `dwh.dim_tecnologia` | 16 |
| `dwh.fact_generacion` | 45.529 |
| `dwh.fact_generacion_total` | 6.875 |
| `dwh.fact_demanda` | 6.875 |

Las vistas `v_balance_diario` y `v_balance_mensual` sirven para contrastar: tus medidas DAX deben dar
las mismas cifras que ellas (es tu prueba de que el modelo está bien montado).

## 2. Modelo

Relaciones (todas **uno a varios**, filtro en una dirección, de la dimensión al hecho):

```
dim_fecha[fecha_id]          → fact_generacion[fecha_id]
                             → fact_generacion_total[fecha_id]
                             → fact_demanda[fecha_id]
dim_sistema[sistema_id]      → fact_generacion[sistema_id]
                             → fact_generacion_total[sistema_id]
                             → fact_demanda[sistema_id]
dim_tecnologia[tecnologia_id]→ fact_generacion[tecnologia_id]
```

- Marca `dim_fecha` como **tabla de fechas** (columna `fecha`). Está completa y sin huecos.
- Ordena `nombre_mes` por `mes` y `nombre_dia` por `dia_semana`.
- Oculta las claves (`*_id`) y las columnas de auditoría (`cargado_en`, `actualizado_en`).
- No hay relaciones entre hechos: se combinan a través de las dimensiones compartidas.

## 3. Medidas DAX

Crea una tabla vacía `_Medidas` para guardarlas.

```dax
Generación (MWh) = SUM ( fact_generacion[mwh] )

Generación total (MWh) = SUM ( fact_generacion_total[mwh_total] )

Demanda (MWh) = SUM ( fact_demanda[mwh] )

Generación renovable (MWh) =
CALCULATE ( [Generación (MWh)], dim_tecnologia[es_renovable] = TRUE () )

% renovable =
DIVIDE ( [Generación renovable (MWh)], [Generación (MWh)] )

Balance generación - demanda (MWh) =
[Generación total (MWh)] - [Demanda (MWh)]

% mix de la tecnología =
DIVIDE (
    [Generación (MWh)],
    CALCULATE ( [Generación (MWh)], ALL ( dim_tecnologia ) )
)

Generación año anterior (MWh) =
CALCULATE ( [Generación (MWh)], SAMEPERIODLASTYEAR ( dim_fecha[fecha] ) )

Variación interanual % =
DIVIDE ( [Generación (MWh)] - [Generación año anterior (MWh)], [Generación año anterior (MWh)] )

% renovable año anterior =
CALCULATE ( [% renovable], SAMEPERIODLASTYEAR ( dim_fecha[fecha] ) )

Δ % renovable vs año anterior (pp) =
( [% renovable] - [% renovable año anterior] ) * 100

% renovable media móvil 30 d =
CALCULATE (
    [% renovable],
    DATESINPERIOD ( dim_fecha[fecha], MAX ( dim_fecha[fecha] ), -30, DAY )
)

Días con datos = DISTINCTCOUNT ( fact_generacion_total[fecha_id] )
```

**Trampas que conviene saber explicar**

- **No promedies porcentajes.** `% renovable` es un cociente de sumas (renovable ÷ total), no la
  media de los porcentajes diarios; la media daría el mismo peso a un día de baja producción que a
  uno de alta. Es la misma regla que sigue la vista `v_balance_mensual`.
- **Año en curso incompleto.** 2026 solo llega hasta el 6 de octubre: no compares un año completo
  con uno parcial en valores absolutos; usa `SAMEPERIODLASTYEAR` (como arriba) o porcentajes.
- **Generación por tecnología puede ser negativa** (generación neta del Carbón algún día): en un
  gráfico de áreas apiladas se verá como una pequeña muesca. No es un error.
- **Sumar sistemas ya es el nacional.** El modelo no incluye el total nacional como hecho aparte,
  así que sumar los cinco sistemas no lo duplica. Para ver «solo Península» filtra por `dim_sistema`.

## 4. Diseño del informe (3 páginas)

**Página 1 — Resumen.**
Tarjetas: generación total, demanda, % renovable y Δ vs año anterior. Línea: % renovable (media móvil
30 d) por día. Barras: generación por familia de tecnología del periodo. Segmentadores: año, sistema.

**Página 2 — Mix y evolución.**
Columnas apiladas al 100 % por mes y `familia` (Power BI no tiene áreas al 100 %), para ver cómo cambia el mix (qué sube: solar, eólica; qué
baja: ciclo combinado, carbón). Matriz tecnología × año con `% mix de la tecnología` y formato condicional.
Dispersión día a día: demanda frente a generación renovable, coloreada por fin de semana.

**Página 3 — Sistemas.**
Comparativa Península / Canarias / Baleares / Ceuta / Melilla: % renovable y balance generación −
demanda. Tabla con detalle y barras de datos. Es útil para ver que los sistemas insulares dependen
mucho más de fuentes no renovables.

**Preguntas que el informe debería poder responder** (comprueba que lo hace):

1. ¿Qué porcentaje de la generación fue renovable cada año y cómo evoluciona mes a mes?
2. ¿Qué tecnologías ganan o pierden peso entre 2023 y ahora?
3. ¿Hay diferencia entre días laborables y fines de semana en demanda?
4. ¿Qué sistema depende más de fuentes no renovables?

Escribe tú las conclusiones que veas en los datos, con tus palabras, en el README del informe.

## 5. Formato

- Fondo claro, **un solo color de acento** (verde apagado) para lo renovable y grises para el resto;
  evita el arcoíris de series. Mismo criterio que el resto del portfolio.
- Títulos que digan algo («% renovable, media móvil 30 días»), no «Gráfico 1».
- Unidades siempre visibles (MWh, GWh o TWh); formato de miles con punto.
- Tema sugerido: guárdalo como `tema-energia.json` e impórtalo en *Vista → Temas → Examinar*.

```json
{
  "name": "Energia España",
  "dataColors": ["#2f6b4f", "#8aa89a", "#c9a96a", "#6b7a8f", "#b5b0a4", "#a45a4a", "#4f6d7a", "#d6cfbf"],
  "background": "#faf7f2",
  "foreground": "#1f2a24",
  "tableAccent": "#2f6b4f",
  "textClasses": {
    "title": { "fontFace": "Georgia", "fontSize": 14, "color": "#1f2a24" },
    "label": { "fontFace": "Segoe UI", "fontSize": 10, "color": "#4a5a52" }
  }
}
```

## 6. Publicar

- Guarda el `.pbix` con la **opción B (CSV)** para que se abra sin base de datos, y súbelo al repo
  junto a capturas de cada página (`docs/img/`).
- Si tienes cuenta de Power BI Service, puedes publicar el informe y enlazarlo; sin licencia Pro no se
  puede compartir públicamente de forma abierta, así que las capturas son el plan B.
