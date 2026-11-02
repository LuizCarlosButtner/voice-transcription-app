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
    Indicador visual flutuante nativo e super discreto do macOS (AppKit puro).
    Fica posicionado centralizado no topo (logo abaixo do notch do Mac).
    - Apenas uma bolinha discreta e limpa (sem caixas, sem divs, sem textos longos).
    - Quando GRAVANDO: bolinha vermelha 🔴 piscando (fade in/out).
    - Quando TRANSCREVENDO: bolinha amarela 🟡 estável.
    - Quando OCIOSO: DESAPARECE completamente da tela.
    - Cliques passam 100% direto (ignoresMouseEvents).
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
            # Janela circular minimalista apenas para a bolinha
            w, h = 26, 26
            x = (s_frame.size.width - w) / 2
            y = s_frame.size.height - h - 4  # Bem no topo, junto ao notch

            rect = NSMakeRect(x, y, w, h)
            style = 0 | (1 << 7)  # Borderless | NonactivatingPanel
            self._panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                rect, style, NSBackingStoreBuffered, False
            )
            self._panel.setLevel_(AppKit.NSStatusWindowLevel + 2)
            self._panel.setOpaque_(False)
            self._panel.setBackgroundColor_(NSColor.clearColor())
            self._panel.setIgnoresMouseEvents_(True)
            self._panel.setHasShadow_(False)

            self._label = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
            self._label.setBezeled_(False)
            self._label.setDrawsBackground_(False)
            self._label.setEditable_(False)
            self._label.setSelectable_(False)
            self._label.setAlignment_(NSTextAlignmentCenter)
            self._label.setStringValue_("")
            self._label.setFont_(NSFont.systemFontOfSize_(16))
            self._panel.contentView().addSubview_(self._label)

            self._setup_done = True
        except Exception as e:
            print(f"[OVERLAY] Erro ao inicializar bolinha: {e}")

    def update_dot(self, dot_emoji: str, show: bool = True):
        def _apply():
            self._ensure_panel()
            if not self._panel or not self._label:
                return

            if show and dot_emoji:
                self._label.setStringValue_(dot_emoji)
                if not self._is_visible:
                    self._panel.orderFront_(None)
                    self._is_visible = True
            else:
                if self._is_visible:
                    self._panel.orderOut_(None)
                    self._is_visible = False

        if AppKit.NSThread.isMainThread():
            _apply()
        else:
            AppHelper.callAfter(_apply)

    def hide(self):
        self.update_dot("", show=False)

    def start(self):
        pass

    def stop(self):
        self.hide()

floating_overlay = NativeFloatingOverlay()
