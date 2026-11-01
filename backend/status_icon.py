import os
import subprocess
from pathlib import Path
from typing import Optional
import rumps

from config import get_settings, update_settings, BASE_APP_DIR
from autostart import is_autostart_installed, install_autostart, uninstall_autostart

STATUS_ICONS = {
    "idle": "🎙️ 🟢",
    "listening": "🎙️ 🔴 Gravando...",
    "processing": "🎙️ 🟡 Transcrevendo...",
    "no_focus": "🎙️ ⚠️ Sem Foco",
    "error": "🎙️ ⚠️ Erro"
}

TONES = [
    ("verbatim", "Verbatim (Sem filtro)"),
    ("colloquial", "Coloquial"),
    ("semiformal", "Semiformal"),
    ("formal", "Formal")
]

class VoiceTranscriptionTrayApp(rumps.App):
    def __init__(self, daemon_ref=None):
        super().__init__("VoiceTranscription", title=STATUS_ICONS["idle"], quit_button=None)
        self.daemon_ref = daemon_ref
        self._current_status = "idle"

        # 1. Item informativo de status
        self.status_item = rumps.MenuItem("Status: Pronto (Ocioso)")
        self.menu.add(self.status_item)
        self.menu.add(rumps.separator)

        # 2. Ação rápida de gravação manual (clicável direto no menu)
        self.record_item = rumps.MenuItem("Gravar / Parar (Clique)", callback=self.on_record_clicked)
        self.menu.add(self.record_item)
        self.menu.add(rumps.separator)

        # 3. Submenu de Tons de Voz
        self.tone_menu = rumps.MenuItem("Tom de Voz (Estilo)")
        self._tone_items = {}
        current_tone = get_settings().tone or "verbatim"

        for key, label in TONES:
            item = rumps.MenuItem(label, callback=self._make_tone_callback(key))
            item.state = 1 if key == current_tone else 0
            self._tone_items[key] = item
            self.tone_menu.add(item)

        self.menu.add(self.tone_menu)

        # 4. Opções e Ajustes rápidos
        self.settings_menu = rumps.MenuItem("Preferências")
        
        # Correção Gramatical
        settings = get_settings()
        self.grammar_item = rumps.MenuItem("Correção Gramatical Automática", callback=self.on_toggle_grammar)
        self.grammar_item.state = 1 if settings.grammar_correction else 0
        self.settings_menu.add(self.grammar_item)

        # Modo Toggle (Push-and-hold vs Dois toques)
        self.toggle_item = rumps.MenuItem("Modo Toggle (Gravar com Dois Toques)", callback=self.on_toggle_mode)
        self.toggle_item.state = 1 if settings.toggle_mode else 0
        self.settings_menu.add(self.toggle_item)

        # Append at cursor
        self.append_item = rumps.MenuItem("Adicionar no Cursor (Append)", callback=self.on_toggle_append)
        self.append_item.state = 1 if settings.append_at_cursor else 0
        self.settings_menu.add(self.append_item)

        # Iniciar com o macOS
        self.autostart_item = rumps.MenuItem("Iniciar Automaticamente no Login", callback=self.on_toggle_autostart)
        self.autostart_item.state = 1 if is_autostart_installed() else 0
        self.settings_menu.add(self.autostart_item)

        self.menu.add(self.settings_menu)
        self.menu.add(rumps.separator)

        # 5. Atalhos de utilitários
        self.menu.add(rumps.MenuItem("Abrir Painel de Controle (Web)...", callback=self.on_open_web_ui))
        self.menu.add(rumps.MenuItem("Abrir Pasta do Histórico...", callback=self.on_open_history_folder))
        self.menu.add(rumps.MenuItem("Ver Documentação e Atalhos...", callback=self.on_open_docs))
        self.menu.add(rumps.separator)

        # 6. Sair
        self.menu.add(rumps.MenuItem("Encerrar Voice Transcription", callback=self.on_quit_clicked))

    def _make_tone_callback(self, tone_key: str):
        def callback(sender):
            update_settings({"tone": tone_key})
            for k, item in self._tone_items.items():
                item.state = 1 if k == tone_key else 0
            label = dict(TONES).get(tone_key, tone_key)
            rumps.notification("Voice Transcription", "Tom de Voz Atualizado", f"Modo ativo: {label}")
        return callback

    def on_record_clicked(self, sender):
        """Permite acionar a gravação diretamente por clique no menu sem precisar de teclado."""
        if not self.daemon_ref:
            return
        if self._current_status == "listening":
            self.daemon_ref._handle_stop()
        else:
            self.daemon_ref._handle_start()

    def on_toggle_grammar(self, sender):
        new_state = not bool(sender.state)
        sender.state = 1 if new_state else 0
        update_settings({"grammar_correction": new_state})

    def on_toggle_mode(self, sender):
        new_state = not bool(sender.state)
        sender.state = 1 if new_state else 0
        update_settings({"toggle_mode": new_state})

    def on_toggle_append(self, sender):
        new_state = not bool(sender.state)
        sender.state = 1 if new_state else 0
        update_settings({"append_at_cursor": new_state})

    def on_toggle_autostart(self, sender):
        new_state = not bool(sender.state)
        if new_state:
            install_autostart()
        else:
            uninstall_autostart()
        sender.state = 1 if is_autostart_installed() else 0
        status_msg = "Ativado" if is_autostart_installed() else "Desativado"
        rumps.notification("Voice Transcription", "Inicialização com macOS", f"Auto-start {status_msg}")

    def on_open_web_ui(self, sender):
        import webbrowser
        settings = get_settings()
        url = f"http://{settings.host}:{settings.port}/"
        webbrowser.open(url)

    def on_open_history_folder(self, sender):
        BASE_APP_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(BASE_APP_DIR)])

    def on_open_docs(self, sender):
        readme_path = Path(__file__).resolve().parent.parent / "README.md"
        if readme_path.exists():
            subprocess.run(["open", str(readme_path)])

    def on_quit_clicked(self, sender):
        if self.daemon_ref:
            self.daemon_ref.stop_listening()
        rumps.quit_application()

    def update_status(self, status: str, detail: Optional[str] = None):
        """Atualiza o ícone e texto do menu bar ao vivo conforme o estado da aplicação."""
        self._current_status = status
        self.title = STATUS_ICONS.get(status, "🎙️")
        detail_msg = detail or status.capitalize()
        self.status_item.title = f"Status: {detail_msg}"

        if status == "listening":
            self.record_item.title = "Parar Gravação (Soltar)"
        else:
            self.record_item.title = "Gravar Agora (Clique)"

def create_tray_app(daemon_ref=None) -> VoiceTranscriptionTrayApp:
    return VoiceTranscriptionTrayApp(daemon_ref=daemon_ref)
