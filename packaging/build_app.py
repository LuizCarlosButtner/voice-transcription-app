import shutil
import stat
from pathlib import Path

NOME_APLICATIVO = "VoiceTranscription.app"
IDENTIFICADOR_PACOTE = "com.luizcarlos.voicetranscription"
RAIZ_PROJETO = Path(__file__).resolve().parent.parent

MODELO_INFO_PLIST = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>VoiceTranscription</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundleIdentifier</key>
    <string>{IDENTIFICADOR_PACOTE}</string>
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


def gerar_script_inicializacao(raiz_projeto: Path | None = None) -> str:
    """Gera o conteúdo do script de inicialização do pacote .app para macOS."""
    diretorio_raiz = (raiz_projeto or RAIZ_PROJETO).resolve()
    return f"""#!/usr/bin/env bash
set -e

DIRETORIO_EXECUTAVEL="$( cd "$( dirname "${{BASH_SOURCE[0]}}" )" && pwd )"
RAIZ_CANDIDATA="$( cd "$DIRETORIO_EXECUTAVEL/../../.." 2>/dev/null && pwd || true )"
if [ -x "$RAIZ_CANDIDATA/venv/bin/python" ] && [ -f "$RAIZ_CANDIDATA/backend/main.py" ]; then
    RAIZ_APLICATIVO="$RAIZ_CANDIDATA"
else
    RAIZ_APLICATIVO="{diretorio_raiz}"
fi

PYTHON_AMBIENTE="$RAIZ_APLICATIVO/venv/bin/python"
SCRIPT_PRINCIPAL="$RAIZ_APLICATIVO/backend/main.py"

# Carrega variáveis de ambiente do usuário se existirem
[ -f "$HOME/.zshenv" ] && source "$HOME/.zshenv" 2>/dev/null || true
[ -f "$HOME/.zshrc" ] && source "$HOME/.zshrc" 2>/dev/null || true
[ -f "$HOME/.dsh/.env" ] && set -a && source "$HOME/.dsh/.env" && set +a 2>/dev/null || true

export PYTHONPATH="$RAIZ_APLICATIVO/backend:$PYTHONPATH"
cd "$RAIZ_APLICATIVO"

exec "$PYTHON_AMBIENTE" "$SCRIPT_PRINCIPAL" "$@"
"""


def construir_pacote_app(diretorio_destino: Path) -> Path:
    """Constrói o pacote de aplicativo macOS (.app) no diretório de destino."""
    diretorio_app = diretorio_destino / NOME_APLICATIVO
    diretorio_conteudo = diretorio_app / "Contents"
    diretorio_macos = diretorio_conteudo / "MacOS"
    diretorio_recursos = diretorio_conteudo / "Resources"

    # Limpa pacote anterior se existir
    if diretorio_app.exists():
        shutil.rmtree(diretorio_app)

    diretorio_macos.mkdir(parents=True, exist_ok=True)
    diretorio_recursos.mkdir(parents=True, exist_ok=True)

    # 1. Grava o Info.plist
    with open(diretorio_conteudo / "Info.plist", "w", encoding="utf-8") as arquivo_plist:
        arquivo_plist.write(MODELO_INFO_PLIST)

    # 2. Grava o PkgInfo
    with open(diretorio_conteudo / "PkgInfo", "w", encoding="utf-8") as arquivo_pkginfo:
        arquivo_pkginfo.write("APPL????")

    # 3. Cria o executável de inicialização
    arquivo_inicializador = diretorio_macos / "VoiceTranscription"
    with open(arquivo_inicializador, "w", encoding="utf-8") as arquivo_script:
        arquivo_script.write(gerar_script_inicializacao(RAIZ_PROJETO))

    # Concede permissão de execução (chmod +x)
    arquivo_inicializador.chmod(
        arquivo_inicializador.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    )

    # 4. Copia o ícone AppIcon.icns
    origem_icone = Path(__file__).resolve().parent / "AppIcon.icns"
    if origem_icone.exists():
        shutil.copy(origem_icone, diretorio_recursos / "AppIcon.icns")

    print(f"[OK] {NOME_APLICATIVO} empacotado com sucesso em: {diretorio_app}")
    return diretorio_app


# Apelido mantido para compatibilidade com chamadas legadas externas
build_app_bundle = construir_pacote_app


if __name__ == "__main__":
    construir_pacote_app(RAIZ_PROJETO)
