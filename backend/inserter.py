"""Inserção de texto transcrito no cursor do aplicativo ativo com preservação da área de transferência."""

import threading
import time
from typing import Optional

import pyperclip
import Quartz

try:
    import config as _modulo_configuracao
    from config import obter_configuracoes
except ImportError:
    from backend import config as _modulo_configuracao
    from backend.config import obter_configuracoes

_referencia_inicial_config = obter_configuracoes


def _ler_configuracoes_atuais():
    """Obtém as configurações ativas respeitando substituição em testes."""
    if obter_configuracoes is not _referencia_inicial_config:
        return obter_configuracoes()
    return _modulo_configuracao.obter_configuracoes()

_trava_insercao = threading.Lock()
_CODIGO_TECLA_V_MACOS = 9


def _disparar_cmd_v_quartz() -> None:
    """Dispara o atalho Command + V utilizando eventos nativos do Quartz CoreGraphics."""
    evento_pressionar = Quartz.CGEventCreateKeyboardEvent(
        None, _CODIGO_TECLA_V_MACOS, True
    )
    Quartz.CGEventSetFlags(evento_pressionar, Quartz.kCGEventFlagMaskCommand)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, evento_pressionar)
    time.sleep(0.02)

    evento_soltar = Quartz.CGEventCreateKeyboardEvent(
        None, _CODIGO_TECLA_V_MACOS, False
    )
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, evento_soltar)


def _digitar_unicode_quartz(texto: str) -> None:
    """Digita cada caractere Unicode diretamente via CGEventKeyboardSetUnicodeString."""
    for caractere in texto:
        evento_pressionar = Quartz.CGEventCreateKeyboardEvent(None, 0, True)
        Quartz.CGEventKeyboardSetUnicodeString(
            evento_pressionar, len(caractere), caractere
        )
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, evento_pressionar)
        time.sleep(0.003)

        evento_soltar = Quartz.CGEventCreateKeyboardEvent(None, 0, False)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, evento_soltar)


class InseridorTexto:
    """Gerencia a inserção sequencial de texto no aplicativo em foco preservando a área de transferência."""

    def __init__(self) -> None:
        self._ultimo_horario_insercao = 0.0

    def inserir_texto(self, texto: str, metodo: Optional[str] = None) -> bool:
        """Insere o texto na posição atual do cursor respeitando o método configurado."""
        if not texto or not texto.strip():
            return False

        configuracoes = _ler_configuracoes_atuais()
        metodo_ativo = (
            metodo
            or getattr(configuracoes, "metodo_insercao", "clipboard_paste")
            or "clipboard_paste"
        )
        metodo_normalizado = str(metodo_ativo).strip().lower()
        adicionar_no_cursor = bool(
            getattr(configuracoes, "adicionar_no_cursor", True)
        )

        with _trava_insercao:
            agora = time.time()
            texto_formatado = texto.strip()

            if (agora - self._ultimo_horario_insercao < 10.0) and adicionar_no_cursor:
                if texto_formatado and texto_formatado[0] not in " .,!?;:\n\t":
                    texto_formatado = " " + texto_formatado

            if metodo_normalizado in ("keystroke", "digitacao"):
                return self._inserir_via_digitacao(texto_formatado)

            return self._inserir_via_area_transferencia(texto_formatado)

    def _inserir_via_area_transferencia(self, texto: str) -> bool:
        """Cola o texto via área de transferência e restaura integralmente o valor anterior."""
        conteudo_original: Optional[str] = None
        leitura_original_sucesso = False

        try:
            valor_atual = pyperclip.paste()
            conteudo_original = "" if valor_atual is None else str(valor_atual)
            leitura_original_sucesso = True
        except Exception:
            leitura_original_sucesso = False

        try:
            pyperclip.copy(texto)
            time.sleep(0.08)

            _disparar_cmd_v_quartz()
            time.sleep(0.15)

            self._ultimo_horario_insercao = time.time()
            return True
        except Exception:
            return self._inserir_via_digitacao(texto)
        finally:
            if leitura_original_sucesso and conteudo_original is not None:
                try:
                    pyperclip.copy(conteudo_original)
                except Exception:
                    pass

    def _inserir_via_digitacao(self, texto: str) -> bool:
        """Insere o texto simulando digitação Unicode caractere a caractere."""
        try:
            _digitar_unicode_quartz(texto)
            self._ultimo_horario_insercao = time.time()
            return True
        except Exception:
            return False


inseridor = InseridorTexto()
