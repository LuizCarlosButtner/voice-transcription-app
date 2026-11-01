from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any

class BaseSTTProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Identificador único do provedor (ex: 'groq', 'sensevoice')."""
        pass

    @abstractmethod
    async def transcribe(self, audio_path: Path, language: str = "pt") -> Dict[str, Any]:
        """
        Executa a transcrição do arquivo de áudio.
        Retorno padronizado obrigatório:
        {
            "ok": bool,
            "text": str,
            "provider": str,
            "took_ms": int,
            "error": Optional[str]
        }
        """
        pass
