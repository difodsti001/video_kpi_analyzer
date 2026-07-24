# Video KPI Analyzer

Video KPI Analyzer es un servicio web para procesar videos, extraer métricas de discurso y devolver un resultado estructurado con transcripción, KPIs y feedback. El flujo actual incluye análisis de audio, postura, gestos y detección de objetos educativos.

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
- Generación de feedback interpretativo
- Persistencia de jobs y resultados en base de datos

## Estructura del proyecto

```text
.
├── main.py                 # API FastAPI, autenticación y endpoints
├── core.py                 # Pipeline principal de análisis
├── index.html              # Frontend estático servido por la API
├── requirements.txt        # Dependencias Python
├── video/                  # Videos disponibles para análisis
├── temp/                   # Archivos temporales generados durante el proceso
├── services/
│   ├── clarity/            # Análisis de claridad
│   ├── feedback/           # Generación de feedback
│   ├── rhythm/             # Ritmo y métrica del discurso
│   ├── sentiment/          # Análisis de sentimiento
│   ├── speech_time/        # Tiempo de habla
│   ├── transcription/      # Transcripción con Whisper
│   └── video/              # Postura, gestos y detección de objetos
├── shared/
│   ├── database.py         # Configuración SQLAlchemy
│   ├── models.py           # Modelos de usuario y jobs
│   └── schemas.py          # Esquemas auxiliares
└── test.py                 # Utilidades de ejemplo/pruebas
```

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
- LLM_PROVIDER / LLM_API_KEY: integración opcional para feedback con modelo externo

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

1. Se extrae el audio del video
2. Se divide en fragmentos para transcripción
3. Se transcribe el contenido con Whisper
4. Se calculan KPIs de speech time, rhythm, sentiment, clarity y audio
5. Se analiza postura y gestos con MediaPipe Pose
6. Se detectan objetos relevantes con YOLO
7. Se construye un feedback general
8. Se guarda el resultado y el estado del job en la base de datos

## Base de datos

Al iniciar la aplicación, SQLAlchemy crea automáticamente las tablas necesarias. Los modelos principales son:

- AnalysisJob: representa cada trabajo de análisis
- User: representa los usuarios del sistema

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
