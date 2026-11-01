import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from providers.base import BaseSTTProvider
from providers.groq import GroqSTTProvider
from providers.sensevoice import SenseVoiceProvider
from config import get_settings

class TranscriberManager:
    def __init__(self):
        self._providers: Dict[str, BaseSTTProvider] = {
            "groq": GroqSTTProvider(),
            "sensevoice": SenseVoiceProvider()
        }

    def get_provider(self, name: str) -> Optional[BaseSTTProvider]:
        return self._providers.get(name)

    def get_active_chain(self) -> List[BaseSTTProvider]:
        settings = get_settings()
        primary_name = settings.provider
        fallback_name = settings.fallback_provider

        chain: List[BaseSTTProvider] = []
        if primary_name in self._providers:
            chain.append(self._providers[primary_name])
        if fallback_name in self._providers and fallback_name != primary_name:
            chain.append(self._providers[fallback_name])
        return chain

    async def transcribe(self, audio_path: Path, language: Optional[str] = None) -> Dict[str, Any]:
        """
        Executa transcrição percorrendo a cadeia de fallback.
        Retorna o resultado do primeiro provedor que obtiver sucesso,
        ou o erro acumulado se todos falharem.
        """
        settings = get_settings()
        lang = language or settings.language or "pt"
        chain = self.get_active_chain()

        last_error = None
        for provider in chain:
            res = await provider.transcribe(audio_path, language=lang)
            if res.get("ok"):
                return res
            last_error = res.get("error") or f"Falha no provedor {provider.name}"

        return {
            "ok": False,
            "text": "",
            "provider": "none",
            "took_ms": 0,
            "error": last_error or "Todos os provedores de transcrição falharam"
        }

transcriber = TranscriberManager()
