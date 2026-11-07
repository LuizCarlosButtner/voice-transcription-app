"""Caça de input editável visível (Jeito 1 do fallback de inserção).

Quando não há campo focado, percorre a árvore AX do app em primeiro plano,
localiza campos de texto editáveis que estejam VISÍVEIS (com posição/tamanho
e não ocultos) e devolve o melhor candidato (maior área). O chamador então
foca o elemento e insere o texto.
"""
from typing import Optional, Any, List
import ApplicationServices as AS
from AppKit import NSScreen
try:
    from active_app import (
        get_frontmost_app,
        _role_of,
        _is_editable,
        _children_of,
        _walk_ax,
    )
except ImportError:
    from backend.active_app import (
        get_frontmost_app,
        _role_of,
        _is_editable,
        _children_of,
        _walk_ax,
    )


def _screen_bounds():
    """Retorna (min_x, min_y, max_x, max_y) da união de todas as telas."""
    try:
        screens = NSScreen.screens()
        if not screens:
            return None
        frames = [s.frame() for s in screens]
        min_x = min(f.origin.x for f in frames)
        min_y = min(f.origin.y for f in frames)
        max_x = max(f.origin.x + f.size.width for f in frames)
        max_y = max(f.origin.y + f.size.height for f in frames)
        return (min_x, min_y, max_x, max_y)
    except Exception:
        return None


def _element_frame(element) -> Optional[tuple]:
    """Extrai (x, y, w, h) do elemento via AXPosition/AXSize, best-effort.

    Retorna None se não for possível (não exposto / oculto).
    """
    try:
        err_p, pos_val = AS.AXUIElementCopyAttributeValue(element, AS.kAXPositionAttribute, None)
        err_s, size_val = AS.AXUIElementCopyAttributeValue(element, AS.kAXSizeAttribute, None)
        if err_p != 0 or err_s != 0:
            return None
        # AXValue -> CGPoint / CGSize
        ok_p, point = AS.AXValueGetValue(pos_val, AS.kAXValueTypeCGPoint, None)
        ok_s, size = AS.AXValueGetValue(size_val, AS.kAXValueTypeCGSize, None)
        if not ok_p or not ok_s:
            return None
        x = float(point.x) if hasattr(point, 'x') else float(point[0])
        y = float(point.y) if hasattr(point, 'y') else float(point[1])
        w = float(size.width) if hasattr(size, 'width') else float(size[0])
        h = float(size.height) if hasattr(size, 'height') else float(size[1])
        return (x, y, w, h)
    except Exception:
        return None


def _is_visible(element) -> bool:
    """Elemento é visível? (não oculto, com frame dentro de alguma tela, área > 0)."""
    try:
        err_h, hidden = AS.AXUIElementCopyAttributeValue(element, "AXHidden", None)
        if err_h == 0 and bool(hidden):
            return False
    except Exception:
        pass

    frame = _element_frame(element)
    if frame is None:
        return False
    x, y, w, h = frame
    if w <= 0 or h <= 0:
        return False

    bounds = _screen_bounds()
    if bounds is not None:
        min_x, min_y, max_x, max_y = bounds
        # Tolera o centro do elemento estar dentro da tela (evita falso-negativo
        # em apps que reportam coordenadas ligeiramente fora).
        cx = x + w / 2.0
        cy = y + h / 2.0
        if not (min_x - 2 <= cx <= max_x + 2 and min_y - 2 <= cy <= max_y + 2):
            return False
    return True


def _visible_editable_inputs(app_ax, max_depth: int = 8) -> List[tuple]:
    """Lista de (area, element) dos inputs editáveis e visíveis da árvore AX."""
    found: List[tuple] = []
    seen = set()
    for elem in _walk_ax(app_ax, max_depth=max_depth):
        try:
            ident = id(elem)
            if ident in seen:
                continue
            seen.add(ident)
        except Exception:
            pass
        if not _is_editable(elem):
            continue
        if not _is_visible(elem):
            continue
        frame = _element_frame(elem)
        area = (frame[2] * frame[3]) if frame else 1.0
        found.append((area, elem))
    return found


def hunt_visible_input() -> Optional[Any]:
    """Procura o melhor campo editável visível no app em primeiro plano.

    Retorna o elemento AX (para focar/inserir) ou None se nada editável visível.
    """
    app_info = get_frontmost_app()
    pid = app_info.get("pid") or 0
    if pid <= 0:
        return None

    try:
        app_ax = AS.AXUIElementCreateApplication(pid)
    except Exception:
        return None

    inputs = _visible_editable_inputs(app_ax)
    if not inputs:
        return None

    # Maior área visível primeiro (campo de escrita é normalmente o maior input)
    inputs.sort(key=lambda t: t[0], reverse=True)
    return inputs[0][1]


def focus_element(element) -> bool:
    """Tenta dar foco ao elemento AX (press action e/ou kAXFocusedAttribute)."""
    try:
        err = AS.AXUIElementPerformAction(element, AS.kAXPressAction)
        if err == 0:
            return True
    except Exception:
        pass
    try:
        err = AS.AXUIElementSetAttributeValue(element, AS.kAXFocusedAttribute, True)
        return err == 0
    except Exception:
        return False
