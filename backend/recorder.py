import time
import wave
import threading
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List
import numpy as np
from config import AUDIO_STORAGE_DIR, get_settings

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = 'int16'

def save_audio_file(audio_data: np.ndarray, destination_path: Path, sample_rate: int = SAMPLE_RATE) -> Path:
    """
    Grava áudio em formato otimizado e leve (OGG Vorbis via soundfile).
    Caso soundfile/OGG não esteja disponível, faz fallback seguro para WAV PCM 16-bit.
    """
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Se o destino já pede .ogg ou por padrão usaremos .ogg
    ogg_path = destination_path.with_suffix(".ogg") if destination_path.suffix in (".wav", ".ogg", "") else destination_path
    
    try:
        import soundfile as sf
        # Normaliza int16 para float ou grava int16 nativo em Vorbis
        sf.write(str(ogg_path), audio_data, sample_rate, format='OGG', subtype='VORBIS')
        return ogg_path
    except Exception:
        # Fallback para WAV caso OGG falhe
        wav_path = destination_path.with_suffix(".wav")
        with wave.open(str(wav_path), 'wb') as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_data.tobytes())
        return wav_path

def get_macos_microphone_status() -> str:
    """Verifica a permissão do microfone via AVFoundation no macOS sem travar a thread."""
    try:
        from Foundation import NSBundle
        import objc
        bundle = NSBundle.bundleWithPath_('/System/Library/Frameworks/AVFoundation.framework')
        if bundle:
            bundle.load()
            AVCaptureDevice = objc.lookUpClass('AVCaptureDevice')
            if AVCaptureDevice:
                status = AVCaptureDevice.authorizationStatusForMediaType_('soun')
                mapping = {0: 'NotDetermined', 1: 'Restricted', 2: 'Denied', 3: 'Authorized'}
                return mapping.get(status, 'Unknown')
    except Exception:
        pass
    return 'Authorized'

def request_macos_microphone_permission():
    """Dispara a solicitação do diálogo de permissão nativo do macOS para o microfone."""
    try:
        from Foundation import NSBundle
        import objc
        bundle = NSBundle.bundleWithPath_('/System/Library/Frameworks/AVFoundation.framework')
        if bundle:
            bundle.load()
            AVCaptureDevice = objc.lookUpClass('AVCaptureDevice')
            if AVCaptureDevice:
                def handler(granted: bool):
                    pass
                AVCaptureDevice.requestAccessForMediaType_completionHandler_('soun', handler)
    except Exception:
        pass

class AudioRecorder:
    def __init__(self, sample_rate: int = SAMPLE_RATE, channels: int = CHANNELS):
        self.sample_rate = sample_rate
        self.channels = channels
        self._stream = None
        self._frames: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._is_recording = False
        self._start_time = 0.0

        # Gerenciamento de Chunks de Backup Anti-Perda
        self._session_id: Optional[str] = None
        self._flushed_samples: int = 0
        self._chunk_index: int = 0
        self._chunk_files: List[Path] = []
        self._watchdog_thread: Optional[threading.Thread] = None
        self._stop_watchdog_event = threading.Event()

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    @property
    def chunk_files(self) -> List[Path]:
        return list(self._chunk_files)

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            pass
        if self._is_recording:
            with self._lock:
                self._frames.append(indata.copy())

    def _watchdog_loop(self):
        """
        Thread de segurança: monitora a gravação ativa.
        A partir do limiar (default 40s), salva fatias de 30s como chunks .ogg em disco.
        """
        while not self._stop_watchdog_event.is_set():
            time.sleep(1.0)
            if not self._is_recording:
                break
            self._maybe_flush_chunk()

    def _maybe_flush_chunk(self):
        settings = get_settings()
        if not settings.chunk_backup_enabled:
            return

        chunk_start_sec = max(1, settings.chunk_start_seconds or 40)
        chunk_sec = max(1, settings.chunk_seconds or 30)
        
        chunk_samples_threshold = int(chunk_sec * self.sample_rate)
        start_samples_threshold = int(chunk_start_sec * self.sample_rate)

        with self._lock:
            if not self._frames:
                return
            
            total_samples = sum(len(f) for f in self._frames)
            unflushed = total_samples - self._flushed_samples

            # Começa a gravar chunks apenas quando a fala acumulada ultrapassa o limiar inicial (default 40s)
            if total_samples >= start_samples_threshold and unflushed >= chunk_samples_threshold:
                # Extrai a fatia exata de samples para o chunk
                full_audio = np.concatenate(self._frames, axis=0)
                chunk_slice = full_audio[self._flushed_samples : self._flushed_samples + chunk_samples_threshold]
                
                self._flushed_samples += chunk_samples_threshold
                idx = self._chunk_index
                self._chunk_index += 1
                sid = self._session_id or f"session_{int(time.time())}"
            else:
                return

        # Grava o chunk no disco (formato leve .ogg)
        chunk_dest = AUDIO_STORAGE_DIR / f"{sid}_chunk_{idx}.ogg"
        saved_path = save_audio_file(chunk_slice, chunk_dest, self.sample_rate)
        with self._lock:
            self._chunk_files.append(saved_path)

    def start(self, session_id: Optional[str] = None) -> Tuple[bool, str]:
        with self._lock:
            if self._is_recording:
                return False, "Já está gravando"

            status = get_macos_microphone_status()
            if status == 'Denied':
                return False, "Permissão de microfone negada no macOS (Ajustes do Sistema > Privacidade e Segurança > Microfone)"
            if status == 'NotDetermined':
                request_macos_microphone_permission()

            self._frames = []
            self._is_recording = True
            self._start_time = time.time()
            self._session_id = session_id or f"rec_{int(time.time() * 1000)}"
            self._flushed_samples = 0
            self._chunk_index = 0
            self._chunk_files = []
            self._stop_watchdog_event.clear()

            try:
                import sounddevice as sd
                self._stream = sd.InputStream(
                    samplerate=self.sample_rate,
                    channels=self.channels,
                    dtype=DTYPE,
                    callback=self._audio_callback
                )
                self._stream.start()

                # Inicia a thread watchdog para fatiamento em background
                self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
                self._watchdog_thread.start()
                return True, "Gravação iniciada"
            except Exception as e:
                self._is_recording = False
                self._stream = None
                return False, f"Falha ao abrir dispositivo de áudio: {e}"

    def stop(self, destination_path: Optional[Path] = None, clean_chunks: bool = True) -> Dict[str, Any]:
        """
        Para a gravação, escreve o arquivo de áudio final consolidado (OGG leve)
        e opcionalmente remove os chunks temporários já que o áudio completo foi garantido.
        """
        self._stop_watchdog_event.set()
        
        with self._lock:
            if not self._is_recording:
                return {"ok": False, "reason": "Não estava gravando"}

            self._is_recording = False
            duration_ms = int((time.time() - self._start_time) * 1000)

            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None

            if not self._frames:
                return {
                    "ok": False,
                    "duration_ms": duration_ms,
                    "reason": "Nenhum frame de áudio capturado"
                }

            audio_data = np.concatenate(self._frames, axis=0)
            self._frames = []
            chunks_recorded = list(self._chunk_files)

        # Destino padrão
        if destination_path is None:
            AUDIO_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
            destination_path = AUDIO_STORAGE_DIR / f"{self._session_id}.ogg"
        else:
            destination_path.parent.mkdir(parents=True, exist_ok=True)

        final_path = save_audio_file(audio_data, destination_path, self.sample_rate)

        # Se consolidou com sucesso e solicitado, apaga os chunks intermediários de backup
        if clean_chunks and final_path.exists() and final_path.stat().st_size > 0:
            for ch in chunks_recorded:
                try:
                    ch.unlink(missing_ok=True)
                except Exception:
                    pass

        max_amplitude = int(np.max(np.abs(audio_data))) if len(audio_data) > 0 else 0
        mean_amplitude = float(np.mean(np.abs(audio_data))) if len(audio_data) > 0 else 0.0

        return {
            "ok": True,
            "path": str(final_path),
            "duration_ms": duration_ms,
            "samples": len(audio_data),
            "max_amplitude": max_amplitude,
            "mean_amplitude": mean_amplitude,
            "is_silent": max_amplitude < 150,
            "chunks_count": len(chunks_recorded)
        }

    def cancel(self, destination_path: Optional[Path] = None) -> Dict[str, Any]:
        """
        NOVO COMPORTAMENTO (Ordem do Luiz):
        Ao cancelar (ex: tecla Esc), NÃO descarta a fala gravada!
        Salva o áudio capturado até o momento em formato OGG para figurar no menu de recuperação.
        """
        self._stop_watchdog_event.set()
        
        with self._lock:
            if not self._is_recording:
                return {"ok": False, "reason": "Não estava gravando"}

            self._is_recording = False
            duration_ms = int((time.time() - self._start_time) * 1000)

            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None

            if not self._frames:
                return {"ok": False, "duration_ms": 0, "path": None}

            audio_data = np.concatenate(self._frames, axis=0)
            self._frames = []
            chunks_recorded = list(self._chunk_files)

        sid = self._session_id or f"cancelled_{int(time.time() * 1000)}"
        if destination_path is None:
            AUDIO_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
            destination_path = AUDIO_STORAGE_DIR / f"{sid}.ogg"

        saved_path = save_audio_file(audio_data, destination_path, self.sample_rate)

        # Remove chunks intermediários já que salvamos o áudio cancelado completo
        for ch in chunks_recorded:
            try:
                ch.unlink(missing_ok=True)
            except Exception:
                pass

        return {
            "ok": True,
            "path": str(saved_path),
            "duration_ms": duration_ms,
            "samples": len(audio_data)
        }

    def inject_synthetic_audio(self, audio_data: np.ndarray, destination_path: Path) -> Dict[str, Any]:
        """Salva buffer de áudio sintetizado para testes automatizados unitários sem hardware."""
        saved_path = save_audio_file(audio_data, destination_path, self.sample_rate)
        duration_ms = int((len(audio_data) / self.sample_rate) * 1000)
        max_amplitude = int(np.max(np.abs(audio_data))) if len(audio_data) > 0 else 0
        mean_amplitude = float(np.mean(np.abs(audio_data))) if len(audio_data) > 0 else 0.0

        return {
            "ok": True,
            "path": str(saved_path),
            "duration_ms": duration_ms,
            "samples": len(audio_data),
            "max_amplitude": max_amplitude,
            "mean_amplitude": mean_amplitude,
            "is_silent": max_amplitude < 150
        }

recorder = AudioRecorder()
