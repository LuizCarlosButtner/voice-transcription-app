"""Testes da máquina de estados de atalho e unicidade de escutador em ServicoVoz."""

import time
from pathlib import Path
from typing import Optional

import pytest
from pynput import keyboard


class EscutadorTecladoSimulado:
    """Dublê de keyboard.Listener para validar unicidade e ciclo de vida sem TCC."""

    instancias_criadas: list["EscutadorTecladoSimulado"] = []

    def __init__(self, on_press=None, on_release=None, **_opcoes):
        self.retorno_pressionar = on_press
        self.retorno_soltar = on_release
        self.daemon = True
        self.vivo = False
        self.foi_iniciado = False
        self.foi_parado = False

        # Associa métodos esperados pela interface pynput/threading
        self.start = self._iniciar_falso
        self.stop = self._parar_falso
        self.is_alive = self._verificar_vivo
        self.join = self._aguardar_falso

        EscutadorTecladoSimulado.instancias_criadas.append(self)

    def _iniciar_falso(self) -> None:
        self.foi_iniciado = True
        self.vivo = True

    def _parar_falso(self) -> None:
        self.foi_parado = True
        self.vivo = False

    def _verificar_vivo(self) -> bool:
        return self.vivo

    def _aguardar_falso(self, timeout: Optional[float] = None) -> None:
        _ = timeout


class GravadorAudioSimulado:
    """Dublê do GravadorAudio para testar o ServicoVoz sem hardware PortAudio."""

    def __init__(self, diretorio_audios: Path):
        self.diretorio_audios = diretorio_audios
        self.esta_gravando = False
        self.nivel_atual = 0.42
        self.arquivos_fatias: list[Path] = []
        self.duracao_silencio = 0.0
        self.ao_parar_automatico = None
        self.id_sessao_atual: Optional[str] = None

        self.chamadas_iniciar = 0
        self.chamadas_parar = 0
        self.chamadas_cancelar = 0

    def iniciar(self, id_sessao: Optional[str] = None) -> tuple[bool, str]:
        self.chamadas_iniciar += 1
        if self.esta_gravando:
            return False, "Já está gravando"
        self.esta_gravando = True
        self.id_sessao_atual = id_sessao or "sessao_simulada"
        return True, "Gravação simulada iniciada"

    def parar(
        self, caminho_destino: Optional[Path] = None, limpar_fatias: bool = True
    ) -> dict:
        _ = limpar_fatias
        self.chamadas_parar += 1
        self.esta_gravando = False
        destino = caminho_destino or (
            self.diretorio_audios / f"{self.id_sessao_atual or 'audio'}.ogg"
        )
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(b"OggS_audio_simulado_valido")
        return {
            "ok": True,
            "path": str(destino),
            "duration_ms": 920,
            "samples": 14720,
            "max_amplitude": 12500,
            "mean_amplitude": 3100.0,
            "is_silent": False,
            "chunks_count": 0,
        }

    def cancelar(self, caminho_destino: Optional[Path] = None) -> dict:
        self.chamadas_cancelar += 1
        self.esta_gravando = False
        destino = caminho_destino or (
            self.diretorio_audios / f"{self.id_sessao_atual or 'cancelado'}.ogg"
        )
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(b"OggS_audio_cancelado_preservado")
        return {
            "ok": True,
            "path": str(destino),
            "duration_ms": 640,
            "samples": 10240,
        }


def _aguardar_conclusao_pipeline(servico, limite_segundos: float = 2.0) -> None:
    """Aguarda a thread assíncrona de transcrição/inserção encerrar com segurança."""
    instante_limite = time.monotonic() + limite_segundos
    while servico.esta_processando and time.monotonic() < instante_limite:
        time.sleep(0.01)
    assert not servico.esta_processando, "O pipeline não concluiu dentro do tempo limite"


def _preparar_ambiente_servico(
    monkeypatch: pytest.MonkeyPatch, ambiente_isolado: dict[str, Path]
):
    """Instancia ServicoVoz isolado com mocks de áudio, STT, LLM, foco e inserção."""
    import active_app
    import daemon
    import inserter
    import recorder
    import rewriter
    import transcriber

    EscutadorTecladoSimulado.instancias_criadas = []
    monkeypatch.setattr(daemon.keyboard, "Listener", EscutadorTecladoSimulado)

    gravador_sim = GravadorAudioSimulado(ambiente_isolado["diretorio_audios"])
    monkeypatch.setattr(recorder, "gravador", gravador_sim)
    monkeypatch.setattr(daemon, "gravador", gravador_sim)

    textos_inseridos: list[str] = []

    async def transcrever_simulado(caminho_audio: Path, idioma: Optional[str] = None) -> dict:
        _ = (caminho_audio, idioma)
        return {
            "ok": True,
            "text": "texto ditado pelo usuario",
            "provider": "groq",
            "took_ms": 85,
            "error": None,
        }

    async def reescrever_simulado(
        texto_bruto: str,
        tom: Optional[str] = None,
        correcao_gramatical: Optional[bool] = None,
        traduzir_para_ingles: Optional[bool] = None,
    ) -> dict:
        _ = (correcao_gramatical, traduzir_para_ingles)
        return {
            "ok": True,
            "text": "Texto ditado pelo usuário.",
            "tone": tom or "verbatim",
            "grammar_fixed": True,
            "translated": False,
            "took_ms": 40,
            "fallback_used": False,
            "warning": None,
        }

    def inserir_simulado(texto: str, metodo: Optional[str] = None) -> bool:
        _ = metodo
        textos_inseridos.append(texto)
        return True

    app_ativo_falso = lambda: {
        "name": "NotasTeste",
        "bundle_id": "com.apple.Notes",
        "pid": 1234,
    }
    foco_permissivo_falso = lambda: (True, "NotasTeste", "AXTextArea")
    foco_estrito_falso = lambda: (True, "NotasTeste", object())

    monkeypatch.setattr(transcriber.transcritor, "transcrever", transcrever_simulado)
    monkeypatch.setattr(rewriter.reescritor, "reescrever", reescrever_simulado)
    monkeypatch.setattr(inserter.inseridor, "inserir_texto", inserir_simulado)

    monkeypatch.setattr(active_app, "obter_aplicativo_ativo", app_ativo_falso)
    monkeypatch.setattr(daemon, "obter_aplicativo_ativo", app_ativo_falso, raising=False)
    monkeypatch.setattr(active_app, "possui_campo_texto_focado", foco_permissivo_falso)
    monkeypatch.setattr(
        daemon, "possui_campo_texto_focado", foco_permissivo_falso, raising=False
    )
    monkeypatch.setattr(active_app, "encontrar_editavel_focado", foco_estrito_falso)
    monkeypatch.setattr(
        daemon, "encontrar_editavel_focado", foco_estrito_falso, raising=False
    )

    servico = daemon.ServicoVoz()
    return servico, gravador_sim, textos_inseridos


def test_escutador_unico_idempotente_e_recriacao_se_morrer(
    monkeypatch: pytest.MonkeyPatch, ambiente_isolado: dict[str, Path]
):
    """Garante que 3 chamadas a iniciar_escuta criam 1 listener e recriam apenas se morrer."""
    servico, _gravador_sim, _inseridos = _preparar_ambiente_servico(
        monkeypatch, ambiente_isolado
    )

    try:
        assert servico.iniciar_escuta() is True
        assert servico.iniciar_escuta() is True
        assert servico.iniciar_escuta() is True

        assert len(EscutadorTecladoSimulado.instancias_criadas) == 1
        primeiro_escutador = EscutadorTecladoSimulado.instancias_criadas[0]
        assert primeiro_escutador.foi_iniciado is True
        assert servico.escuta_ativa is True

        # Simula queda inesperada da thread do listener (ex: revogação/falha de evento)
        primeiro_escutador.vivo = False
        assert servico.escuta_ativa is False

        assert servico.iniciar_escuta() is True
        assert primeiro_escutador.foi_parado is True
        assert len(EscutadorTecladoSimulado.instancias_criadas) == 2
        segundo_escutador = EscutadorTecladoSimulado.instancias_criadas[1]
        assert segundo_escutador.vivo is True
        assert servico.escuta_ativa is True
    finally:
        servico.parar_escuta()
        assert servico.escuta_ativa is False


def test_modo_segurar_curto_e_longo_param_ao_soltar_sem_repeticao(
    monkeypatch: pytest.MonkeyPatch, ambiente_isolado: dict[str, Path]
):
    """No modo 'segurar' (push_and_hold), < 0.35s e >= 0.35s param ao soltar e ignoram key-repeat."""
    import config

    servico, gravador_sim, textos_inseridos = _preparar_ambiente_servico(
        monkeypatch, ambiente_isolado
    )

    cfg = config.atualizar_configuracoes({"modo_acionamento": "push_and_hold"})
    assert cfg.modo_acionamento == "segurar"

    # 1. Segurar curto (< 0.35s) com key-repeat simulado enquanto pressionado
    servico.ao_pressionar(keyboard.Key.alt)
    assert servico.esta_gravando is True

    # Eventos repetidos do SO enquanto a tecla continua pressionada devem ser ignorados
    servico.ao_pressionar(keyboard.Key.alt)
    servico.ao_pressionar(keyboard.Key.alt)
    assert gravador_sim.chamadas_iniciar == 1
    assert gravador_sim.chamadas_parar == 0
    assert servico.esta_gravando is True

    time.sleep(0.04)  # menor que 0.35s
    servico.ao_soltar(keyboard.Key.alt)

    # NÃO pode entrar em modo alternado! Deve parar imediatamente ao soltar
    assert servico.esta_gravando is False
    assert servico.modo_atual == "ocioso"
    assert gravador_sim.chamadas_parar == 1
    _aguardar_conclusao_pipeline(servico)
    assert len(textos_inseridos) == 1

    # 2. Segurar longo (>= 0.35s) também para ao soltar
    servico.ao_pressionar(keyboard.Key.alt)
    assert servico.esta_gravando is True
    time.sleep(0.38)
    servico.ao_soltar(keyboard.Key.alt)

    assert servico.esta_gravando is False
    assert servico.modo_atual == "ocioso"
    assert gravador_sim.chamadas_parar == 2
    _aguardar_conclusao_pipeline(servico)
    assert len(textos_inseridos) == 2


def test_modo_alternar_primeiro_toque_liga_segundo_toque_para_e_envia(
    monkeypatch: pytest.MonkeyPatch, ambiente_isolado: dict[str, Path]
):
    """No modo 'alternar' (toggle), o 1º toque mantém gravando após soltar e o 2º encerra."""
    import config
    import history

    servico, gravador_sim, textos_inseridos = _preparar_ambiente_servico(
        monkeypatch, ambiente_isolado
    )

    cfg = config.atualizar_configuracoes({"modo_acionamento": "toggle"})
    assert cfg.modo_acionamento == "alternar"
    assert cfg.modo_alternar is True

    # 1º toque: inicia gravação
    servico.ao_pressionar(keyboard.Key.alt)
    assert servico.esta_gravando is True
    assert servico.modo_atual == "alternado"

    # Key-repeat antes de soltar no 1º toque NÃO pode desligar a gravação
    servico.ao_pressionar(keyboard.Key.alt)
    assert servico.esta_gravando is True
    assert gravador_sim.chamadas_parar == 0

    # Soltar o 1º toque (mesmo após segurar > 0.35s) mantém a gravação ativa
    time.sleep(0.38)
    servico.ao_soltar(keyboard.Key.alt)
    assert servico.esta_gravando is True
    assert servico.modo_atual == "alternado"
    assert gravador_sim.chamadas_parar == 0

    # 2º toque: encerra e dispara envio
    servico.ao_pressionar(keyboard.Key.alt)
    assert servico.esta_gravando is False
    assert servico.modo_atual == "ocioso"
    assert gravador_sim.chamadas_parar == 1

    servico.ao_soltar(keyboard.Key.alt)
    _aguardar_conclusao_pipeline(servico)

    assert textos_inseridos == ["Texto ditado pelo usuário."]
    registros = history.gerenciador_historico.listar_registros(limite=5)
    assert len(registros) == 1
    assert registros[0]["status"] == "sent"


def test_modo_hibrido_toque_rapido_alterna_e_segurar_longo_para(
    monkeypatch: pytest.MonkeyPatch, ambiente_isolado: dict[str, Path]
):
    """No modo 'hibrido', toque < 0.35s vira 'alternado' e segurar >= 0.35s para ao soltar."""
    import config

    servico, gravador_sim, textos_inseridos = _preparar_ambiente_servico(
        monkeypatch, ambiente_isolado
    )

    config.atualizar_configuracoes(
        {"modo_acionamento": "hibrido", "limiar_toque_segundos": 0.35}
    )

    # Parte A: Toque rápido (< 0.35s) transiciona para "alternado"
    servico.ao_pressionar(keyboard.Key.alt)
    assert servico.esta_gravando is True
    assert servico.modo_atual == "segurando"

    time.sleep(0.05)
    servico.ao_soltar(keyboard.Key.alt)
    assert servico.esta_gravando is True
    assert servico.modo_atual == "alternado"
    assert gravador_sim.chamadas_parar == 0

    # Próximo toque encerra a gravação alternada
    servico.ao_pressionar(keyboard.Key.alt)
    assert servico.esta_gravando is False
    assert servico.modo_atual == "ocioso"
    assert gravador_sim.chamadas_parar == 1
    servico.ao_soltar(keyboard.Key.alt)
    _aguardar_conclusao_pipeline(servico)
    assert len(textos_inseridos) == 1

    # Parte B: Segurar longo (>= 0.35s) encerra imediatamente ao soltar
    servico.ao_pressionar(keyboard.Key.alt)
    assert servico.esta_gravando is True
    assert servico.modo_atual == "segurando"

    time.sleep(0.38)
    servico.ao_soltar(keyboard.Key.alt)
    assert servico.esta_gravando is False
    assert servico.modo_atual == "ocioso"
    assert gravador_sim.chamadas_parar == 2
    _aguardar_conclusao_pipeline(servico)
    assert len(textos_inseridos) == 2


def test_tecla_esc_cancela_gravacao_e_persiste_status_cancelado(
    monkeypatch: pytest.MonkeyPatch, ambiente_isolado: dict[str, Path]
):
    """Pressionar Esc durante a gravação cancela o envio e salva status 'cancelled'."""
    import config
    import history

    servico, gravador_sim, textos_inseridos = _preparar_ambiente_servico(
        monkeypatch, ambiente_isolado
    )
    config.atualizar_configuracoes({"modo_acionamento": "alternar"})

    eventos_status: list[tuple[str, Optional[str]]] = []
    servico.registrar_observador_status(
        lambda estado, detalhe: eventos_status.append((estado, detalhe))
    )

    servico.ao_pressionar(keyboard.Key.alt)
    servico.ao_soltar(keyboard.Key.alt)
    assert servico.esta_gravando is True

    estado_tempo_real = servico.obter_estado_tempo_real()
    assert estado_tempo_real["esta_gravando"] is True
    assert estado_tempo_real["modo_atual"] == "alternado"
    assert "nivel_voz" in estado_tempo_real

    # Pressiona Esc para cancelar preservando o áudio para recuperação
    servico.ao_pressionar(keyboard.Key.esc)

    assert servico.esta_gravando is False
    assert servico.modo_atual == "ocioso"
    assert gravador_sim.chamadas_cancelar == 1
    assert gravador_sim.chamadas_parar == 0
    assert textos_inseridos == []

    registros = history.gerenciador_historico.listar_registros(limite=5)
    assert len(registros) == 1
    assert registros[0]["status"] == "cancelled"
    assert Path(registros[0]["audio_path"]).exists()

    recuperaveis = history.gerenciador_historico.listar_recuperaveis()
    assert any(r["id"] == registros[0]["id"] for r in recuperaveis)
    assert any(est == "listening" for est, _ in eventos_status)
    assert eventos_status[-1][0] == "idle"
