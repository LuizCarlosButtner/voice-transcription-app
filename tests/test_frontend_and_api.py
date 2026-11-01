import sys
import os
import wave
import numpy as np
from io import BytesIO
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from main import app
from history import history_manager
from status_icon import create_tray_app

client = TestClient(app)

def test_frontend_static_files():
    # 1. GET / (index.html)
    res_root = client.get("/")
    assert res_root.status_code == 200
    assert "text/html" in res_root.headers.get("content-type", "")
    assert "Voice Transcription" in res_root.text
    assert "id=\"btn-hero-mic\"" in res_root.text
    assert "id=\"tones-selector-grid\"" in res_root.text

    # 2. GET /css/style.css
    res_css = client.get("/css/style.css")
    assert res_css.status_code == 200
    assert "--bg-main" in res_css.text

    # 3. GET /js/app.js
    res_js = client.get("/js/app.js")
    assert res_js.status_code == 200
    assert "fetchStatus" in res_js.text

def test_audio_serving_endpoint():
    # Cria uma gravação temporária para testar o endpoint /audio/{id}
    test_id = "test-audio-serving-001"
    temp_wav = Path(f"/tmp/{test_id}.wav")

    sr = 16000
    t = np.linspace(0, 0.2, int(sr * 0.2), endpoint=False)
    sine = (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16)
    with wave.open(str(temp_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(sine.tobytes())

    history_manager.create_pending_entry(
        audio_path=str(temp_wav),
        entry_id=test_id,
        active_app="TestAudioServing",
        tone="verbatim"
    )

    # 1. GET /audio/{test_id} válido
    res = client.get(f"/audio/{test_id}")
    assert res.status_code == 200
    assert res.headers["content-type"] == "audio/wav"
    assert len(res.content) > 100

    # 2. GET /audio/{invalid} deve retornar 404
    res_404 = client.get("/audio/non-existent-id-99999")
    assert res_404.status_code == 404

    # Limpeza
    history_manager.delete_entry(test_id)
    temp_wav.unlink(missing_ok=True)

def test_frontend_api_endpoints():
    # 1. /status
    r_status = client.get("/status")
    assert r_status.status_code == 200
    st_data = r_status.json()
    assert "active_provider" in st_data
    assert "available_tones" in st_data

    # 2. /history
    r_hist = client.get("/history?limit=10")
    assert r_hist.status_code == 200
    assert "entries" in r_hist.json()

    # 3. /settings
    r_set = client.post("/settings", json={"tone": "colloquial"})
    assert r_set.status_code == 200
    assert r_set.json()["tone"] == "colloquial"
    client.post("/settings", json={"tone": "verbatim"})

def test_menu_bar_web_ui_action():
    tray = create_tray_app()
    # Verifica se o item do Web UI foi adicionado ao menu
    menu_titles = [item.title for item in tray.menu.values() if hasattr(item, "title")]
    assert any("Abrir Painel de Controle (Web)..." in t for t in menu_titles)
