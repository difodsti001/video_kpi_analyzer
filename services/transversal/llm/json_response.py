# services/transversal/llm/json_response.py
# Parseo defensivo de respuestas JSON de un LLM — compartido por todos los
# servicios de evaluación (evaluacion/, competencias_mbdd/, y los que se
# agreguen después). Antes vivía duplicado, idéntico, en cada uno de esos
# dos servicios — y por eso un mismo bug (saltos de línea literales sin
# escapar dentro de un string largo, típico en textos generados por el LLM)
# hubo que corregirlo dos veces por separado. Ahora se corrige una sola vez,
# acá, y todos los servicios que lo usen quedan corregidos a la vez.
import json
import re


def extraer_json(texto: str | None) -> dict:
    """Busca el primer bloque {...} en el texto y lo parsea como JSON.

    Lanza ValueError si no encuentra ningún bloque, o json.JSONDecodeError
    si lo encuentra pero no es JSON válido — ambos esperados de manejar con
    un try/except en el llamador (ver patrón en evaluacion/analyzer.py y
    competencias_mbdd/analyzer.py: ante cualquier excepción, se sigue con
    data={} en vez de romper toda la evaluación).
    """
    match = re.search(r"\{.*\}", texto or "", re.S)
    if not match:
        raise ValueError("No se encontró JSON en la respuesta del LLM")
    # strict=False: el LLM a veces devuelve saltos de línea literales dentro
    # de un valor string (p.ej. en un resumen largo) en vez de escaparlos
    # como \n — json.loads estricto rechaza eso como "control character
    # inválido" y tira todo el parseo a data={} (todo el contenido queda
    # "no evaluado"). Esto no depende de la rúbrica ni del curso: le puede
    # pasar a cualquier respuesta del LLM con texto libre suficientemente largo.
    return json.loads(match.group(0), strict=False)
