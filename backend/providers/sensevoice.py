"""Provedor local de transcrição offline com SenseVoice via sherpa-onnx."""

import importlib.util
import time
from pathlib import Path
from typing import Any, Optional

from providers.base import ProvedorBaseSTT

DIRETORIO_MODELO_SENSEVOICE = (
    Path.home() / ".dsh" / "speech-to-text" / "sensevoice" / "models" / "sensevoice-onnx"
)
ARQUIVO_MODELO_SENSEVOICE = DIRETORIO_MODELO_SENSEVOICE / "model.int8.onnx"
ARQUIVO_TOKENS_SENSEVOICE = DIRETORIO_MODELO_SENSEVOICE / "tokens.txt"
MENSAGEM_INDISPONIVEL = (
    "Decodificador SenseVoice offline (sherpa-onnx/modelo) não instalado no ambiente"
)


def _decodificador_sherpa_instalado() -> bool:
    """Verifica se o pacote sherpa_onnx está instalado no ambiente Python."""
    return importlib.util.find_spec("sherpa_onnx") is not None


class ProvedorSenseVoice(ProvedorBaseSTT):
    """Executa inferência real local via sherpa-onnx quando modelo e tokens estão instalados."""

    def __init__(
        self,
        caminho_modelo: Optional[Path] = None,
        caminho_tokens: Optional[Path] = None,
    ) -> None:
        self._caminho_modelo = (
            Path(caminho_modelo) if caminho_modelo is not None else ARQUIVO_MODELO_SENSEVOICE
        )
        if caminho_tokens is not None:
            self._caminho_tokens = Path(caminho_tokens)
        elif caminho_modelo is not None:
            self._caminho_tokens = self._caminho_modelo.parent / "tokens.txt"
        else:
            self._caminho_tokens = ARQUIVO_TOKENS_SENSEVOICE
        self._reconhecedor: Any = None

    @property
    def nome(self) -> str:
        return "sensevoice"

    def esta_disponivel(self) -> bool:
        """Retorna True somente quando sherpa_onnx, model.int8.onnx e tokens.txt existem."""
        return (
            _decodificador_sherpa_instalado()
            and self._caminho_modelo.exists()
            and self._caminho_tokens.exists()
        )

    async def transcrever(self, caminho_audio: Path, idioma: str = "pt") -> dict[str, Any]:
        """Decodifica o áudio localmente ou retorna falha honesta caso indisponível."""
        inicio = time.time()
        caminho = Path(caminho_audio)

        if not self.esta_disponivel():
            tempo_ms = int((time.time() - inicio) * 1000)
            return {
                "ok": False,
                "text": "",
                "provider": self.nome,
                "took_ms": tempo_ms,
                "error": MENSAGEM_INDISPONIVEL,
            }

        if not caminho.exists() or caminho.stat().st_size == 0:
            tempo_ms = int((time.time() - inicio) * 1000)
            return {
                "ok": False,
                "text": "",
                "provider": self.nome,
                "took_ms": tempo_ms,
                "error": f"Arquivo de áudio inexistente ou vazio: {caminho}",
            }

        try:
            import numpy
            import sherpa_onnx
            import soundfile

            amostras, taxa_amostragem = soundfile.read(
                str(caminho),
                dtype="float32",
                always_2d=False,
            )
            if amostras.ndim > 1:
                amostras = numpy.mean(amostras, axis=1)

            if self._reconhecedor is None:
                self._reconhecedor = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                    model=str(self._caminho_modelo),
                    tokens=str(self._caminho_tokens),
                    language=idioma or "auto",
                    use_itn=True,
                    num_threads=2,
                )

            fluxo_audio = self._reconhecedor.create_stream()
            fluxo_audio.accept_waveform(taxa_amostragem, amostras)
            self._reconhecedor.decode_stream(fluxo_audio)
            texto_reconhecido = (getattr(fluxo_audio.result, "text", "") or "").strip()
            tempo_ms = int((time.time() - inicio) * 1000)

            return {
                "ok": True,
                "text": texto_reconhecido,
                "provider": self.nome,
                "took_ms": tempo_ms,
                "error": None,
            }
        except Exception as erro:
            tempo_ms = int((time.time() - inicio) * 1000)
            return {
                "ok": False,
                "text": "",
                "provider": self.nome,
                "took_ms": tempo_ms,
                "error": f"Falha na decodificação SenseVoice offline: {erro}",
            }
