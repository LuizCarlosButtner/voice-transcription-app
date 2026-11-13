"""Testes de seleção de microfone, áudio sintético OGG/WAV, fatias órfãs e histórico SQLite."""

import json
import time
import wave
from pathlib import Path

import numpy as np
import pytest
import sounddevice as sd
import soundfile as sf


class FluxoEntradaSimulado:
    """Dublê de sounddevice.InputStream para testar captura e fatiamento sem hardware."""

    ultimo_criado: "FluxoEntradaSimulado | None" = None

    def __init__(self, samplerate=16000, channels=1, dtype="int16", device=None, callback=None, **_extras):
        self.taxa_amostragem = samplerate
        self.canais = channels
        self.tipo_dado = dtype
        self.dispositivo = device
        self.retorno_captura = callback
        self.ativo = False
        self.fechado = False

        self.start = self._iniciar_fluxo
        self.stop = self._parar_fluxo
        self.close = self._fechar_fluxo
        FluxoEntradaSimulado.ultimo_criado = self

    def _iniciar_fluxo(self) -> None:
        self.ativo = True

    def _parar_fluxo(self) -> None:
        self.ativo = False

    def _fechar_fluxo(self) -> None:
        self.fechado = True


def test_selecionar_dispositivo_entrada_pula_virtuais_e_corrompidos(
    monkeypatch: pytest.MonkeyPatch,
):
    """Garante que Voicemod, BlackHole, Soundflower e nomes '???' sejam ignorados."""
    import recorder

    dispositivos_simulados = [
        {"name": "Voicemod Virtual Audio Device", "max_input_channels": 2, "default_samplerate": 48000.0},
        {"name": "BlackHole 2ch", "max_input_channels": 2, "default_samplerate": 48000.0},
        {"name": "Soundflower (64ch)", "max_input_channels": 64, "default_samplerate": 48000.0},
        {"name": "???? ???", "max_input_channels": 1, "default_samplerate": 44100.0},
        {"name": "Saída HDMI Monitor", "max_input_channels": 0, "default_samplerate": 48000.0},
        {"name": "Entrada Linha Auxiliar", "max_input_channels": 2, "default_samplerate": 44100.0},
        {"name": "MacBook Pro Microphone", "max_input_channels": 1, "default_samplerate": 48000.0},
    ]

    chamadas_reinicio_pa = {"encerrar": 0, "inicializar": 0}

    monkeypatch.setattr(sd, "query_devices", lambda *_a, **_kw: dispositivos_simulados)
    monkeypatch.setattr(
        sd, "_terminate", lambda: chamadas_reinicio_pa.__setitem__("encerrar", chamadas_reinicio_pa["encerrar"] + 1)
    )
    monkeypatch.setattr(
        sd, "_initialize", lambda: chamadas_reinicio_pa.__setitem__("inicializar", chamadas_reinicio_pa["inicializar"] + 1)
    )
    if hasattr(recorder, "sd"):
        monkeypatch.setattr(recorder.sd, "query_devices", lambda *_a, **_kw: dispositivos_simulados)

    indice_escolhido = recorder.selecionar_dispositivo_entrada(recarregar=True)
    assert indice_escolhido == 6
    assert chamadas_reinicio_pa["encerrar"] == 1
    assert chamadas_reinicio_pa["inicializar"] == 1

    # Se existirem apenas dispositivos virtuais/corrompidos, deve retornar None com segurança
    apenas_virtuais = dispositivos_simulados[:5]
    monkeypatch.setattr(sd, "query_devices", lambda *_a, **_kw: apenas_virtuais)
    if hasattr(recorder, "sd"):
        monkeypatch.setattr(recorder.sd, "query_devices", lambda *_a, **_kw: apenas_virtuais)
    assert recorder.selecionar_dispositivo_entrada(recarregar=False) is None


def test_injetar_audio_sintetico_ogg_e_contingencia_wav(
    ambiente_isolado: dict[str, Path],
    onda_senoidal_fala,
    monkeypatch: pytest.MonkeyPatch,
):
    """Valida gravação sintética em OGG Vorbis, detecção de silêncio e fallback WAV."""
    import recorder

    diretorio_audios = ambiente_isolado["diretorio_audios"]
    instancia_gravador = recorder.GravadorAudio()

    # 1. Gravação OGG padrão
    resultado_ogg = instancia_gravador.injetar_audio_sintetico(
        onda_senoidal_fala, diretorio_audios / "amostra_fala.ogg"
    )
    assert resultado_ogg["ok"] is True
    caminho_ogg = Path(resultado_ogg["path"])
    assert caminho_ogg.exists()
    assert caminho_ogg.suffix == ".ogg"
    assert caminho_ogg.stat().st_size > 100
    assert resultado_ogg["samples"] == len(onda_senoidal_fala)
    assert resultado_ogg["is_silent"] is False
    assert resultado_ogg["max_amplitude"] > 10000

    metadados_ogg = sf.info(str(caminho_ogg))
    assert metadados_ogg.samplerate == 16000

    # 2. Detecção de áudio silencioso
    amostras_silencio = np.zeros(3200, dtype=np.int16)
    resultado_silencio = instancia_gravador.injetar_audio_sintetico(
        amostras_silencio, diretorio_audios / "amostra_silencio.ogg"
    )
    assert resultado_silencio["ok"] is True
    assert resultado_silencio["is_silent"] is True

    # 3. Fallback automático para WAV PCM 16-bit caso soundfile.write falhe
    def falha_escrita_ogg(*_args, **_kwargs):
        raise RuntimeError("Codificador OGG simulado indisponível")

    monkeypatch.setattr(sf, "write", falha_escrita_ogg)
    if hasattr(recorder, "sf"):
        monkeypatch.setattr(recorder.sf, "write", falha_escrita_ogg, raising=False)

    resultado_wav = instancia_gravador.injetar_audio_sintetico(
        onda_senoidal_fala, diretorio_audios / "amostra_contingencia.wav"
    )
    assert resultado_wav["ok"] is True
    caminho_wav = Path(resultado_wav["path"])
    assert caminho_wav.exists()
    assert caminho_wav.suffix == ".wav"

    with wave.open(str(caminho_wav), "rb") as leitor_wav:
        assert leitor_wav.getnchannels() == 1
        assert leitor_wav.getsampwidth() == 2
        assert leitor_wav.getframerate() == 16000
        assert leitor_wav.getnframes() == len(onda_senoidal_fala)


def test_fatiamento_em_gravacao_e_recuperacao_idempotente_de_fatias_orfas(
    ambiente_isolado: dict[str, Path],
    onda_senoidal_fala,
    monkeypatch: pytest.MonkeyPatch,
):
    """Testa geração de fatias de backup e recuperação 100% idempotente de sessões órfãs."""
    import config
    import history
    import recorder

    diretorio_audios = ambiente_isolado["diretorio_audios"]

    config.atualizar_configuracoes(
        {
            "backup_fatias_ativo": True,
            "inicio_fatias_segundos": 1,
            "duracao_fatia_segundos": 1,
            "parada_silencio_segundos": 0,
        }
    )

    monkeypatch.setattr(recorder, "obter_status_microfone_macos", lambda: "Authorized")
    monkeypatch.setattr(recorder, "selecionar_dispositivo_entrada", lambda recarregar=False: 0)
    monkeypatch.setattr(sd, "InputStream", FluxoEntradaSimulado)
    if hasattr(recorder, "sd"):
        monkeypatch.setattr(recorder.sd, "InputStream", FluxoEntradaSimulado)

    instancia_gravador = recorder.GravadorAudio()
    iniciou, _detalhe = instancia_gravador.iniciar(id_sessao="sessao_queda_energia")
    assert iniciou is True
    assert instancia_gravador.esta_gravando is True
    assert FluxoEntradaSimulado.ultimo_criado is not None

    # Alimenta 2 segundos (32000 amostras a 16kHz) de áudio audível na função de retorno
    bloco_um_segundo = np.tile(onda_senoidal_fala, 4).reshape(-1, 1)
    FluxoEntradaSimulado.ultimo_criado.retorno_captura(
        bloco_um_segundo, len(bloco_um_segundo), None, None
    )
    FluxoEntradaSimulado.ultimo_criado.retorno_captura(
        bloco_um_segundo, len(bloco_um_segundo), None, None
    )
    assert instancia_gravador.nivel_atual > 0.0

    # Aguarda o laço de vigilância gravar ao menos 1 fatia em disco
    limite_espera = time.monotonic() + 1.8
    while not instancia_gravador.arquivos_fatias and time.monotonic() < limite_espera:
        time.sleep(0.05)

    fatias_geradas = instancia_gravador.arquivos_fatias
    assert len(fatias_geradas) >= 1
    assert fatias_geradas[0].exists()

    # Encerra preservando as fatias (limpar_fatias=False) e remove o consolidado para simular crash
    res_parada = instancia_gravador.parar(limpar_fatias=False)
    assert res_parada["ok"] is True
    assert instancia_gravador.nivel_atual == 0.0
    Path(res_parada["path"]).unlink(missing_ok=True)

    # Adiciona uma segunda sessão órfã com múltiplas fatias fora de ordem léxica
    recorder.salvar_arquivo_audio(
        onda_senoidal_fala, diretorio_audios / "sessao_orfa_extra_chunk_1.ogg"
    )
    recorder.salvar_arquivo_audio(
        onda_senoidal_fala, diretorio_audios / "sessao_orfa_extra_chunk_0.ogg"
    )

    # 1ª execução: recupera ambas as sessões órfãs
    recuperadas_primeira_vez = history.gerenciador_historico.recuperar_fatias_orfas()
    assert recuperadas_primeira_vez == 2

    reg_extra = history.gerenciador_historico.obter_registro("sessao_orfa_extra")
    assert reg_extra is not None
    assert reg_extra["status"] == "partial"
    lista_fatias_salvas = json.loads(reg_extra["chunk_files_json"])
    assert lista_fatias_salvas[0].endswith("_chunk_0.ogg")
    assert lista_fatias_salvas[1].endswith("_chunk_1.ogg")

    # 2ª execução consecutiva: idempotência estrita (0 novas entradas duplicadas)
    recuperadas_segunda_vez = history.gerenciador_historico.recuperar_fatias_orfas()
    assert recuperadas_segunda_vez == 0


def test_crud_completo_gerenciador_historico_integridade_e_exclusao_audio(
    ambiente_isolado: dict[str, Path],
    onda_senoidal_fala,
):
    """Exercita integridade PRAGMA, todos os status, filtros, recuperáveis e exclusão física."""
    import history
    import recorder

    diretorio_audios = ambiente_isolado["diretorio_audios"]
    gerenciador = history.GerenciadorHistorico()

    integro, mensagem_integridade = gerenciador.verificar_integridade()
    assert integro is True
    assert "ok" in mensagem_integridade.lower()

    # 1. Registro enviado com sucesso (NÃO deve aparecer em listar_recuperaveis)
    audio_enviado = recorder.salvar_arquivo_audio(
        onda_senoidal_fala, diretorio_audios / "reg_enviado.ogg"
    )
    id_enviado = gerenciador.criar_registro_pendente(
        caminho_audio=str(audio_enviado),
        id_registro="id-enviado-01",
        aplicativo_ativo="Slack",
        modo="segurar",
        tom="formal",
    )
    gerenciador.marcar_enviado(
        id_registro=id_enviado,
        duracao_ms=1500,
        texto_bruto="fala original",
        texto_final="Fala formalizada.",
        tom="formal",
        gramatica_corrigida=True,
        provedor="groq",
    )

    # 2. Registro transcrito mas não colado (DEVE aparecer em listar_recuperaveis)
    audio_nao_colado = recorder.salvar_arquivo_audio(
        onda_senoidal_fala, diretorio_audios / "reg_nao_colado.ogg"
    )
    id_nao_colado = gerenciador.criar_registro_pendente(
        caminho_audio=str(audio_nao_colado), id_registro="id-nao-colado-02"
    )
    gerenciador.marcar_escrito_nao_enviado(
        id_registro=id_nao_colado,
        duracao_ms=1100,
        texto_bruto="texto pendente",
        texto_final="Texto pendente.",
    )

    # 3. Registro com erro (DEVE aparecer em listar_recuperaveis)
    audio_erro = recorder.salvar_arquivo_audio(
        onda_senoidal_fala, diretorio_audios / "reg_erro.ogg"
    )
    id_erro = gerenciador.criar_registro_pendente(
        caminho_audio=str(audio_erro), id_registro="id-erro-03"
    )
    gerenciador.marcar_erro(
        id_registro=id_erro, duracao_ms=800, mensagem_erro="Timeout simulado na API"
    )

    # 4. Registro cancelado (DEVE aparecer em listar_recuperaveis)
    audio_cancelado = recorder.salvar_arquivo_audio(
        onda_senoidal_fala, diretorio_audios / "reg_cancelado.ogg"
    )
    id_cancelado = gerenciador.criar_registro_pendente(
        caminho_audio=str(audio_cancelado), id_registro="id-cancelado-04"
    )
    gerenciador.marcar_cancelado(
        id_registro=id_cancelado, duracao_ms=600, caminho_audio=str(audio_cancelado)
    )

    # 5. Registro vazio (NÃO deve aparecer em listar_recuperaveis)
    audio_vazio = recorder.salvar_arquivo_audio(
        onda_senoidal_fala, diretorio_audios / "reg_vazio.ogg"
    )
    id_vazio = gerenciador.criar_registro_pendente(
        caminho_audio=str(audio_vazio), id_registro="id-vazio-05"
    )
    gerenciador.marcar_vazio(id_registro=id_vazio, duracao_ms=120)

    recuperaveis = gerenciador.listar_recuperaveis(limite=10)
    ids_recuperaveis = {item["id"] for item in recuperaveis}
    assert ids_recuperaveis == {id_nao_colado, id_erro, id_cancelado}

    busca_formal = gerenciador.listar_registros(busca="formalizada")
    assert len(busca_formal) == 1
    assert busca_formal[0]["id"] == id_enviado

    estatisticas = gerenciador.obter_estatisticas()
    assert estatisticas["total"] == 5
    assert estatisticas["sent"] == 1
    assert estatisticas["written_not_sent"] == 1
    assert estatisticas["errors"] == 1
    assert estatisticas["cancelled"] == 1

    # Exclusão física de registro + arquivo de áudio em disco
    assert audio_erro.exists()
    excluiu = gerenciador.excluir_registro(id_erro, remover_audio=True)
    assert excluiu is True
    assert gerenciador.obter_registro(id_erro) is None
    assert not audio_erro.exists()

    # Exclusão de ID inexistente retorna False
    assert gerenciador.excluir_registro("id-inexistente-9999", remover_audio=True) is False
