# Video KPI Analyzer

Video KPI Analyzer es un servicio web para analizar videos de presentaciones, entrevistas o discursos y obtener indicadores de desempeño mediante procesamiento de audio, transcripción, análisis de ritmo, sentimiento, claridad, postura y generación de feedback.

El proyecto está desarrollado con FastAPI, SQLAlchemy, Whisper, OpenCV/Mediapipe, librosa y otras bibliotecas de análisis de audio y visión.

## 1. ¿Qué hace este proyecto?

El sistema procesa un video y devuelve un resultado estructurado con:

- Transcripción del audio
- Tiempo de habla
- Ritmo y fluidez del discurso
- Análisis de sentimiento
- Métricas de claridad
- Análisis de audio (calidad/ruido/etc.)
- Análisis de postura mediante video
- Feedback general del desempeño

## 2. Estructura del proyecto

```text
.
├── main.py                 # Aplicación FastAPI y endpoints HTTP
├── core.py                 # Pipeline principal de análisis del video
├── requirements.txt        # Dependencias de Python
├── index.html              # Frontend estático servido por la API
├── video/                  # Carpeta para videos ya disponibles
├── temp/                   # Archivos temporales generados durante análisis
├── services/
│   ├── clarity/            # Análisis de claridad
│   ├── feedback/           # Generación de feedback
│   ├── rhythm/             # Ritmo y métricas de speaking cadence
│   ├── sentiment/          # Sentimiento y tono del discurso
│   ├── speech_time/        # Tiempo de habla
│   ├── transcription/      # Transcripción con Whisper
│   ├── video/              # Postura / análisis visual
│   └── audio_analyzer.py   # Utilidades de audio
├── shared/
│   ├── database.py         # Configuración de SQLAlchemy y base de datos
│   ├── models.py           # Modelos de usuario y jobs de análisis
│   └── schemas.py          # Esquemas (si aplica en futuras extensiones)
└── test.py                 # Pruebas o utilidades de ejemplo
```

## 3. Requisitos previos

Antes de levantar el servicio, necesitas tener instalado:

- Python 3.10+ (se recomienda 3.12)
- ffmpeg y ffprobe disponibles en PATH
- PostgreSQL (o ajustar DATABASE_URL a una base compatible)
- Dependencias de Python listadas en requirements.txt

### Instalar ffmpeg

En Windows:

- Descarga FFmpeg y añade la carpeta bin al PATH
- Verifica con:

```powershell
ffmpeg -version
ffprobe -version
```

## 4. Instalación

1. Clona o entra al proyecto:

```bash
git clone <repo-url>
cd video-kpi-analyzer
```

2. Crea un entorno virtual:

```bash
python -m venv .venv
```

3. Activa el entorno virtual:

En Windows PowerShell:

```powershell
.\.venv\Scripts\activate
```

En Linux/macOS:

```bash
source .venv/bin/activate
```

4. Instala las dependencias:

```bash
pip install -r requirements.txt
```

## 5. Variables de entorno

El proyecto utiliza un archivo .env para configurar el comportamiento del servicio. Crea un archivo .env en la raíz del proyecto con algo similar a esto:

```env
DATABASE_URL=postgresql://postgres:password@localhost:5432/videokpi
VIDEO_FOLDER=./video
TEMP_FOLDER=./temp
SECRET_KEY=cambiar-en-produccion
FFMPEG_PATH=ffmpeg
FFPROBE_PATH=ffprobe
CHUNK_SECONDS=600
WHISPER_MODEL=base
LLM_PROVIDER=none
LLM_API_KEY=
```

### Descripción de variables

- DATABASE_URL: conexión a la base de datos
- VIDEO_FOLDER: carpeta donde se esperan los videos ya cargados
- TEMP_FOLDER: carpeta usada temporalmente para audio, chunks y frames
- SECRET_KEY: clave para firmar tokens JWT
- FFMPEG_PATH / FFPROBE_PATH: ruta a ffmpeg y ffprobe
- CHUNK_SECONDS: tamaño de cada fragmento de audio para procesamiento
- WHISPER_MODEL: tamaño del modelo de Whisper (base, small, medium, etc.)
- LLM_PROVIDER / LLM_API_KEY: usados por el módulo de feedback si se habilita un proveedor externo

## 6. Cómo levantar el servicio

Una vez instaladas las dependencias y configurado .env, el servicio se levanta con:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

La API quedará disponible en:

- http://localhost:8000
- http://localhost:8000/docs para la documentación Swagger

## 7. Flujo de uso del servicio

### 7.1 Cargar un video

El servicio permite dos formas de iniciar un análisis:

1. Subir un video desde el frontend o un cliente HTTP
2. Usar un video ya presente en la carpeta video/

### 7.2 Endpoint de autenticación

#### Login

```bash
curl -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=tu@email.com&password=tu-password"
```

#### Registro

```bash
curl -X POST "http://localhost:8000/auth/register?email=tu@email.com&nombre=TuNombre&password=tu-password&rol=analista"
```

### 7.3 Subir y analizar un video

```bash
curl -X POST "http://localhost:8000/analyze/upload" \
  -F "file=@video.mp4" \
  -F "nombre_analisis=Mi video" \
  -F "presentador=Juan" \
  -F "tipo=Presentacion" \
  -F "dependencia=Ventas" \
  -F "analista_id=analista-1"
```

### 7.4 Consultar estado del análisis

```bash
curl "http://localhost:8000/analyze/<job_id>/status"
```

### 7.5 Obtener resultado final

```bash
curl "http://localhost:8000/analyze/<job_id>/result"
```

## 8. Endpoints principales

| Endpoint | Método | Descripción |
|---|---|---|
| / | GET | Sirve el frontend estático |
| /auth/login | POST | Inicio de sesión con JWT |
| /auth/register | POST | Registro de usuario |
| /analyze/upload | POST | Sube un video y crea un job de análisis |
| /analyze/from-file | POST | Analiza un video ya almacenado en la carpeta video/ |
| /analyze/{job_id}/status | GET | Consulta el estado del job |
| /analyze/{job_id} | GET | Devuelve el resultado crudo del job |
| /analyze | GET | Lista los jobs disponibles |
| /videos | GET | Lista los videos disponibles en la carpeta video/ |
| /analyze/{job_id}/result | GET | Devuelve un resumen limpio del análisis |

## 9. Cómo funciona el pipeline interno

El flujo principal del análisis es el siguiente:

1. Se extrae el audio del video
2. Se divide en chunks de audio
3. Se transcribe el contenido con Whisper
4. Se calculan KPIs de:
   - speech time
   - rhythm
   - sentiment
   - clarity
   - audio quality
   - posture
5. Se construye un feedback general
6. Se almacena el resultado en la base de datos y se expone por la API

## 10. Base de datos

Al iniciar la aplicación, se crean automáticamente las tablas necesarias con SQLAlchemy.

El modelo principal es:

- AnalysisJob: representa cada trabajo de análisis
- User: representa los usuarios autenticados

## 11. Notas importantes

- El análisis puede tardar varios minutos dependiendo del tamaño del video y del modelo Whisper usado.
- Los archivos temporales se almacenan en la carpeta temp/ y se limpian al final del proceso.
- Si el servicio falla por problemas con ffmpeg o Whisper, verifica la instalación y la configuración del entorno.
- Para producción, conviene cambiar SECRET_KEY y proteger la base de datos y los endpoints.

## 12. Ejecutar en modo desarrollo

```bash
uvicorn main:app --reload
```

## 13. Troubleshooting rápido

### Error con ffmpeg

Verifica que esté instalado y accesible desde la terminal.

### Error al conectar con PostgreSQL

Revisa DATABASE_URL y que el servidor PostgreSQL esté corriendo.

### Error de dependencias

Vuelve a instalar el contenido de requirements.txt:

```bash
pip install -r requirements.txt
```

## 14. Resumen

Este proyecto convierte un video en un conjunto de KPIs y observaciones útiles para evaluar la calidad de un discurso o presentación. Está pensado como una API que puede ser consumida por un frontend o por otros servicios.
