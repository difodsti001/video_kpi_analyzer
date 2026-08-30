# services/llm/client.py
import os
from dotenv import load_dotenv

load_dotenv()

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "none")  # "openai" | "azure" | "anthropic" | "gemini" | "none"
LLM_API_KEY  = os.getenv("LLM_API_KEY", "")

AZURE_OPENAI_ENDPOINT    = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_KEY     = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
AZURE_OPENAI_DEPLOYMENT  = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")


def llamar_llm(prompt: str, max_tokens: int = 400) -> str | None:
    """Llama al proveedor LLM configurado en .env. Devuelve None si no hay proveedor configurado."""
    if LLM_PROVIDER == "anthropic":
        return _llamar_anthropic(prompt, max_tokens)
    elif LLM_PROVIDER == "openai":
        return _llamar_openai(prompt, max_tokens)
    elif LLM_PROVIDER == "azure":
        return _llamar_azure_openai(prompt, max_tokens)
    elif LLM_PROVIDER == "gemini":
        return _llamar_gemini(prompt, max_tokens)
    return None


def _llamar_anthropic(prompt: str, max_tokens: int) -> str:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=LLM_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()
    except Exception as e:
        return f"[Error LLM: {e}]"


def _llamar_openai(prompt: str, max_tokens: int) -> str:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=LLM_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"[Error LLM: {e}]"


def _llamar_azure_openai(prompt: str, max_tokens: int) -> str:
    try:
        from openai import AzureOpenAI
        client = AzureOpenAI(
            azure_endpoint = AZURE_OPENAI_ENDPOINT,
            api_key        = AZURE_OPENAI_API_KEY,
            api_version    = AZURE_OPENAI_API_VERSION,
        )
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,   # en Azure, "model" es el nombre del deployment
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"[Error LLM Azure: {e}]"


def _llamar_gemini(prompt: str, max_tokens: int) -> str:
    try:
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
    except Exception as e:
        return f"[Error LLM Gemini: {e}]"
