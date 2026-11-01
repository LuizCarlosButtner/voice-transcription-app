import time
import threading
from typing import Optional
import pyperclip
import Quartz
from config import get_settings

_insertion_lock = threading.Lock()

def _post_cmd_v_quartz():
    """
    Dispara Command + V usando eventos nativos do Quartz CoreGraphics (CGEvent).
    Funciona no macOS de forma direta e sem depender do daemon osascript.
    KeyCode 9 = tecla 'v' no teclado padrão do Mac.
    """
    # Key down Command + V
    event_down = Quartz.CGEventCreateKeyboardEvent(None, 9, True)
    Quartz.CGEventSetFlags(event_down, Quartz.kCGEventFlagMaskCommand)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event_down)
    time.sleep(0.02)
    # Key up V
    event_up = Quartz.CGEventCreateKeyboardEvent(None, 9, False)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event_up)

def _post_unicode_string_quartz(text: str):
    """
    Digita os caracteres diretamente usando CGEventKeyboardSetUnicodeString.
    Funciona mesmo se a colagem for bloqueada ou não houver foco direto de clipboard.
    """
    for char in text:
        event_down = Quartz.CGEventCreateKeyboardEvent(None, 0, True)
        Quartz.CGEventKeyboardSetUnicodeString(event_down, len(char), char)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event_down)
        time.sleep(0.003)
        event_up = Quartz.CGEventCreateKeyboardEvent(None, 0, False)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event_up)

class TextInserter:
    def __init__(self):
        self._last_insertion_time = 0.0

    def insert_text(self, text: str, method: Optional[str] = None) -> bool:
        """
        Insere o texto no aplicativo ativo exatamente na posição do cursor (append no cursor).
        Preserva o clipboard original do usuário.
        """
        if not text or not text.strip():
            return False

        settings = get_settings()
        insertion_method = method or settings.insertion_method or "clipboard_paste"

        with _insertion_lock:
            now = time.time()
            clean_text = text.strip()
            # Adiciona espaço prévio se já houve inserção recente para manter a frase fluida
            if (now - self._last_insertion_time < 10.0) and settings.append_at_cursor:
                if clean_text and clean_text[0] not in " .,!?;:\n":
                    clean_text = " " + clean_text

            if insertion_method == "keystroke":
                return self._insert_via_keystrokes(clean_text)
            else:
                return self._insert_via_clipboard(clean_text)

    def _insert_via_clipboard(self, text: str) -> bool:
        original_clipboard = ""
        try:
            original_clipboard = pyperclip.paste()
        except Exception:
            pass

        try:
            # 1. Copia o novo texto para o clipboard
            pyperclip.copy(text)
            time.sleep(0.08)

            # 2. Dispara Command + V nativo via Quartz
            _post_cmd_v_quartz()
            time.sleep(0.15)  # Tempo para o aplicativo alvo (Notas, Chrome, etc.) absorver o paste

            # 3. Restaura o clipboard original do usuário
            if original_clipboard:
                pyperclip.copy(original_clipboard)

            self._last_insertion_time = time.time()
            return True

        except Exception as e:
            # Fallback para digitação via caracteres Quartz
            try:
                _post_unicode_string_quartz(text)
                self._last_insertion_time = time.time()
                return True
            except Exception:
                return False

    def _insert_via_keystrokes(self, text: str) -> bool:
        try:
            _post_unicode_string_quartz(text)
            self._last_insertion_time = time.time()
            return True
        except Exception:
            return False

inserter = TextInserter()
