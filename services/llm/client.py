# services/llm/client.py
import os
import time
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
