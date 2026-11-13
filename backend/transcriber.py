"""Orquestrador de provedores de transcrição com cadeia automática de contingência."""

from pathlib import Path
from typing import Any, Optional

from config import obter_configuracoes
from providers.base import ProvedorBaseSTT
from providers.groq import ProvedorGroqSTT
from providers.sensevoice import ProvedorSenseVoice


class GerenciadorTranscricao:
    """Gerencia os provedores de transcrição registrados e executa a cadeia ativa."""

    def __init__(self) -> None:
        self._provedores: dict[str, ProvedorBaseSTT] = {
            "groq": ProvedorGroqSTT(),
            "sensevoice": ProvedorSenseVoice(),
        }

    def obter_provedor(self, nome: str) -> Optional[ProvedorBaseSTT]:
        """Retorna a instância do provedor pelo nome, se existir."""
        return self._provedores.get(nome)

    def obter_cadeia_ativa(self) -> list[ProvedorBaseSTT]:
        """Monta a sequência ordenada de provedores (primário e contingência)."""
        configuracoes = obter_configuracoes()
        nome_primario = configuracoes.provedor
        nome_contingencia = configuracoes.provedor_contingencia

        cadeia: list[ProvedorBaseSTT] = []
        if nome_primario in self._provedores:
            cadeia.append(self._provedores[nome_primario])
        if (
            nome_contingencia in self._provedores
            and nome_contingencia != nome_primario
        ):
            cadeia.append(self._provedores[nome_contingencia])
        return cadeia

    async def transcrever(
        self,
        caminho_audio: Path,
        idioma: Optional[str] = None,
    ) -> dict[str, Any]:
        """Percorre a cadeia ativa e retorna o primeiro resultado bem-sucedido."""
        configuracoes = obter_configuracoes()
        idioma_alvo = idioma or configuracoes.idioma or "pt"
        cadeia = self.obter_cadeia_ativa()

        erros_acumulados: list[str] = []
        tempo_total_ms = 0

        for provedor in cadeia:
            resultado = await provedor.transcrever(Path(caminho_audio), idioma=idioma_alvo)
            tempo_total_ms += int(resultado.get("took_ms", 0) or 0)
            if resultado.get("ok"):
                return resultado
            detalhe_erro = resultado.get("error") or f"Falha no provedor {provedor.nome}"
            erros_acumulados.append(f"{provedor.nome}: {detalhe_erro}")

        mensagem_erro = (
            " | ".join(erros_acumulados)
            if erros_acumulados
            else "Todos os provedores de transcrição falharam"
        )
        return {
            "ok": False,
            "text": "",
            "provider": "none",
            "took_ms": tempo_total_ms,
            "error": mensagem_erro,
        }


transcritor = GerenciadorTranscricao()
