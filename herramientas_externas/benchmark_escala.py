"""
benchmark_escala.py — Fase 5.0 del roadmap de escalabilidad: mide la
capacidad REAL de procesamiento del servicio, no solo la respuesta HTTP.

Sube un lote de videos reales, espera a que cada uno termine de verdad
(polling de GET /analyze/{job_id}/status hasta "done"/"failed" — no solo
la respuesta inmediata del POST), y mide tiempo por video, throughput
(videos/hora) y uso de CPU/RAM del sistema durante la corrida.

Por qué no basta con api_client.py: /analyze/upload responde de inmediato
con un job_id y sigue procesando en background (Whisper + YOLO +
MediaPipe). api_client.py mide esa respuesta rápida, que no dice nada del
tiempo real de procesamiento. Este script sí espera hasta el final.

IMPORTANTE sobre la concurrencia: MAX_CONCURRENT_ANALYSIS se fija al
arrancar el servidor (variable de entorno, leída una sola vez en main.py)
— este script no puede cambiarla en caliente. Para comparar niveles de
concurrencia:
    1) Reiniciar el servidor con MAX_CONCURRENT_ANALYSIS=N
    2) Correr este benchmark (usa un --output distinto por corrida)
    3) Repetir con otro N
    4) Comparar los resúmenes/CSV resultantes

────────────────────────────────────────────────────────────────────────
INSTALACIÓN
    pip install httpx psutil

EJECUCIÓN
    set API_KEY=tu_clave_del_.env
    python benchmark_escala.py --folder "C:\videos_benchmark" --url http://localhost:9000

    python benchmark_escala.py --folder "C:\videos_benchmark" --max-videos 10 \
        --poll-interval 10 --output benchmark_concurrencia2.csv

SALIDA
    - Progreso en consola: cuándo se sube cada video y cuándo termina.
    - Resumen: tiempo total del lote, tiempo promedio/mín/máx por video,
      videos/hora, uso de CPU y RAM (promedio y pico) durante la corrida.
    - CSV de detalle por video (--output, default benchmark_resultados.csv).
────────────────────────────────────────────────────────────────────────
"""

import argparse
import asyncio
import csv
import sys
import time
from dataclasses import asdict, dataclass

import httpx
import psutil

from cliente_comun import ejecutar_con_timing, guardar_csv, headers_autenticacion, timestamp_actual
from procesar_videos import VideoCandidato, listar_desde_carpeta, listar_desde_carpeta_docentes, subir_video

COLUMNAS_CSV = [
    "nombre", "docente", "job_id", "subida_ok", "tiempo_subida_seg",
    "status_final", "tiempo_procesamiento_seg", "error",
]


@dataclass
class ResultadoBenchmark:
    nombre: str
    docente: str = ""
    job_id: str = ""
    subida_ok: bool = False
    tiempo_subida_seg: float = 0.0
    status_final: str = ""
    tiempo_procesamiento_seg: float = 0.0
    error: str = ""


# ── espera hasta que el job termine de verdad ───────────────────────

async def esperar_hasta_terminar(
    cliente: httpx.AsyncClient, job_id: str, headers: dict,
    poll_interval: float, timeout_seg: float,
) -> tuple[str, float]:
    """Un timeout/error puntual al CONSULTAR el estado NO significa que el
    job haya fallado — con el servidor saturado de CPU (Whisper usa casi
    todos los cores), hasta un GET /status simple puede tardar más de lo
    normal en responder. Un fallo de red acá es transitorio: se reintenta
    hasta agotar timeout_seg (el presupuesto de TODO el job), no se
    abandona en el primer tropiezo."""
    inicio = time.perf_counter()
    while True:
        respuesta, _, error = await ejecutar_con_timing(
            cliente.get(f"/analyze/{job_id}/status", headers=headers, timeout=60.0)
        )
        if respuesta is not None and respuesta.status_code == 200:
            status = respuesta.json().get("status")
            if status in ("done", "failed"):
                return status, time.perf_counter() - inicio
        elif respuesta is None:
            print(f"  (aviso: consulta de estado falló para {job_id[:8]}... — {error} — reintentando)")

        if time.perf_counter() - inicio > timeout_seg:
            return "timeout_benchmark", time.perf_counter() - inicio
        await asyncio.sleep(poll_interval)


async def procesar_y_medir(
    cliente: httpx.AsyncClient, candidato: VideoCandidato, headers: dict,
    poll_interval: float, timeout_seg: float, semaforo_en_vuelo: asyncio.Semaphore,
) -> ResultadoBenchmark:
    docente = candidato.metadata.get("presentador", "")

    # El semáforo envuelve TODO: subida + espera. No es solo para no saturar
    # la subida — un video "en vuelo" (subido pero sin terminar) sigue
    # consultando su estado cada poll_interval hasta que termina. Si se
    # suben todos de una y solo se limita la subida, igual quedan N
    # consultas de estado corriendo en paralelo sin tope, y con un lote
    # grande (100, 1000 videos) eso tira el pool de conexiones a la base
    # de datos sin importar qué tan grande se lo haga (confirmado con un
    # lote real de 43). Limitando cuántos están "en vuelo" a la vez, el
    # tamaño total del lote deja de importar — nunca hay más consultas
    # simultáneas que semaforo_en_vuelo, sin importar si son 43 o 1000.
    async with semaforo_en_vuelo:
        resultado_subida = await subir_video(cliente, candidato, candidato.ruta_local, headers, analista_id="benchmark")
        if not resultado_subida.ok:
            print(f"[ERR subida] {candidato.nombre} — {resultado_subida.error}")
            return ResultadoBenchmark(nombre=candidato.nombre, docente=docente, subida_ok=False, error=resultado_subida.error)

        print(f"[subido] {candidato.nombre} -> job_id={resultado_subida.job_id} (subida: {resultado_subida.tiempo_seg:.1f}s)")

        status_final, tiempo_proc = await esperar_hasta_terminar(
            cliente, resultado_subida.job_id, headers, poll_interval, timeout_seg,
        )
        print(f"[{status_final}] {candidato.nombre} — procesado en {tiempo_proc:.1f}s")

    return ResultadoBenchmark(
        nombre=candidato.nombre, docente=docente, job_id=resultado_subida.job_id, subida_ok=True,
        tiempo_subida_seg=resultado_subida.tiempo_seg, status_final=status_final,
        tiempo_procesamiento_seg=tiempo_proc,
    )


# ── monitoreo de CPU/RAM del sistema durante la corrida ─────────────

async def monitorear_recursos(muestras: list[tuple[float, float]], detener: asyncio.Event, intervalo: float = 2.0):
    """Guarda (cpu_pct, ram_pct) del sistema completo cada `intervalo` segundos.
    No distingue qué proceso usa qué — es una foto global de la máquina
    mientras corre el benchmark, suficiente para ver si se satura."""
    psutil.cpu_percent(interval=None)  # primera llamada "prime", se descarta
    while not detener.is_set():
        await asyncio.sleep(intervalo)
        muestras.append((psutil.cpu_percent(interval=None), psutil.virtual_memory().percent))


def _docentes_ya_subidos(ruta_csv: str) -> set[str]:
    """Lee un CSV de una corrida anterior (--source docentes) y devuelve el
    conjunto de docentes cuya subida ya fue exitosa (subida_ok=True) — para
    no volver a subirlos ni duplicar su procesamiento al reanudar un lote
    que falló a mitad de camino."""
    ya_subidos = set()
    with open(ruta_csv, newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            if fila.get("subida_ok", "").strip() == "True" and fila.get("docente"):
                ya_subidos.add(fila["docente"])
    return ya_subidos


# ── orquestación ─────────────────────────────────────────────────────

async def ejecutar(args) -> tuple[list[ResultadoBenchmark], float, list[tuple[float, float]]]:
    if args.source == "docentes":
        candidatos = listar_desde_carpeta_docentes(args.folder, curso_id=args.curso_id)
    else:
        candidatos = listar_desde_carpeta(args.folder)

    if args.resume_desde:
        ya_subidos = _docentes_ya_subidos(args.resume_desde)
        antes = len(candidatos)
        candidatos = [c for c in candidatos if c.metadata.get("presentador") not in ya_subidos]
        print(f"--resume-desde: {antes - len(candidatos)} ya estaban subidos en '{args.resume_desde}' — se omiten.")

    if args.max_videos:
        candidatos = candidatos[:args.max_videos]
    if not candidatos:
        print("No se encontraron videos en la carpeta indicada.")
        return [], 0.0, []

    print(f"Videos a procesar: {len(candidatos)}")
    for c in candidatos:
        print(f"  - {c.nombre}")

    headers = headers_autenticacion()
    if not headers:
        print("Aviso: no se definió API_KEY — se enviará sin header de autenticación.")
    print("-" * 60)
    print("Recordatorio: MAX_CONCURRENT_ANALYSIS se fija al arrancar el servidor.")
    print("Este benchmark mide la corrida bajo el valor que el servidor tenga AHORA MISMO.")
    print("-" * 60)

    muestras_recursos: list[tuple[float, float]] = []
    detener_monitor = asyncio.Event()
    tarea_monitor = asyncio.create_task(monitorear_recursos(muestras_recursos, detener_monitor))

    semaforo_en_vuelo = asyncio.Semaphore(args.concurrency)

    inicio = time.perf_counter()
    async with httpx.AsyncClient(base_url=args.url) as cliente:
        resultados = await asyncio.gather(*(
            procesar_y_medir(cliente, c, headers, args.poll_interval, args.timeout, semaforo_en_vuelo)
            for c in candidatos
        ))
    tiempo_total = time.perf_counter() - inicio

    detener_monitor.set()
    await tarea_monitor

    return list(resultados), tiempo_total, muestras_recursos


def imprimir_resumen(resultados: list[ResultadoBenchmark], tiempo_total: float, muestras_recursos: list[tuple[float, float]]) -> None:
    total      = len(resultados)
    terminados = [r for r in resultados if r.status_final == "done"]
    fallidos   = total - len(terminados)
    tiempos    = [r.tiempo_procesamiento_seg for r in terminados]

    promedio = sum(tiempos) / len(tiempos) if tiempos else 0.0
    minimo   = min(tiempos) if tiempos else 0.0
    maximo   = max(tiempos) if tiempos else 0.0
    rps_hora = (len(terminados) / tiempo_total * 3600) if tiempo_total > 0 else 0.0

    cpu_vals = [m[0] for m in muestras_recursos]
    ram_vals = [m[1] for m in muestras_recursos]
    cpu_prom = sum(cpu_vals) / len(cpu_vals) if cpu_vals else 0.0
    cpu_pico = max(cpu_vals) if cpu_vals else 0.0
    ram_prom = sum(ram_vals) / len(ram_vals) if ram_vals else 0.0
    ram_pico = max(ram_vals) if ram_vals else 0.0

    print("\n" + "=" * 60)
    print("RESUMEN DEL BENCHMARK")
    print("=" * 60)
    print(f"Videos procesados     : {total}")
    print(f"Terminados (done)     : {len(terminados)}")
    print(f"Fallidos/timeout      : {fallidos}")
    print(f"Tiempo total del lote : {tiempo_total:.1f} s ({tiempo_total/60:.1f} min)")
    print(f"Tiempo promedio/video : {promedio:.1f} s ({promedio/60:.1f} min)")
    print(f"Tiempo mínimo/video   : {minimo:.1f} s")
    print(f"Tiempo máximo/video   : {maximo:.1f} s")
    print(f"Throughput estimado   : {rps_hora:.1f} videos/hora")
    print(f"CPU del sistema       : promedio {cpu_prom:.1f}% — pico {cpu_pico:.1f}%")
    print(f"RAM del sistema       : promedio {ram_prom:.1f}% — pico {ram_pico:.1f}%")
    print("=" * 60)
    if len(terminados) > 0:
        print(f"\nProyección para 1000 videos a este ritmo: {1000 / rps_hora:.1f} horas "
              f"({1000 / rps_hora / 24:.1f} días) — SOLO válido si el patrón de llegada "
              f"de videos reales es similar a esta corrida (todos a la vez).")
    print("Para comparar con otro nivel de concurrencia: reinicia el servidor con otro "
          "MAX_CONCURRENT_ANALYSIS y vuelve a correr este script con --output distinto.")


def parsear_argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark de capacidad real de procesamiento (Fase 5.0).")
    parser.add_argument("--folder", required=True, help="Carpeta local con videos reales de prueba")
    parser.add_argument("--source", choices=["folder", "docentes"], default="folder",
                         help="'folder' = videos sueltos; 'docentes' = una subcarpeta por docente (descarga masiva de Moodle)")
    parser.add_argument("--curso-id", default=None, help="Curso/rúbrica a aplicar en la evaluación automática (solo con --source docentes)")
    parser.add_argument("--resume-desde", default=None, help="CSV de una corrida anterior (--source docentes): omite a los docentes que ya subieron bien, para reintentar solo lo que falló")
    parser.add_argument("--url", default="http://localhost:9000", help="URL base del servicio (default: http://localhost:9000)")
    parser.add_argument("--max-videos", type=int, default=None, help="Limitar cuántos videos de la carpeta usar (default: todos)")
    parser.add_argument("--concurrency", type=int, default=1, help="Cuántos videos pueden estar 'en vuelo' (subido + esperando) al mismo tiempo (default: 1). Limita subida Y consultas de estado juntas — debe ser <= MAX_CONCURRENT_ANALYSIS del servidor; subir más no lo hace más rápido porque el servidor igual los procesa de a MAX_CONCURRENT_ANALYSIS, solo acumula consultas de estado en paralelo sin necesidad.")
    parser.add_argument("--poll-interval", type=float, default=10.0, help="Segundos entre consultas de status por video (default: 10)")
    parser.add_argument("--timeout", type=float, default=1800.0, help="Timeout por video en segundos antes de darlo por colgado (default: 1800 = 30 min)")
    parser.add_argument("--output", default="benchmark_resultados.csv", help="CSV de salida (default: benchmark_resultados.csv)")
    return parser.parse_args()


def main():
    args = parsear_argumentos()
    try:
        resultados, tiempo_total, muestras_recursos = asyncio.run(ejecutar(args))
    except (FileNotFoundError,) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not resultados:
        return

    imprimir_resumen(resultados, tiempo_total, muestras_recursos)
    guardar_csv([asdict(r) for r in resultados], COLUMNAS_CSV, args.output)
    print(f"\nDetalle guardado en: {args.output}")


if __name__ == "__main__":
    main()
