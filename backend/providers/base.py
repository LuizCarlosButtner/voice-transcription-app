"""Contrato abstrato base para provedores de transcrição de fala em texto (STT)."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class ProvedorBaseSTT(ABC):
    """Interface obrigatória implementada por todos os provedores de transcrição."""

    @property
    @abstractmethod
    def nome(self) -> str:
        """Retorna o identificador único do provedor (ex.: 'groq', 'sensevoice')."""

    @abstractmethod
    async def transcrever(self, caminho_audio: Path, idioma: str = "pt") -> dict[str, Any]:
        """
        Executa a transcrição do arquivo de áudio informado.

        Retorna dicionário padronizado com as chaves JSON:
        - ok: bool
        - text: str
        - provider: str
        - took_ms: int
        - error: Optional[str]
        """
