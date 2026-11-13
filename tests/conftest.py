"""Configuração global e fixtures de isolamento total para a suíte de testes."""

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# Garante que os diretórios backend/ e raiz do projeto estejam no caminho de busca
RAIZ_PROJETO = Path(__file__).resolve().parent.parent
DIRETORIO_BACKEND = RAIZ_PROJETO / "backend"

if str(DIRETORIO_BACKEND) not in sys.path:
    sys.path.insert(0, str(DIRETORIO_BACKEND))
if str(RAIZ_PROJETO) not in sys.path:
    sys.path.insert(1, str(RAIZ_PROJETO))

# Redireciona o HOME antes de qualquer importação de módulos do backend para impedir
# qualquer toque em ~/.voice-transcription ou ~/Library/LaunchAgents no tempo de import.
_DIRETORIO_SESSAO_TEMPORARIO = Path(tempfile.mkdtemp(prefix="voz_sessao_isolada_"))
os.environ["HOME"] = str(_DIRETORIO_SESSAO_TEMPORARIO)
os.environ.setdefault("GROQ_API_KEY", "gsk_chave_teste_isolada_1234567890abcdef")
atexit.register(shutil.rmtree, _DIRETORIO_SESSAO_TEMPORARIO, True)


@pytest.fixture(autouse=True)
def ambiente_isolado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Isola 100% dos caminhos de configuração, áudio, SQLite e LaunchAgent por teste."""
    diretorio_home = tmp_path / "lar_usuario"
    diretorio_base = diretorio_home / ".voice-transcription"
    diretorio_audios = diretorio_base / "audio"
    arquivo_configuracoes = diretorio_base / "settings.json"
    arquivo_banco = diretorio_base / "history.db"
    diretorio_agentes = diretorio_home / "Library" / "LaunchAgents"
    arquivo_plist = diretorio_agentes / "com.luizcarlos.voicetranscription.plist"

    diretorio_audios.mkdir(parents=True, exist_ok=True)
    diretorio_agentes.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("HOME", str(diretorio_home))
    monkeypatch.setenv("GROQ_API_KEY", "gsk_chave_teste_isolada_1234567890abcdef")

    import autostart
    import config
    import history

    monkeypatch.setattr(config, "DIRETORIO_BASE_APP", diretorio_base)
    monkeypatch.setattr(config, "DIRETORIO_AUDIOS", diretorio_audios)
    monkeypatch.setattr(config, "ARQUIVO_CONFIGURACOES", arquivo_configuracoes)
    monkeypatch.setattr(config, "ARQUIVO_BANCO_HISTORICO", arquivo_banco)
    monkeypatch.setattr(autostart, "ARQUIVO_PLIST", arquivo_plist)

    # Redireciona eventuais constantes auxiliares de diretório/log em autostart
    for nome_atributo, valor_destino in (
        ("DIRETORIO_AGENTES", diretorio_agentes),
        ("DIRETORIO_AGENTES_LANCAMENTO", diretorio_agentes),
        ("DIRETORIO_LAUNCH_AGENTS", diretorio_agentes),
        ("DIRETORIO_LOGS", diretorio_base),
        ("DIRETORIO_LOG", diretorio_base),
        ("LOG_SAIDA", diretorio_base / "launchd.log"),
        ("LOG_ERRO", diretorio_base / "launchd_err.log"),
        ("ARQUIVO_LOG_SAIDA", diretorio_base / "launchd.log"),
        ("ARQUIVO_LOG_ERRO", diretorio_base / "launchd_err.log"),
    ):
        if hasattr(autostart, nome_atributo):
            monkeypatch.setattr(autostart, nome_atributo, valor_destino, raising=False)

    # Propaga os caminhos isolados para módulos que tenham importado constantes por valor
    nomes_modulos_consumidores = (
        "recorder",
        "daemon",
        "history",
        "main",
        "status_icon",
        "protocolo_inicializacao",
    )
    mapa_constantes = {
        "DIRETORIO_BASE_APP": diretorio_base,
        "DIRETORIO_AUDIOS": diretorio_audios,
        "ARQUIVO_CONFIGURACOES": arquivo_configuracoes,
        "ARQUIVO_BANCO_HISTORICO": arquivo_banco,
        "ARQUIVO_PLIST": arquivo_plist,
    }
    for nome_modulo in nomes_modulos_consumidores:
        modulo_carregado = sys.modules.get(nome_modulo)
        if modulo_carregado is not None:
            for nome_constante, caminho_isolado in mapa_constantes.items():
                if hasattr(modulo_carregado, nome_constante):
                    monkeypatch.setattr(
                        modulo_carregado, nome_constante, caminho_isolado, raising=False
                    )

    # Reinicializa o gerenciador de configurações apontando para o arquivo temporário limpo
    novo_gerenciador_cfg = config.GerenciadorConfiguracoes()
    monkeypatch.setattr(config, "gerenciador_configuracoes", novo_gerenciador_cfg)

    # Inicializa um banco SQLite totalmente limpo para este teste
    history.inicializar_banco()

    return {
        "diretorio_home": diretorio_home,
        "diretorio_base": diretorio_base,
        "diretorio_audios": diretorio_audios,
        "arquivo_configuracoes": arquivo_configuracoes,
        "arquivo_banco": arquivo_banco,
        "diretorio_agentes": diretorio_agentes,
        "arquivo_plist": arquivo_plist,
    }


@pytest.fixture
def onda_senoidal_fala():
    """Gera um vetor numpy int16 de 0.25s a 16kHz simulando fala audível."""
    import numpy as np

    taxa_amostragem = 16000
    instantes = np.linspace(0.0, 0.25, int(taxa_amostragem * 0.25), endpoint=False)
    amostras = (np.sin(2.0 * np.pi * 440.0 * instantes) * 14000.0).astype(np.int16)
    return amostras
