import time
import threading
from typing import Optional
import AppKit
from AppKit import (
    NSPanel, NSColor, NSBackingStoreBuffered, NSScreen,
    NSMakeRect, NSTextField, NSTextAlignmentCenter, NSFont
)

from PyObjCTools import AppHelper

class NativeFloatingOverlay:
    """
    Indicador visual flutuante nativo do macOS (AppKit / Cocoa puro).
    Fica posicionado no topo central (logo abaixo do notch do Mac).
    - Quando GRAVANDO: aparece piscando em vermelho (🔴 REC).
    - Quando TRANSCREVENDO: fica amarelo com animação de pontos (🟡 REC...).
    - Quando OCIOSO: DESAPARECE completamente da tela para não atrapalhar o usuário!
    """
    def __init__(self):
        self._panel = None
        self._label = None
        self._is_visible = False
        self._lock = threading.Lock()
        self._setup_done = False

    def _ensure_panel(self):
        if self._setup_done and self._panel is not None:
            return

        try:
            screen = NSScreen.mainScreen()
            if not screen:
                return
            s_frame = screen.frame()
            w, h = 136, 32
            x = (s_frame.size.width - w) / 2
            y = s_frame.size.height - h - 6  # Centralizado no topo, logo abaixo do notch

            rect = NSMakeRect(x, y, w, h)
            style = 0 | (1 << 7)  # NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
            self._panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                rect, style, NSBackingStoreBuffered, False
            )
            # Nível flutuante acima até de apps em tela cheia (F11)
            self._panel.setLevel_(AppKit.NSStatusWindowLevel + 2)
            self._panel.setOpaque_(False)
            self._panel.setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.08, 0.08, 0.12, 0.94))
            self._panel.setIgnoresMouseEvents_(True)  # Cliques passam direto para o app de trás
            self._panel.setHasShadow_(True)

            self._label = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 4, w, 24))
            self._label.setBezeled_(False)
            self._label.setDrawsBackground_(False)
            self._label.setEditable_(False)
            self._label.setSelectable_(False)
            self._label.setAlignment_(NSTextAlignmentCenter)
            self._label.setStringValue_("")
            self._label.setTextColor_(NSColor.whiteColor())
            self._label.setFont_(NSFont.boldSystemFontOfSize_(12))
            self._panel.contentView().addSubview_(self._label)

            self._setup_done = True
        except Exception as e:
            print(f"[OVERLAY] Erro ao inicializar painel AppKit: {e}")

    def update(self, text: str, show: bool = True):
        def _apply():
            self._ensure_panel()
            if not self._panel or not self._label:
                return

            if show:
                self._label.setStringValue_(text)
                if not self._is_visible:
                    self._panel.orderFront_(None)
                    self._is_visible = True
            else:
                if self._is_visible:
                    self._panel.orderOut_(None)
                    self._is_visible = False

        # Garante execução na thread principal do Cocoa
        if AppKit.NSThread.isMainThread():
            _apply()
        else:
            AppHelper.callAfter(_apply)

    def hide(self):
        self.update("", show=False)

    def start(self):
        pass

    def stop(self):
        self.hide()

floating_overlay = NativeFloatingOverlay()
