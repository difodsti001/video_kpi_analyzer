# Video KPI Analyzer

Video KPI Analyzer es un servicio para evaluar videos de clases (pensado para un piloto con MINEDU) en los que un docente enseña frente a una audiencia. El sistema transforma un video de entrada en un informe estructurado con la transcripción, métricas cuantitativas del discurso, indicadores de calidad de audio, señales de comunicación no verbal, objetos/recursos detectados, y una evaluación pedagógica basada en una rúbrica de contenido y en las competencias del Marco del Buen Desempeño Docente (MBDD).

La aplicación está construida alrededor de una API FastAPI y un frontend estático incluido en el repositorio (`index.html`). Cada video sube por la API y se procesa en dos etapas independientes:

1. **Extracción** — la parte cara del pipeline (Whisper, KPIs de oratoria, postura, objetos). Se corre una sola vez por video, sin depender de ningún curso o rúbrica.
2. **Evaluación** — la parte barata (una llamada al LLM) que juzga la extracción ya hecha contra la rúbrica de un curso específico y detecta evidencia de las competencias MBDD. Puede repetirse contra otro curso sin volver a pagar el costo de la extracción.

Esto permite, por ejemplo, re-evaluar el mismo video con una rúbrica distinta en segundos, en vez de volver a correr Whisper/YOLO/MediaPipe.

## Objetivo y alcance

El proyecto sirve como base para convertir observaciones subjetivas sobre una clase en señales medibles y comparables. No pretende sustituir la evaluación humana: sus resultados son indicadores automáticos que deben interpretarse junto con el contexto, el contenido de la clase y los objetivos de cada curso.

El resultado de un análisis incluye:

- La duración del video y el total de palabras detectadas
- La transcripción completa del discurso, con señales de confianza de Whisper (`avg_logprob`, `no_speech_prob`, `compression_ratio`) y un veredicto de calidad agregado
- KPIs separados de tiempo de habla, ritmo, sentimiento, claridad y audio
- Indicadores de postura y gestos (MediaPipe) y objetos/recursos detectados en el video (YOLO)
- Una evaluación de contenido pedagógico (rúbrica configurable por curso) con `score_final`, `score_rubrica`, `score_oratoria` y un resumen ejecutivo
- Evidencia de las 9 competencias del MBDD, con nivel (sí / evidencia parcial / sin evidencia) y fuerza de la evidencia
- El estado del job y, cuando corresponde, el mensaje de error del procesamiento

## Qué incluye el proyecto

El pipeline de **extracción** realiza:

- Obtención de ficha técnica del video (resolución, duración, fps, peso)
- Extracción y normalización de audio (ffmpeg, `loudnorm`)
- División en chunks para transcripción
- Transcripción con Whisper, capturando señales de confianza por segmento y evaluando la calidad agregada de la transcripción
- Cálculo de KPIs de tiempo de habla, ritmo, sentimiento, claridad y calidad de audio
- Análisis de postura y gestos con MediaPipe Pose
- Detección de objetos/recursos educativos con YOLO (modelo COCO o un modelo propio entrenado, `.onnx`)

El pipeline de **evaluación** (repetible por curso) realiza:

- Evaluación de contenido pedagógico contra la rúbrica del curso (criterios, niveles y ponderación contenido/forma configurables)
- Generación de un resumen ejecutivo vía LLM
- Detección de evidencia de las competencias MBDD a partir de la transcripción, los KPIs y los objetos detectados

Todo se persiste en base de datos (PostgreSQL vía SQLAlchemy), con deduplicación por hash de archivo para evitar reprocesar el mismo video subido por el mismo analista.

## Estructura del proyecto

```text
.
├── main.py                    # API FastAPI: endpoints, colas, limpieza de jobs atascados
├── core.py                    # Extractor (pipeline pesado) y evaluar_extraccion (pipeline de evaluación)
├── index.html                 # Frontend estático servido por la API
├── requirements.txt           # Dependencias Python
├── Rubrica_propuesta.docx     # Documento fuente de la rúbrica de contenido pedagógico
├── ffmpeg.exe / ffprobe.exe    # Binarios usados por el pipeline (extracción de audio/frames y duración)
├── yolo26n.pt                 # Modelo YOLO base (COCO), usado si YOLO_MODEL no apunta a uno propio
├── sifods_v1_best.onnx        # Modelo YOLO propio entrenado para objetos educativos específicos
├── video/                     # Videos subidos, pendientes o en proceso de análisis
├── temp/                      # Archivos temporales (audio, chunks, frames) — se limpian al terminar
├── services/
│   ├── clarity/                # Claridad del discurso (muletillas, etc.)
│   ├── competencias_mbdd/      # Detección de evidencia de las 9 competencias del MBDD
│   ├── cursos/                 # Resuelve qué rúbrica/ponderación aplica a cada curso (lee de la BD)
│   ├── evaluacion/              # Evaluación de contenido pedagógico + resumen ejecutivo (vía LLM)
│   ├── feedback/                # Interpretación y consolidación de los KPIs de oratoria
│   ├── llm/                     # Cliente LLM (OpenAI / Azure / Anthropic / Gemini) con reintentos
│   ├── rhythm/                  # Ritmo del habla y análisis acústico
│   ├── sentiment/                # Sentimiento/tono emocional del discurso
│   ├── speech_time/              # Tiempo de habla y proporción de habla
│   ├── transcription/            # Transcripción con Whisper + señales de calidad por segmento
│   └── video/                    # Ficha técnica, postura/gestos (MediaPipe) y objetos (YOLO)
├── shared/
│   ├── database.py              # Motor, sesión y base declarativa de SQLAlchemy
│   └── models.py                 # Extraction, Evaluation y RubricaCurso (ver sección Base de datos)
└── test_objects.py               # Utilidad standalone para probar/depurar la detección YOLO
```

> Nota: las herramientas de línea de comandos para subir videos en lote, probar carga/escalabilidad del servicio, etc. no son parte del servicio en sí y viven aparte, fuera de esta estructura.

### Descripción de las carpetas

- `video/`: videos de entrada, tanto subidos vía `/analyze/upload` como colocados manualmente para `/analyze/from-file`.
- `temp/`: archivos intermedios del pipeline (audio extraído, chunks, frames para postura/objetos). Se eliminan al finalizar el procesamiento, con éxito o con error.
- `services/`: lógica especializada por indicador, cada subcarpeta con su propio analizador:
  - `services/clarity/`: indicadores de claridad del discurso a partir de las palabras transcritas.
  - `services/competencias_mbdd/`: evalúa evidencia de las 9 competencias oficiales del Marco del Buen Desempeño Docente (institución-wide, no varía por curso).
  - `services/cursos/`: resuelve la configuración (rúbrica + ponderación) de un curso leyendo la tabla `rubricas_curso`; cae a `"default"` si el curso pedido no existe o está inactivo.
  - `services/evaluacion/`: evalúa el contenido pedagógico contra la rúbrica del curso (recibida como parámetro, no fija) y redacta el resumen ejecutivo, cruzando esa lectura con los KPIs de oratoria y los objetos detectados.
  - `services/feedback/`: combina los KPIs de discurso y audio en interpretaciones y un score de oratoria.
  - `services/llm/`: encapsula la integración con el proveedor LLM configurado, con reintentos con backoff exponencial.
  - `services/rhythm/`: ritmo del habla y características acústicas.
  - `services/sentiment/`: sentimiento/tono general del discurso.
  - `services/speech_time/`: tiempo hablado y su relación con la duración total del video.
  - `services/transcription/`: transcribe con Whisper, captura `avg_logprob`/`no_speech_prob`/`compression_ratio` por segmento y evalúa la confiabilidad agregada de la transcripción.
  - `services/video/`: ficha técnica del archivo, postura/gestos (MediaPipe Pose) y detección de objetos (YOLO, modelo COCO o propio).
- `shared/`: componentes compartidos por la API y el pipeline:
  - `shared/database.py`: motor, sesión (`SessionLocal`) y base declarativa de SQLAlchemy.
  - `shared/models.py`: `Extraction` (extracciones), `Evaluation` (evaluaciones) y `RubricaCurso` (rubricas_curso) — ver [Base de datos](#base-de-datos).

Los archivos de la raíz cumplen funciones de coordinación: `main.py` expone la API, administra la cola de extracciones concurrentes y limpia jobs atascados; `core.py` contiene la clase `Extractor` (pipeline pesado) y la función `evaluar_extraccion()` (pipeline de evaluación); `index.html` es la interfaz web; `test_objects.py` es una utilidad de diagnóstico para la detección YOLO.

## Requisitos previos
- Python 3.10 o superior
- ffmpeg y ffprobe (ya incluidos en la raíz del proyecto como `ffmpeg.exe`/`ffprobe.exe`, o apuntar `FFMPEG_PATH`/`FFPROBE_PATH` a tu propia instalación)
- PostgreSQL en ejecución o una URL de base de datos accesible
- Dependencias instaladas desde `requirements.txt`
- Credenciales de un proveedor LLM (Azure OpenAI, OpenAI, Anthropic o Gemini) si se quiere la evaluación de contenido pedagógico y competencias MBDD — sin esto, el pipeline de extracción funciona igual, pero la evaluación fallará

### Verificar FFmpeg

En Windows:

```powershell
ffmpeg -version
ffprobe -version
```

## Instalación

1. Crear y activar un entorno virtual:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\activate
```

Linux/macOS:

```bash
source .venv/bin/activate
```

2. Instalar dependencias:

```bash
pip install -r requirements.txt
```

## Variables de entorno

Crea un archivo `.env` en la raíz del proyecto con algo como esto:

```env
DATABASE_URL=postgresql://postgres:password@localhost:5432/videokpi
VIDEO_FOLDER=./video
TEMP_FOLDER=./temp
FFMPEG_PATH=ffmpeg
FFPROBE_PATH=ffprobe
CHUNK_SECONDS=600
WHISPER_MODEL=small

# Autenticación de los endpoints de análisis (header X-API-Key)
API_KEY=cambiar-por-una-clave-propia

# Control de concurrencia y limpieza de jobs atascados
MAX_CONCURRENT_ANALYSIS=2
JOB_STALE_TIMEOUT_MIN=360
JOB_CLEANUP_INTERVAL_SEC=300

# Umbral de calidad de transcripción (sin calibrar todavía con datos propios)
QUALITY_PCT_THRESHOLD=25

# Detección de objetos
YOLO_MODEL=yolo26n.pt
YOLO_CONF=0.35
YOLO_SAMPLE_FPS=1

# Proveedor LLM para evaluación de contenido y competencias MBDD
LLM_PROVIDER=none
LLM_API_KEY=
LLM_MAX_REINTENTOS=3
LLM_ESPERA_INICIAL_SEG=2
DEBUG_LLM_PROMPTS=false

# Azure OpenAI (si LLM_PROVIDER=azure)
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_API_VERSION=2024-08-01-preview
AZURE_OPENAI_DEPLOYMENT=
```

### Descripción de las variables

- `DATABASE_URL`: conexión a la base de datos.
- `VIDEO_FOLDER` / `TEMP_FOLDER`: carpetas de videos de entrada y archivos temporales del pipeline.
- `FFMPEG_PATH` / `FFPROBE_PATH`: ruta a los ejecutables de ffmpeg/ffprobe.
- `CHUNK_SECONDS`: duración de cada fragmento de audio para transcripción.
- `WHISPER_MODEL`: tamaño del modelo de transcripción (`tiny`, `base`, `small`, `medium`, `large`).
- `API_KEY`: clave compartida requerida en el header `X-API-Key` para `/analyze/upload` y `/analyze/from-file`. Si no está configurada, esos endpoints rechazan toda petición (falla cerrado).
- `MAX_CONCURRENT_ANALYSIS`: cuántas extracciones pesadas (Whisper+YOLO+MediaPipe) pueden correr al mismo tiempo; el resto espera en cola.
- `JOB_STALE_TIMEOUT_MIN` / `JOB_CLEANUP_INTERVAL_SEC`: cada cuánto se revisa y después de cuántos minutos sin actividad se marca como `failed` un job que quedó atascado en `running` (por ejemplo, si el proceso se cayó a mitad del análisis).
- `QUALITY_PCT_THRESHOLD`: % máximo de segmentos de transcripción "problema" (según los umbrales internos de Whisper) que se tolera antes de marcar el video como poco confiable. Es un punto de partida, pendiente de calibrar con un lote de referencia evaluado a mano.
- `YOLO_MODEL` / `YOLO_CONF` / `YOLO_SAMPLE_FPS`: modelo de detección de objetos (`.pt` = COCO genérico, `.onnx` = modelo propio), umbral de confianza y a cuántos frames por segundo se muestrea el video.
- `LLM_PROVIDER`: proveedor activo para evaluación de contenido y competencias MBDD (`none`, `openai`, `azure`, `anthropic`, `gemini`).
- `LLM_API_KEY` / `LLM_MAX_REINTENTOS` / `LLM_ESPERA_INICIAL_SEG` / `DEBUG_LLM_PROMPTS`: clave del proveedor, reintentos con backoff exponencial ante fallos, y si se guarda el prompt completo enviado al LLM (solo para depuración — infla el tamaño del resultado guardado).
- `AZURE_OPENAI_*`: configuración específica si `LLM_PROVIDER=azure`.

## Levantar el servicio

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 9000
```

La API queda disponible en:

- http://localhost:9000
- http://localhost:9000/docs (Swagger UI)

## Flujo de uso

### 1. Subir un video para analizar

```bash
curl -X POST "http://localhost:9000/analyze/upload" \
  -H "X-API-Key: tu_clave" \
  -F "file=@video.mp4" \
  -F "nombre_analisis=Clase de fracciones" \
  -F "presentador=Juan" \
  -F "tipo=Sesion" \
  -F "dependencia=UGEL X" \
  -F "analista_id=analista-1"
```

La respuesta devuelve un `job_id` (id de la extracción) y el estado pendiente. La extracción corre en segundo plano y, al terminar, dispara automáticamente una evaluación con el curso `"default"`.

### 2. Consultar el estado

```bash
curl "http://localhost:9000/analyze/<job_id>/status"
```

### 3. Obtener el resultado combinado (extracción + evaluación)

```bash
curl "http://localhost:9000/analyze/<job_id>/result"
```

### 4. Re-evaluar el mismo video contra otro curso (sin repetir la extracción)

```bash
curl -X POST "http://localhost:9000/extracciones/<job_id>/evaluaciones" \
  -H "X-API-Key: tu_clave" \
  -F "curso_id=otro_curso"
```

## Endpoints principales

| Endpoint | Método | Descripción |
|---|---|---|
| / | GET | Sirve el frontend estático |
| /analyze/upload | POST | Sube un video, crea la extracción y encadena la evaluación por defecto |
| /analyze/from-file | POST | Analiza un video ya presente en `video/` (requiere acceso al disco del servidor) |
| /extracciones/{extraction_id}/evaluaciones | POST | Evalúa una extracción ya terminada contra un `curso_id` (re-evaluación o reintento) |
| /extracciones/{extraction_id} | GET | Datos crudos de la extracción |
| /evaluaciones/{evaluation_id} | GET | Datos crudos de una evaluación puntual |
| /analyze/{job_id}/status | GET | Estado combinado (extracción + última evaluación) |
| /analyze/{job_id} | GET | Resultado combinado en crudo |
| /analyze/{job_id}/result | GET | Resultado combinado, resumido para el frontend |
| /analyze | GET | Lista los jobs (filtrable por `analista_id`) |
| /videos | GET | Lista los videos disponibles en `VIDEO_FOLDER` |

`/analyze/upload`, `/analyze/from-file` y `POST /extracciones/{id}/evaluaciones` requieren el header `X-API-Key`; los endpoints de solo lectura no.

## Pipeline interno actual

**Extracción** (`core.Extractor`, una sola vez por video):

1. Ficha técnica del video
2. Extracción y normalización de audio
3. División en chunks para transcripción
4. Transcripción con Whisper, capturando señales de confianza por segmento
5. Evaluación de calidad agregada de la transcripción
6. KPIs de tiempo de habla, ritmo, sentimiento, claridad y audio
7. Postura y gestos (MediaPipe Pose)
8. Detección de objetos (YOLO)

**Evaluación** (`core.evaluar_extraccion`, repetible por curso sin repetir lo anterior):

9. Resolución de la configuración del curso (rúbrica + ponderación) desde `rubricas_curso`
10. Evaluación de contenido pedagógico + resumen ejecutivo vía LLM
11. Detección de evidencia de competencias MBDD

El resultado final combina ambas etapas: junto a los KPIs de extracción, incluye un campo `evaluacion` con `score_final`, `score_rubrica`, `score_oratoria`, `criterios` y `resumen_ejecutivo`, y un campo `competencias_mbdd` con la evidencia por competencia.

## Base de datos

Al iniciar la aplicación, SQLAlchemy crea automáticamente las tablas necesarias. Los modelos son:

- **`Extraction`** (`extracciones`): la parte cara del análisis — Whisper, KPIs de oratoria, postura, objetos, ficha técnica. Se corre una sola vez por video. Incluye `file_hash` para deduplicar videos ya procesados por el mismo analista.
- **`Evaluation`** (`evaluaciones`): la parte barata — rúbrica de contenido + competencias MBDD, evaluadas contra un `curso_id`. Varias evaluaciones pueden apuntar a la misma extracción (FK `extraction_id`), para re-evaluar con otro curso o reintentar sin pagar de nuevo el costo de la extracción.
- **`RubricaCurso`** (`rubricas_curso`): configuración de evaluación por curso — criterios de contenido (con niveles y pesos) y la ponderación contenido/forma. Cada curso es una fila cargada directamente en la base (sin UI de administración todavía); el curso `"default"` debe existir siempre como fallback.

## Notas importantes

- El análisis puede tardar varios minutos según la duración del video y el modelo Whisper usado; con `MAX_CONCURRENT_ANALYSIS` limitado, los videos adicionales esperan en cola.
- El primer uso de YOLO puede descargar o cargar pesos del modelo desde disco.
- Los archivos temporales se almacenan en `temp/` y se limpian al finalizar el proceso, con éxito o con error.
- La evaluación de contenido y competencias MBDD requiere un proveedor LLM configurado (`LLM_PROVIDER` distinto de `none`); sin esto, la extracción se completa pero la evaluación fallará.
- Si la calidad de la transcripción cae por debajo del umbral configurado, el video se marca como poco confiable en los logs del servidor (auditoría interna), no en la interfaz visible al usuario.
- Para producción conviene rotar `API_KEY` y restringir el acceso a la base de datos.

## Troubleshooting rápido

- Si falla ffmpeg/ffprobe: revisa `FFMPEG_PATH`/`FFPROBE_PATH` y que los binarios sean accesibles.
- Si falla PostgreSQL: verifica `DATABASE_URL` y que el servidor esté corriendo.
- Si falla la detección visual: revisa `YOLO_MODEL`, `YOLO_CONF` y `YOLO_SAMPLE_FPS`.
- Si la evaluación falla con error de curso: confirma que exista la fila `"default"` en `rubricas_curso` (ver `services/cursos/registro.py`).
- Si la evaluación falla o no se genera el resumen ejecutivo: revisa que `LLM_PROVIDER` y las credenciales correspondientes estén configuradas.
- Si hay errores de dependencias: vuelve a ejecutar `pip install -r requirements.txt`.
