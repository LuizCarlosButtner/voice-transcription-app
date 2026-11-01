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
