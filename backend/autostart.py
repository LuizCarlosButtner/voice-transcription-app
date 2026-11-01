import os
import subprocess
from pathlib import Path

PLIST_LABEL = "com.luizcarlos.voicetranscription"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_FILE = LAUNCH_AGENTS_DIR / f"{PLIST_LABEL}.plist"

LOG_DIR = Path.home() / ".voice-transcription"
LOG_DIR.mkdir(parents=True, exist_ok=True)
STDOUT_LOG = LOG_DIR / "launchd.log"
STDERR_LOG = LOG_DIR / "launchd_err.log"

APP_EXECUTABLE = Path("/Users/luizcarlospereira/programas/geral/voice-transcription-app/VoiceTranscription.app/Contents/MacOS/VoiceTranscription")

PLIST_CONTENT = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{APP_EXECUTABLE}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>StandardOutPath</key>
    <string>{STDOUT_LOG}</string>
    <key>StandardErrorPath</key>
    <string>{STDERR_LOG}</string>
</dict>
</plist>
"""

def is_autostart_installed() -> bool:
    return PLIST_FILE.exists()

def install_autostart() -> bool:
    """Instala o LaunchAgent no macOS para inicialização automática no login."""
    try:
        LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
        with open(PLIST_FILE, "w", encoding="utf-8") as f:
            f.write(PLIST_CONTENT)
        return True
    except Exception as e:
        print(f"[ERRO] Falha ao instalar LaunchAgent: {e}")
        return False

def uninstall_autostart() -> bool:
    """Remove o LaunchAgent desabilitando a inicialização automática."""
    try:
        if PLIST_FILE.exists():
            # Descarrega do launchctl se ativo
            subprocess.run(["launchctl", "unload", str(PLIST_FILE)], capture_output=True)
            PLIST_FILE.unlink(missing_ok=True)
        return True
    except Exception as e:
        print(f"[ERRO] Falha ao desinstalar LaunchAgent: {e}")
        return False
