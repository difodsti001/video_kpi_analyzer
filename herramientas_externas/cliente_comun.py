"""
cliente_comun.py — Utilidades compartidas entre api_client.py y
procesar_videos.py, para no repetir la misma lógica de autenticación,
medición de tiempo/errores HTTP y escritura de CSV en los dos scripts.
"""

import csv
import os
import time
from datetime import datetime, timezone

import httpx


def timestamp_actual() -> str:
    return datetime.now(timezone.utc).isoformat()


def headers_autenticacion(nombre_header: str = "X-API-Key") -> dict:
    """Lee la API key desde la variable de entorno API_KEY (nunca hardcodeada).
    Devuelve {} si no está definida — el llamador decide si avisar o no."""
    api_key = os.getenv("API_KEY")
    return {nombre_header: api_key} if api_key else {}


def avisar_si_falta_api_key() -> None:
    if not os.getenv("API_KEY"):
        print("Aviso: no se definió la variable de entorno API_KEY — se enviará sin header de autenticación.")


async def ejecutar_con_timing(coro) -> tuple[httpx.Response | None, float, str]:
    """Ejecuta una corutina httpx (cliente.request(...), cliente.post(...), etc.),
    midiendo el tiempo y capturando los errores comunes de red/timeout sin
    propagar la excepción — para que un fallo puntual no tumbe todo el lote.

    Devuelve (respuesta_o_None, duracion_seg, mensaje_error). mensaje_error
    queda vacío si no hubo excepción (igual puede haber status >= 400, eso
    lo decide el llamador según su propio criterio de éxito)."""
    inicio = time.perf_counter()
    try:
        respuesta = await coro
        return respuesta, time.perf_counter() - inicio, ""
    except httpx.TimeoutException:
        return None, time.perf_counter() - inicio, "timeout"
    except httpx.HTTPError as e:
        return None, time.perf_counter() - inicio, f"{type(e).__name__}: {e}"
    except Exception as e:
        return None, time.perf_counter() - inicio, f"error inesperado — {type(e).__name__}: {e}"


def guardar_csv(filas: list[dict], columnas: list[str], ruta_csv: str) -> None:
    """Escribe una lista de dicts a CSV, en el orden de `columnas`."""
    with open(ruta_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columnas)
        writer.writeheader()
        for fila in filas:
            writer.writerow({c: fila.get(c, "") for c in columnas})
