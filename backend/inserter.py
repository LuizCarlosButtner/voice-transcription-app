import time
import threading
from typing import Optional
import pyperclip
from pynput.keyboard import Controller, Key
from config import get_settings

keyboard_controller = Controller()
_insertion_lock = threading.Lock()

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
            # Espaçamento inteligente: se a última inserção foi há menos de 10 segundos
            # e o novo texto não começa com pontuação nem espaço, adiciona espaço à frente
            now = time.time()
            clean_text = text.strip()
            if (now - self._last_insertion_time < 10.0) and settings.append_at_cursor:
                if clean_text and clean_text[0] not in " .,!?;:\n":
                    clean_text = " " + clean_text

            if insertion_method == "keystroke":
                return self._insert_via_keystrokes(clean_text)
            else:
                return self._insert_via_clipboard(clean_text)

    def _insert_via_clipboard(self, text: str) -> bool:
        try:
            # 1. Salva o clipboard original do usuário
            original_clipboard = ""
            try:
                original_clipboard = pyperclip.paste()
            except Exception:
                pass

            # 2. Copia o novo texto transcrito para o clipboard
            pyperclip.copy(text)
            time.sleep(0.04)

            # 3. Dispara Command + V no macOS
            with keyboard_controller.pressed(Key.cmd):
                keyboard_controller.press('v')
                keyboard_controller.release('v')

            time.sleep(0.08)  # Tempo para o aplicativo de destino absorver o paste

            # 4. Restaura o clipboard original do usuário
            if original_clipboard:
                pyperclip.copy(original_clipboard)

            self._last_insertion_time = time.time()
            return True

        except Exception as e:
            # Se falhar a colagem, tenta fallback por digitação de teclas
            try:
                return self._insert_via_keystrokes(text)
            except Exception:
                return False

    def _insert_via_keystrokes(self, text: str) -> bool:
        try:
            for char in text:
                keyboard_controller.type(char)
                time.sleep(0.005)
            self._last_insertion_time = time.time()
            return True
        except Exception:
            return False

inserter = TextInserter()
