"""Testes automatizados para o ProtocoloInicializacao e diagnóstico de boot."""

from pathlib import Path
from typing import Optional

import pytest


class ServicoVozSimulado:
    """Dublê de testes para o ServicoVoz usado na etapa escutador_atalho."""

    def __init__(self, escuta_inicial: bool = False, resultado_inicio: bool = True):
        self.escuta_ativa = escuta_inicial
        self._resultado_inicio = resultado_inicio
        self.chamadas_iniciar_escuta = 0

    def iniciar_escuta(self) -> bool:
        self.chamadas_iniciar_escuta += 1
        self.escuta_ativa = self._resultado_inicio
        return self._resultado_inicio


def _configurar_ambiente_saudavel(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Configura mocks saudáveis para todas as dependências externas do autoteste."""
    import active_app
    import config
    import protocolo_inicializacao as mod_proto
    import providers.sensevoice as mod_sensevoice
    import recorder

    contadores = {"recarregar_dispositivos": 0, "sondar_microfone": 0}

    def chave_groq_valida() -> str:
        return "gsk_chave_valida_autoteste_1234567890"

    def status_mic_autorizado() -> str:
        return "Authorized"

    def permissao_concedida(*_args, **_kwargs) -> bool:
        return True

    def recarregar_falso() -> bool:
        contadores["recarregar_dispositivos"] += 1
        return True

    def sondar_falso() -> dict:
        contadores["sondar_microfone"] += 1
        return {
            "ok": True,
            "dispositivo_indice": 1,
            "dispositivo_nome": "MacBook Pro Microphone",
            "taxa_amostragem": 16000,
            "detalhe": "Fluxo de áudio validado com sucesso",
        }

    monkeypatch.setattr(config, "obter_chave_groq", chave_groq_valida)
    monkeypatch.setattr(mod_proto, "obter_chave_groq", chave_groq_valida, raising=False)

    monkeypatch.setattr(recorder, "obter_status_microfone_macos", status_mic_autorizado)
    monkeypatch.setattr(
        mod_proto, "obter_status_microfone_macos", status_mic_autorizado, raising=False
    )

    monkeypatch.setattr(active_app, "acessibilidade_ativa", permissao_concedida)
    monkeypatch.setattr(
        mod_proto, "acessibilidade_ativa", permissao_concedida, raising=False
    )
    monkeypatch.setattr(active_app, "monitoramento_entrada_ativo", permissao_concedida)
    monkeypatch.setattr(
        mod_proto, "monitoramento_entrada_ativo", permissao_concedida, raising=False
    )

    monkeypatch.setattr(recorder.gravador, "recarregar_dispositivos", recarregar_falso)
    monkeypatch.setattr(recorder.gravador, "sondar_microfone", sondar_falso)
    monkeypatch.setattr(recorder.gravador, "_esta_gravando", False, raising=False)

    monkeypatch.setattr(
        mod_sensevoice.ProvedorSenseVoice, "esta_disponivel", lambda _self: True
    )

    return contadores


def test_autoteste_completo_cinco_etapas_e_ultimo_relatorio(
    monkeypatch: pytest.MonkeyPatch,
):
    """Garante execução das 5 etapas, retorno estruturado e cache em obter_ultimo_relatorio."""
    from protocolo_inicializacao import ProtocoloInicializacao

    contadores = _configurar_ambiente_saudavel(monkeypatch)
    instancia_protocolo = ProtocoloInicializacao()

    assert instancia_protocolo.obter_ultimo_relatorio() is None

    servico_falso = ServicoVozSimulado(escuta_inicial=False, resultado_inicio=True)
    relatorio = instancia_protocolo.executar_autoteste(
        servico_voz_ref=servico_falso, recarregar_audio=True
    )

    assert isinstance(relatorio, dict)
    assert relatorio["ok"] is True
    assert isinstance(relatorio["executado_em"], str) and len(relatorio["executado_em"]) > 5
    assert isinstance(relatorio["duracao_ms"], int) and relatorio["duracao_ms"] >= 0

    etapas = relatorio["etapas"]
    etapas_esperadas = {
        "armazenamento_banco",
        "chaves_provedores",
        "permissoes_macos",
        "subsistema_audio",
        "escutador_atalho",
    }
    assert etapas_esperadas.issubset(set(etapas.keys()))
    for nome_etapa in etapas_esperadas:
        assert etapas[nome_etapa]["ok"] is True, f"Etapa {nome_etapa} deveria estar saudável"

    assert contadores["recarregar_dispositivos"] == 1
    assert contadores["sondar_microfone"] == 1
    assert servico_falso.chamadas_iniciar_escuta == 1
    assert etapas["escutador_atalho"]["escuta_ativa"] is True
    assert "atalho" in etapas["escutador_atalho"]
    assert "modo_acionamento" in etapas["escutador_atalho"]

    ultimo = instancia_protocolo.obter_ultimo_relatorio()
    assert ultimo == relatorio


def test_autoteste_nao_recria_escutador_ja_ativo(monkeypatch: pytest.MonkeyPatch):
    """Se o ServicoVoz já estiver com escuta_ativa=True, não deve reinvocá-lo à toa."""
    from protocolo_inicializacao import ProtocoloInicializacao

    _configurar_ambiente_saudavel(monkeypatch)
    instancia_protocolo = ProtocoloInicializacao()
    servico_ja_ativo = ServicoVozSimulado(escuta_inicial=True, resultado_inicio=True)

    relatorio = instancia_protocolo.executar_autoteste(
        servico_voz_ref=servico_ja_ativo, recarregar_audio=False
    )

    assert relatorio["ok"] is True
    assert servico_ja_ativo.chamadas_iniciar_escuta == 0
    assert relatorio["etapas"]["escutador_atalho"]["escuta_ativa"] is True


def test_autoteste_recupera_fatias_orfas_automaticamente(
    ambiente_isolado: dict[str, Path],
    onda_senoidal_fala,
    monkeypatch: pytest.MonkeyPatch,
):
    """Verifica que a etapa armazenamento_banco resgata fatias órfãs pendentes no disco."""
    import history
    import recorder
    from protocolo_inicializacao import ProtocoloInicializacao

    _configurar_ambiente_saudavel(monkeypatch)
    diretorio_audios = ambiente_isolado["diretorio_audios"]

    id_sessao_orfa = "sessao_interrompida_autoteste"
    recorder.salvar_arquivo_audio(
        onda_senoidal_fala, diretorio_audios / f"{id_sessao_orfa}_chunk_0.ogg"
    )
    recorder.salvar_arquivo_audio(
        onda_senoidal_fala, diretorio_audios / f"{id_sessao_orfa}_chunk_1.ogg"
    )

    instancia_protocolo = ProtocoloInicializacao()
    relatorio = instancia_protocolo.executar_autoteste(
        servico_voz_ref=ServicoVozSimulado(escuta_inicial=True),
        recarregar_audio=False,
    )

    assert relatorio["etapas"]["armazenamento_banco"]["ok"] is True
    registro_recuperado = history.gerenciador_historico.obter_registro(id_sessao_orfa)
    assert registro_recuperado is not None
    assert registro_recuperado["status"] == "partial"


def test_cenario_falha_microfone_negado(monkeypatch: pytest.MonkeyPatch):
    """Simula permissão de microfone negada no macOS sem lançar exceção não tratada."""
    import protocolo_inicializacao as mod_proto
    import recorder
    from protocolo_inicializacao import ProtocoloInicializacao

    _configurar_ambiente_saudavel(monkeypatch)
    monkeypatch.setattr(recorder, "obter_status_microfone_macos", lambda: "Denied")
    monkeypatch.setattr(
        mod_proto, "obter_status_microfone_macos", lambda: "Denied", raising=False
    )

    instancia_protocolo = ProtocoloInicializacao()
    relatorio = instancia_protocolo.executar_autoteste(
        servico_voz_ref=ServicoVozSimulado(escuta_inicial=True)
    )

    etapa_permissoes = relatorio["etapas"]["permissoes_macos"]
    assert "Denied" in str(etapa_permissoes)
    assert etapa_permissoes["ok"] is False
    assert relatorio["ok"] is False


def test_cenario_falha_sem_chave_groq_e_sem_contingencia(
    monkeypatch: pytest.MonkeyPatch,
):
    """Simula ausência simultânea de GROQ_API_KEY e do modelo local SenseVoice."""
    import config
    import protocolo_inicializacao as mod_proto
    import providers.sensevoice as mod_sensevoice
    from protocolo_inicializacao import ProtocoloInicializacao

    _configurar_ambiente_saudavel(monkeypatch)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(config, "obter_chave_groq", lambda: None)
    monkeypatch.setattr(mod_proto, "obter_chave_groq", lambda: None, raising=False)
    monkeypatch.setattr(
        mod_sensevoice.ProvedorSenseVoice, "esta_disponivel", lambda _self: False
    )

    instancia_protocolo = ProtocoloInicializacao()
    relatorio = instancia_protocolo.executar_autoteste(
        servico_voz_ref=ServicoVozSimulado(escuta_inicial=True)
    )

    assert relatorio["etapas"]["chaves_provedores"]["ok"] is False
    assert relatorio["ok"] is False


def test_cenario_falha_fluxo_subsistema_audio_e_excecao_isolada(
    monkeypatch: pytest.MonkeyPatch,
):
    """Simula falha na abertura do fluxo de áudio e exceção inesperada em sondagem."""
    import recorder
    from protocolo_inicializacao import ProtocoloInicializacao

    _configurar_ambiente_saudavel(monkeypatch)

    def sondar_com_erro() -> dict:
        return {
            "ok": False,
            "dispositivo_indice": None,
            "dispositivo_nome": None,
            "taxa_amostragem": 16000,
            "detalhe": "Erro PortAudio simulado: dispositivo indisponível",
        }

    monkeypatch.setattr(recorder.gravador, "sondar_microfone", sondar_com_erro)

    instancia_protocolo = ProtocoloInicializacao()
    relatorio_falha = instancia_protocolo.executar_autoteste(
        servico_voz_ref=ServicoVozSimulado(escuta_inicial=True)
    )
    assert relatorio_falha["etapas"]["subsistema_audio"]["ok"] is False
    assert relatorio_falha["ok"] is False

    # Garante que mesmo uma exceção abrupta dentro de sondar_microfone não derruba o boot
    def sondar_explosivo() -> Optional[dict]:
        raise RuntimeError("Falha catastrófica simulada no driver de áudio")

    monkeypatch.setattr(recorder.gravador, "sondar_microfone", sondar_explosivo)
    relatorio_excecao = instancia_protocolo.executar_autoteste(
        servico_voz_ref=ServicoVozSimulado(escuta_inicial=True)
    )
    assert isinstance(relatorio_excecao, dict)
    assert relatorio_excecao["etapas"]["subsistema_audio"]["ok"] is False
    assert relatorio_excecao["ok"] is False
