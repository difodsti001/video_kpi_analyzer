# Herramientas externas

Scripts que **consultan** el servicio de análisis de videos (FastAPI) desde
afuera, vía HTTP — no son parte del servicio. El servicio en sí vive en la
raíz del proyecto (`main.py`, `core.py`, `services/`, `shared/`, `index.html`)
y no depende de nada de esta carpeta.

Cada archivo:

- **`cliente_comun.py`** — utilidades compartidas por los otros dos scripts
  (autenticación, medición de tiempo/errores HTTP, escritura de CSV). No se
  ejecuta solo.
- **`api_client.py`** — cliente de carga genérico: dispara N solicitudes
  concurrentes a cualquier endpoint, para medir escalabilidad (tiempos,
  solicitudes/segundo, tasa de error). Lee los endpoints a probar de un
  JSON (ver `requests.example.json`).
- **`procesar_videos.py`** — procesamiento masivo real: toma videos de una
  carpeta local o de un aula Moodle y los sube uno por uno a
  `POST /analyze/upload` del servicio. La parte de Moodle (descarga vía su
  API REST) es la única pieza genuinamente "externa" en el sentido de
  hablar con otro sistema — el resto es solo llamar al propio servicio.

Ninguno de los dos scripts "de proceso" (`api_client.py`,
`procesar_videos.py`) tiene interfaz: ambos son de línea de comandos y
pensados para correrse sin supervisión contra el endpoint que ya está
levantado — no reemplazan ni dependen de `index.html`.

Instalación y uso: ver el docstring al inicio de cada archivo.
