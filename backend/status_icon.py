"""
Aplicativo nativo da barra de menus do macOS (rumps + PyObjC AppHelper).

Gerencia o ícone animado de status com total segurança de threads (Main Thread),
acionamento manual, seleção dos 3 modos de acionamento, tons de voz, recuperação
de áudios pendentes e execução sob demanda do protocolo de autoteste.
"""

import asyncio
import datetime
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

import AppKit
import rumps
from PyObjCTools import AppHelper

from autostart import (
    autoinicio_esta_instalado,
    desinstalar_autoinicio,
    instalar_autoinicio,
    obter_executavel_app,
)
from config import DIRETORIO_BASE_APP, atualizar_configuracoes, obter_configuracoes
from floating_overlay import overlay_flutuante
from history import gerenciador_historico
from protocolo_inicializacao import protocolo_inicializacao

ICONES_STATUS = {
    "idle": "🟢",
    "listening": "🔴 REC",
    "processing": "🟡 REC ...",
    "no_focus": "⚠️ Sem Foco",
    "error": "⚠️ Erro",
}

ROTULOS_STATUS_PADRAO = {
    "idle": "Pronto (Ocioso)",
    "listening": "Ouvindo sua voz...",
    "processing": "Transcrevendo e ajustando tom...",
    "no_focus": "Nenhum campo editável em foco",
    "error": "Falha no processamento",
}

TONS_VOZ = [
    ("verbatim", "Verbatim (Sem filtro)"),
    ("colloquial", "Coloquial"),
    ("semiformal", "Semiformal"),
    ("formal", "Formal"),
]

MODOS_ACIONAMENTO = [
    ("hibrido", "Híbrido (Segurar ou Toque Rápido)"),
    ("segurar", "Segurar para Falar (Push-and-Hold)"),
    ("alternar", "Toque para Alternar (Liga/Desliga)"),
]


def _despachar_para_thread_principal(operacao) -> None:
    """Garante que mutações de itens Cocoa/rumps ocorram exclusivamente na Main Thread."""
    if AppKit.NSThread.isMainThread():
        operacao()
    else:
        AppHelper.callAfter(operacao)


def _notificar_usuario(titulo: str, subtitulo: str, mensagem: str) -> None:
    """Exibe notificação nativa do macOS de forma segura e tolerante a ambientes sem bundle."""
    def _enviar() -> None:
        try:
            rumps.notification(titulo, subtitulo, mensagem)
        except Exception as erro:
            print(f"[BANDEJA] Aviso ao exibir notificação ({subtitulo}): {erro}")

    _despachar_para_thread_principal(_enviar)


class AplicativoBandejaVoz(rumps.App):
    """Aplicativo de barra de menus do Voice Transcription com despacho thread-safe."""

    def __init__(self, servico_ref=None):
        super().__init__(
            "VoiceTranscription",
            title=ICONES_STATUS["idle"],
            quit_button=None,
        )
        self.servico_ref = servico_ref
        self._status_atual = "idle"
        self._ultimo_titulo_enviado = ICONES_STATUS["idle"]
        self._evento_parar_animacao = threading.Event()
        self._thread_animacao: Optional[threading.Thread] = None

        configuracoes = obter_configuracoes()

        # 1. Item informativo de status
        self.item_status = rumps.MenuItem("Status: Pronto (Ocioso)")
        self.menu.add(self.item_status)
        self.menu.add(rumps.separator)

        # 2. Ação rápida de gravação manual
        self.item_gravar = rumps.MenuItem(
            "Gravar Agora (Clique)",
            callback=self.ao_clicar_gravar,
        )
        self.menu.add(self.item_gravar)
        self.menu.add(rumps.separator)

        # 3. Submenu Modo de Acionamento (3 opções exclusivas)
        self.menu_modo_acionamento = rumps.MenuItem("Modo de Acionamento")
        self._itens_modo_acionamento: dict[str, rumps.MenuItem] = {}
        modo_ativo = configuracoes.modo_acionamento or "hibrido"

        for chave_modo, rotulo_modo in MODOS_ACIONAMENTO:
            item_modo = rumps.MenuItem(
                rotulo_modo,
                callback=self._criar_retorno_modo_acionamento(chave_modo),
            )
            item_modo.state = 1 if chave_modo == modo_ativo else 0
            self._itens_modo_acionamento[chave_modo] = item_modo
            self.menu_modo_acionamento.add(item_modo)

        self.menu.add(self.menu_modo_acionamento)

        # 4. Submenu Tom de Voz (Estilo)
        self.menu_tons = rumps.MenuItem("Tom de Voz (Estilo)")
        self._itens_tons: dict[str, rumps.MenuItem] = {}
        tom_ativo = configuracoes.tom or "verbatim"

        for chave_tom, rotulo_tom in TONS_VOZ:
            item_tom = rumps.MenuItem(
                rotulo_tom,
                callback=self._criar_retorno_tom(chave_tom),
            )
            item_tom.state = 1 if chave_tom == tom_ativo else 0
            self._itens_tons[chave_tom] = item_tom
            self.menu_tons.add(item_tom)

        self.menu.add(self.menu_tons)

        # 5. Tradutor Instantâneo PT -> EN
        self.item_traduzir = rumps.MenuItem(
            "🌐 Traduzir para Inglês (PT ➔ EN)",
            callback=self.ao_alternar_traducao,
        )
        self.item_traduzir.state = 1 if configuracoes.traduzir_para_ingles else 0
        self.menu.add(self.item_traduzir)

        # 6. Submenu de Recuperação de Áudios Pendentes
        self.menu_recuperacao = rumps.MenuItem("🔄 Recuperação (Não Enviados)")
        self.menu.add(self.menu_recuperacao)
        self._atualizar_menu_recuperacao()
        self.menu.add(rumps.separator)

        # 7. Submenu de Preferências
        self.menu_preferencias = rumps.MenuItem("Preferências")

        self.item_gramatica = rumps.MenuItem(
            "Correção Gramatical Automática",
            callback=self.ao_alternar_gramatica,
        )
        self.item_gramatica.state = 1 if configuracoes.correcao_gramatical else 0
        self.menu_preferencias.add(self.item_gramatica)

        self.item_adicionar_cursor = rumps.MenuItem(
            "Adicionar no Cursor (Append)",
            callback=self.ao_alternar_adicionar_cursor,
        )
        self.item_adicionar_cursor.state = 1 if configuracoes.adicionar_no_cursor else 0
        self.menu_preferencias.add(self.item_adicionar_cursor)

        self.item_caca_campo = rumps.MenuItem(
            "Caçar Campo Visível na Aba Ativa",
            callback=self.ao_alternar_caca_campo,
        )
        self.item_caca_campo.state = 1 if configuracoes.cacar_input_automatico else 0
        self.menu_preferencias.add(self.item_caca_campo)

        self.item_clique_foco = rumps.MenuItem(
            "Permitir Clique Suave para Focar Input",
            callback=self.ao_alternar_clique_foco,
        )
        self.item_clique_foco.state = 1 if configuracoes.clicar_para_focar_input else 0
        self.menu_preferencias.add(self.item_clique_foco)

        self.item_autoinicio = rumps.MenuItem(
            "Iniciar Automaticamente no Login",
            callback=self.ao_alternar_autoinicio,
        )
        self.item_autoinicio.state = 1 if autoinicio_esta_instalado() else 0
        self.menu_preferencias.add(self.item_autoinicio)

        self.item_backup_fatias = rumps.MenuItem(
            "Backup Contínuo por Fatias (OGG)",
            callback=self.ao_alternar_backup_fatias,
        )
        self.item_backup_fatias.state = 1 if configuracoes.backup_fatias_ativo else 0
        self.menu_preferencias.add(self.item_backup_fatias)

        self.item_limiar_fatias = rumps.MenuItem(
            f"Iniciar Fatias aos: {configuracoes.inicio_fatias_segundos}s (Alterar...)",
            callback=self.ao_alterar_limiar_fatias,
        )
        self.menu_preferencias.add(self.item_limiar_fatias)

        self.item_parada_silencio = rumps.MenuItem(
            f"Auto-Parar após Silêncio: {configuracoes.parada_silencio_segundos}s (Alterar...)",
            callback=self.ao_alterar_parada_silencio,
        )
        self.menu_preferencias.add(self.item_parada_silencio)

        self.menu.add(self.menu_preferencias)
        self.menu.add(rumps.separator)

        # 8. Diagnóstico e Utilitários
        self.item_autoteste = rumps.MenuItem(
            "🩺 Executar Autoteste de Inicialização",
            callback=self.ao_executar_autoteste,
        )
        self.menu.add(self.item_autoteste)

        self.menu.add(
            rumps.MenuItem(
                "Abrir Painel de Controle (Web)...",
                callback=self.ao_abrir_painel_web,
            )
        )
        self.menu.add(
            rumps.MenuItem(
                "Abrir Pasta do Histórico...",
                callback=self.ao_abrir_pasta_historico,
            )
        )
        self.menu.add(
            rumps.MenuItem(
                "Ver Documentação e Atalhos...",
                callback=self.ao_abrir_documentacao,
            )
        )
        self.menu.add(rumps.separator)

        # 9. Reiniciar e Encerrar
        self.menu.add(
            rumps.MenuItem(
                "🔄 Reiniciar Voice Transcription",
                callback=self.ao_clicar_reiniciar,
            )
        )
        self.menu.add(
            rumps.MenuItem(
                "Encerrar Voice Transcription",
                callback=self.ao_clicar_sair,
            )
        )

        # Inicia overlay nativo e thread de animação de status
        overlay_flutuante.iniciar()
        self._thread_animacao = threading.Thread(
            target=self._laco_animacao,
            name="AnimacaoBandejaThread",
            daemon=True,
        )
        self._thread_animacao.start()

    def _criar_retorno_modo_acionamento(self, chave_modo: str):
        """Gera callback para selecionar um dos 3 modos de acionamento."""
        def _ao_selecionar(_remetente) -> None:
            atualizar_configuracoes({"modo_acionamento": chave_modo})
            for codigo, item in self._itens_modo_acionamento.items():
                item.state = 1 if codigo == chave_modo else 0
            rotulo = dict(MODOS_ACIONAMENTO).get(chave_modo, chave_modo)
            _notificar_usuario(
                "Voice Transcription",
                "Modo de Acionamento Atualizado",
                f"Ativo: {rotulo}",
            )

        return _ao_selecionar

    def _criar_retorno_tom(self, chave_tom: str):
        """Gera callback para selecionar o tom de voz desejado."""
        def _ao_selecionar(_remetente) -> None:
            atualizar_configuracoes({"tone": chave_tom})
            for codigo, item in self._itens_tons.items():
                item.state = 1 if codigo == chave_tom else 0
            rotulo = dict(TONS_VOZ).get(chave_tom, chave_tom)
            _notificar_usuario(
                "Voice Transcription",
                "Tom de Voz Atualizado",
                f"Estilo ativo: {rotulo}",
            )

        return _ao_selecionar

    def ao_alternar_traducao(self, remetente) -> None:
        novo_estado = not bool(remetente.state)
        remetente.state = 1 if novo_estado else 0
        atualizar_configuracoes({"translate_to_english": novo_estado})
        mensagem = (
            "Ativada (Fala em PT ➔ Digita em EN)"
            if novo_estado
            else "Desativada (Digita no idioma original)"
        )
        _notificar_usuario("Voice Transcription", "Tradução PT ➔ EN", mensagem)

    def _atualizar_menu_recuperacao(self) -> None:
        """Recarrega os áudios pendentes/recuperáveis do banco SQLite."""
        try:
            if hasattr(self.menu_recuperacao, "_menu") and self.menu_recuperacao._menu is not None:
                self.menu_recuperacao.clear()
            else:
                for chave in list(self.menu_recuperacao.keys()):
                    del self.menu_recuperacao[chave]

            pendentes = gerenciador_historico.listar_recuperaveis(limite=10)
            if not pendentes:
                self.menu_recuperacao.add(
                    rumps.MenuItem("Nenhum áudio pendente (Tudo enviado)")
                )
                return

            for registro in pendentes:
                id_registro = registro["id"]
                previa_bruta = (
                    registro.get("text_final")
                    or registro.get("text_raw")
                    or "Áudio salvo aguardando transcrição"
                )
                texto_curto = (
                    f"{previa_bruta[:30]}..."
                    if len(previa_bruta) > 30
                    else previa_bruta
                )

                prefixo_hora = ""
                criado_em = registro.get("created_at")
                if criado_em:
                    try:
                        instante = datetime.datetime.fromisoformat(
                            criado_em.replace("Z", "+00:00")
                        )
                        instante_local = instante.astimezone()
                        prefixo_hora = f"[{instante_local.strftime('%H:%M:%S')}] "
                    except Exception:
                        pass

                rotulo_item = f'{prefixo_hora}"{texto_curto}"'
                self.menu_recuperacao.add(
                    rumps.MenuItem(
                        rotulo_item,
                        callback=self._criar_retorno_recuperacao(id_registro),
                    )
                )

            self.menu_recuperacao.add(rumps.separator)
            self.menu_recuperacao.add(
                rumps.MenuItem(
                    "Atualizar Lista de Pendências",
                    callback=lambda _s: self._atualizar_menu_recuperacao(),
                )
            )
        except Exception as erro:
            print(f"[BANDEJA] Falha ao atualizar menu de recuperação: {erro}")

    def _criar_retorno_recuperacao(self, id_registro: str):
        """Gera callback assíncrono para recuperar e colar um áudio pendente."""
        def _ao_recuperar(_remetente) -> None:
            if self.servico_ref is None:
                return

            def _executar_recuperacao() -> None:
                try:
                    asyncio.run(self.servico_ref.recuperar_e_inserir(id_registro))
                finally:
                    _despachar_para_thread_principal(self._atualizar_menu_recuperacao)

            threading.Thread(
                target=_executar_recuperacao,
                name="RecuperacaoAudioThread",
                daemon=True,
            ).start()

        return _ao_recuperar

    def ao_clicar_gravar(self, _remetente) -> None:
        """Inicia ou interrompe manualmente a gravação pela barra de menus."""
        if self.servico_ref is None:
            return
        if self._status_atual == "listening":
            self.servico_ref.parar_gravacao_manual()
        else:
            self.servico_ref.iniciar_gravacao_manual()

    def ao_alternar_gramatica(self, remetente) -> None:
        novo_estado = not bool(remetente.state)
        remetente.state = 1 if novo_estado else 0
        atualizar_configuracoes({"grammar_correction": novo_estado})

    def ao_alternar_adicionar_cursor(self, remetente) -> None:
        novo_estado = not bool(remetente.state)
        remetente.state = 1 if novo_estado else 0
        atualizar_configuracoes({"append_at_cursor": novo_estado})

    def ao_alternar_caca_campo(self, remetente) -> None:
        novo_estado = not bool(remetente.state)
        remetente.state = 1 if novo_estado else 0
        atualizar_configuracoes({"auto_hunt_input": novo_estado})
        _notificar_usuario(
            "Voice Transcription",
            "Caça Inteligente de Campo",
            "Ativada" if novo_estado else "Desativada",
        )

    def ao_alternar_clique_foco(self, remetente) -> None:
        novo_estado = not bool(remetente.state)
        remetente.state = 1 if novo_estado else 0
        atualizar_configuracoes({"click_to_focus_input": novo_estado})

    def ao_alternar_autoinicio(self, remetente) -> None:
        deseja_ativar = not bool(remetente.state)
        if deseja_ativar:
            instalar_autoinicio()
        else:
            desinstalar_autoinicio()
        instalado = autoinicio_esta_instalado()
        remetente.state = 1 if instalado else 0
        atualizar_configuracoes({"auto_start_login": instalado})
        _notificar_usuario(
            "Voice Transcription",
            "Inicialização no Login",
            "Ativada no LaunchAgent" if instalado else "Desativada",
        )

    def ao_alternar_backup_fatias(self, remetente) -> None:
        novo_estado = not bool(remetente.state)
        remetente.state = 1 if novo_estado else 0
        atualizar_configuracoes({"chunk_backup_enabled": novo_estado})
        _notificar_usuario(
            "Voice Transcription",
            "Backup Contínuo OGG",
            "Ativado" if novo_estado else "Desativado",
        )

    def ao_alterar_limiar_fatias(self, remetente) -> None:
        """Permite digitar o tempo inicial antes de gravar fatias de 30s."""
        configuracoes = obter_configuracoes()
        janela = rumps.Window(
            message=(
                "Digite o tempo inicial de fala contínua (em segundos) antes de "
                "iniciar o fatiamento preventivo em OGG de 30s:\n\n"
                f"Atual: {configuracoes.inicio_fatias_segundos}s (Padrão: 40s)"
            ),
            title="Limiar de Início das Fatias",
            default_text=str(configuracoes.inicio_fatias_segundos),
            ok="Salvar",
            cancel="Cancelar",
            dimensions=(280, 24),
        )
        resposta = janela.run()
        if not resposta.clicked:
            return
        try:
            segundos = int(resposta.text.strip())
            if segundos >= 5:
                atualizar_configuracoes({"chunk_start_seconds": segundos})
                remetente.title = f"Iniciar Fatias aos: {segundos}s (Alterar...)"
                _notificar_usuario(
                    "Voice Transcription",
                    "Limiar Atualizado",
                    f"Fatias preventivas iniciarão após {segundos}s de fala.",
                )
            else:
                rumps.alert("Valor Inválido", "O tempo mínimo deve ser de pelo menos 5 segundos.")
        except ValueError:
            rumps.alert("Valor Inválido", "Digite um número inteiro válido em segundos.")

    def ao_alterar_parada_silencio(self, remetente) -> None:
        """Permite digitar o limite de silêncio contínuo antes da parada automática."""
        configuracoes = obter_configuracoes()
        janela = rumps.Window(
            message=(
                "Digite quantos segundos de silêncio contínuo aguardar antes de "
                "encerrar e transcrever automaticamente:\n\n"
                f"Atual: {configuracoes.parada_silencio_segundos}s (Padrão: 60s)"
            ),
            title="Auto-Parada por Silêncio",
            default_text=str(configuracoes.parada_silencio_segundos),
            ok="Salvar",
            cancel="Cancelar",
            dimensions=(280, 24),
        )
        resposta = janela.run()
        if not resposta.clicked:
            return
        try:
            segundos = int(resposta.text.strip())
            if segundos >= 5:
                atualizar_configuracoes({"silence_auto_stop_seconds": segundos})
                remetente.title = f"Auto-Parar após Silêncio: {segundos}s (Alterar...)"
                _notificar_usuario(
                    "Voice Transcription",
                    "Auto-Parada Atualizada",
                    f"A gravação encerrará após {segundos}s de silêncio.",
                )
            else:
                rumps.alert("Valor Inválido", "O tempo mínimo deve ser de pelo menos 5 segundos.")
        except ValueError:
            rumps.alert("Valor Inválido", "Digite um número inteiro válido em segundos.")

    def ao_executar_autoteste(self, _remetente) -> None:
        """Executa o protocolo completo de autoteste de inicialização e resume o resultado."""
        def _rodar_diagnostico() -> None:
            relatorio = protocolo_inicializacao.executar_autoteste(
                servico_voz_ref=self.servico_ref
            )
            saudavel = bool(relatorio.get("ok"))
            duracao = relatorio.get("duracao_ms", 0)
            etapas = relatorio.get("etapas") or {}

            falhas = [
                nome_etapa.replace("_", " ")
                for nome_etapa, dados_etapa in etapas.items()
                if isinstance(dados_etapa, dict) and not dados_etapa.get("ok", False)
            ]

            if saudavel and not falhas:
                subtitulo = "Autoteste Concluído: 100% Saudável"
                resumo = f"Todas as {len(etapas) or 5} etapas verificadas em {duracao}ms."
            else:
                subtitulo = "Autoteste: Atenção Necessária"
                lista_falhas = ", ".join(falhas) if falhas else "verifique o Painel Web"
                resumo = f"Pendências detectadas em: {lista_falhas}."

            _notificar_usuario("Voice Transcription", subtitulo, resumo)
            _despachar_para_thread_principal(self._atualizar_menu_recuperacao)

        threading.Thread(
            target=_rodar_diagnostico,
            name="AutotesteBandejaThread",
            daemon=True,
        ).start()

    def ao_abrir_painel_web(self, _remetente) -> None:
        configuracoes = obter_configuracoes()
        url_painel = f"http://127.0.0.1:{configuracoes.porta}/"
        webbrowser.open(url_painel)

    def ao_abrir_pasta_historico(self, _remetente) -> None:
        DIRETORIO_BASE_APP.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(DIRETORIO_BASE_APP)], check=False)

    def ao_abrir_documentacao(self, _remetente) -> None:
        caminho_readme = Path(__file__).resolve().parent.parent / "README.md"
        if caminho_readme.exists():
            subprocess.run(["open", str(caminho_readme)], check=False)

    def ao_clicar_reiniciar(self, _remetente) -> None:
        """Reinicia o aplicativo respeitando a porta configurada e o executável empacotado."""
        configuracoes = obter_configuracoes()
        porta_ativa = int(configuracoes.porta)

        _notificar_usuario(
            "Voice Transcription",
            "Reiniciando Serviço",
            f"Reiniciando aplicativo e servidor na porta {porta_ativa}...",
        )

        self._evento_parar_animacao.set()
        overlay_flutuante.parar()
        if self.servico_ref is not None:
            self.servico_ref.parar_escuta()

        executavel_app = obter_executavel_app()
        if executavel_app.exists():
            comando_inicio = f"'{executavel_app}'"
        else:
            script_principal = Path(__file__).resolve().parent / "main.py"
            comando_inicio = f"'{sys.executable}' '{script_principal}'"

        comando_shell = (
            f"kill $(lsof -ti :{porta_ativa}) 2>/dev/null || true; "
            f"sleep 0.5; {comando_inicio} &"
        )
        subprocess.Popen(["sh", "-c", comando_shell])
        rumps.quit_application()

    def ao_clicar_sair(self, _remetente) -> None:
        self._evento_parar_animacao.set()
        overlay_flutuante.parar()
        if self.servico_ref is not None:
            self.servico_ref.parar_escuta()
        rumps.quit_application()

    def _definir_titulo_bandeja_seguro(self, novo_titulo: str) -> None:
        """Atualiza `self.title` na Main Thread apenas quando o texto muda."""
        if novo_titulo == self._ultimo_titulo_enviado:
            return
        self._ultimo_titulo_enviado = novo_titulo

        def _aplicar_titulo() -> None:
            self.title = novo_titulo

        _despachar_para_thread_principal(_aplicar_titulo)

    def _laco_animacao(self) -> None:
        """
        Anima o ícone da barra de menus a cada 0.25s despachando estritamente
        para a Main Thread via AppHelper.callAfter.
        """
        ponto_aceso = True
        indice_quadro = 0
        quadros_reticencias = ("...", " ..", ". .", ".. ")

        while not self._evento_parar_animacao.is_set():
            time.sleep(0.25)
            if self._evento_parar_animacao.is_set():
                break

            estado = self._status_atual
            if estado == "listening":
                ponto_aceso = not ponto_aceso
                texto_animado = "🔴 REC" if ponto_aceso else "⚫ REC"
                self._definir_titulo_bandeja_seguro(texto_animado)
                overlay_flutuante.definir_modo("listening")
            elif estado == "processing":
                onda_pontos = quadros_reticencias[indice_quadro % len(quadros_reticencias)]
                indice_quadro += 1
                self._definir_titulo_bandeja_seguro(f"🟡 REC {onda_pontos}")
                overlay_flutuante.definir_modo("processing")
            else:
                icone_repouso = ICONES_STATUS.get(estado, "🟢")
                self._definir_titulo_bandeja_seguro(icone_repouso)
                overlay_flutuante.ocultar()

    def atualizar_status(self, status: str, detalhe: Optional[str] = None) -> None:
        """
        Recebe transições de estado do `ServicoVoz` (de qualquer thread) e sincroniza
        com segurança a barra de menus e o brilho flutuante nativo.
        """
        self._status_atual = status
        mensagem_detalhe = detalhe or ROTULOS_STATUS_PADRAO.get(status, status.capitalize())

        if status == "listening":
            rotulo_gravar = "Parar Gravação (Clique)"
            titulo_imediato = "🔴 REC"
            overlay_flutuante.definir_modo("listening")
        elif status == "processing":
            rotulo_gravar = "Processando transcrição..."
            titulo_imediato = "🟡 REC ..."
            overlay_flutuante.definir_modo("processing")
        else:
            rotulo_gravar = "Gravar Agora (Clique)"
            titulo_imediato = ICONES_STATUS.get(status, "🟢")
            overlay_flutuante.ocultar()

        self._ultimo_titulo_enviado = titulo_imediato

        def _atualizar_itens_na_thread_principal() -> None:
            self.title = titulo_imediato
            self.item_status.title = f"Status: {mensagem_detalhe}"
            self.item_gravar.title = rotulo_gravar
            if status in ("idle", "error", "no_focus"):
                self._atualizar_menu_recuperacao()

        _despachar_para_thread_principal(_atualizar_itens_na_thread_principal)


def criar_app_bandeja(servico_ref=None) -> AplicativoBandejaVoz:
    """Fábrica do aplicativo de barra de menus nativo."""
    return AplicativoBandejaVoz(servico_ref=servico_ref)
