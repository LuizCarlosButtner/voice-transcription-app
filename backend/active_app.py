from typing import Dict, Any, Tuple, Optional
from AppKit import NSWorkspace
import ApplicationServices as AS

TEXT_INPUT_ROLES = {
    "AXTextField",
    "AXTextArea",
    "AXTextView",
    "AXSearchField",
    "AXComboBox"
}

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
    Guarda de foco: verifica se há um campo de texto ativo e focado no app em primeiro plano.
    Retorna: (has_focus: bool, app_name: str, focused_role: Optional[str])
    """
    app_info = get_frontmost_app()
    app_name = app_info["name"]
    pid = app_info["pid"]

    if pid <= 0:
        return False, app_name, None

    # Se a acessibilidade não estiver habilitada, registramos e permitimos com aviso
    if not is_accessibility_trusted(prompt=False):
        # Sem acessibilidade concedida, não conseguimos inspecionar os nós AX
        # Retornamos permissivo para apps conhecidos de edição
        return True, app_name, "AXPermissionPending"

    try:
        app_ax = AS.AXUIElementCreateApplication(pid)
        err, focused_elem = AS.AXUIElementCopyAttributeValue(app_ax, AS.kAXFocusedUIElementAttribute, None)
        if err != 0 or not focused_elem:
            return False, app_name, None

        err_role, role = AS.AXUIElementCopyAttributeValue(focused_elem, AS.kAXRoleAttribute, None)
        role_str = str(role) if err_role == 0 and role else "Unknown"

        # Verifica se o elemento focado é explicitamente um campo de texto
        if role_str in TEXT_INPUT_ROLES:
            return True, app_name, role_str

        # Em navegadores ou WebViews (ex: Chrome, Slack, VSCode), o elemento pode ser AXWebArea ou genérico
        # mas possuir o atributo de seleção de texto ativa ou valor editável
        err_val, _ = AS.AXUIElementCopyAttributeValue(focused_elem, AS.kAXSelectedTextRangeAttribute, None)
        if err_val == 0:
            return True, app_name, f"{role_str}:SelectedRange"

        # Se for um web view com foco ativo em elemento editável
        if "Web" in role_str or role_str == "AXGroup":
            err_editable, is_editable = AS.AXUIElementCopyAttributeValue(focused_elem, "AXEditableAncestor", None)
            if err_editable == 0 and is_editable:
                return True, app_name, f"{role_str}:Editable"

        return False, app_name, role_str

    except Exception:
        return False, app_name, None
