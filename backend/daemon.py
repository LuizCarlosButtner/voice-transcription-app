import time
import asyncio
import uuid
import threading
from pathlib import Path
from typing import Optional, Callable
from pynput import keyboard

from config import get_settings, AUDIO_STORAGE_DIR
from history import history_manager
from recorder import recorder
from transcriber import transcriber
from rewriter import rewriter
from active_app import has_focused_text_input, get_frontmost_app
from inserter import inserter

# Limiar de tempo para diferenciar toque rápido (tap) de segurar (hold)
TAP_THRESHOLD_SEC = 0.35

class VoiceDaemon:
    def __init__(self, on_status_change: Optional[Callable[[str, Optional[str]], None]] = None):
        self.on_status_change = on_status_change or (lambda status, detail: None)
        self._current_entry_id: Optional[str] = None
        self._current_audio_path: Optional[Path] = None
        self._is_recording = False
        self._is_toggle_active = False  # Ativado via toque simples (fica ligado até o próximo toque)
        self._press_start_time = 0.0
        self._active_app_info = {}
        self._focused_role = None
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._listener: Optional[keyboard.Listener] = None

    def _set_status(self, status: str, detail: Optional[str] = None):
        """Notifica UI/ícone sobre mudança de estado."""
        self.on_status_change(status, detail)

    def _is_hotkey(self, key) -> bool:
        settings = get_settings()
        hotkey_name = (settings.hotkey or "Alt").lower()
        if hotkey_name in ("alt", "option"):
            return key in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r)
        elif hotkey_name in ("ctrl", "control"):
            return key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r)
        elif hotkey_name == "cmd":
            return key in (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r)
        elif hotkey_name == "shift":
            return key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r)
        return False

    def on_press(self, key):
        if key == keyboard.Key.esc:
            self._handle_cancel()
            return

        if self._is_hotkey(key):
            with self._lock:
                # Se já estiver em gravação contínua acionada por toque simples prévio,
                # este segundo toque desliga a gravação imediatamente
                if self._is_toggle_active and self._is_recording:
                    self._is_toggle_active = False
                    self._handle_stop()
                    return

                # Se não estiver gravando, inicia nova sessão
                if not self._is_recording:
                    self._press_start_time = time.time()
                    self._handle_start()

    def on_release(self, key):
        if self._is_hotkey(key):
            with self._lock:
                if not self._is_recording:
                    return

                held_duration = time.time() - self._press_start_time

                # Comportamento Híbrido:
                # 1. Se segurou por mais de TAP_THRESHOLD_SEC: é Push-and-Hold explícito
                #    -> Soltou o dedo, encerra a gravação e envia o texto!
                # 2. Se soltou rapidamente (< TAP_THRESHOLD_SEC): é Tap-to-Toggle
                #    -> Mantém gravando até que o usuário pressione a tecla novamente!
                if held_duration >= TAP_THRESHOLD_SEC:
                    self._is_toggle_active = False
                    self._handle_stop()
                else:
                    self._is_toggle_active = True
                    self._set_status("listening", "Gravando continuamente (toque novamente para enviar)...")

    def _handle_start(self):
        settings = get_settings()

        # 1. Guarda de foco (verifica campo editável antes de gravar)
        has_focus, app_name, role = has_focused_text_input()
        if not has_focus:
            self._set_status("no_focus", f"Nenhum campo de texto em foco no {app_name}")
            return

        self._is_recording = True
        self._active_app_info = get_frontmost_app()
        self._focused_role = role

        # Gera ID de sessão e arquivo WAV
        entry_id = str(uuid.uuid4())
        self._current_entry_id = entry_id
        audio_path = AUDIO_STORAGE_DIR / f"{entry_id}.wav"
        self._current_audio_path = audio_path

        # 2. Registra imediatamente no SQLite para garantir persistência do áudio
        history_manager.create_pending_entry(
            audio_path=str(audio_path),
            entry_id=entry_id,
            active_app=self._active_app_info.get("name"),
            focused_element=role,
            mode="hybrid_tap_hold",
            language=settings.language,
            provider=settings.provider,
            tone=settings.tone
        )

        # 3. Inicia gravação de áudio
        ok, msg = recorder.start()
        if not ok:
            self._is_recording = False
            self._is_toggle_active = False
            history_manager.mark_error(entry_id, 0, msg)
            self._set_status("error", msg)
            return

        self._set_status("listening", f"Gravando para {self._active_app_info.get('name')}...")

    def _handle_stop(self):
        self._is_recording = False
        self._is_toggle_active = False
        entry_id = self._current_entry_id
        audio_path = self._current_audio_path

        if not entry_id or not audio_path:
            return

        self._set_status("processing", "Transcrevendo...")

        # Para gravação e salva arquivo físico WAV no disco
        rec_info = recorder.stop(destination_path=audio_path)
        duration_ms = rec_info.get("duration_ms", 0)

        if not rec_info.get("ok"):
            history_manager.mark_error(entry_id, duration_ms, rec_info.get("reason", "Erro de captura"))
            self._set_status("error", "Erro ao salvar áudio")
            return

        if rec_info.get("duration_ms", 0) < 200 or rec_info.get("is_silent"):
            history_manager.mark_empty(entry_id, duration_ms)
            self._set_status("idle", "Áudio vazio ou muito curto")
            return

        # Executa processamento assíncrono (STT + Tom + Inserção)
        if self._loop:
            asyncio.run_coroutine_threadsafe(
                self._process_pipeline(entry_id, audio_path, duration_ms),
                self._loop
            )
        else:
            threading.Thread(
                target=lambda: asyncio.run(self._process_pipeline(entry_id, audio_path, duration_ms)),
                daemon=True
            ).start()

    async def _process_pipeline(self, entry_id: str, audio_path: Path, duration_ms: int):
        settings = get_settings()
        try:
            # 1. Transcrição (Groq -> SenseVoice fallback)
            stt_res = await transcriber.transcribe(audio_path, language=settings.language)
            if not stt_res.get("ok") or not stt_res.get("text"):
                err = stt_res.get("error") or "Transcrição não retornou texto"
                history_manager.mark_error(entry_id, duration_ms, err, provider=stt_res.get("provider"))
                self._set_status("error", err)
                return

            text_raw = stt_res["text"].strip()
            provider_used = stt_res.get("provider", settings.provider)

            # 2. Verifica se tradução para inglês deve ser acionada (global ou automática por aplicativo)
            should_translate = settings.translate_to_english
            active_app_name = (self._active_app_info.get("name") or "").lower()
            if not should_translate and settings.translate_auto_apps:
                for auto_app in settings.translate_auto_apps:
                    if auto_app.lower() in active_app_name:
                        should_translate = True
                        break

            # 3. Ajuste de Tom, Gramática e Tradução
            rw_res = await rewriter.rewrite(
                raw_text=text_raw,
                tone=settings.tone,
                grammar_correction=settings.grammar_correction,
                translate_to_english=should_translate
            )
            text_final = rw_res.get("text", text_raw).strip()
            grammar_applied = rw_res.get("grammar_fixed", False)

            # 3. Inserção contínua no cursor (Append)
            inserted = inserter.insert_text(text_final)

            # 4. Atualização de sucesso no histórico SQLite
            history_manager.mark_success(
                entry_id=entry_id,
                duration_ms=duration_ms,
                text_raw=text_raw,
                text_final=text_final,
                tone=settings.tone,
                grammar_fixed=grammar_applied,
                provider=provider_used
            )

            self._set_status("idle", "Concluído com sucesso")

        except Exception as e:
            history_manager.mark_error(entry_id, duration_ms, f"Erro inesperado no pipeline: {e}")
            self._set_status("error", str(e))

    def _handle_cancel(self):
        with self._lock:
            if self._is_recording or recorder.is_recording:
                self._is_recording = False
                self._is_toggle_active = False
                recorder.cancel()
                if self._current_entry_id:
                    history_manager.mark_cancelled(self._current_entry_id)
                self._set_status("idle", "Gravação cancelada")

    def start_listening(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        """Inicia o escutador de teclado global pynput em background."""
        self._loop = loop
        self._listener = keyboard.Listener(
            on_press=self.on_press,
            on_release=self.on_release
        )
        self._listener.daemon = True
        self._listener.start()
        self._set_status("idle", "Pronto")

    def stop_listening(self):
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
