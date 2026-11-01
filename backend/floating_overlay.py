import tkinter as tk
import threading
import time
from typing import Optional

class FloatingStatusOverlay:
    """
    Indicador visual flutuante na tela (Always-on-top, sem bordas, estilo badge moderno).
    Fica posicionado no topo central (próximo ao notch do Mac) ou canto superior direito,
    exibindo cores pulsantes para Ocioso (Verde), Gravando (Vermelho piscando) e Transcrevendo (Amarelo).
    """
    def __init__(self):
        self._root: Optional[tk.Tk] = None
        self._canvas: Optional[tk.Canvas] = None
        self._dot_item = None
        self._text_item = None
        self._thread: Optional[threading.Thread] = None
        self._current_status = "idle"
        self._detail_text = "Pronto"
        self._running = False
        self._lock = threading.Lock()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._gui_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._root:
            try:
                self._root.after(0, self._root.destroy)
            except Exception:
                pass
        self._root = None

    def set_status(self, status: str, detail: Optional[str] = None):
        with self._lock:
            self._current_status = status
            if detail:
                self._detail_text = detail

    def _gui_loop(self):
        try:
            self._root = tk.Tk()
            self._root.overrideredirect(True)  # Remove barra de título e bordas
            self._root.attributes("-topmost", True)  # Sempre no topo de todas as janelas
            self._root.attributes("-alpha", 0.85)    # Leve transparência elegante
            
            # Deixa a janela flutuante ignorar eventos de clique (clique passa direto)
            try:
                self._root.attributes("-transparent", True)
            except Exception:
                pass

            # Posição: Topo central (próximo ao notch) ou canto superior direito
            # Largura 110px, Altura 32px
            screen_width = self._root.winfo_screenwidth()
            window_width = 110
            window_height = 32
            pos_x = (screen_width // 2) - (window_width // 2)
            pos_y = 8  # Bem no topo, próximo ao notch

            self._root.geometry(f"{window_width}x{window_height}+{pos_x}+{pos_y}")
            self._root.configure(bg="#1e1e2e")

            self._canvas = tk.Canvas(self._root, width=window_width, height=window_height, bg="#1e1e2e", highlightthickness=0)
            self._canvas.pack(fill="both", expand=True)

            # Desenha fundo arredondado/cápsula via retângulo
            self._canvas.create_rectangle(2, 2, window_width-2, window_height-2, fill="#11111b", outline="#313244", width=1, tags="bg")

            # Bolinha indicadora
            self._dot_item = self._canvas.create_oval(12, 10, 24, 22, fill="#22c55e", outline="")

            # Texto de status (REC, IDLE, etc.)
            self._text_item = self._canvas.create_text(34, 16, anchor="w", text="PRONTO", fill="#cdd6f4", font=("SF Pro Display", 11, "bold"))

            # Loop de animação interno do Tkinter
            self._update_animation()
            self._root.mainloop()
        except Exception as e:
            print(f"[OVERLAY] Erro no loop gráfico: {e}")
            self._running = False

    def _update_animation(self):
        if not self._running or not self._root:
            return

        with self._lock:
            st = self._current_status
            dt = self._detail_text

        # Cores e textos por estado
        if st == "listening":
            # Pisca vermelho a cada 500ms
            current_time = time.time()
            is_on = int(current_time * 2) % 2 == 0
            color = "#ef4444" if is_on else "#450a0a"
            dot_color = "#ef4444" if is_on else "#7f1d1d"
            text_label = "REC 🔴" if is_on else "REC ⚫"
            bg_color = "#2a0808" if is_on else "#11111b"
        elif st == "processing":
            color = "#eab308"
            dot_color = "#eab308"
            text_label = "TRANS…"
            bg_color = "#221e08"
        elif st == "no_focus":
            color = "#f97316"
            dot_color = "#f97316"
            text_label = "SEM FOCO"
            bg_color = "#221308"
        elif st == "error":
            color = "#dc2626"
            dot_color = "#dc2626"
            text_label = "ERRO"
            bg_color = "#2a0808"
        else:
            color = "#22c55e"
            dot_color = "#22c55e"
            text_label = "PRONTO"
            bg_color = "#11111b"

        try:
            self._canvas.itemconfig(self._dot_item, fill=dot_color)
            self._canvas.itemconfig(self._text_item, text=text_label)
            self._canvas.itemconfig("bg", fill=bg_color)
        except Exception:
            pass

        # Agenda próxima atualização em 250ms
        if self._root:
            self._root.after(250, self._update_animation)

floating_overlay = FloatingStatusOverlay()
