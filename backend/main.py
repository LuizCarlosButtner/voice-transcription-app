import os
import sys
import base64
import time
import uuid
import tempfile
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

from config import get_settings, update_settings, get_groq_key, Settings
from history import history_manager
from transcriber import transcriber
from rewriter import rewriter
from daemon import VoiceDaemon
from active_app import is_accessibility_trusted, get_frontmost_app
from recorder import get_macos_microphone_status

app = FastAPI(
    title="Voice Transcription Daemon & API",
    description="Backend local standalone para transcrição de voz universal no macOS",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Instância global do Daemon
daemon = VoiceDaemon()

@app.on_event("startup")
def on_startup():
    try:
        daemon.start_listening()
    except Exception as e:
        print(f"[AVISO] Não foi possível iniciar listener de atalhos globais: {e}")

@app.on_event("shutdown")
def on_shutdown():
    try:
        daemon.stop_listening()
    except Exception:
        pass

# --- Modelos de Entrada ---
class TranscribeRequest(BaseModel):
    dataBase64: str = Field(description="Áudio codificado em base64 (WAV ou formato compatível)")
    mimeType: str = Field(default="audio/wav")
    language: Optional[str] = Field(default="pt")
    tone: Optional[str] = Field(default=None)

class RewriteRequest(BaseModel):
    text: str
    tone: Optional[str] = Field(default=None)
    grammar_correction: Optional[bool] = Field(default=None)

class SettingsUpdate(BaseModel):
    tone: Optional[str] = None
    language: Optional[str] = None
    hotkey: Optional[str] = None
    grammar_correction: Optional[bool] = None
    toggle_mode: Optional[bool] = None
    append_at_cursor: Optional[bool] = None
    translate_to_english: Optional[bool] = None
    translate_auto_apps: Optional[List[str]] = None

# --- Endpoints ---

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "app": "Voice Transcription Daemon & API",
        "version": "1.0.0",
        "groq_key_configured": bool(get_groq_key())
    }

@app.get("/status")
def get_status():
    settings = get_settings()
    return {
        "active_provider": settings.provider,
        "fallback_provider": settings.fallback_provider,
        "language": settings.language,
        "tone": settings.tone,
        "available_tones": settings.available_tones,
        "grammar_correction": settings.grammar_correction,
        "hotkey": settings.hotkey,
        "toggle_mode": settings.toggle_mode,
        "append_at_cursor": settings.append_at_cursor,
        "translate_to_english": settings.translate_to_english,
        "translate_auto_apps": settings.translate_auto_apps,
        "permissions": {
            "accessibility_trusted": is_accessibility_trusted(),
            "microphone_status": get_macos_microphone_status()
        },
        "frontmost_app": get_frontmost_app(),
        "stats": history_manager.get_stats()
    }

@app.get("/history")
def list_history(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status: Optional[str] = None,
    query: Optional[str] = None
):
    entries = history_manager.list_entries(limit=limit, offset=offset, status=status, query=query)
    stats = history_manager.get_stats()
    return {
        "entries": entries,
        "stats": stats,
        "count": len(entries)
    }

@app.get("/history/{entry_id}")
def get_history_entry(entry_id: str):
    entry = history_manager.get_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Registro não encontrado")
    return entry

@app.post("/transcribe")
async def transcribe_audio(payload: TranscribeRequest):
    """
    Endpoint compatível com dsh-voice: recebe áudio em base64, executa transcrição
    e reescrita de tom, persistindo o histórico.
    """
    try:
        audio_bytes = base64.b64decode(payload.dataBase64)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Base64 inválido: {e}")

    entry_id = str(uuid.uuid4())
    temp_wav = Path(tempfile.gettempdir()) / f"api_req_{entry_id}.wav"
    with open(temp_wav, "wb") as f:
        f.write(audio_bytes)

    settings = get_settings()
    lang = payload.language or settings.language
    tone = payload.tone or settings.tone

    history_manager.create_pending_entry(
        audio_path=str(temp_wav),
        entry_id=entry_id,
        active_app="API_Client",
        mode="api",
        language=lang,
        provider=settings.provider,
        tone=tone
    )

    # 1. Transcrição
    stt_res = await transcriber.transcribe(temp_wav, language=lang)
    took_ms = stt_res.get("took_ms", 0)

    if not stt_res.get("ok"):
        err = stt_res.get("error") or "Falha na transcrição"
        history_manager.mark_error(entry_id, took_ms, err, provider=stt_res.get("provider"))
        return {
            "ok": False,
            "text_raw": "",
            "text_final": "",
            "provider": stt_res.get("provider", "none"),
            "took_ms": took_ms,
            "error": err
        }

    text_raw = stt_res.get("text", "").strip()

    # 2. Tom e Gramática
    rw_res = await rewriter.rewrite(raw_text=text_raw, tone=tone, grammar_correction=settings.grammar_correction)
    text_final = rw_res.get("text", text_raw).strip()

    history_manager.mark_success(
        entry_id=entry_id,
        duration_ms=took_ms,
        text_raw=text_raw,
        text_final=text_final,
        tone=tone,
        grammar_fixed=rw_res.get("grammar_fixed", False),
        provider=stt_res.get("provider")
    )

    return {
        "ok": True,
        "entry_id": entry_id,
        "text_raw": text_raw,
        "text_final": text_final,
        "tone": tone,
        "provider": stt_res.get("provider"),
        "took_ms": took_ms,
        "error": None
    }

@app.post("/rewrite")
async def rewrite_text(payload: RewriteRequest):
    res = await rewriter.rewrite(
        raw_text=payload.text,
        tone=payload.tone,
        grammar_correction=payload.grammar_correction
    )
    return res

@app.post("/retry/{entry_id}")
async def retry_transcription(entry_id: str):
    """
    Retranscreve um registro existente que tenha falhado, utilizando seu arquivo WAV bruto salvo em disco.
    """
    entry = history_manager.get_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Registro não encontrado")

    audio_path = Path(entry["audio_path"])
    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise HTTPException(status_code=400, detail="Arquivo de áudio original não encontrado em disco para retry")

    settings = get_settings()
    stt_res = await transcriber.transcribe(audio_path, language=entry["language"])
    if not stt_res.get("ok"):
        err = stt_res.get("error") or "Retry falhou na transcrição"
        history_manager.mark_error(entry_id, stt_res.get("took_ms", 0), err, provider=stt_res.get("provider"))
        return {"ok": False, "error": err}

    text_raw = stt_res["text"].strip()
    rw_res = await rewriter.rewrite(raw_text=text_raw, tone=entry["tone"], grammar_correction=settings.grammar_correction)
    text_final = rw_res.get("text", text_raw).strip()

    history_manager.mark_success(
        entry_id=entry_id,
        duration_ms=stt_res.get("took_ms", 0),
        text_raw=text_raw,
        text_final=text_final,
        tone=entry["tone"],
        grammar_fixed=rw_res.get("grammar_fixed", False),
        provider=stt_res.get("provider")
    )

    return {
        "ok": True,
        "entry_id": entry_id,
        "text_raw": text_raw,
        "text_final": text_final,
        "provider": stt_res.get("provider")
    }

@app.post("/settings")
def save_settings_endpoint(payload: SettingsUpdate):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    updated = update_settings(updates)
    return updated

@app.get("/audio/{entry_id}")
def get_audio_file(entry_id: str):
    """Serve o arquivo de áudio gravado (.wav) para streaming e reprodução no player web."""
    entry = history_manager.get_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Registro não encontrado no histórico")
    audio_path_str = entry.get("audio_path")
    if not audio_path_str:
        raise HTTPException(status_code=404, detail="Caminho de áudio não registrado")
    audio_path = Path(audio_path_str)
    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise HTTPException(status_code=404, detail="Arquivo de áudio não encontrado no disco")
    return FileResponse(str(audio_path), media_type="audio/wav", filename=f"{entry_id}.wav")

# Monta arquivos estáticos do frontend (HTML, CSS, JS) na raiz
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
FRONTEND_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

def run_server():
    settings = get_settings()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="warning")

def run_app():
    # Executa o servidor FastAPI em thread paralela de segundo plano
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(0.5)

    # Conecta o ícone do Menu Bar do macOS na thread principal
    from status_icon import create_tray_app
    tray_app = create_tray_app(daemon_ref=daemon)
    daemon.on_status_change = tray_app.update_status
    tray_app.run()

if __name__ == "__main__":
    if "--headless" in sys.argv or "--server-only" in sys.argv:
        run_server()
    else:
        run_app()
