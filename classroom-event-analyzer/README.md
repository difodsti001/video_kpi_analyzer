# Classroom Event Analyzer

MVP independiente para extraer eventos visuales observables de videos de aula.
No reconoce rostros, no identifica estudiantes y no depende del servicio
`video-kpi-analyzer`.

## Alcance inicial

- Tracking anónimo de personas con YOLO + ByteTrack.
- Selección heurística del presentador: pista con mayor presencia y área media.
- Línea de tiempo por pista: posición, caja y duración visible.
- Evento `presentador_desplazamiento` basado en desplazamiento sostenido.
- Capa opcional de IA de visión que resume ventanas de tiempo en lenguaje
  objetivo y estructurado, sin identificar rostros ni inferir intenciones.
- Fusión: una observación de IA se marca como corroborada solo si coincide en
  el tiempo con evidencia de tracking o pose.

La detección de mano levantada se deja para la segunda fase: requiere pose
**multipersona** o un clasificador temporal entrenado con clips de aula.

## Instalación

```powershell
cd classroom-event-analyzer
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## Uso

```powershell
python -m app.cli ..\video\clase.mp4 --output resultado_eventos.json
```

Para habilitar la detección multipersona de mano levantada, proporciona un
modelo YOLO de pose:

```powershell
python -m app.cli ..\video\clase.mp4 --pose-model yolo11n-pose.pt --output resultado_eventos.json
```

El primer uso puede descargar el modelo indicado. La salida conserva pistas
anónimas y solo confirma el evento cuando la postura se mantiene en el tiempo.

## Modo híbrido: IA de visión + evidencia instrumental

El modo híbrido toma tres frames por cada ventana de 15 segundos, los envía a
un modelo de visión y solicita una única síntesis estrictamente visible por
ventana. No analiza cada frame: hacerlo elevaría el costo y no aportaría
información proporcional. Los frames se redimensionan en memoria y no se
guardan en disco.

Con Azure OpenAI configurado en el archivo `.env` del proyecto padre:

```powershell
python -m app.cli ..\video\clase.mp4 --pose-model yolo11n-pose.pt --vision-provider azure --output resultado_hibrido.json
```

Con OpenAI, configura `OPENAI_API_KEY` (y opcionalmente `OPENAI_VISION_MODEL`)
en `.env` y ejecuta `--vision-provider openai`. Puede cambiar la granularidad:

```powershell
python -m app.cli ..\video\clase.mp4 --vision-provider azure --vision-window-seconds 20
```

La salida incluye tres capas: `events` (reglas verificables),
`visual_descriptions` (lo dicho por la IA) y `hybrid_observations` (la unión,
con el campo `verification`). Una observación sin corroboración sigue siendo
una pista para revisión, no una afirmación automática sobre la clase.

### Comparar pose de YOLO y MediaPipe

`--mediapipe-presenter` habilita una segunda medición, exclusivamente sobre el
recorte del presentador elegido por la heurística de YOLO. Los recortes se
procesan en memoria y no se guardan. El JSON incorpora
`mediapipe_presenter_pose` con la señal `hand_up` y la inclinación de hombros;
no la convierte automáticamente en un evento ni en identidad.

```powershell
python -m app.cli ..\video\clase.mp4 --sample-fps 4 --pose-model yolo11n-pose.pt --vision-provider azure --mediapipe-presenter --output resultado_comparativo.json
```

### Personas anónimas que reaparecen

Activa `--appearance-reid` para vincular tracklets compatibles dentro de un
único video como `persona_1`, `persona_2`, etc. El comparador usa color de
ropa, posición y tiempo; excluye la franja superior del recorte corporal
y no almacena rostros, recortes ni vectores de apariencia en el JSON.

```powershell
python -m app.cli ..\video\clase.mp4 --sample-fps 4 --pose-model yolo11n-pose.pt --appearance-reid --output resultado_personas.json
```

La coincidencia es una inferencia visual y no una identidad civil. Si dos
personas llevan ropa similar, el resultado puede asignar personas distintas o
fusionarlas; debe revisarse con clips anotados antes de usarlo para decisiones.

Por defecto intenta usar el modelo COCO ya presente en el proyecto padre
(`../yolo26n.pt`). Para usar otro modelo:

```powershell
python -m app.cli clase.mp4 --model C:\modelos\yolo.pt
```

## Salida

```json
{
  "events": [
    {
      "type": "presentador_desplazamiento",
      "start_seconds": 42.0,
      "end_seconds": 47.5,
      "subject": "presentador",
      "confidence": 0.81,
      "evidence": {
        "track_id": 3,
        "horizontal_displacement": 0.23
      }
    }
  ]
}
```

Los `track_id` son identificadores efímeros del video: no deben persistirse
como identidad de una persona entre videos.

## Próximas fases

1. Diarización de audio para eventos de cambio de hablante.
2. Fusión de eventos visuales y audio/transcripción.
3. Conjunto de clips anotados para medir precisión, recall y falsos positivos.
4. Clasificador propio para acciones específicas de aula.
