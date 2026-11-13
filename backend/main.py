"""Servidor FastAPI, streaming de eventos em tempo real e inicialização unificada do aplicativo."""

import asyncio
import base64
import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

import config
from active_app import (
    acessibilidade_ativa,
    monitoramento_entrada_ativo,
    obter_aplicativo_ativo,
)
from autostart import (
    autoinicio_esta_instalado,
    desinstalar_autoinicio,
    instalar_autoinicio,
)
from config import (
    ARQUIVO_BANCO_HISTORICO,
    DIRETORIO_AUDIOS,
    atualizar_configuracoes,
    obter_chave_groq,
    obter_configuracoes,
)
from daemon import servico_voz
from history import gerenciador_historico
from protocolo_inicializacao import protocolo_inicializacao
from recorder import obter_status_microfone_macos
from rewriter import reescritor
from transcriber import transcritor

_trava_inicializacao = threading.Lock()
_inicializado = False


def inicializar_servicos() -> Optional[dict[str, Any]]:
    """Executa o protocolo de autoteste e inicia a escuta global apenas uma vez por processo."""
    global _inicializado
    with _trava_inicializacao:
        if _inicializado:
            return protocolo_inicializacao.obter_ultimo_relatorio()

        relatorio = None
        try:
            relatorio = protocolo_inicializacao.executar_autoteste(
                servico_voz_ref=servico_voz
            )
        except Exception as erro:
            print(f"[AVISO] Falha ao executar autoteste de inicialização: {erro}")

        try:
            servico_voz.iniciar_escuta()
        except Exception as erro:
            print(f"[AVISO] Não foi possível iniciar escuta global de atalho: {erro}")

        _inicializado = True
        return relatorio


def encerrar_servicos() -> None:
    """Encerra de forma limpa o escutador global ao finalizar o ciclo de vida."""
    global _inicializado
    with _trava_inicializacao:
        try:
            servico_voz.parar_escuta()
        except Exception:
            pass
        _inicializado = False


@asynccontextmanager
async def ciclo_vida_aplicacao(aplicacao: FastAPI):
    """Gerencia a inicialização idempotente e o desligamento do backend FastAPI."""
    inicializar_servicos()
    try:
        yield
    finally:
        encerrar_servicos()


app = FastAPI(
    title="Voice Transcription Daemon & API",
    description="Backend local para transcrição universal de voz no macOS",
    version="1.0.0",
    lifespan=ciclo_vida_aplicacao,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Modelos de Entrada Pydantic ---


class RequisicaoTranscricao(BaseModel):
    """Carga de entrada para transcrição direta de áudio codificado em base64."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    dados_base64: str = Field(
        alias="dataBase64",
        description="Áudio codificado em base64",
    )
    tipo_mime: str = Field(default="audio/wav", alias="mimeType")
    idioma: Optional[str] = Field(default=None, alias="language")
    tom: Optional[str] = Field(default=None, alias="tone")
    traduzir_para_ingles: Optional[bool] = Field(
        default=None,
        alias="translate_to_english",
    )


class RequisicaoReescrita(BaseModel):
    """Carga de entrada para reescrita isolada de texto."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    texto: str = Field(alias="text")
    tom: Optional[str] = Field(default=None, alias="tone")
    correcao_gramatical: Optional[bool] = Field(
        default=None,
        alias="grammar_correction",
    )
    traduzir_para_ingles: Optional[bool] = Field(
        default=None,
        alias="translate_to_english",
    )


class AtualizacaoConfiguracoes(BaseModel):
    """Carga parcial de atualização aceitando todos os campos de Configuracoes."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    atalho: Optional[str] = Field(default=None, alias="hotkey")
    modo_acionamento: Optional[str] = Field(default=None)
    modo_alternar: Optional[bool] = Field(default=None, alias="toggle_mode")
    limiar_toque_segundos: Optional[float] = Field(
        default=None,
        alias="tap_threshold_seconds",
    )
    idioma: Optional[str] = Field(default=None, alias="language")
    provedor: Optional[str] = Field(default=None, alias="provider")
    provedor_contingencia: Optional[str] = Field(
        default=None,
        alias="fallback_provider",
    )
    modelo_stt_groq: Optional[str] = Field(default=None, alias="groq_stt_model")
    modelo_llm_groq: Optional[str] = Field(default=None, alias="groq_llm_model")
    tom: Optional[str] = Field(default=None, alias="tone")
    tons_disponiveis: Optional[list[str]] = Field(
        default=None,
        alias="available_tones",
    )
    correcao_gramatical: Optional[bool] = Field(
        default=None,
        alias="grammar_correction",
    )
    traduzir_para_ingles: Optional[bool] = Field(
        default=None,
        alias="translate_to_english",
    )
    apps_traducao_automatica: Optional[list[str]] = Field(
        default=None,
        alias="translate_auto_apps",
    )
    adicionar_no_cursor: Optional[bool] = Field(
        default=None,
        alias="append_at_cursor",
    )
    metodo_insercao: Optional[str] = Field(default=None, alias="insertion_method")
    cacar_input_automatico: Optional[bool] = Field(
        default=None,
        alias="auto_hunt_input",
    )
    clicar_para_focar_input: Optional[bool] = Field(
        default=None,
        alias="click_to_focus_input",
    )
    profundidade_busca_ax: Optional[int] = Field(default=None, alias="ax_search_depth")
    backup_fatias_ativo: Optional[bool] = Field(
        default=None,
        alias="chunk_backup_enabled",
    )
    inicio_fatias_segundos: Optional[int] = Field(
        default=None,
        alias="chunk_start_seconds",
    )
    duracao_fatia_segundos: Optional[int] = Field(default=None, alias="chunk_seconds")
    parada_silencio_segundos: Optional[int] = Field(
        default=None,
        alias="silence_auto_stop_seconds",
    )
    endereco_host: Optional[str] = Field(default=None, alias="host")
    porta: Optional[int] = Field(default=None, alias="port")
    iniciar_no_login: Optional[bool] = Field(default=None, alias="auto_start_login")


# --- Funções Auxiliares de Mídia ---


def _extensao_por_tipo_mime(tipo_mime: str) -> str:
    """Resolve a extensão de arquivo adequada para o tipo MIME recebido."""
    texto_mime = (tipo_mime or "").lower()
    if "webm" in texto_mime:
        return ".webm"
    if "ogg" in texto_mime or "opus" in texto_mime:
        return ".ogg"
    if "mp4" in texto_mime or "m4a" in texto_mime:
        return ".m4a"
    return ".wav"


def _tipo_mime_por_arquivo(caminho_audio: Path) -> str:
    """Resolve o media_type HTTP real a partir da extensão do arquivo no disco."""
    extensao = caminho_audio.suffix.lower()
    if extensao in (".ogg", ".oga", ".opus"):
        return "audio/ogg"
    if extensao == ".wav":
        return "audio/wav"
    if extensao == ".webm":
        return "audio/webm"
    if extensao in (".m4a", ".mp4"):
        return "audio/mp4"
    return "audio/wav"


# --- Rotas HTTP ---


@app.get("/health")
def verificar_saude() -> dict[str, Any]:
    """Verifica disponibilidade imediata do servidor HTTP e presença da chave Groq."""
    return {
        "status": "ok",
        "app": "Voice Transcription Daemon & API",
        "version": "1.0.0",
        "groq_key_configured": bool(obter_chave_groq()),
    }


@app.get("/status")
def obter_status_geral() -> dict[str, Any]:
    """Retorna configurações ativas, permissões do macOS, estatísticas e diagnóstico."""
    configuracoes = obter_configuracoes()
    resposta = configuracoes.para_dicionario_api().copy()
    resposta.update(
        {
            "permissions": {
                "accessibility_trusted": acessibilidade_ativa(),
                "microphone_status": obter_status_microfone_macos(),
                "input_monitoring_trusted": monitoramento_entrada_ativo(),
            },
            "autostart_installed": autoinicio_esta_instalado(),
            "frontmost_app": obter_aplicativo_ativo(),
            "stats": gerenciador_historico.obter_estatisticas(),
            "daemon_state": servico_voz.obter_estado_tempo_real(),
            "startup_diagnostics": protocolo_inicializacao.obter_ultimo_relatorio(),
        }
    )
    return resposta


@app.get("/diagnostico")
def obter_diagnostico() -> dict[str, Any]:
    """Retorna o último relatório do protocolo de inicialização ou executa se ausente."""
    relatorio = protocolo_inicializacao.obter_ultimo_relatorio()
    if relatorio is None:
        relatorio = protocolo_inicializacao.executar_autoteste(
            servico_voz_ref=servico_voz
        )
    return relatorio


@app.post("/diagnostico/executar")
def executar_diagnostico_agora() -> dict[str, Any]:
    """Executa uma nova rodada completa do autoteste recarregando subsistemas de áudio."""
    return protocolo_inicializacao.executar_autoteste(
        servico_voz_ref=servico_voz,
        recarregar_audio=True,
    )


@app.get("/eventos")
async def transmitir_eventos_tempo_real(requisicao: Request) -> StreamingResponse:
    """Transmite via Server-Sent Events (SSE) o estado em tempo real do serviço de voz."""

    async def gerador_eventos():
        try:
            while True:
                if await requisicao.is_disconnected():
                    break
                estado = servico_voz.obter_estado_tempo_real()
                carga_json = json.dumps(estado, ensure_ascii=False)
                yield f"data: {carga_json}\n\n"
                em_atividade = bool(
                    estado.get("esta_gravando")
                    or estado.get("esta_processando")
                    or estado.get("estado") in ("listening", "processing")
                )
                await asyncio.sleep(0.12 if em_atividade else 1.0)
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        gerador_eventos(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/history")
def listar_historico(
    requisicao: Request,
    limite: int = Query(default=50, ge=1, le=200, alias="limit"),
    deslocamento: int = Query(default=0, ge=0, alias="offset"),
    status: Optional[str] = Query(default=None),
    busca: Optional[str] = Query(default=None, alias="query"),
) -> dict[str, Any]:
    """Lista os registros de histórico paginados junto às estatísticas globais."""
    parametros_url = requisicao.query_params
    if "limite" in parametros_url and "limit" not in parametros_url:
        try:
            limite = max(1, min(200, int(parametros_url["limite"])))
        except ValueError:
            pass
    if "deslocamento" in parametros_url and "offset" not in parametros_url:
        try:
            deslocamento = max(0, int(parametros_url["deslocamento"]))
        except ValueError:
            pass
    if "busca" in parametros_url and "query" not in parametros_url:
        busca = parametros_url["busca"]

    registros = gerenciador_historico.listar_registros(
        limite=limite,
        deslocamento=deslocamento,
        status=status,
        busca=busca,
    )
    estatisticas = gerenciador_historico.obter_estatisticas()
    return {
        "entries": registros,
        "stats": estatisticas,
        "count": len(registros),
    }


@app.get("/history/{id_registro}")
def obter_item_historico(id_registro: str) -> dict[str, Any]:
    """Retorna os detalhes completos de um registro específico do histórico."""
    registro = gerenciador_historico.obter_registro(id_registro)
    if not registro:
        raise HTTPException(status_code=404, detail="Registro não encontrado")
    return registro


@app.delete("/history/{id_registro}")
def remover_item_historico(id_registro: str) -> dict[str, Any]:
    """Remove o registro do banco SQLite e apaga o respectivo áudio salvo em disco."""
    removido = gerenciador_historico.excluir_registro(
        id_registro,
        remover_audio=True,
    )
    if not removido:
        raise HTTPException(status_code=404, detail="Registro não encontrado")
    return {"ok": True, "id": id_registro, "entry_id": id_registro}


@app.post("/transcribe")
async def transcrever_audio_rota(dados: RequisicaoTranscricao) -> dict[str, Any]:
    """Recebe áudio em base64, salva em DIRETORIO_AUDIOS e executa transcrição + reescrita."""
    conteudo_base64 = (dados.dados_base64 or "").strip()
    if "," in conteudo_base64 and conteudo_base64.lower().startswith("data:"):
        conteudo_base64 = conteudo_base64.split(",", 1)[1]

    try:
        dados_binarios_audio = base64.b64decode(conteudo_base64)
    except Exception as erro:
        raise HTTPException(status_code=400, detail=f"Base64 inválido: {erro}") from erro

    if not dados_binarios_audio:
        raise HTTPException(status_code=400, detail="Conteúdo de áudio vazio")

    diretorio_destino = Path(config.DIRETORIO_AUDIOS)
    diretorio_destino.mkdir(parents=True, exist_ok=True)

    id_registro = str(uuid.uuid4())
    extensao = _extensao_por_tipo_mime(dados.tipo_mime)
    caminho_audio = diretorio_destino / f"{id_registro}{extensao}"
    caminho_audio.write_bytes(dados_binarios_audio)

    configuracoes = obter_configuracoes()
    idioma = dados.idioma or configuracoes.idioma
    tom = dados.tom or configuracoes.tom
    deve_traduzir = (
        configuracoes.traduzir_para_ingles
        if dados.traduzir_para_ingles is None
        else dados.traduzir_para_ingles
    )

    gerenciador_historico.criar_registro_pendente(
        caminho_audio=str(caminho_audio),
        id_registro=id_registro,
        aplicativo_ativo="Painel Web",
        modo="api",
        idioma=idioma,
        provedor=configuracoes.provedor,
        tom=tom,
    )

    resultado_transcricao = await transcritor.transcrever(caminho_audio, idioma=idioma)
    tempo_ms = int(resultado_transcricao.get("took_ms", 0) or 0)

    if not resultado_transcricao.get("ok"):
        mensagem_erro = resultado_transcricao.get("error") or "Falha na transcrição"
        gerenciador_historico.marcar_erro(
            id_registro,
            tempo_ms,
            mensagem_erro,
            provedor=resultado_transcricao.get("provider"),
            caminho_audio=str(caminho_audio),
        )
        return {
            "ok": False,
            "entry_id": id_registro,
            "text_raw": "",
            "text_final": "",
            "provider": resultado_transcricao.get("provider", "none"),
            "took_ms": tempo_ms,
            "error": mensagem_erro,
        }

    texto_bruto = (resultado_transcricao.get("text") or "").strip()
    if not texto_bruto:
        gerenciador_historico.marcar_vazio(
            id_registro,
            tempo_ms,
            caminho_audio=str(caminho_audio),
        )
        return {
            "ok": True,
            "entry_id": id_registro,
            "text_raw": "",
            "text_final": "",
            "tone": tom,
            "translated": False,
            "provider": resultado_transcricao.get("provider"),
            "took_ms": tempo_ms,
            "error": None,
        }

    resultado_reescrita = await reescritor.reescrever(
        texto_bruto=texto_bruto,
        tom=tom,
        correcao_gramatical=configuracoes.correcao_gramatical,
        traduzir_para_ingles=deve_traduzir,
    )
    texto_final = (resultado_reescrita.get("text") or texto_bruto).strip()

    gerenciador_historico.marcar_enviado(
        id_registro=id_registro,
        duracao_ms=tempo_ms,
        texto_bruto=texto_bruto,
        texto_final=texto_final,
        tom=tom,
        gramatica_corrigida=bool(resultado_reescrita.get("grammar_fixed", False)),
        provedor=resultado_transcricao.get("provider"),
        caminho_audio=str(caminho_audio),
    )

    return {
        "ok": True,
        "entry_id": id_registro,
        "text_raw": texto_bruto,
        "text_final": texto_final,
        "tone": tom,
        "translated": bool(resultado_reescrita.get("translated", False)),
        "provider": resultado_transcricao.get("provider"),
        "took_ms": tempo_ms,
        "error": None,
    }


@app.post("/rewrite")
async def reescrever_texto_rota(dados: RequisicaoReescrita) -> dict[str, Any]:
    """Executa reescrita isolada de um texto bruto informado."""
    return await reescritor.reescrever(
        texto_bruto=dados.texto,
        tom=dados.tom,
        correcao_gramatical=dados.correcao_gramatical,
        traduzir_para_ingles=dados.traduzir_para_ingles,
    )


@app.post("/retry/{id_registro}")
async def repetir_transcricao_rota(id_registro: str) -> dict[str, Any]:
    """Reprocessa a transcrição de um registro existente usando o arquivo de áudio salvo."""
    registro = gerenciador_historico.obter_registro(id_registro)
    if not registro:
        raise HTTPException(status_code=404, detail="Registro não encontrado")

    caminho_audio = Path(registro.get("audio_path") or "")
    if not caminho_audio.exists() or caminho_audio.stat().st_size == 0:
        raise HTTPException(
            status_code=400,
            detail="Arquivo de áudio original não encontrado em disco para reprocessamento",
        )

    configuracoes = obter_configuracoes()
    idioma = registro.get("language") or configuracoes.idioma
    tom = registro.get("tone") or configuracoes.tom

    resultado_transcricao = await transcritor.transcrever(caminho_audio, idioma=idioma)
    tempo_ms = int(resultado_transcricao.get("took_ms", 0) or 0)
    if not resultado_transcricao.get("ok"):
        mensagem_erro = resultado_transcricao.get("error") or "Falha ao reprocessar transcrição"
        gerenciador_historico.marcar_erro(
            id_registro,
            tempo_ms,
            mensagem_erro,
            provedor=resultado_transcricao.get("provider"),
        )
        return {"ok": False, "error": mensagem_erro}

    texto_bruto = (resultado_transcricao.get("text") or "").strip()
    resultado_reescrita = await reescritor.reescrever(
        texto_bruto=texto_bruto,
        tom=tom,
        correcao_gramatical=configuracoes.correcao_gramatical,
        traduzir_para_ingles=configuracoes.traduzir_para_ingles,
    )
    texto_final = (resultado_reescrita.get("text") or texto_bruto).strip()

    gerenciador_historico.marcar_enviado(
        id_registro=id_registro,
        duracao_ms=tempo_ms,
        texto_bruto=texto_bruto,
        texto_final=texto_final,
        tom=tom,
        gramatica_corrigida=bool(resultado_reescrita.get("grammar_fixed", False)),
        provedor=resultado_transcricao.get("provider"),
        caminho_audio=str(caminho_audio),
    )

    return {
        "ok": True,
        "entry_id": id_registro,
        "text_raw": texto_bruto,
        "text_final": texto_final,
        "provider": resultado_transcricao.get("provider"),
    }


@app.post("/settings")
def atualizar_configuracoes_rota(dados: AtualizacaoConfiguracoes) -> dict[str, Any]:
    """Atualiza as preferências persistentes e sincroniza o agente de login se solicitado."""
    atualizacoes = {
        chave: valor
        for chave, valor in dados.model_dump(exclude_unset=True).items()
        if valor is not None
    }
    atualizado = atualizar_configuracoes(atualizacoes)

    if dados.iniciar_no_login is not None:
        if dados.iniciar_no_login:
            instalar_autoinicio()
        else:
            desinstalar_autoinicio()

    return atualizado.para_dicionario_api()


@app.get("/audio/{id_registro}")
def servir_arquivo_audio(id_registro: str) -> FileResponse:
    """Serve o arquivo de áudio com o media_type correspondente à extensão real no disco."""
    registro = gerenciador_historico.obter_registro(id_registro)
    if not registro:
        raise HTTPException(
            status_code=404,
            detail="Registro não encontrado no histórico",
        )

    caminho_str = registro.get("audio_path")
    if not caminho_str:
        raise HTTPException(status_code=404, detail="Caminho de áudio não registrado")

    caminho_audio = Path(caminho_str)
    if not caminho_audio.exists() or caminho_audio.stat().st_size == 0:
        raise HTTPException(
            status_code=404,
            detail="Arquivo de áudio não encontrado no disco",
        )

    tipo_mime = _tipo_mime_por_arquivo(caminho_audio)
    extensao = caminho_audio.suffix.lower() or ".wav"
    return FileResponse(
        str(caminho_audio),
        media_type=tipo_mime,
        filename=f"{id_registro}{extensao}",
    )


# Monta os arquivos estáticos do painel web na raiz
DIRETORIO_FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
DIRETORIO_FRONTEND.mkdir(parents=True, exist_ok=True)
app.mount(
    "/",
    StaticFiles(directory=str(DIRETORIO_FRONTEND), html=True),
    name="frontend",
)


def encerrar_porta_zumbi(porta: int) -> None:
    """Encerra qualquer processo antigo preso na porta HTTP antes de subir o servidor."""
    try:
        resultado = subprocess.run(
            ["lsof", "-ti", f":{porta}"],
            capture_output=True,
            text=True,
            check=False,
        )
        identificadores_processo = resultado.stdout.strip().split()
        meu_id_processo = str(os.getpid())
        for id_processo_texto in identificadores_processo:
            if id_processo_texto and id_processo_texto != meu_id_processo:
                try:
                    os.kill(int(id_processo_texto), signal.SIGKILL)
                except Exception:
                    pass
    except Exception:
        pass


def iniciar_servidor() -> None:
    """Inicia o servidor HTTP Uvicorn na porta configurada."""
    configuracoes = obter_configuracoes()
    encerrar_porta_zumbi(configuracoes.porta)
    uvicorn.run(
        app,
        host=configuracoes.endereco_host,
        port=configuracoes.porta,
        log_level="warning",
    )


def iniciar_aplicativo() -> None:
    """Inicia serviços, servidor HTTP em segundo plano e aplicativo nativo na barra de menus."""
    configuracoes = obter_configuracoes()
    encerrar_porta_zumbi(configuracoes.porta)

    inicializar_servicos()

    tarefa_servidor = threading.Thread(target=iniciar_servidor, daemon=True)
    tarefa_servidor.start()
    time.sleep(0.3)

    from status_icon import criar_app_bandeja

    app_bandeja = criar_app_bandeja(servico_ref=servico_voz)
    servico_voz.registrar_observador_status(app_bandeja.atualizar_status)
    app_bandeja.run()


if __name__ == "__main__":
    if "--headless" in sys.argv or "--server-only" in sys.argv:
        iniciar_servidor()
    else:
        iniciar_aplicativo()
