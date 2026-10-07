# Cómo explicar este proyecto en una entrevista

Guion de apoyo. Léelo hasta que puedas contarlo sin mirarlo; si hay algo que no entiendes de
verdad, no lo cuentes hasta entenderlo (pídeme que te lo explique).

## En 30 segundos

> «Hice un pipeline en Python y SQL que descarga cada día la generación y la demanda eléctrica de
> España desde la API de Red Eléctrica y la carga en PostgreSQL de forma incremental, en un modelo en
> estrella. Tiene controles de calidad que bloquean la carga si algo no cuadra, tests con base de datos
> real y se ejecuta solo con GitHub Actions. Lo uso de base para un informe de Power BI.»

## En 3 minutos (el recorrido)

1. **Extraer.** Llamo a la API por conjunto de datos y sistema eléctrico (península, Canarias,
   Baleares, Ceuta y Melilla) con reintentos. Guardo la respuesta tal cual en `raw`, con una huella
   del contenido para no duplicar.
2. **Cargar de forma incremental.** Cada par (dato, sistema) tiene una marca de agua: hasta qué día
   está cargado. En cada ejecución pido desde la marca menos 7 días, porque la fuente revisa datos
   recientes.
3. **Transformar.** Aplano el JSON a `stg` y hago upsert en las tablas de hechos, clasificando cada
   fila como nueva, modificada o igual.
4. **Controlar.** 11 controles en SQL. Los de severidad *error* hacen rollback de toda la
   transformación y mandan la respuesta a cuarentena; los de *aviso* solo se registran.
5. **Consumir.** Vistas listas para BI y export a CSV.

## Preguntas probables

**¿Por qué ELT y no ETL?**
Porque guardo primero el dato crudo y transformo dentro de la base de datos. Si cambio una regla,
reprocesar desde `raw` sin llamar otra vez a la API, y el SQL es más fácil de revisar y testear.

**¿Qué significa que sea idempotente? ¿Cómo lo compruebas?**
Que ejecutarlo dos veces seguidas deja el modelo igual. Lo garantizan la clave primaria con upsert y la
huella de contenido; lo compruebo en un test, y en la ejecución real la segunda pasada dio
0 nuevos, 0 modificados, 264 sin cambios.

**¿Por qué una ventana de solape de 7 días?**
Si solo pidiera desde la última fecha cargada, nunca vería las correcciones de la fuente sobre días ya
cargados. Con el solape las detecto: el hecho pasa a «modificada» y se actualiza.

**¿Qué pasa si falla la API a mitad?**
Lo ya descargado queda en `raw` (hay un test), la ejecución se marca como fallida y la siguiente retoma
desde las marcas de agua, que solo avanzan cuando la transformación termina bien.

**¿Qué pasa si la API cambia el formato?**
Valido el contrato mínimo de la respuesta y falla con un mensaje claro en vez de cargar basura. Además,
el workflow diario ejecuta pruebas contra la API real que avisan si las premisas dejan de cumplirse.

**¿Por qué no Airflow/dbt/Spark?**
Para este volumen (decenas de miles de filas) serían sobreingeniería. Lo he estructurado por capas y con
SQL separado para que migrar a dbt o a un orquestador sea natural, pero no lo he hecho y no quiero
aparentar que sí.

**¿Cómo escalaría?**
Granularidad horaria (×24 filas), particionado de los hechos por fecha, cargas por lotes con `COPY`
en vez de inserciones, y un orquestador con reintentos y alertas. Hoy el cuello de botella es la
latencia de la API, no la base de datos (medido: transformar 81.000 filas tarda unos 11 s de 259 s).

**Cuéntame un problema real que encontraste.**
Elige uno de verdad, por ejemplo: puse un `CHECK (mwh >= 0)` y la carga real se rompió, porque la
generación neta del Carbón es negativa algún día. Lo cambié por dos controles: negativos menores
(aviso) y extremos (error). O: el 400 de la API es el mismo para errores permanentes y transitorios;
decidí no reintentarlo.

**¿Por qué el nacional no está en el modelo?**
Porque duplicaría la generación al agregar. Lo guardo aparte solo para comprobar que la suma de los
sistemas lo iguala.

**¿Qué mejorarías?**
Datos horarios, histórico de revisiones (ahora el detalle de qué cambió está en `raw`, no en una tabla
de auditoría propia), orquestador y alertas por correo.

## Sobre el uso de IA

Si te preguntan cómo lo hiciste, **cuéntalo con naturalidad y verdad**: lo desarrollaste con un
asistente de IA. Lo que se valora es que sepas explicar cada decisión, defenderla y modificar el
código. Practica con estos ejercicios: añadir un control de calidad nuevo, cambiar el solape a 14 días y
explicar qué cambia, o añadir otra tecnología a la dimensión.
