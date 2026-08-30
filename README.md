# Video KPI Analyzer

Video KPI Analyzer es una aplicación web para evaluar presentaciones, clases, reuniones u otros videos en los que una persona habla frente a una audiencia. El sistema transforma un video de entrada en un informe estructurado con la transcripción, métricas cuantitativas del discurso, indicadores de calidad de audio, señales de comunicación no verbal y recomendaciones de mejora.

La aplicación está construida alrededor de una API FastAPI y un frontend estático incluido en el repositorio. Cada video se registra como un job de análisis: la API recibe el archivo y sus datos descriptivos, responde con un identificador y ejecuta el procesamiento en segundo plano. Esto permite consultar el estado mientras se ejecutan modelos de transcripción y visión por computadora, y recuperar posteriormente el resultado completo o un resumen preparado para consumo del frontend.

El análisis combina varias fuentes de información. El audio se extrae y se normaliza con FFmpeg; después se divide en fragmentos para transcribirlo con Whisper. A partir de la transcripción se calculan el tiempo de habla, el ritmo, la claridad y el sentimiento. En paralelo, se revisan características acústicas, postura y gestos mediante MediaPipe, y se detectan objetos presentes en los fotogramas con YOLO. Finalmente, los indicadores se integran en un feedback general que ayuda a interpretar el desempeño del presentador.

Además del análisis, el servicio incluye autenticación mediante JWT, gestión de usuarios y persistencia de jobs y resultados en PostgreSQL a través de SQLAlchemy. También calcula una huella del archivo para identificar si el mismo video ya fue procesado por un analista, evitando repetir trabajos completados.

## Objetivo y alcance

El proyecto sirve como base para convertir observaciones subjetivas sobre una presentación en señales medibles y comparables. No pretende sustituir la evaluación humana: sus resultados son indicadores automáticos que deben interpretarse junto con el contexto, el contenido de la presentación y los objetivos de cada análisis.

El resultado de un análisis incluye:

- La duración del video y el total de palabras detectadas
- La transcripción completa del discurso
- KPIs separados de tiempo de habla, ritmo, sentimiento, claridad y audio
- Indicadores de postura, gestos y objetos detectados en el video
- Feedback consolidado a partir de los KPIs de discurso y audio
- El estado del job y, cuando corresponde, el mensaje de error del procesamiento

## Qué incluye el proyecto

El pipeline actual realiza lo siguiente:

- Extracción de audio desde el video
- División en chunks para transcripción
- Transcripción con Whisper
- Cálculo de KPIs de:
  - tiempo de habla
  - ritmo
  - sentimiento
  - claridad
  - calidad de audio
  - postura y gestos
  - detección de objetos visuales
  - información técnica del video
- Evaluación docente integral con rúbrica pedagógica y resumen ejecutivo
- Generación de feedback interpretativo
- Persistencia de jobs y resultados en base de datos
- Integración opcional con LLM para evaluación de contenido pedagógico y resumen ejecutivo

## Estructura del proyecto

```text
.
├── main.py                 # API FastAPI, gestión de jobs y endpoints principales
├── core.py                 # Pipeline principal del análisis de video
├── index.html              # Frontend estático servido por la API
├── requirements.txt        # Dependencias Python
├── video/                  # Videos disponibles para análisis
├── temp/                   # Archivos temporales generados durante el proceso
├── services/
│   ├── clarity/            # Análisis de claridad del discurso
│   ├── evaluacion/         # Evaluación docente, rúbrica y resumen ejecutivo
│   ├── feedback/           # Interpretación y consolidación de indicadores
│   ├── llm/                # Clientes LLM para OpenAI / Azure / Anthropic / Gemini
│   ├── rhythm/             # Ritmo y métricas de audio/discurso
│   ├── sentiment/          # Análisis de sentimiento y tono emocional
│   ├── speech_time/        # Tiempo de habla y proporción de habla
│   ├── transcription/      # Transcripción con Whisper y gestión de chunks
│   └── video/              # Información del video, postura, gestos y detección con YOLO
├── shared/
│   ├── database.py         # Configuración SQLAlchemy
│   ├── models.py           # Modelos de usuario y jobs
│   └── schemas.py          # Esquemas auxiliares
├── test.py                 # Utilidades de ejemplo/pruebas
├── test_objects.py         # Pruebas y utilidades de detección de objetos
└── README.md               # Documentación del proyecto
```

### Descripción de las carpetas

- `video/`: almacena los videos de entrada disponibles para análisis. Se utiliza tanto para los archivos incluidos previamente como para los videos recibidos mediante el endpoint de carga.
- `temp/`: contiene los archivos intermedios creados durante el procesamiento, como el audio WAV extraído, los fragmentos de audio y los fotogramas usados por el análisis visual. Estos archivos se eliminan al finalizar el pipeline cuando el proceso termina correctamente o con error.
- `services/`: agrupa la lógica especializada de cada indicador. Cada subcarpeta mantiene un analizador independiente para que el pipeline principal pueda coordinar los pasos sin mezclar sus responsabilidades:
  - `services/clarity/`: calcula indicadores relacionados con la claridad del discurso a partir de las palabras y la transcripción.
  - `services/evaluacion/`: evalúa la calidad docente con una rúbrica pedagógica, pondera contenido y forma, y genera un resumen ejecutivo a partir de la evidencia del video y la transcripción.
  - `services/feedback/`: combina los KPIs de discurso y audio para generar una interpretación y recomendaciones generales.
  - `services/llm/`: encapsula la integración con proveedores LLM para producir una evaluación más rica y un resumen ejecutivo cuando hay configuración activa.
  - `services/rhythm/`: analiza el ritmo del habla y contiene también el análisis de características acústicas.
  - `services/sentiment/`: estima el sentimiento o tono general del discurso usando la transcripción y la información temporal de las palabras.
  - `services/speech_time/`: calcula métricas sobre el tiempo hablado y su relación con la duración total del video.
  - `services/transcription/`: extrae la duración, transcribe el audio con Whisper y normaliza los segmentos y palabras reconocidos.
  - `services/video/`: procesa la parte visual del video; analiza información técnica, postura, gestos con MediaPipe y detecta objetos mediante YOLO.
- `shared/`: reúne componentes compartidos por la API y el pipeline, sin pertenecer a un KPI concreto:
  - `shared/database.py`: crea el motor, la sesión y la base declarativa de SQLAlchemy.
  - `shared/models.py`: define las entidades persistidas, principalmente usuarios y trabajos de análisis.
  - `shared/schemas.py`: contiene esquemas auxiliares para validar o estructurar datos intercambiados por la aplicación.

Los archivos de la raíz cumplen funciones de coordinación: `main.py` expone la API y administra los jobs, `core.py` ejecuta el pipeline completo, `index.html` proporciona la interfaz web, `requirements.txt` fija las dependencias del proyecto y `test.py` / `test_objects.py` sirven de referencia para pruebas y utilidades de diagnóstico.

## Requisitos previos
- Python 3.10 o superior
- ffmpeg y ffprobe disponibles en PATH
- PostgreSQL en ejecución o una URL de base de datos accesible
- Dependencias instaladas desde requirements.txt

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

Crea un archivo .env en la raíz del proyecto con algo como esto:

```env
DATABASE_URL=postgresql://postgres:password@localhost:5432/videokpi
VIDEO_FOLDER=./video
TEMP_FOLDER=./temp
SECRET_KEY=cambiar-en-produccion
FFMPEG_PATH=ffmpeg
FFPROBE_PATH=ffprobe
CHUNK_SECONDS=600
WHISPER_MODEL=base
YOLO_MODEL=yolo26n.pt
YOLO_CONF=0.35
YOLO_FRAME_SKIP=2
LLM_PROVIDER=none
LLM_API_KEY=
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_API_VERSION=2024-08-01-preview
AZURE_OPENAI_DEPLOYMENT=
```

### Descripción de las variables

- DATABASE_URL: conexión a la base de datos
- VIDEO_FOLDER: carpeta donde se guardan los videos de entrada
- TEMP_FOLDER: carpeta temporal para audio, chunks y frames
- SECRET_KEY: clave para firmar JWT
- FFMPEG_PATH / FFPROBE_PATH: ejecutables de ffmpeg y ffprobe
- CHUNK_SECONDS: duración de cada fragmento de audio
- WHISPER_MODEL: tamaño del modelo de transcripción
- YOLO_MODEL / YOLO_CONF / YOLO_FRAME_SKIP: configuración para detección de objetos
- LLM_PROVIDER: proveedor activo para la evaluación docente con LLM (`none`, `openai`, `azure`, `anthropic`, `gemini`)
- LLM_API_KEY: clave del proveedor seleccionado
- AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY / AZURE_OPENAI_API_VERSION / AZURE_OPENAI_DEPLOYMENT: configuración específica para Azure OpenAI

## Levantar el servicio

Ejecuta:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

La API quedará disponible en:

- http://localhost:8000
- http://localhost:8000/docs (Swagger UI)

## Flujo de uso

### 1. Registrar un usuario

```bash
curl -X POST "http://localhost:8000/auth/register?email=demo@email.com&nombre=Demo&password=123456&rol=analista"
```

### 2. Iniciar sesión

```bash
curl -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=demo@email.com&password=123456"
```

### 3. Subir un video para analizar

```bash
curl -X POST "http://localhost:8000/analyze/upload" \
  -F "file=@video.mp4" \
  -F "nombre_analisis=Mi video" \
  -F "presentador=Juan" \
  -F "tipo=Presentacion" \
  -F "dependencia=Ventas" \
  -F "analista_id=analista-1"
```

La respuesta devuelve un job_id y el estado pendiente. El análisis se ejecuta en segundo plano.

### 4. Consultar el estado del job

```bash
curl "http://localhost:8000/analyze/<job_id>/status"
```

### 5. Obtener el resultado

```bash
curl "http://localhost:8000/analyze/<job_id>/result"
```

## Endpoints principales

| Endpoint | Método | Descripción |
|---|---|---|
| / | GET | Sirve el frontend estático |
| /auth/login | POST | Inicio de sesión con JWT |
| /auth/register | POST | Registro de usuario |
| /analyze/upload | POST | Sube un video y crea un job de análisis |
| /analyze/from-file | POST | Analiza un video ya presente en la carpeta video/ |
| /analyze/{job_id}/status | GET | Consulta el estado del job |
| /analyze/{job_id} | GET | Devuelve el resultado crudo del job |
| /analyze | GET | Lista los jobs de análisis |
| /videos | GET | Lista los videos disponibles |
| /analyze/{job_id}/result | GET | Devuelve un resumen limpio del análisis |

## Pipeline interno actual

El flujo interno del análisis sigue este orden:

1. Se obtiene la información técnica del video
2. Se extrae el audio del video
3. Se divide en fragmentos para transcripción
4. Se transcribe el contenido con Whisper
5. Se calculan KPIs de speech time, rhythm, sentiment, clarity y audio
6. Se analiza postura y gestos con MediaPipe Pose
7. Se detectan objetos relevantes con YOLO
8. Se construye una evaluación docente con rúbrica y resumen ejecutivo usando el proveedor LLM configurado
9. Se guarda el resultado y el estado del job en la base de datos

El resultado final incluye además de los KPIs, un campo `evaluacion` con `score_final`, `score_rubrica`, `score_oratoria`, `criterios` y `resumen_ejecutivo` para un análisis más completo de la presentación.

## Base de datos

Al iniciar la aplicación, SQLAlchemy crea automáticamente las tablas necesarias. El modelo principal es:

- AnalysisJob: representa cada trabajo de análisis, guarda el estado, el resultado, la ruta del video, los metadatos del análisis y el hash del archivo para evitar duplicados.

La API actual del repositorio se centra en la gestión de jobs de análisis y el resultado del procesamiento; la parte de autenticación mencionada en otros documentos no es el flujo activo en este código base.

## Notas importantes

- El análisis puede tardar varios minutos según el tamaño del video y el modelo Whisper usado.
- El primer uso de YOLO puede descargar pesos del modelo automáticamente.
- Los archivos temporales se almacenan en temp/ y se limpian tras finalizar el proceso.
- Para producción conviene cambiar SECRET_KEY y proteger el acceso a la base de datos y a los endpoints.

## Troubleshooting rápido

- Si falla ffmpeg: revisa que esté instalado y accesible desde PATH
- Si falla PostgreSQL: verifica DATABASE_URL y que el servidor esté corriendo
- Si falla la detección visual: revisa YOLO_MODEL, YOLO_CONF y YOLO_FRAME_SKIP
- Si hay errores de dependencias: vuelve a ejecutar pip install -r requirements.txt
