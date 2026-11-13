import subprocess
from pathlib import Path

import config

ROTULO_AGENTE = "com.luizcarlos.voicetranscription"
DIRETORIO_AGENTES_LANCAMENTO = Path.home() / "Library" / "LaunchAgents"
ARQUIVO_PLIST = DIRETORIO_AGENTES_LANCAMENTO / f"{ROTULO_AGENTE}.plist"


def obter_executavel_app() -> Path:
    """
    Localiza o executável do pacote `VoiceTranscription.app`.
    Verifica primeiro `~/Applications/VoiceTranscription.app` e faz fallback
    para o `.app` empacotado na raiz do repositório.
    """
    caminho_aplicacoes_usuario = (
        Path.home()
        / "Applications"
        / "VoiceTranscription.app"
        / "Contents"
        / "MacOS"
        / "VoiceTranscription"
    )
    if caminho_aplicacoes_usuario.exists():
        return caminho_aplicacoes_usuario

    return (
        Path(__file__).resolve().parent.parent
        / "VoiceTranscription.app"
        / "Contents"
        / "MacOS"
        / "VoiceTranscription"
    )


def _gerar_conteudo_plist() -> str:
    """Monta o XML do LaunchAgent dinamicamente com caminhos atualizados."""
    diretorio_logs = config.DIRETORIO_BASE_APP
    log_saida = diretorio_logs / "launchd.log"
    log_erro = diretorio_logs / "launchd_err.log"
    executavel = obter_executavel_app()

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{ROTULO_AGENTE}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{executavel}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>StandardOutPath</key>
    <string>{log_saida}</string>
    <key>StandardErrorPath</key>
    <string>{log_erro}</string>
</dict>
</plist>
"""


def autoinicio_esta_instalado() -> bool:
    """Verifica se o arquivo plist do LaunchAgent está instalado."""
    return ARQUIVO_PLIST.exists()


def instalar_autoinicio() -> bool:
    """Instala o LaunchAgent no macOS para inicialização automática no login."""
    try:
        ARQUIVO_PLIST.parent.mkdir(parents=True, exist_ok=True)
        config.DIRETORIO_BASE_APP.mkdir(parents=True, exist_ok=True)
        conteudo = _gerar_conteudo_plist()
        with open(ARQUIVO_PLIST, "w", encoding="utf-8") as arquivo:
            arquivo.write(conteudo)
        return True
    except Exception as erro:
        print(f"[ERRO] Falha ao instalar LaunchAgent: {erro}")
        return False


def desinstalar_autoinicio() -> bool:
    """Remove o LaunchAgent desabilitando a inicialização automática no login."""
    try:
        if ARQUIVO_PLIST.exists():
            try:
                subprocess.run(
                    ["launchctl", "unload", str(ARQUIVO_PLIST)],
                    capture_output=True,
                    check=False,
                )
            except Exception:
                pass
            ARQUIVO_PLIST.unlink(missing_ok=True)
        return True
    except Exception as erro:
        print(f"[ERRO] Falha ao desinstalar LaunchAgent: {erro}")
        return False
