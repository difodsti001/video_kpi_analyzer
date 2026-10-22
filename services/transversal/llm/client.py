# services/llm/client.py
import os
import time
import base64
from dotenv import load_dotenv

load_dotenv()

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "none")  # "openai" | "azure" | "anthropic" | "gemini" | "none"
LLM_API_KEY  = os.getenv("LLM_API_KEY", "")

AZURE_OPENAI_ENDPOINT    = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_KEY     = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
AZURE_OPENAI_DEPLOYMENT  = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")

# Si es true, las respuestas de evaluación/competencias incluyen el prompt
# completo enviado al LLM (útil para depurar, pero infla el tamaño de cada
# fila en la base de datos si se deja activo en producción).
DEBUG_LLM_PROMPTS = os.getenv("DEBUG_LLM_PROMPTS", "false").strip().lower() in ("1", "true", "yes")

LLM_MAX_REINTENTOS  = int(os.getenv("LLM_MAX_REINTENTOS", "3"))
LLM_ESPERA_INICIAL  = float(os.getenv("LLM_ESPERA_INICIAL_SEG", "2"))


def llamar_llm(prompt: str, max_tokens: int = 400) -> str | None:
    """Llama al proveedor LLM configurado en .env, con reintentos ante fallos
    transitorios (rate limits, timeouts, errores de red). Devuelve None si no
    hay proveedor configurado, o si la llamada sigue fallando tras agotar los
    reintentos — nunca un string de error disfrazado de respuesta válida."""
    if LLM_PROVIDER == "anthropic":
        fn = _llamar_anthropic
    elif LLM_PROVIDER == "openai":
        fn = _llamar_openai
    elif LLM_PROVIDER == "azure":
        fn = _llamar_azure_openai
    elif LLM_PROVIDER == "gemini":
        fn = _llamar_gemini
    else:
        return None

    return _con_reintentos(fn, prompt, max_tokens)


def _uso(response, imagenes: int = 0) -> dict:
    usage = getattr(response, "usage", None)
    return {"proveedor": LLM_PROVIDER, "modelo": getattr(response, "model", None) or AZURE_OPENAI_DEPLOYMENT,
            "solicitudes": 1, "imagenes_enviadas": imagenes,
            "tokens_entrada": getattr(usage, "prompt_tokens", None),
            "tokens_salida": getattr(usage, "completion_tokens", None),
            "tokens_totales": getattr(usage, "total_tokens", None), "estado": "exitoso"}


def llamar_llm_con_uso(prompt: str, max_tokens: int = 400) -> tuple[str | None, dict | None]:
    if LLM_PROVIDER != "azure":
        return llamar_llm(prompt, max_tokens), None
    try:
        from openai import AzureOpenAI
        client = AzureOpenAI(azure_endpoint=AZURE_OPENAI_ENDPOINT, api_key=AZURE_OPENAI_API_KEY, api_version=AZURE_OPENAI_API_VERSION)
        response = client.chat.completions.create(model=AZURE_OPENAI_DEPLOYMENT, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}])
        return response.choices[0].message.content.strip(), _uso(response)
    except Exception as exc:
        print(f"[llm] No se pudo obtener uso de tokens ({LLM_PROVIDER}): {exc}")
        return llamar_llm(prompt, max_tokens), None


def llamar_llm_con_imagenes(prompt: str, images: list[bytes],
                            max_tokens: int = 800) -> str | None:
    """Envía imágenes JPEG transitorias a un modelo con visión."""
    if not images:
        return None
    if LLM_PROVIDER == "azure":
        return _con_reintentos(
            lambda _prompt, _tokens: _llamar_azure_openai_vision(prompt, images, max_tokens),
            prompt, max_tokens,
        )
    if LLM_PROVIDER == "openai":
        return _con_reintentos(
            lambda _prompt, _tokens: _llamar_openai_vision(prompt, images, max_tokens),
            prompt, max_tokens,
        )
    return None


def llamar_llm_con_imagenes_con_uso(prompt: str, images: list[bytes], max_tokens: int = 800) -> tuple[str | None, dict | None]:
    if LLM_PROVIDER != "azure" or not images:
        return llamar_llm_con_imagenes(prompt, images, max_tokens), None
    try:
        from openai import AzureOpenAI
        client = AzureOpenAI(azure_endpoint=AZURE_OPENAI_ENDPOINT, api_key=AZURE_OPENAI_API_KEY, api_version=AZURE_OPENAI_API_VERSION)
        response = client.chat.completions.create(model=AZURE_OPENAI_DEPLOYMENT, max_tokens=max_tokens,
            messages=[{"role": "user", "content": _contenido_con_imagenes(prompt, images)}])
        return response.choices[0].message.content.strip(), _uso(response, len(images))
    except Exception as exc:
        print(f"[llm] No se pudo obtener uso de visión ({LLM_PROVIDER}): {exc}")
        return llamar_llm_con_imagenes(prompt, images, max_tokens), None


def _con_reintentos(fn, prompt: str, max_tokens: int) -> str | None:
    espera = LLM_ESPERA_INICIAL
    for intento in range(1, LLM_MAX_REINTENTOS + 1):
        try:
            return fn(prompt, max_tokens)
        except Exception as e:
            if intento == LLM_MAX_REINTENTOS:
                print(f"[llm] Fallaron los {LLM_MAX_REINTENTOS} intentos ({LLM_PROVIDER}): {e}")
                return None
            print(f"[llm] Intento {intento}/{LLM_MAX_REINTENTOS} falló ({e}), "
                  f"reintentando en {espera:.0f}s...")
            time.sleep(espera)
            espera *= 2
    return None


def _llamar_anthropic(prompt: str, max_tokens: int) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=LLM_API_KEY)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip()


def _llamar_openai(prompt: str, max_tokens: int) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=LLM_API_KEY)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content.strip()


def _llamar_azure_openai(prompt: str, max_tokens: int) -> str:
    from openai import AzureOpenAI
    client = AzureOpenAI(
        azure_endpoint = AZURE_OPENAI_ENDPOINT,
        api_key        = AZURE_OPENAI_API_KEY,
        api_version    = AZURE_OPENAI_API_VERSION,
    )
    response = client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content.strip()


def _contenido_con_imagenes(prompt: str, images: list[bytes]) -> list[dict]:
    contenido = [{"type": "text", "text": prompt}]
    for image in images:
        encoded = base64.b64encode(image).decode("ascii")
        contenido.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{encoded}", "detail": "low"},
        })
    return contenido


def _llamar_azure_openai_vision(prompt: str, images: list[bytes], max_tokens: int) -> str:
    from openai import AzureOpenAI
    client = AzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_API_KEY,
        api_version=AZURE_OPENAI_API_VERSION,
    )
    response = client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": _contenido_con_imagenes(prompt, images)}],
    )
    return response.choices[0].message.content.strip()


def _llamar_openai_vision(prompt: str, images: list[bytes], max_tokens: int) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=LLM_API_KEY)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": _contenido_con_imagenes(prompt, images)}],
    )
    return response.choices[0].message.content.strip()


def _llamar_gemini(prompt: str, max_tokens: int) -> str:
    from google import genai
    client = genai.Client(api_key=LLM_API_KEY)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config={
            "max_output_tokens": max_tokens,
            "temperature": 0.4
        }
    )
    return response.text.strip()
