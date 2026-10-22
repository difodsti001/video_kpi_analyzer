# Video KPI Analyzer

Video KPI Analyzer convierte un video temporal de aula en una **ficha de evidencias pedagógicas**. Combina transcripción, señales de audio y video, descripciones visuales con tiempo y orientación pedagógica guiada por una rúbrica configurable.

No reemplaza la valoración humana. La rúbrica organiza las evidencias y la retroalimentación; una persona revisa la ficha y realiza la valoración posterior.

```text
Video temporal → extracción de evidencias → análisis pedagógico
               → ficha + orientación narrativa → valoración humana externa
```

## Resultado

- Transcripción por segmentos y calidad agregada de Whisper.
- Ficha multimodal por tiempo: audio, descripción visual, fuente y confianza.
- Señales de discurso, postura, recursos y composición visual.
- Orientación pedagógica por criterio, vinculada a evidencias temporales reales.
- Evidencia relacionada con las competencias del MBDD.
- Uso de IA por llamada: proveedor, modelo, solicitudes, imágenes y tokens; sin precios ni costos.

La ficha no identifica biométricamente a las personas ni atribuye automáticamente roles como docente o estudiante. La ausencia de evidencia tampoco demuestra la ausencia de un hecho.

## Retención

- El video fuente se elimina después de una extracción exitosa.
- No se conservan clips, audio temporal ni frames.
- Los frames usados por visión se procesan solo en memoria; se persiste únicamente texto con tiempo.

## Arquitectura

```text
services/
├── extractions/
│   ├── transcription/       # Whisper y calidad de transcripción
│   ├── speech_time/, rhythm/, sentiment/, clarity/, audio/
│   ├── posture/             # MediaPipe Pose
│   ├── objects/             # YOLO / ONNX Runtime
│   ├── vision_description/ # Descripción visual temporal con modelo multimodal
│   ├── evidence_fusion/     # Ficha de evidencias por ventanas
│   └── video_info/          # Datos técnicos del video
├── pedagogical_analysis/
│   ├── evaluacion/          # Orientación pedagógica trazable por rúbrica
│   └── competencias_mbdd/   # Evidencia relacionada con MBDD
└── transversal/
    ├── cursos/              # Rúbricas configurables por curso
    ├── feedback/            # Interpretación de KPIs por reglas
    └── llm/                 # Proveedores LLM y captura de tokens
```

Archivos principales: `main.py` (API), `jobs.py` (trabajos y persistencia), `core.py` (pipeline), `index.html` (interfaz) y `shared/models.py` (modelos de base de datos).

## Requisitos e instalación

- Python 3.10 o superior.
- PostgreSQL.
- FFmpeg y FFprobe.
- Dependencias de `requirements.txt`.
- Un proveedor LLM para visión, orientación pedagógica y MBDD.

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 9000
```

La interfaz queda en `http://localhost:9000` y Swagger en `http://localhost:9000/docs`.

## Configuración

Ejemplo de `.env`:

```env
DATABASE_URL=postgresql://postgres:password@localhost:5432/videokpi
VIDEO_FOLDER=./video
TEMP_FOLDER=./temp
FFMPEG_PATH=ffmpeg
FFPROBE_PATH=ffprobe
WHISPER_MODEL=small
API_KEY=cambiar-por-una-clave-propia

LLM_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_API_VERSION=2024-05-01-preview
AZURE_OPENAI_DEPLOYMENT=

YOLO_MODEL=sifods_v1_best.onnx
YOLO_FALLBACK_MODEL=sifods_v1_best.onnx
YOLO_CONF=0.35
YOLO_SAMPLE_FPS=1

VISION_ENABLED=true
VISION_SAMPLE_SECONDS=30
VISION_BATCH_SIZE=4
VISION_MAX_FRAMES=120
VISION_MAX_WIDTH=768
EVIDENCE_WINDOW_SECONDS=30
```

- `VISION_SAMPLE_SECONDS`: menor intervalo produce mayor detalle y más tokens.
- `VISION_BATCH_SIZE`: imágenes enviadas por llamada de visión.
- `VISION_MAX_FRAMES`: límite de frames para videos largos.
- `YOLO_FALLBACK_MODEL`: ONNX local usado si un checkpoint `.pt` no es compatible.
- `EVIDENCE_WINDOW_SECONDS`: duración de cada ventana de la ficha.

## Rúbricas por curso

Las rúbricas se almacenan en `rubricas_curso`. Cada `curso_id` puede tener criterios, descripciones y ponderaciones propias. El curso `default` usa la rúbrica MBDD configurada con 90 % pedagógico y 10 % oratoria.

```text
curso A → rúbrica A → orientación A
curso B → rúbrica B → orientación B
```

Cambiar de rúbrica no obliga a repetir Whisper, YOLO, MediaPipe ni visión: se reutiliza la extracción persistida.

## Flujo interno

1. Se sube el video.
2. Se extraen audio, transcripción, KPIs, postura, objetos, ficha técnica y descripción visual.
3. Se genera la ficha de evidencias con marcas de tiempo.
4. Se elimina el material temporal y el video fuente tras una extracción exitosa.
5. Se aplica la rúbrica para producir orientación pedagógica y evidencia MBDD.
6. Se registra el modelo y los tokens de cada llamada a IA.

La orientación pública se construye desde IDs de evidencia reales: el backend inserta el tiempo y fragmento seleccionado, evitando afirmaciones sin trazabilidad.

## Endpoints

| Endpoint | Método | Descripción |
|---|---|---|
| `/analyze/upload` | POST | Sube un video e inicia la extracción. |
| `/analyze/from-file` | POST | Analiza un video existente en `video/`. |
| `/analyze/{job_id}/status` | GET | Estado del trabajo. |
| `/analyze/{job_id}` | GET | Resultado para la interfaz. |
| `/analyze/{job_id}/result` | GET | Resultado resumido. |
| `/analyze/{job_id}/ficha-evidencias` | GET | Ficha persistente sin medios. |
| `/analyze/{job_id}/consumo-ia` | GET | Uso de IA por llamada, sin costos. |
| `/extracciones/{id}/evaluaciones` | POST | Ejecuta análisis pedagógico contra otro curso. |
| `/evaluaciones/{id}` | GET | Resultado de un análisis puntual. |

Los endpoints de inicio y reanálisis requieren el header `X-API-Key`.

## Uso de IA y tokens

`consumo_ia` guarda una fila por llamada exitosa:

```text
extraction_id, evaluation_id, capa_ia, proveedor, modelo,
solicitudes, imagenes_enviadas, tokens_entrada, tokens_salida,
tokens_totales, estado, fecha
```

Las capas actuales son `descripcion_visual`, `analisis_pedagogico` y `competencias_mbdd`. Los datos están destinados a que otro equipo estime costos con sus propias tarifas.

## Troubleshooting

- MediaPipe falla: confirme la versión de `protobuf` fijada en `requirements.txt`.
- YOLO `.pt` incompatible: use `sifods_v1_best.onnx` o configure `YOLO_FALLBACK_MODEL`.
- Visión vacía: verifique un deployment compatible con imágenes y `VISION_ENABLED=true`.
- Rúbrica no visible: reinicie el servidor y confirme el curso en `rubricas_curso`.
- Sin tokens: la trazabilidad comienza con la versión que incorpora `consumo_ia`; no reconstruye llamadas históricas.
