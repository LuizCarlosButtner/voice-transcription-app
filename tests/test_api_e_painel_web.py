"""Testes de integração das rotas FastAPI, SSE e entrega do Painel Web estático."""

import asyncio
import base64
import json
import wave
from pathlib import Path
from typing import Optional

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def cliente_painel(
    monkeypatch: pytest.MonkeyPatch, ambiente_isolado: dict[str, Path]
):
    """Fornece TestClient isolado sem iniciar hardware real de áudio ou teclado."""
    _ = ambiente_isolado
    import active_app
    import autostart
    import daemon
    import main
    import protocolo_inicializacao as mod_proto
    import recorder

    class EscutadorAtivoSimulado:
        """Simula um keyboard.Listener vivo para que servico_voz.escuta_ativa seja True."""

        def __init__(self):
            self.vivo = True
            self.is_alive = lambda: self.vivo
            self.stop = lambda: setattr(self, "vivo", False)

    escutador_sim = EscutadorAtivoSimulado()

    def iniciar_escuta_simulado(*_a, **_kw) -> bool:
        escutador_sim.vivo = True
        daemon.servico_voz._escutador = escutador_sim
        return True

    def parar_escuta_simulado(*_a, **_kw) -> None:
        escutador_sim.vivo = False

    monkeypatch.setattr(daemon.servico_voz, "iniciar_escuta", iniciar_escuta_simulado)
    monkeypatch.setattr(daemon.servico_voz, "parar_escuta", parar_escuta_simulado)
    monkeypatch.setattr(daemon.servico_voz, "_escutador", escutador_sim, raising=False)

    monkeypatch.setattr(recorder.gravador, "recarregar_dispositivos", lambda: True)
    monkeypatch.setattr(
        recorder.gravador,
        "sondar_microfone",
        lambda: {
            "ok": True,
            "dispositivo_indice": 0,
            "dispositivo_nome": "Microfone Integrado Simulado",
            "taxa_amostragem": 16000,
            "detalhe": "Sondagem simulada OK",
        },
    )

    estado_microfone_ok = lambda: "Authorized"
    permissao_ok = lambda *_a, **_kw: True
    app_foco_ok = lambda: {
        "name": "EditorSimulado",
        "bundle_id": "br.teste.Editor",
        "pid": 4321,
    }

    for mod in (recorder, main, mod_proto):
        monkeypatch.setattr(
            mod, "obter_status_microfone_macos", estado_microfone_ok, raising=False
        )
    for mod in (active_app, main, mod_proto):
        monkeypatch.setattr(mod, "acessibilidade_ativa", permissao_ok, raising=False)
        monkeypatch.setattr(
            mod, "monitoramento_entrada_ativo", permissao_ok, raising=False
        )
    for mod in (active_app, main):
        monkeypatch.setattr(mod, "obter_aplicativo_ativo", app_foco_ok, raising=False)

    if hasattr(autostart, "subprocess"):
        monkeypatch.setattr(
            autostart.subprocess,
            "run",
            lambda *_a, **_kw: None,
            raising=False,
        )

    monkeypatch.setattr(main, "_inicializado", False, raising=False)

    with TestClient(main.app) as cliente:
        yield cliente


def test_rotas_saude_status_e_diagnostico(cliente_painel: TestClient):
    """Valida GET /health, GET /status, GET /diagnostico e POST /diagnostico/executar."""
    resp_saude = cliente_painel.get("/health")
    assert resp_saude.status_code == 200
    dados_saude = resp_saude.json()
    assert dados_saude["status"] == "ok"
    assert dados_saude["groq_key_configured"] is True

    resp_status = cliente_painel.get("/status")
    assert resp_status.status_code == 200
    dados_status = resp_status.json()
    for chave_obrigatoria in (
        "active_provider",
        "modo_acionamento",
        "available_tones",
        "silence_auto_stop_seconds",
        "permissions",
        "autostart_installed",
        "frontmost_app",
        "stats",
        "daemon_state",
        "startup_diagnostics",
    ):
        assert chave_obrigatoria in dados_status, f"Chave ausente em /status: {chave_obrigatoria}"

    permissoes = dados_status["permissions"]
    assert "accessibility_trusted" in permissoes
    assert "microphone_status" in permissoes
    assert "input_monitoring_trusted" in permissoes

    resp_diag = cliente_painel.get("/diagnostico")
    assert resp_diag.status_code == 200
    dados_diag = resp_diag.json()
    assert "etapas" in dados_diag
    assert {
        "armazenamento_banco",
        "chaves_provedores",
        "permissoes_macos",
        "subsistema_audio",
        "escutador_atalho",
    }.issubset(set(dados_diag["etapas"].keys()))

    resp_exec_diag = cliente_painel.post("/diagnostico/executar")
    assert resp_exec_diag.status_code == 200
    dados_exec = resp_exec_diag.json()
    assert dados_exec["ok"] is True
    assert "duracao_ms" in dados_exec


def test_rota_configuracoes_modos_acionamento_silencio_e_autoinicio(
    cliente_painel: TestClient, ambiente_isolado: dict[str, Path]
):
    """Testa POST /settings sincronizando modo_acionamento, silence_auto_stop_seconds e plist."""
    resp_segurar = cliente_painel.post(
        "/settings",
        json={
            "modo_acionamento": "segurar",
            "silence_auto_stop_seconds": 105,
            "tone": "semiformal",
            "auto_hunt_input": False,
            "click_to_focus_input": False,
            "auto_start_login": True,
        },
    )
    assert resp_segurar.status_code == 200
    corpo_segurar = resp_segurar.json()
    assert corpo_segurar["modo_acionamento"] == "segurar"
    assert corpo_segurar["toggle_mode"] is False
    assert corpo_segurar["silence_auto_stop_seconds"] == 105
    assert corpo_segurar["tone"] == "semiformal"
    assert corpo_segurar["auto_hunt_input"] is False
    assert corpo_segurar["click_to_focus_input"] is False
    assert ambiente_isolado["arquivo_plist"].exists() is True

    resp_alternar = cliente_painel.post(
        "/settings",
        json={
            "modo_acionamento": "alternar",
            "auto_start_login": False,
        },
    )
    assert resp_alternar.status_code == 200
    corpo_alternar = resp_alternar.json()
    assert corpo_alternar["modo_acionamento"] == "alternar"
    assert corpo_alternar["toggle_mode"] is True
    assert ambiente_isolado["arquivo_plist"].exists() is False


def test_rotas_historico_exclusao_e_audio_ogg_e_wav(
    cliente_painel: TestClient,
    ambiente_isolado: dict[str, Path],
    onda_senoidal_fala,
):
    """Valida GET /history, DELETE /history/{id} e GET /audio/{id} tanto em OGG quanto WAV."""
    import history
    import recorder

    diretorio_audios = ambiente_isolado["diretorio_audios"]

    # 1. Cria gravação OGG
    caminho_ogg = recorder.salvar_arquivo_audio(
        onda_senoidal_fala, diretorio_audios / "item_teste_ogg.ogg"
    )
    id_ogg = history.gerenciador_historico.criar_registro_pendente(
        caminho_audio=str(caminho_ogg),
        id_registro="reg-api-ogg-01",
        aplicativo_ativo="PainelWeb",
        tom="verbatim",
    )

    # 2. Cria gravação WAV explícita
    caminho_wav = diretorio_audios / "item_teste_wav.wav"
    with wave.open(str(caminho_wav), "wb") as escritor_wav:
        escritor_wav.setnchannels(1)
        escritor_wav.setsampwidth(2)
        escritor_wav.setframerate(16000)
        escritor_wav.writeframes(onda_senoidal_fala.tobytes())

    id_wav = history.gerenciador_historico.criar_registro_pendente(
        caminho_audio=str(caminho_wav),
        id_registro="reg-api-wav-02",
        aplicativo_ativo="PainelWeb",
        tom="formal",
    )

    resp_lista = cliente_painel.get("/history?limit=10")
    assert resp_lista.status_code == 200
    dados_lista = resp_lista.json()
    assert dados_lista["count"] == 2
    assert len(dados_lista["entries"]) == 2

    # Verifica MIME correto para OGG e WAV
    resp_audio_ogg = cliente_painel.get(f"/audio/{id_ogg}")
    assert resp_audio_ogg.status_code == 200
    assert "audio/ogg" in resp_audio_ogg.headers["content-type"]
    assert len(resp_audio_ogg.content) > 100

    resp_audio_wav = cliente_painel.get(f"/audio/{id_wav}")
    assert resp_audio_wav.status_code == 200
    assert "audio/wav" in resp_audio_wav.headers["content-type"]
    assert len(resp_audio_wav.content) > 100

    resp_audio_404 = cliente_painel.get("/audio/registro-inexistente-999")
    assert resp_audio_404.status_code == 404

    # Exclui registro OGG via DELETE /history/{id} e confirma remoção física do arquivo
    resp_exclusao = cliente_painel.delete(f"/history/{id_ogg}")
    assert resp_exclusao.status_code == 200
    assert not caminho_ogg.exists()

    resp_detalhe_apagado = cliente_painel.get(f"/history/{id_ogg}")
    assert resp_detalhe_apagado.status_code == 404


def test_rota_transcricao_com_duble_transcritor_e_reescritor(
    cliente_painel: TestClient,
    ambiente_isolado: dict[str, Path],
    onda_senoidal_fala,
    monkeypatch: pytest.MonkeyPatch,
):
    """Valida POST /transcribe com dublês de STT e LLM, persistindo áudio em DIRETORIO_AUDIOS."""
    import recorder
    import rewriter
    import transcriber

    caminho_origem = recorder.salvar_arquivo_audio(
        onda_senoidal_fala, ambiente_isolado["diretorio_audios"] / "entrada_api.ogg"
    )
    conteudo_base64 = base64.b64encode(caminho_origem.read_bytes()).decode("ascii")

    async def stt_falso(caminho_audio: Path, idioma: Optional[str] = None) -> dict:
        assert caminho_audio.exists()
        assert caminho_audio.suffix == ".ogg"
        assert idioma == "pt"
        return {
            "ok": True,
            "text": "gravacao enviada pelo navegador",
            "provider": "groq",
            "took_ms": 110,
            "error": None,
        }

    async def llm_falso(
        texto_bruto: str,
        tom: Optional[str] = None,
        correcao_gramatical: Optional[bool] = None,
        traduzir_para_ingles: Optional[bool] = None,
    ) -> dict:
        _ = (correcao_gramatical, traduzir_para_ingles)
        assert texto_bruto == "gravacao enviada pelo navegador"
        return {
            "ok": True,
            "text": "Gravação enviada pelo navegador.",
            "tone": tom or "colloquial",
            "grammar_fixed": True,
            "translated": False,
            "took_ms": 65,
            "fallback_used": False,
            "warning": None,
        }

    monkeypatch.setattr(transcriber.transcritor, "transcrever", stt_falso)
    monkeypatch.setattr(rewriter.reescritor, "reescrever", llm_falso)

    resp_transcricao = cliente_painel.post(
        "/transcribe",
        json={
            "dataBase64": conteudo_base64,
            "mimeType": "audio/ogg; codecs=opus",
            "language": "pt",
            "tone": "colloquial",
        },
    )
    assert resp_transcricao.status_code == 200
    dados_tr = resp_transcricao.json()
    assert dados_tr["ok"] is True
    assert dados_tr["text_raw"] == "gravacao enviada pelo navegador"
    assert dados_tr["text_final"] == "Gravação enviada pelo navegador."
    id_criado = dados_tr["entry_id"]

    # Confirma que o áudio salvo continua acessível para o reprodutor web
    resp_reprodutor = cliente_painel.get(f"/audio/{id_criado}")
    assert resp_reprodutor.status_code == 200
    assert "audio/ogg" in resp_reprodutor.headers["content-type"]


def test_rotas_reescrita_retentativa_e_fluxo_eventos_sse(
    cliente_painel: TestClient,
    ambiente_isolado: dict[str, Path],
    onda_senoidal_fala,
    monkeypatch: pytest.MonkeyPatch,
):
    """Valida GET /eventos (SSE), POST /rewrite e POST /retry/{id} (sucesso e 404)."""
    import daemon
    import history
    import main
    import recorder
    import rewriter
    import transcriber

    # 1. Testa GET /eventos (SSE text/event-stream) sem travar usando Request simulada
    respostas_desconexao = iter([False, True])

    class RequisicaoSseSimulada:
        def __init__(self):
            self.is_disconnected = self._verificar_desconexao

        async def _verificar_desconexao(self) -> bool:
            return next(respostas_desconexao, True)

    async def dormir_instantaneo(_segundos: float) -> None:
        return None

    monkeypatch.setattr(main.asyncio, "sleep", dormir_instantaneo)
    monkeypatch.setattr(
        daemon.servico_voz,
        "obter_estado_tempo_real",
        lambda: {
            "estado": "listening",
            "detalhe": "Gravando teste SSE",
            "esta_gravando": True,
            "esta_processando": False,
            "modo_atual": "segurando",
            "nivel_voz": 0.77,
            "escuta_ativa": True,
        },
    )

    async def consumir_um_quadro_sse() -> tuple[str, list[str]]:
        resposta_stream = await main.transmitir_eventos_tempo_real(RequisicaoSseSimulada())
        blocos: list[str] = []
        async for fragmento in resposta_stream.body_iterator:
            texto_frag = (
                fragmento.decode("utf-8")
                if isinstance(fragmento, bytes)
                else str(fragmento)
            )
            blocos.append(texto_frag)
        return resposta_stream.media_type, blocos

    tipo_midia_sse, quadros_sse = asyncio.run(consumir_um_quadro_sse())
    assert tipo_midia_sse == "text/event-stream"
    assert len(quadros_sse) == 1
    assert quadros_sse[0].startswith("data: ")
    assert quadros_sse[0].endswith("\n\n")
    carga_evento = json.loads(quadros_sse[0][len("data: ") :].strip())
    assert carga_evento["estado"] == "listening"
    assert carga_evento["esta_gravando"] is True
    assert carga_evento["nivel_voz"] == 0.77

    # 2. Testa POST /rewrite com dublê em reescritor.reescrever
    async def reescrever_duble(
        texto_bruto: str,
        tom: Optional[str] = None,
        correcao_gramatical: Optional[bool] = None,
        traduzir_para_ingles: Optional[bool] = None,
    ) -> dict:
        return {
            "ok": True,
            "text": f"[{tom}] {texto_bruto.capitalize()}.",
            "tone": tom or "formal",
            "grammar_fixed": bool(correcao_gramatical),
            "translated": bool(traduzir_para_ingles),
            "took_ms": 48,
            "fallback_used": False,
            "warning": None,
        }

    monkeypatch.setattr(rewriter.reescritor, "reescrever", reescrever_duble)

    resp_reescrita = cliente_painel.post(
        "/rewrite",
        json={
            "text": "precisamos alinhar a entrega hoje",
            "tone": "formal",
            "grammar_correction": True,
            "translate_to_english": False,
        },
    )
    assert resp_reescrita.status_code == 200
    dados_rw = resp_reescrita.json()
    assert dados_rw["ok"] is True
    assert dados_rw["tone"] == "formal"
    assert dados_rw["grammar_fixed"] is True
    assert "Precisamos alinhar a entrega hoje" in dados_rw["text"]

    # 3. Testa POST /retry/{id} (404 para ID inexistente e 200 para áudio existente)
    resp_retentativa_404 = cliente_painel.post("/retry/id-nao-existente-404")
    assert resp_retentativa_404.status_code == 404

    caminho_audio_falho = recorder.salvar_arquivo_audio(
        onda_senoidal_fala, ambiente_isolado["diretorio_audios"] / "falha_rede.ogg"
    )
    id_para_repetir = history.gerenciador_historico.criar_registro_pendente(
        caminho_audio=str(caminho_audio_falho),
        id_registro="reg-repetir-01",
        aplicativo_ativo="Notas",
        idioma="pt",
        tom="formal",
    )
    history.gerenciador_historico.marcar_erro(
        id_para_repetir, 500, "Erro temporário de conexão"
    )

    async def transcrever_retentativa(caminho_audio: Path, idioma: Optional[str] = None) -> dict:
        _ = idioma
        assert caminho_audio == caminho_audio_falho
        return {
            "ok": True,
            "text": "audio recuperado na retentativa",
            "provider": "groq",
            "took_ms": 95,
            "error": None,
        }

    monkeypatch.setattr(transcriber.transcritor, "transcrever", transcrever_retentativa)

    resp_retentativa_ok = cliente_painel.post(f"/retry/{id_para_repetir}")
    assert resp_retentativa_ok.status_code == 200
    dados_retentativa = resp_retentativa_ok.json()
    assert dados_retentativa["ok"] is True
    assert dados_retentativa["entry_id"] == id_para_repetir
    assert dados_retentativa["text_raw"] == "audio recuperado na retentativa"

    registro_atualizado = history.gerenciador_historico.obter_registro(id_para_repetir)
    assert registro_atualizado is not None
    assert registro_atualizado["status"] == "sent"


def test_arquivos_estaticos_painel_web_e_elementos_essenciais(
    cliente_painel: TestClient,
):
    """Confirma que /, /css/style.css e /js/app.js são servidos com os IDs essenciais."""
    resp_html = cliente_painel.get("/")
    assert resp_html.status_code == 200
    assert "text/html" in resp_html.headers.get("content-type", "")
    conteudo_html = resp_html.text
    assert "btn-hero-mic" in conteudo_html
    assert "tones-selector-grid" in conteudo_html
    assert "visualizer-canvas" in conteudo_html

    resp_css = cliente_painel.get("/css/style.css")
    assert resp_css.status_code == 200
    assert "css" in resp_css.headers.get("content-type", "")
    assert len(resp_css.text) > 100

    resp_js = cliente_painel.get("/js/app.js")
    assert resp_js.status_code == 200
    assert "javascript" in resp_js.headers.get("content-type", "")
    assert len(resp_js.text) > 100
