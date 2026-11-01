import os
import sys
import time
import wave
import pytest
from pathlib import Path
import numpy as np

# Adiciona o diretório backend ao path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from config import get_settings, update_settings, get_groq_key
from history import history_manager
from recorder import recorder, get_macos_microphone_status
from providers.groq import GroqSTTProvider
from providers.sensevoice import SenseVoiceProvider
from transcriber import transcriber
from rewriter import rewriter
from active_app import get_frontmost_app, has_focused_text_input
from inserter import inserter
from autostart import is_autostart_installed, install_autostart, PLIST_FILE

def test_config_and_key_resolution():
    key = get_groq_key()
    assert key is not None and len(key) > 10, "GROQ_API_KEY deve ser resolvida automaticamente"
    settings = get_settings()
    assert settings.port == 8100
    assert "verbatim" in settings.available_tones

def test_sqlite_history_retention():
    eid = history_manager.create_pending_entry(
        audio_path="/tmp/test_hist_audio.wav",
        active_app="PytestApp",
        tone="formal"
    )
    history_manager.mark_error(eid, 1200, "Erro simulado para testar retenção de áudio")
    entry = history_manager.get_entry(eid)
    assert entry["status"] == "error"
    assert entry["audio_path"] == "/tmp/test_hist_audio.wav"
    history_manager.delete_entry(eid)

def test_audio_recorder_format():
    test_wav = Path("/tmp/test_pytest_audio.wav")
    sr = 16000
    t = np.linspace(0, 0.2, int(sr * 0.2), endpoint=False)
    sine = (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16)

    res = recorder.inject_synthetic_audio(sine, test_wav)
    assert res["ok"] is True
    assert test_wav.exists()

    with wave.open(str(test_wav), "rb") as wf:
        assert wf.getframerate() == 16000
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2

    test_wav.unlink(missing_ok=True)

@pytest.mark.asyncio
async def test_rewriter_all_tones():
    text = "mano vamos fechar isso agora caralho com calma"
    
    # Verbatim
    v = await rewriter.rewrite(text, tone="verbatim", grammar_correction=True)
    assert v["ok"] is True
    assert "mano" in v["text"].lower()
    assert "caralho" in v["text"].lower()

    # Formal
    f = await rewriter.rewrite(text, tone="formal")
    assert f["ok"] is True
    assert len(f["text"]) > 5

def test_active_app_and_focus_guard():
    app_info = get_frontmost_app()
    assert "name" in app_info
    has_focus, app_name, role = has_focused_text_input()
    assert isinstance(has_focus, bool)

def test_inserter_clipboard_safety():
    import pyperclip
    original = "SAFE_CLIPBOARD_PYTEST_999"
    pyperclip.copy(original)
    ok = inserter._insert_via_clipboard("Texto inserido")
    assert ok is True
    assert pyperclip.paste() == original

def test_autostart_plist_generation():
    assert install_autostart() is True
    assert is_autostart_installed() is True
    assert PLIST_FILE.exists()
