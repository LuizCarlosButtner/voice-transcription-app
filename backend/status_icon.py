import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional
import rumps

from config import get_settings, update_settings, BASE_APP_DIR
from autostart import is_autostart_installed, install_autostart, uninstall_autostart
from history import history_manager
from floating_overlay import floating_overlay

STATUS_ICONS = {
    "idle": "🟢",
    "listening": "REC 🔴",
    "processing": "REC 🟡",
    "no_focus": "⚠️ Sem Foco",
    "error": "⚠️ Erro"
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
        self._anim_thread = None
        self._anim_stop_event = threading.Event()

        # Inicia thread de animação em background e o overlay flutuante na tela
        self._anim_thread = threading.Thread(target=self._animation_loop, daemon=True)
        self._anim_thread.start()
        floating_overlay.start()

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

        # Tradutor Instantâneo PT -> EN (Toggle Rápido em Destaque)
        settings = get_settings()
        self.translate_item = rumps.MenuItem("🌐 Traduzir para Inglês (PT ➔ EN)", callback=self.on_toggle_translate)
        self.translate_item.state = 1 if settings.translate_to_english else 0
        self.menu.add(self.translate_item)

        # 4. Menu de Recuperação de Áudios Não Enviados (Ordem do Luiz)
        self.recovery_menu = rumps.MenuItem("🔄 Recuperação (Não Enviados)")
        self.menu.add(self.recovery_menu)
        self._refresh_recovery_menu()
        self.menu.add(rumps.separator)

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

        # Backup Anti-Perda em Chunks
        self.chunk_backup_item = rumps.MenuItem("Backup Contínuo por Chunks", callback=self.on_toggle_chunk_backup)
        self.chunk_backup_item.state = 1 if settings.chunk_backup_enabled else 0
        self.settings_menu.add(self.chunk_backup_item)

        # Limiar de Chunks Digitável (Campo Livre, default 40s)
        self.chunk_threshold_item = rumps.MenuItem(
            f"Iniciar Chunks aos: {settings.chunk_start_seconds}s (Alterar...)",
            callback=self.on_change_chunk_threshold
        )
        self.settings_menu.add(self.chunk_threshold_item)

        # Auto-parada por Silêncio (Campo Livre, default 60s)
        self.silence_stop_item = rumps.MenuItem(
            f"Auto-Parar após Silêncio: {settings.silence_auto_stop_seconds}s (Alterar...)",
            callback=self.on_change_silence_stop
        )
        self.settings_menu.add(self.silence_stop_item)

        self.menu.add(self.settings_menu)
        self.menu.add(rumps.separator)

        # 5. Atalhos de utilitários
        self.menu.add(rumps.MenuItem("Abrir Painel de Controle (Web)...", callback=self.on_open_web_ui))
        self.menu.add(rumps.MenuItem("Abrir Pasta do Histórico...", callback=self.on_open_history_folder))
        self.menu.add(rumps.MenuItem("Ver Documentação e Atalhos...", callback=self.on_open_docs))
        self.menu.add(rumps.separator)

        # 6. Reiniciar e Sair
        self.menu.add(rumps.MenuItem("🔄 Reiniciar Voice Transcription", callback=self.on_restart_clicked))
        self.menu.add(rumps.MenuItem("Encerrar Voice Transcription", callback=self.on_quit_clicked))

    def _make_tone_callback(self, tone_key: str):
        def callback(sender):
            update_settings({"tone": tone_key})
            for k, item in self._tone_items.items():
                item.state = 1 if k == tone_key else 0
            label = dict(TONES).get(tone_key, tone_key)
            rumps.notification("Voice Transcription", "Tom de Voz Atualizado", f"Modo ativo: {label}")
        return callback

    def on_toggle_translate(self, sender):
        new_state = not bool(sender.state)
        sender.state = 1 if new_state else 0
        update_settings({"translate_to_english": new_state})
        status_msg = "Ativada (Fala em PT ➔ Digita em EN)" if new_state else "Desativada (Digita em PT)"
        rumps.notification("Voice Transcription", "Tradução PT ➔ EN", status_msg)

    def _refresh_recovery_menu(self):
        """Atualiza dinamicamente os itens pendentes dentro do submenu de recuperação."""
        try:
            # Em rumps, remove itens limpando as chaves internas se o menu Cocoa já existir
            if hasattr(self.recovery_menu, "_menu") and self.recovery_menu._menu is not None:
                self.recovery_menu.clear()
            else:
                for k in list(self.recovery_menu.keys()):
                    del self.recovery_menu[k]

            recoverable = history_manager.list_recoverable(limit=10)
            if not recoverable:
                empty_item = rumps.MenuItem("Nenhum áudio pendente (Tudo enviado)")
                self.recovery_menu.add(empty_item)
                return

            for item in recoverable:
                entry_id = item["id"]
                raw_preview = item.get("text_final") or item.get("text_raw") or "Áudio não transcrito"
                # Exibe o início da frase e o horário do erro de forma limpa e direta
                short_text = (raw_preview[:28] + "...") if len(raw_preview) > 28 else raw_preview
                
                # Formata hora HH:MM:SS
                time_str = ""
                created = item.get("created_at")
                if created:
                    try:
                        # Extrai hora de ISO string YYYY-MM-DDTHH:MM:SS...
                        time_part = created.split("T")[1].split(".")[0]
                        time_str = f"[{time_part}] "
                    except Exception:
                        pass

                label = f"{time_str}\"{short_text}\""

                menu_item = rumps.MenuItem(label, callback=self._make_recovery_callback(entry_id))
                self.recovery_menu.add(menu_item)

            self.recovery_menu.add(rumps.separator)
            self.recovery_menu.add(rumps.MenuItem("Atualizar Lista de Pendências", callback=lambda s: self._refresh_recovery_menu()))
        except Exception as e:
            print(f"[RECOVERY MENU] Falha ao atualizar: {e}")

    def _make_recovery_callback(self, entry_id: str):
        def callback(sender):
            if self.daemon_ref:
                import asyncio
                import threading
                threading.Thread(
                    target=lambda: asyncio.run(self.daemon_ref.recover_and_insert(entry_id)),
                    daemon=True
                ).start()
                self._refresh_recovery_menu()
        return callback

    def on_toggle_chunk_backup(self, sender):
        new_state = not bool(sender.state)
        sender.state = 1 if new_state else 0
        update_settings({"chunk_backup_enabled": new_state})
        status_msg = "Ativado" if new_state else "Desativado"
        rumps.notification("Voice Transcription", "Backup de Chunks", f"Backup contínuo {status_msg}")

    def on_change_chunk_threshold(self, sender):
        """Abre janela de entrada livre para o usuário digitar o valor em segundos (sem presets fixos)."""
        settings = get_settings()
        window = rumps.Window(
            message=f"Digite o tempo inicial de fala (em segundos) antes de começar o fatiamento em chunks de 30s:\n\nAtual: {settings.chunk_start_seconds} segundos (Padrão: 40s)",
            title="Limiar de Início dos Chunks",
            default_text=str(settings.chunk_start_seconds),
            ok="Salvar",
            cancel="Cancelar",
            dimensions=(280, 24)
        )
        response = window.run()
        if response.clicked:
            text_val = response.text.strip()
            try:
                val = int(text_val)
                if val >= 5:
                    update_settings({"chunk_start_seconds": val})
                    sender.title = f"Iniciar Chunks aos: {val}s (Alterar...)"
                    rumps.notification("Voice Transcription", "Limiar Atualizado", f"Chunks iniciarão após {val} segundos de fala.")
                else:
                    rumps.alert("Valor Inválido", "O tempo mínimo deve ser de pelo menos 5 segundos.")
            except ValueError:
                rumps.alert("Valor Inválido", "Por favor digite um número inteiro válido em segundos.")

    def on_change_silence_stop(self, sender):
        """Abre janela para o usuário digitar livremente o tempo de silêncio antes da auto-parada."""
        settings = get_settings()
        window = rumps.Window(
            message=f"Digite quantos segundos de silêncio contínuo o aplicativo deve aguardar antes de parar e transcrever automaticamente:\n\nAtual: {settings.silence_auto_stop_seconds} segundos (Padrão: 60s)",
            title="Auto-Parada por Silêncio",
            default_text=str(settings.silence_auto_stop_seconds),
            ok="Salvar",
            cancel="Cancelar",
            dimensions=(280, 24)
        )
        response = window.run()
        if response.clicked:
            text_val = response.text.strip()
            try:
                val = int(text_val)
                if val >= 5:
                    update_settings({"silence_auto_stop_seconds": val})
                    sender.title = f"Auto-Parar após Silêncio: {val}s (Alterar...)"
                    rumps.notification("Voice Transcription", "Auto-Parada Atualizada", f"Auto-parar após {val} segundos de silêncio.")
                else:
                    rumps.alert("Valor Inválido", "O tempo mínimo deve ser de pelo menos 5 segundos.")
            except ValueError:
                rumps.alert("Valor Inválido", "Por favor digite um número inteiro válido em segundos.")

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
        url = f"http://127.0.0.1:{settings.port}/"
        webbrowser.open(url)

    def on_open_history_folder(self, sender):
        BASE_APP_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(BASE_APP_DIR)])

    def on_open_docs(self, sender):
        readme_path = Path(__file__).resolve().parent.parent / "README.md"
        if readme_path.exists():
            subprocess.run(["open", str(readme_path)])

    def on_restart_clicked(self, sender):
        """Reinicia todo o serviço Voice Transcription de forma limpa."""
        rumps.notification("Voice Transcription", "Reiniciando", "Reiniciando o aplicativo e serviços...")
        self._anim_stop_event.set()
        floating_overlay.stop()
        if self.daemon_ref:
            self.daemon_ref.stop_listening()

        app_bundle = Path(__file__).resolve().parent.parent / "VoiceTranscription.app"
        launcher_bin = app_bundle / "Contents" / "MacOS" / "VoiceTranscription"
        
        # Mata qualquer processo na porta 8100 e sobe uma nova instância do app
        cmd = f"kill $(lsof -ti :8100) 2>/dev/null || true; sleep 0.5; '{launcher_bin}' &"
        subprocess.Popen(["sh", "-c", cmd])
        rumps.quit_application()

    def on_quit_clicked(self, sender):
        self._anim_stop_event.set()
        floating_overlay.stop()
        if self.daemon_ref:
            self.daemon_ref.stop_listening()
        rumps.quit_application()

    def _animation_loop(self):
        """
        Loop executado em background para animar a barra de menus do macOS e o badge flutuante.
        - Dobro da velocidade (0.25s por frame).
        - Espaçamento constante dos pontos para evitar que o texto balance horizontal ou verticalmente.
        - Bolinha amarela 🟡 no processamento e vermelha piscante 🔴 no REC.
        """
        dot_state = True
        dots_count = 0
        while not self._anim_stop_event.is_set():
            time.sleep(0.25)
            st = getattr(self, "_current_status", "idle")
            if st == "listening":
                # Pisca a lampadinha vermelha a cada 0.25s (🔴 REC e ⚫ REC)
                dot_state = not dot_state
                anim_text = "🔴 REC" if dot_state else "⚫ REC"
                self.title = anim_text
                # Overlay flutuante: apenas a bolinha vermelha piscando discretamente
                floating_overlay.update_dot("🔴" if dot_state else "", show=True)
            elif st == "processing":
                dots_count = (dots_count + 1) % 4
                if dots_count == 0:
                    dots_padded = "   "
                elif dots_count == 1:
                    dots_padded = ".  "
                elif dots_count == 2:
                    dots_padded = ".. "
                else:
                    dots_padded = "..."
                
                anim_text = f"🟡 REC{dots_padded}"
                self.title = anim_text
                # Overlay flutuante: bolinha amarela enquanto transcreve
                floating_overlay.update_dot("🟡", show=True)
            else:
                if self.title != "🟢":
                    self.title = "🟢"
                floating_overlay.hide()

    def update_status(self, status: str, detail: Optional[str] = None):
        """Atualiza o estado da aplicação."""
        self._current_status = status
        detail_msg = detail or status.capitalize()
        self.status_item.title = f"Status: {detail_msg}"

        if status == "listening":
            self.record_item.title = "Parar Gravação (Soltar)"
        elif status == "processing":
            self.record_item.title = "Processando..."
        else:
            self.record_item.title = "Gravar Agora (Clique)"
            self.title = STATUS_ICONS.get(status, "🟢")
            floating_overlay.hide()

def create_tray_app(daemon_ref=None) -> VoiceTranscriptionTrayApp:
    return VoiceTranscriptionTrayApp(daemon_ref=daemon_ref)
