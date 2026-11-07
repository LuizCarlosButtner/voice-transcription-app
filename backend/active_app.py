from typing import Dict, Any, Tuple, Optional, List, Iterator
from AppKit import NSWorkspace
import ApplicationServices as AS

TEXT_INPUT_ROLES = {
    "AXTextField",
    "AXTextArea",
    "AXTextView",
    "AXSearchField",
    "AXComboBox"
}

# Papéis de "contêiner" que podem ter um input editável descendente (ex.: web views)
_CONTAINER_ROLES = {"AXWebArea", "AXGroup", "AXScrollArea", "AXWindow", "AXTabGroup"}


def _role_of(element) -> str:
    """Retorna o papel AX do elemento (string), ou 'Unknown' em falha."""
    try:
        err, role = AS.AXUIElementCopyAttributeValue(element, AS.kAXRoleAttribute, None)
        return str(role) if err == 0 and role else "Unknown"
    except Exception:
        return "Unknown"


def _is_editable(element) -> bool:
    """True se o elemento é um campo de texto editável (papel ou faixa de seleção)."""
    role = _role_of(element)
    if role in TEXT_INPUT_ROLES:
        return True
    try:
        err, _ = AS.AXUIElementCopyAttributeValue(element, AS.kAXSelectedTextRangeAttribute, None)
        if err == 0:
            return True
    except Exception:
        pass
    return False


def _children_of(element) -> List[Any]:
    """Filhos AX diretos do elemento (lista vazia em falha)."""
    try:
        err, children = AS.AXUIElementCopyAttributeValue(element, AS.kAXChildrenAttribute, None)
        if err == 0 and children:
            return list(children)
    except Exception:
        pass
    return []


def _walk_ax(root, max_depth: int = 8) -> Iterator[Any]:
    """Percorre a árvore AX em largura, devolvendo cada elemento (com teto de profundidade)."""
    if max_depth <= 0:
        return
    for child in _children_of(root):
        yield child
        if _role_of(child) in _CONTAINER_ROLES or _children_of(child):
            yield from _walk_ax(child, max_depth - 1)

def is_accessibility_trusted(prompt: bool = False) -> bool:
    """Verifica se o processo possui permissão de Acessibilidade no macOS."""
    if prompt:
        options = {AS.kAXTrustedCheckOptionPrompt: True}
        return bool(AS.AXIsProcessTrustedWithOptions(options))
    return bool(AS.AXIsProcessTrusted())

def get_frontmost_app() -> Dict[str, Any]:
    """Retorna metadados do aplicativo ativo em primeiro plano."""
    workspace = NSWorkspace.sharedWorkspace()
    app = workspace.frontmostApplication()
    if not app:
        return {
            "name": "Desconhecido",
            "bundle_id": None,
            "pid": 0
        }
    return {
        "name": str(app.localizedName() or "Desconhecido"),
        "bundle_id": str(app.bundleIdentifier() or ""),
        "pid": int(app.processIdentifier())
    }

def has_focused_text_input() -> Tuple[bool, str, Optional[str]]:
    """
    Guarda de foco PERMISSIVA.
    Retorna (has_focus: bool, app_name: str, focused_role: Optional[str]).

    IMPORTANTE (diagnóstico real 01/11): o Chrome/Chromium NÃO expõe o elemento
    focado de forma confiável via AXFocusedUIElementAttribute — retorna
    kAXErrorCannotComplete (-25212). Nesses casos, NÃO devemos concluir que
    "não há foco": o Cmd+V no cursor continua funcionando normalmente no app.
    Portanto, em qualquer erro/indeterminação do AX, assumimos que há foco
    (comportamento permissivo), evitando o falso "nenhum campo selecionado".
    """
    app_info = get_frontmost_app()
    app_name = app_info["name"]
    pid = app_info["pid"]

    if pid <= 0:
        return False, app_name, None

    # Sem acessibilidade concedida, não conseguimos inspecionar; assume foco (permissivo)
    if not is_accessibility_trusted(prompt=False):
        return True, app_name, "AXPermissionPending"

    try:
        app_ax = AS.AXUIElementCreateApplication(pid)
        err, focused_elem = AS.AXUIElementCopyAttributeValue(app_ax, AS.kAXFocusedUIElementAttribute, None)

        # Se o AX não conseguiu determinar o foco (erro -25212 cannot-complete,
        # -25204 api-disabled, etc.), assume que há foco para não bloquear a colagem.
        if err != 0 or not focused_elem:
            return True, app_name, "AXFocusAssumed"

        err_role, role = AS.AXUIElementCopyAttributeValue(focused_elem, AS.kAXRoleAttribute, None)
        role_str = str(role) if err_role == 0 and role else "Unknown"

        # Campo de texto explícito
        if role_str in TEXT_INPUT_ROLES:
            return True, app_name, role_str

        # Possui seleção de texto ativa (indica campo editável)
        err_val, _ = AS.AXUIElementCopyAttributeValue(focused_elem, AS.kAXSelectedTextRangeAttribute, None)
        if err_val == 0:
            return True, app_name, f"{role_str}:SelectedRange"

        # Web view / grupo com ancestral editável (ex: navegadores)
        if "Web" in role_str or role_str == "AXGroup":
            return True, app_name, f"{role_str}:Editable"

        # Chegou até aqui com um papel conhecido e não-editável.
        # Ainda assim, para não perder a colagem em apps que reportam papel genérico,
        # retornamos permissivo. (A colagem via Cmd+V é decidida pelo cursor do SO.)
        return True, app_name, role_str

    except Exception:
        # Qualquer exceção de inspeção: assume foco (permissivo)
        return True, app_name, "AXExceptionAssumed"


def find_focused_editable() -> Tuple[bool, str, Optional[Any]]:
    """
    Detecção de foco ESTRITA (usada pelo pipeline de inserção).

    Retorna (is_editable_focused, app_name, focused_element).

    Diferente de `has_focused_text_input` (permissiva), aqui só retorna True
    quando o elemento focado é EXPLICITAMENTE editável (TEXT_INPUT_ROLES ou com
    AXSelectedTextRange). Em indeterminação de AX (Chrome/Electron = -25212,
    papel genérico sem descendente editável), retorna False — o que dispara a
    "caça" de input do Jeito 1 e, na falta dele, o "mouse engordando" do Jeito 2.
    """
    app_info = get_frontmost_app()
    app_name = app_info["name"]
    pid = app_info["pid"]

    if pid <= 0:
        return False, app_name, None

    if not is_accessibility_trusted(prompt=False):
        return False, app_name, None

    try:
        app_ax = AS.AXUIElementCreateApplication(pid)
        err, focused_elem = AS.AXUIElementCopyAttributeValue(app_ax, AS.kAXFocusedUIElementAttribute, None)
        if err != 0 or not focused_elem:
            return False, app_name, None

        if _is_editable(focused_elem):
            return True, app_name, focused_elem

        # Foco em um contêiner (web view / grupo): confirma se há um campo
        # editável descendente realmente focado.
        for elem in _walk_ax(focused_elem, max_depth=6):
            if _is_editable(elem):
                return True, app_name, elem

        return False, app_name, focused_elem
    except Exception:
        return False, app_name, None
