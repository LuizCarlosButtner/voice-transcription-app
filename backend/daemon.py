import asyncio
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

from pynput import keyboard

import config as modulo_config
from active_app import (
    encontrar_editavel_focado,
    obter_aplicativo_ativo,
    possui_campo_texto_focado,
)
from config import DIRETORIO_AUDIOS, obter_configuracoes
from history import gerenciador_historico
from input_hunter import cacar_input_visivel, focar_elemento
from inserter import inseridor
from prompt_modal import exibir_alerta_selecao_campo
from recorder import gravador
from rewriter import reescritor
from transcriber import transcritor

_DIRETORIO_AUDIOS_INICIAL = DIRETORIO_AUDIOS


def _obter_diretorio_audios() -> Path:
    """Obtém dinamicamente o diretório de áudios respeitando redirecionamentos em testes."""
    if DIRETORIO_AUDIOS != _DIRETORIO_AUDIOS_INICIAL:
        return DIRETORIO_AUDIOS
    return modulo_config.DIRETORIO_AUDIOS


class ServicoVoz:
    """
    Serviço principal de captura por atalho global, máquina de estados de acionamento
    (`segurar`, `alternar`, `hibrido`), transcrição, ajuste de tom e inserção no cursor.
    """

    def __init__(
        self,
        ao_mudar_status: Optional[Callable[[str, Optional[str]], None]] = None,
    ) -> None:
        self.ao_mudar_status = ao_mudar_status
        self._observadores_status: list[Callable[[str, Optional[str]], None]] = []

        self._id_registro_atual: Optional[str] = None
        self._caminho_audio_atual: Optional[Path] = None

        self._esta_gravando = False
        self._esta_processando = False
        self._modo_atual = "ocioso"  # "ocioso" | "segurando" | "alternado"
        self._estado_atual = "idle"
        self._detalhe_atual = "Pronto"

        self._tecla_atalho_pressionada = False
        self._ignorar_proxima_soltura = False
        self._inicio_pressionamento = 0.0
        self._info_app_ativo: dict = {}
        self._papel_focado: Optional[str] = None
        self._tinha_foco_no_inicio = False

        self._trava = threading.RLock()
        self._trava_escuta = threading.RLock()
        self._laco_eventos: Optional[asyncio.AbstractEventLoop] = None
        self._escutador: Optional[keyboard.Listener] = None
        self._escuta_desejada = False
        self._evento_parar_supervisao = threading.Event()
        self._thread_supervisao_escuta: Optional[threading.Thread] = None

    @property
    def esta_gravando(self) -> bool:
        return self._esta_gravando

    @property
    def esta_processando(self) -> bool:
        return self._esta_processando

    @property
    def modo_atual(self) -> str:
        return self._modo_atual

    @property
    def escuta_ativa(self) -> bool:
        with self._trava_escuta:
            return self._escutador is not None and bool(self._escutador.is_alive())

    def registrar_observador_status(
        self, observador: Callable[[str, Optional[str]], None]
    ) -> None:
        """Registra um observador adicional para receber mudanças de status do serviço."""
        if observador is not None and observador not in self._observadores_status:
            self._observadores_status.append(observador)

    def _definir_status(self, status: str, detalhe: Optional[str] = None) -> None:
        """Notifica todos os observadores e o callback principal sobre mudança de status."""
        self._estado_atual = status
        self._detalhe_atual = detalhe or ""

        if self.ao_mudar_status is not None:
            try:
                self.ao_mudar_status(status, detalhe)
            except Exception:
                pass

        for observador in list(self._observadores_status):
            if observador is self.ao_mudar_status:
                continue
            try:
                observador(status, detalhe)
            except Exception:
                pass

    def _eh_tecla_atalho(self, tecla) -> bool:
        """Verifica se a tecla recebida corresponde ao modificador de atalho configurado."""
        configuracoes = obter_configuracoes()
        nome_atalho = (configuracoes.atalho or "Alt").strip().lower()

        if nome_atalho in ("alt", "option"):
            if tecla in (
                keyboard.Key.alt,
                getattr(keyboard.Key, "alt_l", keyboard.Key.alt),
                getattr(keyboard.Key, "alt_r", keyboard.Key.alt),
            ):
                return True
            nome_tecla = getattr(tecla, "name", "")
            if nome_tecla and "alt" in nome_tecla:
                return True
            if hasattr(tecla, "vk") and tecla.vk in (58, 61):
                return True
            return False

        if nome_atalho in ("ctrl", "control"):
            if tecla in (
                keyboard.Key.ctrl,
                getattr(keyboard.Key, "ctrl_l", keyboard.Key.ctrl),
                getattr(keyboard.Key, "ctrl_r", keyboard.Key.ctrl),
            ):
                return True
            nome_tecla = getattr(tecla, "name", "")
            if nome_tecla and "ctrl" in nome_tecla:
                return True
            if hasattr(tecla, "vk") and tecla.vk in (59, 62):
                return True
            return False

        if nome_atalho in ("cmd", "command"):
            if tecla in (
                keyboard.Key.cmd,
                getattr(keyboard.Key, "cmd_l", keyboard.Key.cmd),
                getattr(keyboard.Key, "cmd_r", keyboard.Key.cmd),
            ):
                return True
            nome_tecla = getattr(tecla, "name", "")
            if nome_tecla and "cmd" in nome_tecla:
                return True
            if hasattr(tecla, "vk") and tecla.vk in (55, 54):
                return True
            return False

        if nome_atalho == "shift":
            if tecla in (
                keyboard.Key.shift,
                getattr(keyboard.Key, "shift_l", keyboard.Key.shift),
                getattr(keyboard.Key, "shift_r", keyboard.Key.shift),
            ):
                return True
            nome_tecla = getattr(tecla, "name", "")
            if nome_tecla and "shift" in nome_tecla:
                return True
            if hasattr(tecla, "vk") and tecla.vk in (56, 60):
                return True
            return False

        return False

    def ao_pressionar(self, tecla) -> None:
        """Trata o evento de pressionamento de tecla respeitando `modo_acionamento` e anti-repetição."""
        if tecla == keyboard.Key.esc:
            self.cancelar_gravacao()
            return

        if not self._eh_tecla_atalho(tecla):
            return

        with self._trava:
            # Ignora eventos repetidos do sistema operacional enquanto a tecla permanece segurada
            if self._tecla_atalho_pressionada:
                return

            self._tecla_atalho_pressionada = True

            if self._esta_processando:
                return

            configuracoes = obter_configuracoes()
            modo_configurado = configuracoes.modo_acionamento

            if modo_configurado == "segurar":
                if self._esta_gravando and self._modo_atual == "alternado":
                    self._modo_atual = "ocioso"
                    self._executar_parada()
                    return
                if not self._esta_gravando:
                    self._modo_atual = "segurando"
                    self._inicio_pressionamento = time.time()
                    self._ignorar_proxima_soltura = False
                    self._executar_inicio(modo_historico="segurar")
                return

            if modo_configurado == "alternar":
                if not self._esta_gravando:
                    self._modo_atual = "alternado"
                    self._inicio_pressionamento = time.time()
                    self._ignorar_proxima_soltura = True
                    self._executar_inicio(modo_historico="alternar")
                else:
                    self._modo_atual = "ocioso"
                    self._ignorar_proxima_soltura = True
                    self._executar_parada()
                return

            # Modo "hibrido" (padrão)
            if self._esta_gravando and self._modo_atual == "alternado":
                self._modo_atual = "ocioso"
                self._ignorar_proxima_soltura = True
                self._executar_parada()
                return

            if not self._esta_gravando:
                self._modo_atual = "segurando"
                self._inicio_pressionamento = time.time()
                self._ignorar_proxima_soltura = False
                self._executar_inicio(modo_historico="hibrido")

    def ao_soltar(self, tecla) -> None:
        """Trata o evento de soltura da tecla de atalho conforme o modo ativo."""
        if not self._eh_tecla_atalho(tecla):
            return

        with self._trava:
            self._tecla_atalho_pressionada = False

            if self._ignorar_proxima_soltura:
                self._ignorar_proxima_soltura = False
                return

            if not self._esta_gravando:
                return

            configuracoes = obter_configuracoes()
            modo_configurado = configuracoes.modo_acionamento

            if modo_configurado == "segurar":
                # Modo segurar estrito: SEMPRE para e envia ao soltar, mesmo abaixo de 0.35s
                self._modo_atual = "ocioso"
                self._executar_parada()
                return

            if modo_configurado == "alternar":
                # No modo alternar puro, soltar a tecla nunca encerra a gravação
                return

            # Modo "hibrido"
            if self._modo_atual == "segurando":
                duracao_pressionada = time.time() - self._inicio_pressionamento
                limiar_toque = configuracoes.limiar_toque_segundos
                if duracao_pressionada >= limiar_toque:
                    self._modo_atual = "ocioso"
                    self._executar_parada()
                else:
                    self._modo_atual = "alternado"
                    self._definir_status(
                        "listening",
                        "Gravando contínuo (toque novamente para enviar)...",
                    )

    def iniciar_gravacao_manual(self) -> bool:
        """Inicia uma gravação acionada manualmente pela interface ou menu."""
        with self._trava:
            if self._esta_gravando or self._esta_processando:
                return False
            self._modo_atual = "alternado"
            self._tecla_atalho_pressionada = False
            self._ignorar_proxima_soltura = False
            self._inicio_pressionamento = time.time()
            self._executar_inicio(modo_historico="alternar")
            return self._esta_gravando

    def parar_gravacao_manual(self) -> bool:
        """Encerra uma gravação ativa acionada manualmente."""
        with self._trava:
            if not self._esta_gravando:
                return False
            self._modo_atual = "ocioso"
            self._tecla_atalho_pressionada = False
            self._ignorar_proxima_soltura = False
            self._executar_parada()
            return True

    def _executar_inicio(self, modo_historico: str = "hibrido") -> None:
        configuracoes = obter_configuracoes()

        possui_foco, _nome_app, papel = possui_campo_texto_focado()
        self._tinha_foco_no_inicio = possui_foco

        self._esta_gravando = True
        self._info_app_ativo = obter_aplicativo_ativo() or {}
        self._papel_focado = papel

        id_registro = str(uuid.uuid4())
        self._id_registro_atual = id_registro
        diretorio_audios = _obter_diretorio_audios()
        diretorio_audios.mkdir(parents=True, exist_ok=True)
        caminho_audio = diretorio_audios / f"{id_registro}.ogg"
        self._caminho_audio_atual = caminho_audio

        gerenciador_historico.criar_registro_pendente(
            caminho_audio=str(caminho_audio),
            id_registro=id_registro,
            aplicativo_ativo=self._info_app_ativo.get("name"),
            elemento_focado=papel,
            modo=modo_historico,
            idioma=configuracoes.idioma,
            provedor=configuracoes.provedor,
            tom=configuracoes.tom,
        )

        iniciou_ok, mensagem = gravador.iniciar(id_sessao=id_registro)
        if not iniciou_ok:
            self._esta_gravando = False
            self._modo_atual = "ocioso"
            gerenciador_historico.marcar_erro(id_registro, 0, mensagem)
            self._definir_status("error", mensagem)
            return

        nome_app_destino = self._info_app_ativo.get("name") or "aplicativo ativo"
        self._definir_status("listening", f"Gravando para {nome_app_destino}...")

    def _executar_parada(self) -> None:
        self._esta_gravando = False
        self._modo_atual = "ocioso"
        self._tecla_atalho_pressionada = False
        self._ignorar_proxima_soltura = False

        id_registro = self._id_registro_atual
        caminho_audio = self._caminho_audio_atual

        if not id_registro or not caminho_audio:
            self._definir_status("idle", "Pronto")
            return

        self._esta_processando = True
        self._definir_status("processing", "Transcrevendo...")

        info_gravacao = gravador.parar(caminho_destino=caminho_audio)
        duracao_ms = int(info_gravacao.get("duration_ms", 0) or 0)

        if not info_gravacao.get("ok"):
            self._esta_processando = False
            motivo = info_gravacao.get("reason", "Erro de captura")
            gerenciador_historico.marcar_erro(id_registro, duracao_ms, motivo)
            self._definir_status("error", "Erro ao salvar áudio")
            return

        caminho_final_audio = Path(info_gravacao.get("path") or caminho_audio)

        if duracao_ms < 200 or info_gravacao.get("is_silent"):
            self._esta_processando = False
            gerenciador_historico.marcar_vazio(
                id_registro, duracao_ms, caminho_audio=str(caminho_final_audio)
            )
            self._definir_status("idle", "Áudio vazio ou muito curto")
            return

        def _tarefa_segundo_plano() -> None:
            try:
                asyncio.run(
                    self._processar_fluxo_completo(
                        id_registro, caminho_final_audio, duracao_ms
                    )
                )
            finally:
                self._esta_processando = False

        threading.Thread(target=_tarefa_segundo_plano, daemon=True).start()

    async def _processar_fluxo_completo(
        self, id_registro: str, caminho_audio: Path, duracao_ms: int
    ) -> None:
        configuracoes = obter_configuracoes()
        try:
            resultado_stt = await transcritor.transcrever(
                caminho_audio, idioma=configuracoes.idioma
            )
            if not resultado_stt.get("ok") or not resultado_stt.get("text"):
                mensagem_erro = (
                    resultado_stt.get("error") or "Transcrição não retornou texto"
                )
                gerenciador_historico.marcar_erro(
                    id_registro,
                    duracao_ms,
                    mensagem_erro,
                    provedor=resultado_stt.get("provider"),
                    caminho_audio=str(caminho_audio),
                )
                self._definir_status("error", mensagem_erro)
                return

            texto_bruto = resultado_stt["text"].strip()
            provedor_usado = resultado_stt.get("provider", configuracoes.provedor)

            deve_traduzir = configuracoes.traduzir_para_ingles
            nome_app_ativo = (self._info_app_ativo.get("name") or "").lower()
            if not deve_traduzir and configuracoes.apps_traducao_automatica:
                for app_auto in configuracoes.apps_traducao_automatica:
                    if app_auto.lower() in nome_app_ativo:
                        deve_traduzir = True
                        break

            resultado_reescrita = await reescritor.reescrever(
                texto_bruto=texto_bruto,
                tom=configuracoes.tom,
                correcao_gramatical=configuracoes.correcao_gramatical,
                traduzir_para_ingles=deve_traduzir,
            )
            texto_final = resultado_reescrita.get("text", texto_bruto).strip()
            gramatica_aplicada = bool(resultado_reescrita.get("grammar_fixed", False))

            inserido = False
            possui_foco_estrito, _nome_app, _elemento_focado = encontrar_editavel_focado()

            if possui_foco_estrito:
                inserido = inseridor.inserir_texto(
                    texto_final, metodo=configuracoes.metodo_insercao
                )
            elif configuracoes.cacar_input_automatico:
                campo_alvo = cacar_input_visivel(
                    profundidade_maxima=configuracoes.profundidade_busca_ax
                )
                if campo_alvo is not None:
                    focou_ok = focar_elemento(
                        campo_alvo,
                        permitir_clique_fallback=configuracoes.clicar_para_focar_input,
                    )
                    if focou_ok:
                        time.sleep(0.08)
                inserido = inseridor.inserir_texto(
                    texto_final, metodo=configuracoes.metodo_insercao
                )
            else:
                inserido = inseridor.inserir_texto(
                    texto_final, metodo=configuracoes.metodo_insercao
                )

            if not inserido:
                inserido = exibir_alerta_selecao_campo(texto_final)

            if inserido:
                gerenciador_historico.marcar_enviado(
                    id_registro=id_registro,
                    duracao_ms=duracao_ms,
                    texto_bruto=texto_bruto,
                    texto_final=texto_final,
                    tom=configuracoes.tom,
                    gramatica_corrigida=gramatica_aplicada,
                    provedor=provedor_usado,
                    caminho_audio=str(caminho_audio),
                )
                self._definir_status("idle", "Concluído e enviado")
            else:
                gerenciador_historico.marcar_escrito_nao_enviado(
                    id_registro=id_registro,
                    duracao_ms=duracao_ms,
                    texto_bruto=texto_bruto,
                    texto_final=texto_final,
                    tom=configuracoes.tom,
                    gramatica_corrigida=gramatica_aplicada,
                    provedor=provedor_usado,
                    caminho_audio=str(caminho_audio),
                    motivo="Texto transcrito com sucesso, mas a inserção automática no cursor falhou (salvo para recuperação)",
                )
                self._definir_status("idle", "Transcrito (salvo na recuperação)")

        except Exception as erro:
            gerenciador_historico.marcar_erro(
                id_registro,
                duracao_ms,
                f"Erro inesperado no fluxo de transcrição: {erro}",
                caminho_audio=str(caminho_audio),
            )
            self._definir_status("error", str(erro))

    def cancelar_gravacao(self) -> bool:
        """Cancela a gravação atual preservando o áudio em OGG e marcando como cancelado no histórico."""
        with self._trava:
            self._tecla_atalho_pressionada = False
            self._ignorar_proxima_soltura = False

            if self._esta_gravando or gravador.esta_gravando:
                self._esta_gravando = False
                self._modo_atual = "ocioso"

                diretorio_audios = _obter_diretorio_audios()
                diretorio_audios.mkdir(parents=True, exist_ok=True)
                caminho_destino = self._caminho_audio_atual or (
                    diretorio_audios / f"{self._id_registro_atual or 'cancelado'}.ogg"
                )
                resultado = gravador.cancelar(caminho_destino=caminho_destino)

                audio_salvo = resultado.get("path") if resultado.get("ok") else None
                duracao_ms = int(resultado.get("duration_ms", 0) or 0)

                if self._id_registro_atual:
                    gerenciador_historico.marcar_cancelado(
                        self._id_registro_atual,
                        duracao_ms=duracao_ms,
                        caminho_audio=str(audio_salvo)
                        if audio_salvo
                        else str(caminho_destino),
                    )
                self._definir_status("idle", "Gravação cancelada (áudio preservado)")
                return True
            return False

    def _tratar_parada_automatica(self) -> None:
        """Acionado pelo gravador quando o tempo máximo de silêncio contínuo é atingido."""
        with self._trava:
            if self._esta_gravando or gravador.esta_gravando:
                self._modo_atual = "ocioso"
                self._definir_status(
                    "processing", "Silêncio detectado — transcrevendo..."
                )
                self._executar_parada()

    async def recuperar_e_inserir(self, id_registro: str) -> bool:
        """Recupera uma gravação pendente/cancelada do histórico e insere no cursor ativo."""
        await asyncio.sleep(0.6)

        registro = gerenciador_historico.obter_registro(id_registro)
        if not registro:
            return False

        texto_para_inserir = registro.get("text_final") or registro.get("text_raw")
        configuracoes = obter_configuracoes()

        if not texto_para_inserir:
            caminho_audio = Path(registro.get("audio_path") or "")
            if not caminho_audio.exists() or caminho_audio.stat().st_size == 0:
                self._definir_status(
                    "error", "Arquivo de áudio não encontrado para recuperação"
                )
                return False

            self._definir_status("processing", "Transcrevendo áudio recuperado...")
            resultado_stt = await transcritor.transcrever(
                caminho_audio,
                idioma=registro.get("language") or configuracoes.idioma,
            )
            if not resultado_stt.get("ok") or not resultado_stt.get("text"):
                self._definir_status("error", "Falha ao transcrever áudio recuperado")
                return False

            texto_bruto = resultado_stt["text"].strip()
            resultado_reescrita = await reescritor.reescrever(
                texto_bruto=texto_bruto,
                tom=registro.get("tone") or configuracoes.tom,
                correcao_gramatical=configuracoes.correcao_gramatical,
                traduzir_para_ingles=configuracoes.traduzir_para_ingles,
            )
            texto_para_inserir = resultado_reescrita.get("text", texto_bruto).strip()

        if not texto_para_inserir:
            return False

        inserido_ok = inseridor.inserir_texto(
            texto_para_inserir, metodo=configuracoes.metodo_insercao
        )
        if inserido_ok:
            gerenciador_historico.marcar_enviado(
                id_registro=id_registro,
                duracao_ms=registro.get("duration_ms") or 0,
                texto_bruto=registro.get("text_raw") or texto_para_inserir,
                texto_final=texto_para_inserir,
                tom=registro.get("tone") or "verbatim",
                caminho_audio=registro.get("audio_path"),
            )
            self._definir_status("idle", "Áudio recuperado e colado no cursor")
            return True

        self._definir_status("error", "Não foi possível colar no cursor (verifique foco)")
        return False

    def _criar_ou_garantir_escutador(self) -> bool:
        """Cria um único `keyboard.Listener` de forma estritamente idempotente sob trava."""
        with self._trava_escuta:
            if self._escutador is not None:
                if bool(self._escutador.is_alive()):
                    return True
                try:
                    self._escutador.stop()
                except Exception:
                    pass
                self._escutador = None

            try:
                novo_escutador = keyboard.Listener(
                    on_press=self.ao_pressionar,
                    on_release=self.ao_soltar,
                )
                novo_escutador.daemon = True
                novo_escutador.start()
                self._escutador = novo_escutador
                return bool(novo_escutador.is_alive())
            except Exception:
                self._escutador = None
                return False

    def _laco_supervisao_escutador(self) -> None:
        """Verifica a cada 10s se o listener global morreu e tenta recriá-lo silenciosamente."""
        while not self._evento_parar_supervisao.wait(timeout=10.0):
            if not self._escuta_desejada:
                break
            if not self.escuta_ativa:
                self._criar_ou_garantir_escutador()

    def iniciar_escuta(
        self, laco_eventos: Optional[asyncio.AbstractEventLoop] = None
    ) -> bool:
        """
        Inicia o escutador global de teclado de forma estritamente idempotente.
        Se já houver um listener vivo, reutiliza a mesma instância e retorna `True`.
        """
        gravador.ao_parar_automatico = self._tratar_parada_automatica

        if laco_eventos is not None:
            self._laco_eventos = laco_eventos

        with self._trava_escuta:
            self._escuta_desejada = True
            self._evento_parar_supervisao.clear()

            ja_estava_ativo = (
                self._escutador is not None and bool(self._escutador.is_alive())
            )
            escuta_ok = self._criar_ou_garantir_escutador()

            if (
                self._thread_supervisao_escuta is None
                or not self._thread_supervisao_escuta.is_alive()
            ):
                self._thread_supervisao_escuta = threading.Thread(
                    target=self._laco_supervisao_escutador,
                    daemon=True,
                )
                self._thread_supervisao_escuta.start()

        if not ja_estava_ativo and escuta_ok and not self._esta_gravando and not self._esta_processando:
            self._definir_status("idle", "Pronto")

        return escuta_ok

    def parar_escuta(self) -> None:
        """Encerra o escutador global de teclado e sua thread de supervisão."""
        with self._trava_escuta:
            self._escuta_desejada = False
            self._evento_parar_supervisao.set()
            if self._escutador is not None:
                try:
                    self._escutador.stop()
                except Exception:
                    pass
                self._escutador = None

    def obter_estado_tempo_real(self) -> dict:
        """Retorna snapshot em tempo real para o stream SSE `/eventos` e API `/status`."""
        return {
            "estado": self._estado_atual,
            "detalhe": self._detalhe_atual,
            "esta_gravando": self.esta_gravando,
            "esta_processando": self.esta_processando,
            "modo_atual": self.modo_atual,
            "nivel_voz": float(gravador.nivel_atual),
            "escuta_ativa": self.escuta_ativa,
        }


servico_voz = ServicoVoz()
