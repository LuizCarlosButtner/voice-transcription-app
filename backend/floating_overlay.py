"""
Indicador visual flutuante nativo do macOS (AppKit + CoreGraphics / Quartz).

Renderiza um brilho vermelho difuso, orgânico e nebuloso na região inferior
central da tela (~5.5% acima da base) em um painel transparente de 220x220 px
que ignora completamente cliques de mouse e nunca corta o halo nas bordas.
"""

import math
import threading
import time
from typing import Optional

import objc
import AppKit
import Quartz
from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSGraphicsContext,
    NSMakeRect,
    NSPanel,
    NSScreen,
    NSView,
)
from PyObjCTools import AppHelper

from recorder import gravador

LARGURA_PADRAO_OVERLAY = 220.0
ALTURA_PADRAO_OVERLAY = 220.0
PROPORCAO_ALTURA_BASE_TELA = 0.055
DURACAO_DISSOLUCAO_SEGUNDOS = 0.35
INTERVALO_QUADRO_SEGUNDOS = 1.0 / 50.0


def _executar_na_thread_principal(acao) -> None:
    """Garante execução segura de operações de interface Cocoa na thread principal."""
    if AppKit.NSThread.isMainThread():
        acao()
    else:
        AppHelper.callAfter(acao)


def _limitar_intervalo(valor: float, minimo: float = 0.0, maximo: float = 1.0) -> float:
    """Restringe um valor numérico ao intervalo fechado [minimo, maximo]."""
    if valor < minimo:
        return minimo
    if valor > maximo:
        return maximo
    return valor


def _normalizar_nivel_voz(nivel_bruto: float) -> float:
    """
    Converte a amplitude linear do microfone em uma curva perceptiva orgânica [0.0, 1.0],
    destacando modulações sutis de fala sem saturar precocemente.
    """
    nivel_positivo = max(0.0, float(nivel_bruto or 0.0))
    ganho_ajustado = min(1.0, nivel_positivo * 3.4)
    return _limitar_intervalo(ganho_ajustado ** 0.72, 0.0, 1.0)


def _obter_quadro_alvo(
    largura: float = LARGURA_PADRAO_OVERLAY,
    altura: float = ALTURA_PADRAO_OVERLAY,
):
    """
    Calcula o retângulo de 220x220 px centralizado horizontalmente na tela principal,
    posicionado a aproximadamente 5.5% da altura a partir da base da tela.
    """
    tela_principal = NSScreen.mainScreen()
    if tela_principal is None:
        telas = NSScreen.screens()
        tela_principal = telas[0] if telas else None

    if tela_principal is None:
        return NSMakeRect(500.0, 60.0, largura, altura)

    quadro_tela = tela_principal.frame()
    posicao_x = quadro_tela.origin.x + (quadro_tela.size.width - largura) / 2.0
    posicao_y = quadro_tela.origin.y + (quadro_tela.size.height * PROPORCAO_ALTURA_BASE_TELA)
    return NSMakeRect(posicao_x, posicao_y, largura, altura)


class VisaoOverlayBrilhoDifuso(NSView):
    """
    Visão CoreGraphics que desenha camadas radiais difusas sem bordas rígidas:
    - 'listening': halo carmesim/rubi amplo + 2 ondas de névoa acústica + núcleo rubi-coral.
    - 'processing': halo âmbar/rubi suave + arco fino minimalista girando com suavidade.
    - 'esvaindo': dissolução exponencial de 0.35s com contração suave até alpha 0.0.
    """

    def initWithFrame_(self, quadro):
        self = objc.super(VisaoOverlayBrilhoDifuso, self).initWithFrame_(quadro)
        if self is None:
            return None

        self._espaco_cor = Quartz.CGColorSpaceCreateDeviceRGB()
        self._modo_visual = "idle"
        self._modo_anterior_ativo = "listening"
        self._nivel_suavizado = 0.0
        self._nivel_congelado = 0.0
        self._instante_referencia = time.monotonic()
        self._instante_inicio_esvaimento = 0.0
        return self

    def isOpaque(self):
        return False

    def definir_modo_visual(self, novo_modo: str) -> None:
        """Atualiza o modo visual gerenciando a transição suave para dissolução."""
        agora = time.monotonic()
        if novo_modo in ("listening", "processing"):
            self._modo_visual = novo_modo
            self._modo_anterior_ativo = novo_modo
            self.setNeedsDisplay_(True)
            return

        if novo_modo == "idle":
            if self._modo_visual in ("listening", "processing"):
                self._modo_visual = "esvaindo"
                self._instante_inicio_esvaimento = agora
                self._nivel_congelado = self._nivel_suavizado
                self.setNeedsDisplay_(True)
            elif self._modo_visual != "esvaindo":
                self._modo_visual = "idle"
                self._nivel_suavizado = 0.0
                self.setNeedsDisplay_(True)

    def forcar_ocultacao_imediata(self) -> None:
        """Zera imediatamente o estado visual sem aguardar a dissolução."""
        self._modo_visual = "idle"
        self._nivel_suavizado = 0.0
        self._nivel_congelado = 0.0
        self.setNeedsDisplay_(True)

    def atualizar_animacao(self, nivel_bruto: float) -> bool:
        """
        Avança o envelope acústico e verifica se a visão ainda precisa permanecer visível.
        Retorna True enquanto houver conteúdo luminoso ativo na tela.
        """
        agora = time.monotonic()

        if self._modo_visual == "idle":
            self._nivel_suavizado = 0.0
            return False

        if self._modo_visual == "esvaindo":
            decorrido = agora - self._instante_inicio_esvaimento
            if decorrido >= DURACAO_DISSOLUCAO_SEGUNDOS:
                self._modo_visual = "idle"
                self._nivel_suavizado = 0.0
                self.setNeedsDisplay_(True)
                return False
            self.setNeedsDisplay_(True)
            return True

        alvo_nivel = _normalizar_nivel_voz(nivel_bruto) if self._modo_visual == "listening" else 0.0
        fator_interpolacao = 0.38 if alvo_nivel > self._nivel_suavizado else 0.14
        self._nivel_suavizado += (alvo_nivel - self._nivel_suavizado) * fator_interpolacao
        self._nivel_suavizado = _limitar_intervalo(self._nivel_suavizado, 0.0, 1.0)
        self.setNeedsDisplay_(True)
        return True

    def _desenhar_gradiente_radial(
        self,
        contexto_cg,
        centro_x: float,
        centro_y: float,
        raio_inicial: float,
        raio_final: float,
        paradas_cor: list[tuple[float, float, float, float, float]],
    ) -> None:
        """
        Renderiza um gradiente radial suave via CGGradientCreateWithColors.
        Cada item de `paradas_cor` contém (posicao, r_255, g_255, b_255, alpha).
        """
        if raio_final <= max(0.5, raio_inicial):
            return

        cores_cg = []
        posicoes = []
        for posicao, vermelho, verde, azul, opacidade in paradas_cor:
            opacidade_segura = _limitar_intervalo(opacidade, 0.0, 1.0)
            cor_cg = Quartz.CGColorCreate(
                self._espaco_cor,
                (vermelho / 255.0, verde / 255.0, azul / 255.0, opacidade_segura),
            )
            cores_cg.append(cor_cg)
            posicoes.append(_limitar_intervalo(posicao, 0.0, 1.0))

        gradiente = Quartz.CGGradientCreateWithColors(self._espaco_cor, cores_cg, posicoes)
        if gradiente is None:
            return

        ponto_central = Quartz.CGPointMake(centro_x, centro_y)
        # Opção 0 garante que nada seja pintado além de raio_final (sem corte nas bordas).
        Quartz.CGContextDrawRadialGradient(
            contexto_cg,
            gradiente,
            ponto_central,
            max(0.0, raio_inicial),
            ponto_central,
            raio_final,
            0,
        )

    def _desenhar_modo_ouvindo(
        self,
        contexto_cg,
        centro_x: float,
        centro_y: float,
        tempo_decorrido: float,
        nivel_voz: float,
    ) -> None:
        """Desenha o brilho vermelho carmesim/rubi difuso reativo à voz."""
        respiracao_suave = 0.5 + 0.5 * math.sin(tempo_decorrido * 2.2)

        # 1. Halo externo amplo e difuso (~48px em silêncio até ~102px nos picos de voz)
        raio_halo_externo = min(
            102.0,
            48.0 + (respiracao_suave * 4.5) + (nivel_voz * 49.5),
        )
        opacidade_centro_halo = 0.30 + (respiracao_suave * 0.06) + (nivel_voz * 0.36)
        opacidade_meio_halo = 0.15 + (respiracao_suave * 0.03) + (nivel_voz * 0.22)

        self._desenhar_gradiente_radial(
            contexto_cg,
            centro_x,
            centro_y,
            0.0,
            raio_halo_externo,
            [
                (0.00, 239.0, 68.0, 68.0, opacidade_centro_halo),
                (0.42, 220.0, 38.0, 38.0, opacidade_meio_halo),
                (0.76, 165.0, 28.0, 28.0, opacidade_meio_halo * 0.34),
                (1.00, 127.0, 29.0, 29.0, 0.0),
            ],
        )

        # 2. Duas ondas de névoa acústica concêntricas ultra-suaves moduladas pela voz
        velocidade_nevoa = 0.58 + (nivel_voz * 0.35)
        for indice_onda in range(2):
            fase_onda = (tempo_decorrido * velocidade_nevoa + indice_onda * 0.5) % 1.0
            decaimento_onda = (1.0 - fase_onda) ** 1.65
            opacidade_pico_nevoa = decaimento_onda * (0.075 + nivel_voz * 0.19)

            alcance_onda = min(
                104.0,
                34.0 + fase_onda * (42.0 + nivel_voz * 26.0),
            )
            inicio_onda = max(0.0, alcance_onda * 0.24)

            self._desenhar_gradiente_radial(
                contexto_cg,
                centro_x,
                centro_y,
                inicio_onda,
                alcance_onda,
                [
                    (0.00, 248.0, 113.0, 113.0, 0.0),
                    (0.45, 239.0, 68.0, 68.0, opacidade_pico_nevoa),
                    (0.78, 185.0, 28.0, 28.0, opacidade_pico_nevoa * 0.38),
                    (1.00, 127.0, 29.0, 29.0, 0.0),
                ],
            )

        # 3. Núcleo luminoso interno rubi-coral quente difuso
        raio_nucleo = 19.0 + (respiracao_suave * 2.2) + (nivel_voz * 21.0)
        opacidade_coral = 0.42 + (respiracao_suave * 0.05) + (nivel_voz * 0.44)
        opacidade_rubi_interno = 0.22 + (nivel_voz * 0.25)

        self._desenhar_gradiente_radial(
            contexto_cg,
            centro_x,
            centro_y,
            0.0,
            raio_nucleo,
            [
                (0.00, 255.0, 160.0, 155.0, opacidade_coral),
                (0.46, 239.0, 68.0, 68.0, opacidade_rubi_interno),
                (1.00, 220.0, 38.0, 38.0, 0.0),
            ],
        )

    def _desenhar_modo_processando(
        self,
        contexto_cg,
        centro_x: float,
        centro_y: float,
        tempo_decorrido: float,
    ) -> None:
        """Desenha halo difuso âmbar/rubi suave acompanhado de arco fino minimalista."""
        pulsacao = 0.5 + 0.5 * math.sin(tempo_decorrido * 3.1)
        raio_halo = 56.0 + pulsacao * 5.0

        self._desenhar_gradiente_radial(
            contexto_cg,
            centro_x,
            centro_y,
            0.0,
            raio_halo,
            [
                (0.00, 245.0, 158.0, 11.0, 0.34 + pulsacao * 0.05),
                (0.45, 225.0, 62.0, 45.0, 0.17 + pulsacao * 0.03),
                (0.80, 153.0, 27.0, 27.0, 0.05),
                (1.00, 127.0, 29.0, 29.0, 0.0),
            ],
        )

        raio_nucleo = 21.0 + pulsacao * 2.0
        self._desenhar_gradiente_radial(
            contexto_cg,
            centro_x,
            centro_y,
            0.0,
            raio_nucleo,
            [
                (0.00, 254.0, 215.0, 155.0, 0.48),
                (0.52, 245.0, 130.0, 50.0, 0.21),
                (1.00, 239.0, 68.0, 68.0, 0.0),
            ],
        )

        # Arco fino minimalista anti-aliased girando ao redor do centro luminoso
        angulo_inicial = -(tempo_decorrido * 3.4) % (2.0 * math.pi)
        angulo_final = angulo_inicial - (math.pi * 0.68)
        raio_arco = 25.5

        Quartz.CGContextSaveGState(contexto_cg)
        Quartz.CGContextSetLineCap(contexto_cg, Quartz.kCGLineCapRound)

        # Trilha sutil de fundo
        Quartz.CGContextSetLineWidth(contexto_cg, 1.4)
        Quartz.CGContextSetRGBStrokeColor(contexto_cg, 245.0 / 255.0, 158.0 / 255.0, 90.0 / 255.0, 0.14)
        Quartz.CGContextAddArc(contexto_cg, centro_x, centro_y, raio_arco, 0.0, 2.0 * math.pi, 0)
        Quartz.CGContextStrokePath(contexto_cg)

        # Arco principal luminoso
        Quartz.CGContextSetLineWidth(contexto_cg, 1.85)
        Quartz.CGContextSetRGBStrokeColor(contexto_cg, 254.0 / 255.0, 215.0 / 255.0, 165.0 / 255.0, 0.78)
        Quartz.CGContextAddArc(contexto_cg, centro_x, centro_y, raio_arco, angulo_inicial, angulo_final, 1)
        Quartz.CGContextStrokePath(contexto_cg)
        Quartz.CGContextRestoreGState(contexto_cg)

    def _desenhar_modo_esvaindo(
        self,
        contexto_cg,
        centro_x: float,
        centro_y: float,
        progresso: float,
    ) -> None:
        """Dissolução elegante em 0.35s com contração suave e decaimento exponencial."""
        progresso_seguro = _limitar_intervalo(progresso, 0.0, 1.0)
        fator_exponencial = math.exp(-4.0 * progresso_seguro) * (1.0 - progresso_seguro)
        fator_contracao = 1.0 - (0.38 * (progresso_seguro ** 1.25))

        raio_base = (52.0 + self._nivel_congelado * 28.0) * fator_contracao
        raio_nucleo = (20.0 + self._nivel_congelado * 12.0) * fator_contracao

        if self._modo_anterior_ativo == "processing":
            cor_primaria = (245.0, 140.0, 45.0)
        else:
            cor_primaria = (239.0, 68.0, 68.0)

        self._desenhar_gradiente_radial(
            contexto_cg,
            centro_x,
            centro_y,
            0.0,
            raio_base,
            [
                (0.00, cor_primaria[0], cor_primaria[1], cor_primaria[2], 0.34 * fator_exponencial),
                (0.48, 220.0, 38.0, 38.0, 0.16 * fator_exponencial),
                (1.00, 127.0, 29.0, 29.0, 0.0),
            ],
        )

        self._desenhar_gradiente_radial(
            contexto_cg,
            centro_x,
            centro_y,
            0.0,
            raio_nucleo,
            [
                (0.00, 255.0, 160.0, 155.0, 0.40 * fator_exponencial),
                (0.55, 239.0, 68.0, 68.0, 0.18 * fator_exponencial),
                (1.00, 220.0, 38.0, 38.0, 0.0),
            ],
        )

    def drawRect_(self, retangulo_sujo):
        contexto_atual = NSGraphicsContext.currentContext()
        if contexto_atual is None:
            return

        contexto_cg = contexto_atual.CGContext()
        limites = self.bounds()
        Quartz.CGContextClearRect(contexto_cg, limites)

        if self._modo_visual == "idle":
            return

        Quartz.CGContextSaveGState(contexto_cg)
        Quartz.CGContextSetAllowsAntialiasing(contexto_cg, True)
        Quartz.CGContextSetShouldAntialias(contexto_cg, True)

        largura = float(limites.size.width)
        altura = float(limites.size.height)
        centro_x = largura * 0.5
        centro_y = altura * 0.5
        agora = time.monotonic()
        tempo_decorrido = agora - self._instante_referencia

        if self._modo_visual == "listening":
            self._desenhar_modo_ouvindo(
                contexto_cg,
                centro_x,
                centro_y,
                tempo_decorrido,
                self._nivel_suavizado,
            )
        elif self._modo_visual == "processing":
            self._desenhar_modo_processando(
                contexto_cg,
                centro_x,
                centro_y,
                tempo_decorrido,
            )
        elif self._modo_visual == "esvaindo":
            progresso = (agora - self._instante_inicio_esvaimento) / DURACAO_DISSOLUCAO_SEGUNDOS
            self._desenhar_modo_esvaindo(
                contexto_cg,
                centro_x,
                centro_y,
                progresso,
            )

        Quartz.CGContextRestoreGState(contexto_cg)


class OverlayFlutuanteNativo:
    """
    Controlador thread-safe do painel transparente NSPanel (220x220 px)
    que hospeda a `VisaoOverlayBrilhoDifuso`.
    """

    def __init__(self) -> None:
        self._painel: Optional[NSPanel] = None
        self._visao: Optional[VisaoOverlayBrilhoDifuso] = None
        self._esta_visivel = False
        self._inicializado = False
        self._modo_solicitado = "idle"
        self._trava = threading.Lock()
        self._evento_parar = threading.Event()
        self._evento_atividade = threading.Event()
        self._thread_quadros: Optional[threading.Thread] = None

    def _garantir_painel_na_thread_principal(self) -> None:
        """Cria e configura o NSPanel transparente caso ainda não exista."""
        if self._inicializado and self._painel is not None and self._visao is not None:
            return

        try:
            quadro_alvo = _obter_quadro_alvo(
                largura=LARGURA_PADRAO_OVERLAY,
                altura=ALTURA_PADRAO_OVERLAY,
            )
            mascara_estilo = (
                AppKit.NSWindowStyleMaskBorderless
                | AppKit.NSWindowStyleMaskNonactivatingPanel
            )

            painel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                quadro_alvo,
                mascara_estilo,
                NSBackingStoreBuffered,
                False,
            )
            painel.setLevel_(AppKit.NSStatusWindowLevel + 2)
            painel.setOpaque_(False)
            painel.setBackgroundColor_(NSColor.clearColor())
            painel.setIgnoresMouseEvents_(True)
            painel.setHasShadow_(False)
            painel.setHidesOnDeactivate_(False)
            painel.setCollectionBehavior_(
                AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                | AppKit.NSWindowCollectionBehaviorStationary
                | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
            )

            quadro_interno = NSMakeRect(
                0.0,
                0.0,
                LARGURA_PADRAO_OVERLAY,
                ALTURA_PADRAO_OVERLAY,
            )
            visao = VisaoOverlayBrilhoDifuso.alloc().initWithFrame_(quadro_interno)
            painel.setContentView_(visao)

            self._painel = painel
            self._visao = visao
            self._inicializado = True
        except Exception as erro:
            print(f"[OVERLAY] Falha ao inicializar painel difuso: {erro}")

    def _reposicionar_painel_se_necessario(self) -> None:
        """Mantém o painel centralizado caso a resolução ou monitor ativo mude."""
        if self._painel is None:
            return
        quadro_alvo = _obter_quadro_alvo(
            largura=LARGURA_PADRAO_OVERLAY,
            altura=ALTURA_PADRAO_OVERLAY,
        )
        self._painel.setFrame_display_(quadro_alvo, False)

    def _laco_renderizacao(self) -> None:
        """
        Laço de quadros (~50fps) ativo apenas enquanto o brilho estiver em exibição
        ou em dissolução, mantendo consumo zero de CPU quando ocioso.
        """
        while not self._evento_parar.is_set():
            self._evento_atividade.wait()
            if self._evento_parar.is_set():
                break

            nivel_capturado = float(getattr(gravador, "nivel_atual", 0.0) or 0.0)

            def _atualizar_quadro_interface(nivel_local: float = nivel_capturado) -> None:
                if self._visao is None or self._painel is None:
                    return
                continua_ativo = self._visao.atualizar_animacao(nivel_local)
                if not continua_ativo and self._modo_solicitado == "idle":
                    if self._esta_visivel:
                        self._painel.orderOut_(None)
                        self._esta_visivel = False
                    self._evento_atividade.clear()

            _executar_na_thread_principal(_atualizar_quadro_interface)
            time.sleep(INTERVALO_QUADRO_SEGUNDOS)

    def iniciar(self) -> None:
        """Inicia o trabalhador de animação do overlay de forma idempotente."""
        with self._trava:
            if self._thread_quadros is not None and self._thread_quadros.is_alive():
                return
            self._evento_parar.clear()
            self._thread_quadros = threading.Thread(
                target=self._laco_renderizacao,
                name="OverlayBrilhoDifusoThread",
                daemon=True,
            )
            self._thread_quadros.start()

    def definir_modo(self, modo: str) -> None:
        """
        Define o modo operacional do overlay: 'idle', 'listening' ou 'processing'.
        Idempotente para preservar a dissolução suave de 0.35s ao retornar a 'idle'.
        """
        modo_normalizado = modo if modo in ("idle", "listening", "processing") else "idle"

        with self._trava:
            if modo_normalizado == self._modo_solicitado and (
                modo_normalizado == "idle" or self._esta_visivel
            ):
                return
            self._modo_solicitado = modo_normalizado

        if modo_normalizado in ("listening", "processing"):
            self.iniciar()

        def _aplicar_modo_interface() -> None:
            self._garantir_painel_na_thread_principal()
            if self._painel is None or self._visao is None:
                return

            if modo_normalizado in ("listening", "processing"):
                self._reposicionar_painel_se_necessario()
                self._visao.definir_modo_visual(modo_normalizado)
                if not self._esta_visivel:
                    self._painel.orderFrontRegardless()
                    self._esta_visivel = True
                self._evento_atividade.set()
            else:
                if self._esta_visivel:
                    self._visao.definir_modo_visual("idle")
                    self._evento_atividade.set()
                else:
                    self._visao.forcar_ocultacao_imediata()
                    self._evento_atividade.clear()

        _executar_na_thread_principal(_aplicar_modo_interface)

    def ocultar(self) -> None:
        """Solicita o fechamento suave do overlay (dissolução de 0.35s até desaparecer)."""
        self.definir_modo("idle")

    def parar(self) -> None:
        """Encerra imediatamente a thread de renderização e remove o painel da tela."""
        with self._trava:
            self._modo_solicitado = "idle"
            self._evento_parar.set()
            self._evento_atividade.set()

        def _ocultar_imediato_interface() -> None:
            if self._visao is not None:
                self._visao.forcar_ocultacao_imediata()
            if self._painel is not None and self._esta_visivel:
                self._painel.orderOut_(None)
                self._esta_visivel = False

        _executar_na_thread_principal(_ocultar_imediato_interface)


overlay_flutuante = OverlayFlutuanteNativo()
