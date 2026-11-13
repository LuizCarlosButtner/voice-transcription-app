"""Testes automatizados para o brilho flutuante CoreGraphics e a bandeja de menus macOS."""

import threading
import time
from typing import Optional

import AppKit
import pytest
from AppKit import (
    NSBitmapImageRep,
    NSCalibratedRGBColorSpace,
    NSGraphicsContext,
    NSMakeRect,
)


def _renderizar_visao_em_bitmap(visao, largura: int = 220, altura: int = 220):
    """Renderiza uma NSView em um NSBitmapImageRep RGBA offscreen e devolve o bitmap."""
    representacao_bitmap = (
        NSBitmapImageRep.alloc()
        .initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
            None,
            largura,
            altura,
            8,
            4,
            True,
            False,
            NSCalibratedRGBColorSpace,
            0,
            0,
        )
    )
    contexto_grafico = NSGraphicsContext.graphicsContextWithBitmapImageRep_(
        representacao_bitmap
    )

    NSGraphicsContext.saveGraphicsState()
    try:
        NSGraphicsContext.setCurrentContext_(contexto_grafico)
        visao.drawRect_(NSMakeRect(0.0, 0.0, float(largura), float(altura)))
        contexto_grafico.flushGraphics()
    finally:
        NSGraphicsContext.restoreGraphicsState()

    return representacao_bitmap


def _obter_alfa_pixel(bitmap, coord_x: int, coord_y: int) -> float:
    """Extrai o componente alfa [0.0, 1.0] de um pixel específico do bitmap RGBA."""
    cor = bitmap.colorAtX_y_(coord_x, coord_y)
    if cor is None:
        return 0.0
    return float(cor.alphaComponent())


def test_quadro_alvo_e_renderizacao_em_memoria_visao_brilho_difuso():
    """Valida dimensões 220x220px e renderização radial difusa sem corte nas bordas."""
    import floating_overlay

    assert floating_overlay.LARGURA_PADRAO_OVERLAY == 220.0
    assert floating_overlay.ALTURA_PADRAO_OVERLAY == 220.0

    quadro_alvo = floating_overlay._obter_quadro_alvo()
    assert float(quadro_alvo.size.width) == 220.0
    assert float(quadro_alvo.size.height) == 220.0

    visao = floating_overlay.VisaoOverlayBrilhoDifuso.alloc().initWithFrame_(
        NSMakeRect(0.0, 0.0, 220.0, 220.0)
    )
    assert visao is not None
    assert visao.isOpaque() is False

    # 1. Modo 'listening': brilho intenso no centro (110, 110) e alfa 0.0 nas bordas
    visao.definir_modo_visual("listening")
    for _ in range(4):
        assert visao.atualizar_animacao(0.85) is True

    bitmap_ouvindo = _renderizar_visao_em_bitmap(visao, 220, 220)
    assert _obter_alfa_pixel(bitmap_ouvindo, 110, 110) > 0.25
    assert _obter_alfa_pixel(bitmap_ouvindo, 0, 110) == 0.0
    assert _obter_alfa_pixel(bitmap_ouvindo, 219, 110) == 0.0
    assert _obter_alfa_pixel(bitmap_ouvindo, 110, 0) == 0.0
    assert _obter_alfa_pixel(bitmap_ouvindo, 110, 219) == 0.0

    # 2. Modo 'processing': centro luminoso âmbar/rubi e bordas transparentes
    visao.definir_modo_visual("processing")
    assert visao.atualizar_animacao(0.0) is True

    bitmap_processando = _renderizar_visao_em_bitmap(visao, 220, 220)
    assert _obter_alfa_pixel(bitmap_processando, 110, 110) > 0.20
    assert _obter_alfa_pixel(bitmap_processando, 0, 110) == 0.0
    assert _obter_alfa_pixel(bitmap_processando, 219, 110) == 0.0

    # 3. Transição para 'idle' entra em 'esvaindo' (dissolução suave de 0.35s)
    visao.definir_modo_visual("idle")
    assert visao._modo_visual == "esvaindo"
    bitmap_esvaindo = _renderizar_visao_em_bitmap(visao, 220, 220)
    assert _obter_alfa_pixel(bitmap_esvaindo, 110, 110) > 0.0
    assert _obter_alfa_pixel(bitmap_esvaindo, 0, 110) == 0.0
    assert _obter_alfa_pixel(bitmap_esvaindo, 219, 110) == 0.0

    # 4. Ocultação imediata ('idle' puro): transparência total inclusive no centro
    visao.forcar_ocultacao_imediata()
    assert visao.atualizar_animacao(0.0) is False
    bitmap_ocioso = _renderizar_visao_em_bitmap(visao, 220, 220)
    assert _obter_alfa_pixel(bitmap_ocioso, 110, 110) == 0.0


def test_ciclo_vida_overlay_flutuante_nativo_encerra_threads(
    monkeypatch: pytest.MonkeyPatch,
):
    """Testa iniciar, definir_modo, ocultar e parar garantindo encerramento de threads."""
    import floating_overlay

    # Intercepta despacho de UI para evitar dependência de WindowServer ativo em ambiente headless
    operacoes_despachadas: list[str] = []

    class PainelSimulado:
        def setFrame_display_(self, _quadro, _exibir):
            operacoes_despachadas.append("reposicionar")

        def orderFrontRegardless(self):
            operacoes_despachadas.append("exibir")

        def orderOut_(self, _remetente):
            operacoes_despachadas.append("ocultar")

    controlador = floating_overlay.OverlayFlutuanteNativo()

    def garantir_painel_falso() -> None:
        if controlador._inicializado:
            return
        controlador._painel = PainelSimulado()
        controlador._visao = floating_overlay.VisaoOverlayBrilhoDifuso.alloc().initWithFrame_(
            NSMakeRect(0.0, 0.0, 220.0, 220.0)
        )
        controlador._inicializado = True

    monkeypatch.setattr(
        controlador, "_garantir_painel_na_thread_principal", garantir_painel_falso
    )
    monkeypatch.setattr(
        floating_overlay, "_executar_na_thread_principal", lambda acao: acao()
    )

    try:
        controlador.iniciar()
        assert controlador._thread_quadros is not None
        assert controlador._thread_quadros.is_alive() is True

        controlador.definir_modo("listening")
        assert controlador._esta_visivel is True
        assert "exibir" in operacoes_despachadas

        controlador.definir_modo("processing")
        assert controlador._modo_solicitado == "processing"

        controlador.ocultar()
        assert controlador._modo_solicitado == "idle"
    finally:
        controlador.parar()
        if controlador._thread_quadros is not None:
            controlador._thread_quadros.join(timeout=1.5)
            assert controlador._thread_quadros.is_alive() is False


def test_bandeja_menus_modos_acionamento_autoteste_e_seguranca_threads(
    monkeypatch: pytest.MonkeyPatch,
):
    """Valida AplicativoBandejaVoz: 3 modos, autoteste e despacho AppHelper.callAfter."""
    import config
    import floating_overlay
    import protocolo_inicializacao as mod_proto
    import status_icon

    notificacoes_emitidas: list[tuple[str, str, str]] = []
    chamadas_despacho_principal: list = []

    monkeypatch.setattr(
        status_icon,
        "_notificar_usuario",
        lambda titulo, subtitulo, msg: notificacoes_emitidas.append((titulo, subtitulo, msg)),
    )
    monkeypatch.setattr(floating_overlay.overlay_flutuante, "iniciar", lambda: None)
    monkeypatch.setattr(floating_overlay.overlay_flutuante, "definir_modo", lambda _m: None)
    monkeypatch.setattr(floating_overlay.overlay_flutuante, "ocultar", lambda: None)
    monkeypatch.setattr(floating_overlay.overlay_flutuante, "parar", lambda: None)

    monkeypatch.setattr(
        status_icon.AppHelper,
        "callAfter",
        lambda operacao, *args, **kwargs: chamadas_despacho_principal.append((operacao, args, kwargs)),
    )

    class ServicoReferenciaSimulado:
        def __init__(self):
            self.chamadas_gravar_manual = 0
            self.chamadas_parar_manual = 0

        def iniciar_gravacao_manual(self):
            self.chamadas_gravar_manual += 1

        def parar_gravacao_manual(self):
            self.chamadas_parar_manual += 1

        def parar_escuta(self):
            pass

    servico_sim = ServicoReferenciaSimulado()
    app_bandeja = status_icon.criar_app_bandeja(servico_ref=servico_sim)

    try:
        # 1. Verifica os 3 modos de acionamento no submenu
        assert set(app_bandeja._itens_modo_acionamento.keys()) == {
            "hibrido",
            "segurar",
            "alternar",
        }

        for modo_esperado in ("segurar", "alternar", "hibrido"):
            item_menu = app_bandeja._itens_modo_acionamento[modo_esperado]
            item_menu.callback(item_menu)
            assert config.obter_configuracoes().modo_acionamento == modo_esperado
            assert app_bandeja._itens_modo_acionamento[modo_esperado].state == 1
            for outro_modo, outro_item in app_bandeja._itens_modo_acionamento.items():
                if outro_modo != modo_esperado:
                    assert outro_item.state == 0

        # 2. Testa execução sob demanda do autoteste de inicialização
        evento_autoteste = threading.Event()
        referencias_recebidas: list = []

        def autoteste_simulado(servico_voz_ref=None, recarregar_audio: bool = True) -> dict:
            _ = recarregar_audio
            referencias_recebidas.append(servico_voz_ref)
            evento_autoteste.set()
            return {
                "ok": True,
                "executado_em": "2026-11-13T05:00:00",
                "duracao_ms": 18,
                "etapas": {
                    "armazenamento_banco": {"ok": True},
                    "chaves_provedores": {"ok": True},
                    "permissoes_macos": {"ok": True},
                    "subsistema_audio": {"ok": True},
                    "escutador_atalho": {"ok": True},
                },
            }

        monkeypatch.setattr(
            mod_proto.protocolo_inicializacao, "executar_autoteste", autoteste_simulado
        )
        app_bandeja.ao_executar_autoteste(app_bandeja.item_autoteste)
        assert evento_autoteste.wait(timeout=2.0) is True
        time.sleep(0.05)
        assert referencias_recebidas == [servico_sim]
        assert any("100% Saudável" in sub for _tit, sub, _msg in notificacoes_emitidas)

        # 3. Garante despacho via AppHelper.callAfter quando atualizar_status roda em thread secundária
        chamadas_despacho_principal.clear()
        erro_thread: list[Optional[BaseException]] = []

        def chamar_de_thread_secundaria() -> None:
            try:
                assert AppKit.NSThread.isMainThread() is False
                app_bandeja.atualizar_status("listening", "Capturando microfone")
            except BaseException as exc:
                erro_thread.append(exc)

        trabalhador = threading.Thread(target=chamar_de_thread_secundaria)
        trabalhador.start()
        trabalhador.join(timeout=2.0)

        assert erro_thread == []
        assert len(chamadas_despacho_principal) >= 1

        # Executa na thread principal a operação enfileirada no AppHelper.callAfter
        for operacao_pendente, args_p, kwargs_p in list(chamadas_despacho_principal):
            operacao_pendente(*args_p, **kwargs_p)

        assert app_bandeja.title == "🔴 REC"
        assert "Capturando microfone" in app_bandeja.item_status.title
        assert "Parar Gravação" in app_bandeja.item_gravar.title
    finally:
        app_bandeja._evento_parar_animacao.set()
        if app_bandeja._thread_animacao is not None:
            app_bandeja._thread_animacao.join(timeout=1.0)
        floating_overlay.overlay_flutuante.parar()
