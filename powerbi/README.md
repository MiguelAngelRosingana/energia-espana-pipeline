# Informe de Power BI — Energía España

Proyecto de Power BI (formato **PBIP**, texto plano y versionable en git) sobre el modelo en estrella
del pipeline: modelo semántico (tablas, relaciones, tabla de fechas, medidas DAX) y un informe de
3 páginas.

```
powerbi/
├── energia.pbip              ← ábrelo con Power BI Desktop
├── energia.SemanticModel/    ← modelo: tablas (TMDL), relaciones, medidas
├── energia.Report/           ← informe: 3 páginas
├── datos/                    ← CSV exportados por el pipeline (instantánea)
└── tema-energia.json         ← tema de colores (Vista → Temas → Examinar)
```

## Abrirlo

1. Requiere Power BI Desktop reciente. Si al abrir el `.pbip` se queja del formato, activa en
   *Archivo → Opciones → Características en versión preliminar* «Formato de proyecto de Power BI
   (.pbip)» y «Almacenar el modelo semántico con formato TMDL», y reinicia.
2. Abre `energia.pbip`.
3. **Parámetro `RutaDatos`**: debe apuntar a la carpeta `datos\` con la ruta absoluta de TU equipo
   (por defecto `C:\tmp\energia\powerbi\datos\`, **con la barra final**). Se cambia en
   *Transformar datos → Administrar parámetros → RutaDatos*. Después, *Actualizar*.
4. Comprueba la carga (deben coincidir):

| Tabla | Filas |
|---|---|
| dim_fecha | 1.375 |
| dim_sistema | 5 |
| dim_tecnologia | 16 |
| fact_generacion | 45.529 |
| fact_generacion_total | 6.875 |
| fact_demanda | 6.875 |

5. En *Vista de modelo*: estrella con 3 dimensiones y 3 hechos, relaciones 1:N con filtro de la
   dimensión al hecho, y `dim_fecha` como tabla de fechas.
6. Importa el tema: *Vista → Temas → Examinar los temas* → `tema-energia.json`.

## Actualizar los datos

Los CSV son una instantánea (7 de octubre de 2026). Para refrescarlos:

```bash
python -m energia run
python -m energia exportar --destino export
# copiar de export/ a powerbi/datos/ las 6 tablas (dim_*, fact_*)
```
y *Actualizar* en Power BI. (Mejora posible: conectar directamente a PostgreSQL en lugar de CSV.)

## Medidas (tabla `_Medidas`)

Carpetas: **1 Base** (Generación MWh, Generación total, Demanda, TWh, Balance, Días con datos),
**2 Renovables** (Generación renovable, % renovable, % mix de la tecnología) y **3 Comparativas**
(año anterior, variación interanual, Δ % renovable en puntos porcentuales, media móvil 30 d).

- `Generación (MWh)` suma por **tecnología** (`fact_generacion`): úsala cuando haya `dim_tecnologia`
  en el visual.
- `Generación total (MWh)` usa el total que reporta la fuente (`fact_generacion_total`): úsala sin
  tecnología. Ambas coinciden (el pipeline lo comprueba).
- `% renovable` es un **cociente de sumas**, no una media de porcentajes.

## Páginas

Diseño: fondo crema, cada visual en una tarjeta blanca, un color fijo por familia de tecnología en todos
los gráficos, cabecera con navegación entre páginas y filtros de Año y Sistema sincronizados.

| Página | Visuales |
|---|---|
| **Resumen** | 4 tarjetas (Generación TWh, Demanda TWh, % renovable, Δ pp vs año anterior), cuota renovable mensual frente al mismo mes del año anterior, generación por familia en TWh |
| **Mix y evolución** | Columnas apiladas al 100 % por mes y familia, matriz tecnología × año con mapa de calor, dispersión demanda vs generación renovable por día (laborable / fin de semana) |
| **Sistemas** | Cuota renovable por sistema, tabla de balance (generación, demanda, balance, % renovable) y mix por familia en cada sistema |

Columnas añadidas a `dim_fecha` para el informe: `mes_inicio` (primer día del mes, eje continuo) y
`tipo_dia` (Laborable / Fin de semana). Medidas extra para ejes y etiquetas: `Generación tecnologías
(TWh)`, `Demanda (GWh)` y `Generación renovable (GWh)`.

**Escribe tus conclusiones** (qué sube, qué baja, qué sistema depende más de no renovables) en el
README del repositorio: las cifras salen de los datos; las conclusiones, de ti.

## Comprobaciones antes de publicar

- [ ] El % renovable de 2024 sale **56,8 %** con todos los sistemas (igual que `dwh.v_balance_diario`
      en SQL). Contrasta cualquier cifra con la vista SQL antes de enseñarla.
- [ ] 2026 es un año incompleto: no lo compares en absoluto con un año completo.
- [ ] Todos los visuales con unidades, formato de miles y título descriptivo.
- [ ] Exporta capturas de cada página a `docs/img/` y enlázalas desde el README principal.
