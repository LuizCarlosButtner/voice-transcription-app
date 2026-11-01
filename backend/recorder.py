import time
import wave
import threading
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import numpy as np
from config import AUDIO_STORAGE_DIR

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = 'int16'

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
                # 0=NotDetermined, 1=Restricted, 2=Denied, 3=Authorized
                mapping = {0: 'NotDetermined', 1: 'Restricted', 2: 'Denied', 3: 'Authorized'}
                return mapping.get(status, 'Unknown')
    except Exception:
        pass
    return 'Authorized'  # Fallback permissivo se não conseguir consultar

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

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            pass
        if self._is_recording:
            with self._lock:
                self._frames.append(indata.copy())

    def start(self) -> Tuple[bool, str]:
        with self._lock:
            if self._is_recording:
                return False, "Já está gravando"

            # Checagem de permissão no macOS
            status = get_macos_microphone_status()
            if status == 'Denied':
                return False, "Permissão de microfone negada no macOS (Ajustes do Sistema > Privacidade e Segurança > Microfone)"
            if status == 'NotDetermined':
                request_macos_microphone_permission()

            self._frames = []
            self._is_recording = True
            self._start_time = time.time()
            try:
                import sounddevice as sd
                self._stream = sd.InputStream(
                    samplerate=self.sample_rate,
                    channels=self.channels,
                    dtype=DTYPE,
                    callback=self._audio_callback
                )
                self._stream.start()
                return True, "Gravação iniciada"
            except Exception as e:
                self._is_recording = False
                self._stream = None
                return False, f"Falha ao abrir dispositivo de áudio: {e}"

    def stop(self, destination_path: Optional[Path] = None) -> Dict[str, Any]:
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

        if destination_path is None:
            AUDIO_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
            destination_path = AUDIO_STORAGE_DIR / f"rec_{int(time.time() * 1000)}.wav"
        else:
            destination_path.parent.mkdir(parents=True, exist_ok=True)

        with wave.open(str(destination_path), 'wb') as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio_data.tobytes())

        max_amplitude = int(np.max(np.abs(audio_data))) if len(audio_data) > 0 else 0
        mean_amplitude = float(np.mean(np.abs(audio_data))) if len(audio_data) > 0 else 0.0

        return {
            "ok": True,
            "path": str(destination_path),
            "duration_ms": duration_ms,
            "samples": len(audio_data),
            "max_amplitude": max_amplitude,
            "mean_amplitude": mean_amplitude,
            "is_silent": max_amplitude < 150
        }

    def cancel(self):
        with self._lock:
            if self._is_recording:
                self._is_recording = False
                if self._stream:
                    try:
                        self._stream.stop()
                        self._stream.close()
                    except Exception:
                        pass
                    self._stream = None
            self._frames = []

    def inject_synthetic_audio(self, audio_data: np.ndarray, destination_path: Path) -> Dict[str, Any]:
        """Salva buffer de áudio sintetizado para testes automatizados unitários sem hardware."""
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(destination_path), 'wb') as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio_data.tobytes())

        duration_ms = int((len(audio_data) / self.sample_rate) * 1000)
        max_amplitude = int(np.max(np.abs(audio_data))) if len(audio_data) > 0 else 0
        mean_amplitude = float(np.mean(np.abs(audio_data))) if len(audio_data) > 0 else 0.0

        return {
            "ok": True,
            "path": str(destination_path),
            "duration_ms": duration_ms,
            "samples": len(audio_data),
            "max_amplitude": max_amplitude,
            "mean_amplitude": mean_amplitude,
            "is_silent": max_amplitude < 150
        }

recorder = AudioRecorder()
