import time
from pathlib import Path
from typing import Dict, Any, Optional
import httpx
from providers.base import BaseSTTProvider
from config import get_groq_key, get_settings

GROQ_STT_ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"

class GroqSTTProvider(BaseSTTProvider):
    def __init__(self, api_key: Optional[str] = None):
        self._explicit_key = api_key

    @property
    def name(self) -> str:
        return "groq"

    def _get_key(self) -> Optional[str]:
        return self._explicit_key or get_groq_key()

    async def transcribe(self, audio_path: Path, language: str = "pt") -> Dict[str, Any]:
        start_time = time.time()
        api_key = self._get_key()
        if not api_key:
            return {
                "ok": False,
                "text": "",
                "provider": self.name,
                "took_ms": 0,
                "error": "GROQ_API_KEY não encontrada no ambiente (~/.zshenv, ~/.dsh/.env ou os.environ)"
            }

        if not audio_path.exists() or audio_path.stat().st_size == 0:
            return {
                "ok": False,
                "text": "",
                "provider": self.name,
                "took_ms": 0,
                "error": f"Arquivo de áudio inexistente ou vazio: {audio_path}"
            }

        settings = get_settings()
        model = settings.groq_stt_model or "whisper-large-v3-turbo"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                with open(audio_path, "rb") as f:
                    files = {
                        "file": (audio_path.name, f, "audio/wav")
                    }
                    data = {
                        "model": model,
                        "language": language,
                        "response_format": "json"
                    }
                    headers = {
                        "Authorization": f"Bearer {api_key}"
                    }

                    response = await client.post(
                        GROQ_STT_ENDPOINT,
                        headers=headers,
                        files=files,
                        data=data
                    )

            took_ms = int((time.time() - start_time) * 1000)

            if response.status_code == 200:
                result = response.json()
                text = (result.get("text") or "").strip()
                return {
                    "ok": True,
                    "text": text,
                    "provider": self.name,
                    "took_ms": took_ms,
                    "error": None
                }
            elif response.status_code == 429:
                return {
                    "ok": False,
                    "text": "",
                    "provider": self.name,
                    "took_ms": took_ms,
                    "error": "Rate limit atingido na API Groq (HTTP 429). Acionando fallback..."
                }
            elif response.status_code == 401:
                return {
                    "ok": False,
                    "text": "",
                    "provider": self.name,
                    "took_ms": took_ms,
                    "error": "Chave GROQ_API_KEY inválida ou expirada (HTTP 401)"
                }
            else:
                err_text = response.text[:200]
                return {
                    "ok": False,
                    "text": "",
                    "provider": self.name,
                    "took_ms": took_ms,
                    "error": f"Erro na API Groq HTTP {response.status_code}: {err_text}"
                }

        except httpx.TimeoutException:
            took_ms = int((time.time() - start_time) * 1000)
            return {
                "ok": False,
                "text": "",
                "provider": self.name,
                "took_ms": took_ms,
                "error": "Timeout ao conectar na API Groq (30s excedidos)"
            }
        except Exception as e:
            took_ms = int((time.time() - start_time) * 1000)
            return {
                "ok": False,
                "text": "",
                "provider": self.name,
                "took_ms": took_ms,
                "error": f"Exceção ao chamar Groq STT: {e}"
            }
