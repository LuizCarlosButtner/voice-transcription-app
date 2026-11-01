import os
import stat
import shutil
from pathlib import Path

APP_NAME = "VoiceTranscription.app"
BUNDLE_ID = "com.luizcarlos.voicetranscription"

INFO_PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>VoiceTranscription</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundleIdentifier</key>
    <string>com.luizcarlos.voicetranscription</string>
    <key>CFBundleName</key>
    <string>VoiceTranscription</string>
    <key>CFBundleDisplayName</key>
    <string>Voice Transcription</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSMicrophoneUsageDescription</key>
    <string>O Voice Transcription necessita do microfone para converter sua fala em texto em qualquer aplicativo.</string>
    <key>NSAppleEventsUsageDescription</key>
    <string>O Voice Transcription utiliza eventos de acessibilidade para colar o texto transcrito diretamente no cursor do aplicativo em foco.</string>
</dict>
</plist>
"""

LAUNCHER_SCRIPT_TEMPLATE = """#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
APP_ROOT="/Users/luizcarlospereira/programas/geral/voice-transcription-app"
VENV_PYTHON="$APP_ROOT/venv/bin/python"
MAIN_SCRIPT="$APP_ROOT/backend/main.py"

# Carrega variáveis de ambiente do usuário se existirem
[ -f "$HOME/.zshenv" ] && source "$HOME/.zshenv" 2>/dev/null || true
[ -f "$HOME/.zshrc" ] && source "$HOME/.zshrc" 2>/dev/null || true
[ -f "$HOME/.dsh/.env" ] && set -a && source "$HOME/.dsh/.env" && set +a 2>/dev/null || true

export PYTHONPATH="$APP_ROOT/backend:$PYTHONPATH"
cd "$APP_ROOT"

exec "$VENV_PYTHON" "$MAIN_SCRIPT" "$@"
"""

def build_app_bundle(destination_dir: Path):
    app_dir = destination_dir / APP_NAME
    contents_dir = app_dir / "Contents"
    macos_dir = contents_dir / "MacOS"
    resources_dir = contents_dir / "Resources"

    # Limpa build anterior se existir
    if app_dir.exists():
        shutil.rmtree(app_dir)

    macos_dir.mkdir(parents=True, exist_ok=True)
    resources_dir.mkdir(parents=True, exist_ok=True)

    # 1. Info.plist
    with open(contents_dir / "Info.plist", "w", encoding="utf-8") as f:
        f.write(INFO_PLIST_TEMPLATE)

    # 2. PkgInfo
    with open(contents_dir / "PkgInfo", "w", encoding="utf-8") as f:
        f.write("APPL????")

    # 3. Executável launcher
    launcher_file = macos_dir / "VoiceTranscription"
    with open(launcher_file, "w", encoding="utf-8") as f:
        f.write(LAUNCHER_SCRIPT_TEMPLATE)
    
    # Dá permissão de execução (chmod +x)
    launcher_file.chmod(launcher_file.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # 4. Copia o AppIcon.icns
    icns_source = Path(__file__).resolve().parent / "AppIcon.icns"
    if icns_source.exists():
        shutil.copy(icns_source, resources_dir / "AppIcon.icns")

    print(f"[OK] {APP_NAME} empacotado com sucesso em: {app_dir}")
    return app_dir

if __name__ == "__main__":
    pkg_dir = Path(__file__).resolve().parent
    project_root = pkg_dir.parent
    build_app_bundle(project_root)
