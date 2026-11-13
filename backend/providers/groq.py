"""Provedor de transcrição em nuvem utilizando Whisper via API Groq."""

import time
from pathlib import Path
from typing import Any, Optional

import httpx

from config import obter_chave_groq, obter_configuracoes
from providers.base import ProvedorBaseSTT

URL_TRANSCRICAO_GROQ = "https://api.groq.com/openai/v1/audio/transcriptions"

MAPA_MIME_POR_EXTENSAO: dict[str, str] = {
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
}


def detectar_tipo_mime_audio(caminho_audio: Path) -> str:
    """Detecta o MIME real do arquivo de áudio pela extensão, com contingência para audio/ogg."""
    extensao = Path(caminho_audio).suffix.lower()
    return MAPA_MIME_POR_EXTENSAO.get(extensao, "audio/ogg")


class ProvedorGroqSTT(ProvedorBaseSTT):
    """Cliente assíncrono para transcrição de áudio na nuvem Groq."""

    def __init__(self, chave_api: Optional[str] = None) -> None:
        self._chave_explicita = chave_api

    @property
    def nome(self) -> str:
        return "groq"

    def _obter_chave(self) -> Optional[str]:
        return self._chave_explicita or obter_chave_groq()

    async def transcrever(self, caminho_audio: Path, idioma: str = "pt") -> dict[str, Any]:
        """Envia o áudio com o MIME correto para a API Groq e retorna o texto transcrito."""
        inicio = time.time()
        caminho = Path(caminho_audio)
        chave_api = self._obter_chave()

        if not chave_api:
            return {
                "ok": False,
                "text": "",
                "provider": self.nome,
                "took_ms": 0,
                "error": "GROQ_API_KEY não encontrada no ambiente (~/.zshenv, ~/.dsh/.env ou variáveis de ambiente)",
            }

        if not caminho.exists() or caminho.stat().st_size == 0:
            return {
                "ok": False,
                "text": "",
                "provider": self.nome,
                "took_ms": 0,
                "error": f"Arquivo de áudio inexistente ou vazio: {caminho}",
            }

        configuracoes = obter_configuracoes()
        modelo = configuracoes.modelo_stt_groq or "whisper-large-v3-turbo"
        tipo_mime = detectar_tipo_mime_audio(caminho)

        try:
            async with httpx.AsyncClient(timeout=30.0) as cliente:
                with open(caminho, "rb") as arquivo_binario:
                    arquivos_envio = {
                        "file": (caminho.name, arquivo_binario, tipo_mime),
                    }
                    dados_formulario = {
                        "model": modelo,
                        "language": idioma,
                        "response_format": "json",
                    }
                    cabecalhos = {
                        "Authorization": f"Bearer {chave_api}",
                    }
                    resposta = await cliente.post(
                        URL_TRANSCRICAO_GROQ,
                        headers=cabecalhos,
                        files=arquivos_envio,
                        data=dados_formulario,
                    )

            tempo_ms = int((time.time() - inicio) * 1000)

            if resposta.status_code == 200:
                resultado = resposta.json()
                texto = (resultado.get("text") or "").strip()
                return {
                    "ok": True,
                    "text": texto,
                    "provider": self.nome,
                    "took_ms": tempo_ms,
                    "error": None,
                }
            if resposta.status_code == 429:
                return {
                    "ok": False,
                    "text": "",
                    "provider": self.nome,
                    "took_ms": tempo_ms,
                    "error": "Limite de requisições atingido na API Groq (HTTP 429)",
                }
            if resposta.status_code == 401:
                return {
                    "ok": False,
                    "text": "",
                    "provider": self.nome,
                    "took_ms": tempo_ms,
                    "error": "Chave GROQ_API_KEY inválida ou expirada (HTTP 401)",
                }

            trecho_erro = resposta.text[:200]
            return {
                "ok": False,
                "text": "",
                "provider": self.nome,
                "took_ms": tempo_ms,
                "error": f"Erro na API Groq HTTP {resposta.status_code}: {trecho_erro}",
            }

        except httpx.TimeoutException:
            tempo_ms = int((time.time() - inicio) * 1000)
            return {
                "ok": False,
                "text": "",
                "provider": self.nome,
                "took_ms": tempo_ms,
                "error": "Tempo limite excedido ao conectar na API Groq (30s)",
            }
        except Exception as erro:
            tempo_ms = int((time.time() - inicio) * 1000)
            return {
                "ok": False,
                "text": "",
                "provider": self.nome,
                "took_ms": tempo_ms,
                "error": f"Exceção ao consultar Groq STT: {erro}",
            }
