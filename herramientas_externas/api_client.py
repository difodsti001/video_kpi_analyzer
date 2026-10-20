"""
api_client.py — Cliente de carga para evaluar la escalabilidad del servicio FastAPI.

Envía solicitudes HTTP (por defecto POST) de forma concurrente a un endpoint,
usando una lista de "registros" leída de un archivo JSON, con un número de
usuarios simultáneos configurable. Pensado para probar, por ejemplo,
POST /analyze/from-file de este proyecto, pero sirve para cualquier endpoint
JSON: cada registro del archivo de entrada decide a qué ruta y con qué
cuerpo/parámetros se dispara su propia solicitud.

────────────────────────────────────────────────────────────────────────
INSTALACIÓN
    pip install httpx

EJECUCIÓN
    python api_client.py --input requests.json
    python api_client.py --url http://localhost:9000 --concurrency 10 --max-requests 200 --input requests.json

    Autenticación (opcional, vía variables de entorno — no hardcodear claves):
        set API_KEY=tu_clave_aqui          (Windows cmd)
        $env:API_KEY = "tu_clave_aqui"     (PowerShell)
        export API_KEY=tu_clave_aqui       (bash)
    El header se envía como "X-API-Key: <API_KEY>" si la variable existe.
    El nombre del header es configurable con --api-key-header.

ARCHIVO DE ENTRADA (JSON) — ejemplo de estructura:
    [
        {
            "path": "/analyze/from-file",
            "method": "POST",
            "params": {"filename": "video_prueba_1.mp4"},
            "json": null
        },
        {
            "path": "/analyze/from-file",
            "method": "POST",
            "params": {"filename": "video_prueba_2.mp4"},
            "json": null
        }
    ]

    Campos por registro:
        path   : ruta del endpoint, relativa a --url (obligatorio)
        method : "GET"/"POST"/etc. (opcional, default "POST")
        params : query params (opcional)
        json   : cuerpo JSON (opcional)
        headers: headers extra para esta solicitud puntual (opcional)

    Si hay más solicitudes a lanzar (--max-requests) que registros en el
    archivo, la lista se recicla (round-robin) hasta completar el total.

SALIDA
    - Resumen en consola (totales, tiempos, RPS).
    - Detalle fila por fila en un CSV (--output, default resultados.csv).
────────────────────────────────────────────────────────────────────────
"""

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict, dataclass, field

import httpx

from cliente_comun import avisar_si_falta_api_key, ejecutar_con_timing, guardar_csv, headers_autenticacion, timestamp_actual

COLUMNAS_CSV = ["indice", "timestamp", "method", "path", "status_code", "tiempo_seg", "ok", "error"]


@dataclass
class ResultadoSolicitud:
    indice: int
    path: str
    method: str
    status_code: int | None
    tiempo_seg: float
    ok: bool
    error: str = ""
    timestamp: str = field(default_factory=timestamp_actual)


def cargar_registros(ruta_json: str) -> list[dict]:
    with open(ruta_json, "r", encoding="utf-8") as f:
        registros = json.load(f)
    if not isinstance(registros, list) or not registros:
        raise ValueError("El archivo de entrada debe ser una lista JSON no vacía de registros.")
    for r in registros:
        if "path" not in r:
            raise ValueError(f"Cada registro necesita al menos la clave 'path': {r}")
    return registros


def construir_lista_de_trabajo(registros: list[dict], max_requests: int | None) -> list[dict]:
    """Repite la lista de registros (round-robin) hasta llegar a max_requests.
    Si no se indica max_requests, se envía cada registro una sola vez."""
    if not max_requests:
        return list(registros)
    trabajo = []
    i = 0
    while len(trabajo) < max_requests:
        trabajo.append(registros[i % len(registros)])
        i += 1
    return trabajo


async def enviar_solicitud(
    cliente: httpx.AsyncClient,
    indice: int,
    registro: dict,
    base_url: str,
    headers_base: dict,
    timeout_seg: float,
) -> ResultadoSolicitud:
    path    = registro["path"]
    method  = registro.get("method", "POST").upper()
    params  = registro.get("params")
    body    = registro.get("json")
    headers = {**headers_base, **registro.get("headers", {})}

    respuesta, duracion, error = await ejecutar_con_timing(
        cliente.request(method, path, params=params, json=body, headers=headers, timeout=timeout_seg)
    )

    if respuesta is not None:
        ok = 200 <= respuesta.status_code < 300
        status_code = respuesta.status_code
        if not ok:
            error = f"HTTP {respuesta.status_code}: {respuesta.text[:200]}"
    else:
        ok = False
        status_code = None

    return ResultadoSolicitud(
        indice=indice, path=path, method=method,
        status_code=status_code, tiempo_seg=duracion, ok=ok, error=error,
    )


async def ejecutar_carga(
    base_url: str,
    trabajo: list[dict],
    concurrencia: int,
    timeout_seg: float,
    api_key_header: str,
) -> list[ResultadoSolicitud]:
    headers_base = headers_autenticacion(api_key_header)

    semaforo = asyncio.Semaphore(concurrencia)
    resultados: list[ResultadoSolicitud] = [None] * len(trabajo)  # type: ignore

    async with httpx.AsyncClient(base_url=base_url) as cliente:

        async def tarea(i: int, registro: dict):
            async with semaforo:
                resultado = await enviar_solicitud(
                    cliente, i, registro, base_url, headers_base, timeout_seg,
                )
                resultados[i] = resultado
                estado = "OK " if resultado.ok else "ERR"
                print(
                    f"[{estado}] #{i:04d} {resultado.method:5s} {resultado.path:30s} "
                    f"status={resultado.status_code} tiempo={resultado.tiempo_seg:.3f}s"
                    + (f" — {resultado.error}" if resultado.error else "")
                )

        await asyncio.gather(*(tarea(i, r) for i, r in enumerate(trabajo)))

    return resultados


def imprimir_resumen(resultados: list[ResultadoSolicitud], tiempo_total: float) -> None:
    total      = len(resultados)
    exitosas   = sum(1 for r in resultados if r.ok)
    fallidas   = total - exitosas
    tiempos    = [r.tiempo_seg for r in resultados]
    promedio   = sum(tiempos) / total if total else 0.0
    minimo     = min(tiempos) if tiempos else 0.0
    maximo     = max(tiempos) if tiempos else 0.0
    rps        = total / tiempo_total if tiempo_total > 0 else 0.0

    print("\n" + "=" * 60)
    print("RESUMEN")
    print("=" * 60)
    print(f"Total de solicitudes : {total}")
    print(f"Exitosas             : {exitosas}")
    print(f"Fallidas             : {fallidas}")
    print(f"Tiempo total         : {tiempo_total:.3f} s")
    print(f"Tiempo promedio      : {promedio:.3f} s")
    print(f"Tiempo mínimo        : {minimo:.3f} s")
    print(f"Tiempo máximo        : {maximo:.3f} s")
    print(f"Solicitudes/segundo  : {rps:.2f}")
    print("=" * 60)


def parsear_argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cliente de carga para probar escalabilidad de la API FastAPI.")
    parser.add_argument("--url", default="http://localhost:9000", help="URL base del servicio (default: http://localhost:9000)")
    parser.add_argument("--input", default="requests.json", help="Archivo JSON con la lista de registros de prueba")
    parser.add_argument("--concurrency", type=int, default=5, help="Cantidad de usuarios/solicitudes simultáneas (default: 5)")
    parser.add_argument("--max-requests", type=int, default=None, help="Cantidad máxima de solicitudes a enviar (recicla los registros si hacen falta más). Si se omite, envía cada registro del archivo una sola vez.")
    parser.add_argument("--timeout", type=float, default=30.0, help="Timeout por solicitud en segundos (default: 30)")
    parser.add_argument("--output", default="resultados.csv", help="Archivo CSV de salida (default: resultados.csv)")
    parser.add_argument("--api-key-header", default="X-API-Key", help="Nombre del header de autenticación (default: X-API-Key)")
    return parser.parse_args()


def main():
    args = parsear_argumentos()

    try:
        registros = cargar_registros(args.input)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        print(f"Error leyendo el archivo de entrada '{args.input}': {e}", file=sys.stderr)
        sys.exit(1)

    trabajo = construir_lista_de_trabajo(registros, args.max_requests)

    print(f"Servicio objetivo   : {args.url}")
    print(f"Registros base      : {len(registros)}")
    print(f"Solicitudes a enviar: {len(trabajo)}")
    print(f"Concurrencia        : {args.concurrency}")
    print(f"Timeout por request : {args.timeout}s")
    avisar_si_falta_api_key()
    print("-" * 60)

    inicio = time.perf_counter()
    resultados = asyncio.run(
        ejecutar_carga(args.url, trabajo, args.concurrency, args.timeout, args.api_key_header)
    )
    tiempo_total = time.perf_counter() - inicio

    imprimir_resumen(resultados, tiempo_total)
    filas = [{**asdict(r), "tiempo_seg": f"{r.tiempo_seg:.4f}"} for r in resultados]
    guardar_csv(filas, COLUMNAS_CSV, args.output)
    print(f"\nDetalle guardado en: {args.output}")


if __name__ == "__main__":
    main()
