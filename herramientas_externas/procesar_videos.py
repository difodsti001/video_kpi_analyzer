"""
procesar_videos.py — Dispara el análisis de un lote de videos que vienen de
una CARPETA local o de un AULA MOODLE, subiéndolos vía POST /analyze/upload.

Por qué siempre /analyze/upload y no /analyze/from-file:
    /analyze/from-file asume que el video YA está en el disco del servidor
    (carpeta video/). Eso solo funciona si este script corre en la misma
    máquina que el servidor. /analyze/upload, en cambio, sube el archivo
    por HTTP — funciona sin importar de dónde vino el video (carpeta local
    en tu PC, o descargado de Moodle a un temporal), y además ya trae
    deduplicación por hash en el servidor (shared/models.py / main.py).

────────────────────────────────────────────────────────────────────────
INSTALACIÓN
    pip install httpx

EJECUCIÓN

  1) Fuente: carpeta local (un video por archivo, todos sueltos en la carpeta)
    python procesar_videos.py --source folder --folder "C:\videos_clase" \
        --url http://localhost:9000 --concurrency 2

  2) Fuente: carpeta con una subcarpeta por docente (típico de una descarga
     masiva de envíos de tarea de Moodle: "<Nombre Docente>_<id>_assignsubmission_file/")
    python procesar_videos.py --source docentes --folder "G:/ruta/a/la/descarga" \
        --url http://localhost:9000 --concurrency 2 --curso-id video_en_clase_2026

  3) Fuente: aula Moodle (contenido del curso, no una tarea específica)
    Variables de entorno necesarias (no hardcodear el token):
        set MOODLE_TOKEN=tu_token_webservice

    python procesar_videos.py --source moodle \
        --moodle-url https://tu-moodle.edu.pe \
        --course-id 123 \
        --url http://localhost:9000 --concurrency 2

    Requisitos del lado de Moodle (lo configura un administrador una vez):
      - Activar servicios web REST: Administración del sitio > Servidor >
        Servicios web > Habilitar servicios web, y habilitar el protocolo REST.
      - Crear un token de usuario con permiso sobre core_course_get_contents
        (Administración del sitio > Servicios web > Gestionar tokens).
      - El usuario del token debe estar matriculado/con acceso de lectura
        al curso del que se quieren sacar los videos.

  4) Fuente: una actividad de tarea (assignment) puntual en Moodle — ej.
     https://.../mod/assign/view.php?id=165125 en el aula 1454: el id de la
     URL es el cmid (id del módulo de curso), no el id del assignment; este
     modo lo resuelve solo.

    python procesar_videos.py --source moodle_assign \
        --moodle-url https://campusvirtual-sifods.minedu.gob.pe \
        --course-id 1454 --cmid 165125 \
        --curso-id aula_1454 \
        --url http://localhost:9000 --concurrency 2

    Requisitos del lado de Moodle (además de los del modo 3):
      - El token necesita permiso también sobre mod_assign_get_assignments
        y mod_assign_get_submissions.
      - El "presentador" que queda guardado es el userid de Moodle (no el
        nombre) — se resuelve a nombre por fuera, no hace falta pedir acá
        el permiso de core_user_get_users_by_field.

AUTENTICACIÓN CONTRA ESTE SERVICIO (FastAPI)
    set API_KEY=tu_clave_del_.env
    El header se envía como "X-API-Key: <API_KEY>".

SALIDA
    - Log en consola por cada video: origen, nombre, job_id o error.
    - CSV de detalle (--output, default procesados.csv).
────────────────────────────────────────────────────────────────────────
"""

import argparse
import asyncio
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

from cliente_comun import ejecutar_con_timing, guardar_csv, headers_autenticacion, timestamp_actual

EXTENSIONES_VIDEO = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
COLUMNAS_CSV = ["timestamp", "origen", "nombre", "ok", "job_id", "status_code", "tiempo_seg", "error"]


# ══════════════════════════════════════════════════════════════════
# FUENTES — cada una devuelve una lista de "VideoCandidato" con la
# misma forma, sin que el resto del script sepa de dónde vino.
# ══════════════════════════════════════════════════════════════════

@dataclass
class VideoCandidato:
    nombre: str              # nombre de archivo a usar al subir
    origen: str              # "local" | "moodle"
    ruta_local: str | None = None   # ya está en disco (fuente local)
    url_descarga: str | None = None  # hay que descargarlo primero (moodle)
    metadata: dict = field(default_factory=dict)  # nombre_analisis/presentador/etc.


def listar_desde_carpeta(carpeta: str) -> list[VideoCandidato]:
    base = Path(carpeta)
    if not base.is_dir():
        raise FileNotFoundError(f"La carpeta no existe: {carpeta}")

    candidatos = []
    for archivo in sorted(base.iterdir()):
        if archivo.suffix.lower() in EXTENSIONES_VIDEO:
            candidatos.append(VideoCandidato(
                nombre=archivo.name,
                origen="local",
                ruta_local=str(archivo),
                metadata={"nombre_analisis": archivo.stem},
            ))
    return candidatos


_SUFIJO_MOODLE = re.compile(r"^(.*)_\d+_assignsubmission_file$", re.IGNORECASE)


def _nombre_docente_desde_carpeta(nombre_carpeta: str) -> str:
    """'JUAN PEREZ_1495701_assignsubmission_file' -> 'JUAN PEREZ'. Si el
    nombre de la carpeta no sigue el patrón de Moodle, se usa tal cual."""
    m = _SUFIJO_MOODLE.match(nombre_carpeta)
    return m.group(1).strip() if m else nombre_carpeta


def listar_desde_carpeta_docentes(carpeta: str, curso_id: str | None = None) -> list[VideoCandidato]:
    """Para una descarga masiva de envíos de tarea (Moodle: 'Descargar todas
    las entregas'), donde cada subcarpeta es un docente/estudiante y contiene
    su video (y a veces otros archivos: docx, pdf, etc. — se ignoran).

    Casos especiales, avisados en consola, no abortan el lote:
    - Subcarpeta sin ningún video (solo documento, o video por enlace externo
      en vez de archivo subido): se salta.
    - Subcarpeta con más de un video: se toma el primero (orden alfabético)
      y se avisa — no se adivina cuál es el correcto.
    """
    base = Path(carpeta)
    if not base.is_dir():
        raise FileNotFoundError(f"La carpeta no existe: {carpeta}")

    candidatos = []
    for sub in sorted(p for p in base.iterdir() if p.is_dir()):
        videos = sorted(f for f in sub.iterdir() if f.is_file() and f.suffix.lower() in EXTENSIONES_VIDEO)
        docente = _nombre_docente_desde_carpeta(sub.name)

        if not videos:
            print(f"Aviso: '{sub.name}' no tiene ningún video — se omite.")
            continue
        if len(videos) > 1:
            print(f"Aviso: '{sub.name}' tiene {len(videos)} videos — se usa '{videos[0].name}', se ignoran los demás.")

        metadata = {"nombre_analisis": docente, "presentador": docente}
        if curso_id:
            metadata["curso_id"] = curso_id

        candidatos.append(VideoCandidato(
            nombre=videos[0].name,
            origen="local",
            ruta_local=str(videos[0]),
            metadata=metadata,
        ))
    return candidatos


def listar_desde_moodle(moodle_url: str, token: str, course_id: int, curso_id: str | None = None) -> list[VideoCandidato]:
    """Usa el API REST de Moodle (core_course_get_contents) para listar los
    archivos de video de un curso. No descarga nada todavía — solo arma la
    lista con la URL de descarga (que ya incluye el token)."""
    endpoint = f"{moodle_url.rstrip('/')}/webservice/rest/server.php"
    params = {
        "wstoken": token,
        "wsfunction": "core_course_get_contents",
        "courseid": course_id,
        "moodlewsrestformat": "json",
    }

    respuesta = httpx.get(endpoint, params=params, timeout=30.0)
    respuesta.raise_for_status()
    data = respuesta.json()

    if isinstance(data, dict) and data.get("exception"):
        raise RuntimeError(f"Moodle rechazó la solicitud: {data.get('message', data)}")

    candidatos = []
    for seccion in data:
        for modulo in seccion.get("modules", []):
            nombre_modulo = modulo.get("name", "")
            for contenido in modulo.get("contents", []) or []:
                filename = contenido.get("filename", "")
                mimetype = contenido.get("mimetype", "") or ""
                es_video = (
                    Path(filename).suffix.lower() in EXTENSIONES_VIDEO
                    or mimetype.startswith("video/")
                )
                if not es_video:
                    continue

                fileurl = contenido.get("fileurl", "")
                # Moodle exige el token también en la URL de descarga del archivo.
                sep = "&" if "?" in fileurl else "?"
                url_con_token = f"{fileurl}{sep}token={token}"

                metadata = {
                    "nombre_analisis": f"{nombre_modulo} — {filename}",
                    "dependencia": f"curso_moodle_{course_id}",
                }
                if curso_id:
                    metadata["curso_id"] = curso_id

                candidatos.append(VideoCandidato(
                    nombre=filename,
                    origen="moodle",
                    url_descarga=url_con_token,
                    metadata=metadata,
                ))
    return candidatos


def _moodle_rest(moodle_url: str, token: str, wsfunction: str, extra_params: dict) -> dict:
    endpoint = f"{moodle_url.rstrip('/')}/webservice/rest/server.php"
    params = {
        "wstoken": token,
        "wsfunction": wsfunction,
        "moodlewsrestformat": "json",
        **extra_params,
    }
    respuesta = httpx.get(endpoint, params=params, timeout=30.0)
    respuesta.raise_for_status()
    data = respuesta.json()
    if isinstance(data, dict) and data.get("exception"):
        raise RuntimeError(f"Moodle rechazó la solicitud ({wsfunction}): {data.get('message', data)}")
    return data


def _resolver_assignment_id(moodle_url: str, token: str, course_id: int, cmid: int) -> int:
    """El id de view.php?id=165125 es el cmid (id del módulo de curso), pero
    mod_assign_get_submissions pide el id interno del assignment — hay que
    resolverlo primero listando los assignments del curso y matcheando cmid."""
    data = _moodle_rest(moodle_url, token, "mod_assign_get_assignments", {"courseids[0]": course_id})
    for curso in data.get("courses", []):
        for asignacion in curso.get("assignments", []):
            if asignacion.get("cmid") == cmid:
                return asignacion["id"]
    raise RuntimeError(f"No se encontró ningún assignment con cmid={cmid} en el curso {course_id}.")


def listar_desde_moodle_assign(moodle_url: str, token: str, course_id: int, cmid: int,
                                curso_id: str | None = None) -> list[VideoCandidato]:
    """Lista los videos entregados en UNA actividad de tarea puntual (no todo
    el contenido del curso). El 'presentador' queda como el userid de Moodle
    tal cual — la resolución a nombre se hace por fuera, no acá."""
    assignment_id = _resolver_assignment_id(moodle_url, token, course_id, cmid)
    data = _moodle_rest(moodle_url, token, "mod_assign_get_submissions", {"assignmentids[0]": assignment_id})

    candidatos = []
    for asignacion in data.get("assignments", []):
        for envio in asignacion.get("submissions", []):
            userid = envio.get("userid")
            for plugin in envio.get("plugins", []) or []:
                if plugin.get("type") != "file":
                    continue
                for area in plugin.get("fileareas", []) or []:
                    for archivo in area.get("files", []) or []:
                        filename = archivo.get("filename", "")
                        if Path(filename).suffix.lower() not in EXTENSIONES_VIDEO:
                            continue

                        fileurl = archivo.get("fileurl", "")
                        sep = "&" if "?" in fileurl else "?"
                        url_con_token = f"{fileurl}{sep}token={token}"

                        metadata = {
                            "nombre_analisis": f"{userid} — {filename}",
                            "presentador":     str(userid),
                            "dependencia":     f"curso_moodle_{course_id}_assign_{assignment_id}",
                        }
                        if curso_id:
                            metadata["curso_id"] = curso_id

                        candidatos.append(VideoCandidato(
                            nombre=filename,
                            origen="moodle",
                            url_descarga=url_con_token,
                            metadata=metadata,
                        ))
    return candidatos


async def descargar_de_moodle(cliente: httpx.AsyncClient, candidato: VideoCandidato, carpeta_temp: str) -> str:
    """Descarga el archivo a un temporal local y devuelve la ruta."""
    destino = os.path.join(carpeta_temp, candidato.nombre)
    async with cliente.stream("GET", candidato.url_descarga, timeout=120.0) as resp:
        resp.raise_for_status()
        with open(destino, "wb") as f:
            async for chunk in resp.aiter_bytes():
                f.write(chunk)
    return destino


# ══════════════════════════════════════════════════════════════════
# ENVÍO AL SERVICIO DE ANÁLISIS
# ══════════════════════════════════════════════════════════════════

@dataclass
class ResultadoProcesamiento:
    nombre: str
    origen: str
    ok: bool
    job_id: str = ""
    status_code: int | None = None
    tiempo_seg: float = 0.0
    error: str = ""
    timestamp: str = field(default_factory=timestamp_actual)


async def subir_video(
    cliente: httpx.AsyncClient,
    candidato: VideoCandidato,
    ruta_local: str,
    headers: dict,
    analista_id: str,
) -> ResultadoProcesamiento:
    with open(ruta_local, "rb") as f:
        files = {"file": (candidato.nombre, f, "application/octet-stream")}
        form = {
            "nombre_analisis": candidato.metadata.get("nombre_analisis", candidato.nombre),
            "presentador":     candidato.metadata.get("presentador", ""),
            "tipo":            candidato.metadata.get("tipo", ""),
            "dependencia":     candidato.metadata.get("dependencia", ""),
            "analista_id":     analista_id,
        }
        if candidato.metadata.get("curso_id"):
            form["curso_id"] = candidato.metadata["curso_id"]
        respuesta, duracion, error = await ejecutar_con_timing(
            cliente.post("/analyze/upload", files=files, data=form, headers=headers, timeout=300.0)
        )

    if respuesta is None:
        return ResultadoProcesamiento(
            nombre=candidato.nombre, origen=candidato.origen, ok=False,
            tiempo_seg=duracion, error=error,
        )
    if respuesta.status_code == 200:
        data = respuesta.json()
        return ResultadoProcesamiento(
            nombre=candidato.nombre, origen=candidato.origen, ok=True,
            job_id=data.get("job_id", ""), status_code=200, tiempo_seg=duracion,
            error="" if not data.get("duplicate") else "duplicado (ya analizado antes)",
        )
    return ResultadoProcesamiento(
        nombre=candidato.nombre, origen=candidato.origen, ok=False,
        status_code=respuesta.status_code, tiempo_seg=duracion,
        error=f"HTTP {respuesta.status_code}: {respuesta.text[:200]}",
    )


async def procesar_candidato(
    cliente: httpx.AsyncClient,
    candidato: VideoCandidato,
    carpeta_temp: str,
    headers: dict,
    analista_id: str,
    semaforo: asyncio.Semaphore,
) -> ResultadoProcesamiento:
    async with semaforo:
        try:
            if candidato.origen == "moodle":
                ruta_local = await descargar_de_moodle(cliente, candidato, carpeta_temp)
            else:
                ruta_local = candidato.ruta_local

            resultado = await subir_video(cliente, candidato, ruta_local, headers, analista_id)
        finally:
            # el descargado temporal de Moodle se borra; el local del usuario NO se toca
            if candidato.origen == "moodle":
                ruta_descargada = os.path.join(carpeta_temp, candidato.nombre)
                if os.path.exists(ruta_descargada):
                    os.remove(ruta_descargada)

    estado = "OK " if resultado.ok else "ERR"
    print(f"[{estado}] ({resultado.origen}) {resultado.nombre} — job_id={resultado.job_id} "
          f"tiempo={resultado.tiempo_seg:.2f}s" + (f" — {resultado.error}" if resultado.error else ""))
    return resultado


async def ejecutar(args) -> list[ResultadoProcesamiento]:
    if args.source == "folder":
        candidatos = listar_desde_carpeta(args.folder)
    elif args.source == "docentes":
        candidatos = listar_desde_carpeta_docentes(args.folder, curso_id=args.curso_id)
    elif args.source == "moodle":
        candidatos = listar_desde_moodle(args.moodle_url, os.environ["MOODLE_TOKEN"], args.course_id, curso_id=args.curso_id)
    else:
        candidatos = listar_desde_moodle_assign(args.moodle_url, os.environ["MOODLE_TOKEN"], args.course_id, args.cmid, curso_id=args.curso_id)

    if not candidatos:
        print("No se encontraron videos para procesar.")
        return []

    print(f"Videos encontrados ({args.source}): {len(candidatos)}")
    for c in candidatos:
        print(f"  - {c.nombre}")

    headers = headers_autenticacion()
    if not headers:
        print("Aviso: no se definió API_KEY — se enviará sin header de autenticación.")

    semaforo = asyncio.Semaphore(args.concurrency)

    with tempfile.TemporaryDirectory(prefix="procesar_videos_") as carpeta_temp:
        async with httpx.AsyncClient(base_url=args.url) as cliente:
            resultados = await asyncio.gather(*(
                procesar_candidato(cliente, c, carpeta_temp, headers, args.analista_id, semaforo)
                for c in candidatos
            ))

    return list(resultados)


def parsear_argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dispara el análisis de videos desde una carpeta local o un aula Moodle.")
    parser.add_argument("--source", choices=["folder", "docentes", "moodle", "moodle_assign"], required=True, help="De dónde sacar los videos")
    parser.add_argument("--folder", help="Ruta de la carpeta local (requerido si --source folder o docentes)")
    parser.add_argument("--curso-id", default=None, help="Curso/rúbrica a aplicar en la evaluación automática. Si se omite, el servidor usa el curso por defecto.")
    parser.add_argument("--moodle-url", help="URL base del Moodle, p.ej. https://tu-moodle.edu.pe (requerido si --source moodle o moodle_assign)")
    parser.add_argument("--course-id", type=int, help="ID numérico del curso/aula en Moodle (requerido si --source moodle o moodle_assign)")
    parser.add_argument("--cmid", type=int, help="id del módulo de curso de la tarea — el 'id' en view.php?id=... (requerido si --source moodle_assign)")
    parser.add_argument("--url", default="http://localhost:9000", help="URL base de este servicio FastAPI")
    parser.add_argument("--concurrency", type=int, default=2, help="Subidas simultáneas (default: 2, igual al límite de extracción del servicio)")
    parser.add_argument("--analista-id", default="", help="Identificador del analista que dispara el lote (opcional)")
    parser.add_argument("--output", default="procesados.csv", help="CSV de salida (default: procesados.csv)")
    return parser.parse_args()


def main():
    args = parsear_argumentos()

    if args.source in ("folder", "docentes") and not args.folder:
        print(f"Falta --folder cuando --source {args.source}", file=sys.stderr)
        sys.exit(1)
    if args.source in ("moodle", "moodle_assign"):
        if not args.moodle_url or not args.course_id:
            print(f"Faltan --moodle-url y/o --course-id cuando --source {args.source}", file=sys.stderr)
            sys.exit(1)
        if args.source == "moodle_assign" and not args.cmid:
            print("Falta --cmid cuando --source moodle_assign", file=sys.stderr)
            sys.exit(1)
        if not os.getenv("MOODLE_TOKEN"):
            print("Falta la variable de entorno MOODLE_TOKEN", file=sys.stderr)
            sys.exit(1)

    resultados = asyncio.run(ejecutar(args))
    if resultados:
        filas = [{**asdict(r), "tiempo_seg": f"{r.tiempo_seg:.2f}"} for r in resultados]
        guardar_csv(filas, COLUMNAS_CSV, args.output)
        exitosos = sum(1 for r in resultados if r.ok)
        print(f"\nListo: {exitosos}/{len(resultados)} videos enviados correctamente. Detalle en {args.output}")


if __name__ == "__main__":
    main()
