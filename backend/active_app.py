"""Inspeção de acessibilidade e descoberta de elementos de texto no macOS."""

from collections import deque
from typing import Any, Dict, Iterator, List, Optional, Tuple

from AppKit import NSWorkspace
import ApplicationServices as AS
import Quartz

PAPEIS_CAMPO_TEXTO = {
    "AXTextField",
    "AXTextArea",
    "AXTextView",
    "AXSearchField",
    "AXComboBox",
}

_PAPEIS_NAO_EDITAVEIS = {
    "AXWindow",
    "AXScrollBar",
    "AXSlider",
    "AXCheckBox",
    "AXRadioButton",
    "AXButton",
}

_LIMITE_NOS_ARVORE_AX = 4000


def acessibilidade_ativa(exibir_prompt: bool = False) -> bool:
    """Verifica se o processo atual possui permissão de Acessibilidade no macOS."""
    try:
        if exibir_prompt:
            chave_prompt = getattr(
                AS, "kAXTrustedCheckOptionPrompt", "AXTrustedCheckOptionPrompt"
            )
            opcoes = {chave_prompt: True}
            return bool(AS.AXIsProcessTrustedWithOptions(opcoes))
        return bool(AS.AXIsProcessTrusted())
    except Exception:
        return False


def monitoramento_entrada_ativo() -> bool:
    """Verifica permissão de Monitoramento de Entrada no macOS com contingência segura."""
    try:
        funcao_verificacao = getattr(Quartz, "CGPreflightListenEventAccess", None)
        if funcao_verificacao is None:
            return True
        return bool(funcao_verificacao())
    except Exception:
        return True


def obter_aplicativo_ativo() -> Dict[str, Any]:
    """Retorna os metadados do aplicativo em primeiro plano no macOS."""
    try:
        espaco_trabalho = NSWorkspace.sharedWorkspace()
        aplicativo = espaco_trabalho.frontmostApplication()
    except Exception:
        aplicativo = None

    if not aplicativo:
        return {
            "name": "Desconhecido",
            "bundle_id": "",
            "pid": 0,
        }

    return {
        "name": str(aplicativo.localizedName() or "Desconhecido"),
        "bundle_id": str(aplicativo.bundleIdentifier() or ""),
        "pid": int(aplicativo.processIdentifier() or 0),
    }


def ativar_acessibilidade_aprimorada(elemento_app: Any) -> None:
    """Solicita exposição completa da árvore de acessibilidade para navegadores Chromium e Electron."""
    if elemento_app is None:
        return

    for atributo in ("AXEnhancedUserInterface", "AXManualAccessibility"):
        try:
            AS.AXUIElementSetAttributeValue(elemento_app, atributo, True)
        except Exception:
            pass


def obter_papel_ax(elemento: Any) -> str:
    """Retorna o papel AX do elemento informado ou 'Unknown' caso indisponível."""
    if elemento is None:
        return "Unknown"
    try:
        atributo_papel = getattr(AS, "kAXRoleAttribute", "AXRole")
        erro, papel = AS.AXUIElementCopyAttributeValue(elemento, atributo_papel, None)
        if erro == 0 and papel:
            return str(papel)
    except Exception:
        pass
    return "Unknown"


def obter_atributo_texto_ax(elemento: Any, atributo: str) -> str:
    """Lê um atributo textual da API de acessibilidade do elemento, retornando string vazia em falha."""
    if elemento is None or not atributo:
        return ""
    try:
        erro, valor = AS.AXUIElementCopyAttributeValue(elemento, atributo, None)
        if erro == 0 and valor is not None:
            texto = str(valor).strip()
            return texto
    except Exception:
        pass
    return ""


def eh_elemento_editavel(elemento: Any) -> bool:
    """Verifica de forma estrita se o elemento AX aceita edição real de texto pelo usuário."""
    if elemento is None:
        return False

    try:
        atributo_habilitado = getattr(AS, "kAXEnabledAttribute", "AXEnabled")
        erro_hab, habilitado = AS.AXUIElementCopyAttributeValue(
            elemento, atributo_habilitado, None
        )
        if erro_hab == 0 and habilitado is not None and not bool(habilitado):
            return False
    except Exception:
        pass

    papel = obter_papel_ax(elemento)
    if papel in PAPEIS_CAMPO_TEXTO:
        return True

    try:
        erro_editavel, valor_editavel = AS.AXUIElementCopyAttributeValue(
            elemento, "AXEditable", None
        )
        if erro_editavel == 0 and bool(valor_editavel):
            return True
    except Exception:
        pass

    if papel not in _PAPEIS_NAO_EDITAVEIS:
        try:
            funcao_ajustavel = getattr(AS, "AXUIElementIsAttributeSettable", None)
            if funcao_ajustavel is not None:
                atributo_valor = getattr(AS, "kAXValueAttribute", "AXValue")
                erro_aj, ajustavel = funcao_ajustavel(elemento, atributo_valor, None)
                if erro_aj == 0 and bool(ajustavel):
                    return True
        except Exception:
            pass

    return False


def obter_filhos_ax(elemento: Any) -> List[Any]:
    """Obtém a lista de elementos filhos AX diretos, usando atributos alternativos se necessário."""
    if elemento is None:
        return []

    atributos_filhos = (
        getattr(AS, "kAXChildrenAttribute", "AXChildren"),
        "AXVisibleChildren",
        "AXContents",
    )
    for atributo in atributos_filhos:
        try:
            erro, filhos = AS.AXUIElementCopyAttributeValue(elemento, atributo, None)
            if erro == 0 and filhos:
                lista_filhos = list(filhos)
                if lista_filhos:
                    return lista_filhos
        except Exception:
            continue
    return []


def obter_janela_focada_ax(elemento_app: Any) -> Optional[Any]:
    """Localiza a janela focada do aplicativo, com contingência para janela principal ou primeira janela."""
    if elemento_app is None:
        return None

    for atributo in (
        getattr(AS, "kAXFocusedWindowAttribute", "AXFocusedWindow"),
        getattr(AS, "kAXMainWindowAttribute", "AXMainWindow"),
    ):
        try:
            erro, janela = AS.AXUIElementCopyAttributeValue(elemento_app, atributo, None)
            if erro == 0 and janela is not None:
                return janela
        except Exception:
            pass

    try:
        atributo_janelas = getattr(AS, "kAXWindowsAttribute", "AXWindows")
        erro_janelas, janelas = AS.AXUIElementCopyAttributeValue(
            elemento_app, atributo_janelas, None
        )
        if erro_janelas == 0 and janelas:
            lista_janelas = list(janelas)
            if lista_janelas:
                return lista_janelas[0]
    except Exception:
        pass

    return None


def _elemento_oculto_ax(elemento: Any) -> bool:
    """Retorna True quando o elemento declara explicitamente estar oculto (AXHidden == True)."""
    try:
        erro, oculto = AS.AXUIElementCopyAttributeValue(elemento, "AXHidden", None)
        if erro == 0 and oculto is not None and bool(oculto):
            return True
    except Exception:
        pass
    return False


def _chave_identidade_ax(elemento: Any) -> Any:
    """Gera uma chave estável para evitar ciclos durante a travessia da árvore AX."""
    try:
        hash(elemento)
        return elemento
    except TypeError:
        return ("id_objeto", id(elemento))


def percorrer_arvore_ax_contextual(
    raiz: Any, profundidade_maxima: int = 18
) -> Iterator[Tuple[Any, bool]]:
    """Percorre a árvore AX em largura podando nós ocultos e indicando ancestral AXWebArea."""
    if raiz is None or profundidade_maxima <= 0:
        return
    if _elemento_oculto_ax(raiz):
        return

    papel_raiz = obter_papel_ax(raiz)
    dentro_web_inicial = papel_raiz == "AXWebArea"

    fila = deque([(raiz, 0, dentro_web_inicial)])
    visitados = {_chave_identidade_ax(raiz)}
    nos_inspecionados = 0

    while fila and nos_inspecionados < _LIMITE_NOS_ARVORE_AX:
        elemento_atual, profundidade_atual, ancestral_web = fila.popleft()
        if profundidade_atual >= profundidade_maxima:
            continue

        for filho in obter_filhos_ax(elemento_atual):
            if filho is None:
                continue

            chave_filho = _chave_identidade_ax(filho)
            if chave_filho in visitados:
                continue
            visitados.add(chave_filho)

            nos_inspecionados += 1
            if nos_inspecionados > _LIMITE_NOS_ARVORE_AX:
                break

            if _elemento_oculto_ax(filho):
                continue

            papel_filho = obter_papel_ax(filho)
            dentro_area_web = ancestral_web or (papel_filho == "AXWebArea")
            yield filho, dentro_area_web

            if profundidade_atual + 1 < profundidade_maxima:
                fila.append((filho, profundidade_atual + 1, dentro_area_web))


def percorrer_arvore_ax(raiz: Any, profundidade_maxima: int = 18) -> Iterator[Any]:
    """Percorre a árvore AX em largura podando subárvores ocultas e produzindo cada elemento."""
    for elemento, _ in percorrer_arvore_ax_contextual(
        raiz, profundidade_maxima=profundidade_maxima
    ):
        yield elemento


def possui_campo_texto_focado() -> Tuple[bool, str, Optional[str]]:
    """Guarda permissiva que inspeciona o aplicativo ativo sem bloquear colagem em indeterminação AX."""
    dados_app = obter_aplicativo_ativo()
    nome_app = dados_app["name"]
    pid = dados_app["pid"]

    if pid <= 0:
        return False, nome_app, None

    if not acessibilidade_ativa(exibir_prompt=False):
        return True, nome_app, "AXPermissionPending"

    try:
        elemento_app = AS.AXUIElementCreateApplication(pid)
        ativar_acessibilidade_aprimorada(elemento_app)

        atributo_focado = getattr(
            AS, "kAXFocusedUIElementAttribute", "AXFocusedUIElement"
        )
        erro, elemento_focado = AS.AXUIElementCopyAttributeValue(
            elemento_app, atributo_focado, None
        )
        if erro != 0 or elemento_focado is None:
            return True, nome_app, "AXFocusAssumed"

        papel = obter_papel_ax(elemento_focado)
        if eh_elemento_editavel(elemento_focado):
            return True, nome_app, papel

        if "Web" in papel or papel == "AXGroup":
            return True, nome_app, f"{papel}:Conteiner"

        return True, nome_app, papel
    except Exception:
        return True, nome_app, "AXExceptionAssumed"


def encontrar_editavel_focado() -> Tuple[bool, str, Optional[Any]]:
    """Verifica estritamente se o elemento atualmente em foco no aplicativo ativo é editável."""
    dados_app = obter_aplicativo_ativo()
    nome_app = dados_app["name"]
    pid = dados_app["pid"]

    if pid <= 0:
        return False, nome_app, None

    if not acessibilidade_ativa(exibir_prompt=False):
        return False, nome_app, None

    try:
        elemento_app = AS.AXUIElementCreateApplication(pid)
        ativar_acessibilidade_aprimorada(elemento_app)

        atributo_focado = getattr(
            AS, "kAXFocusedUIElementAttribute", "AXFocusedUIElement"
        )
        erro, elemento_focado = AS.AXUIElementCopyAttributeValue(
            elemento_app, atributo_focado, None
        )
        if erro != 0 or elemento_focado is None:
            return False, nome_app, None

        if eh_elemento_editavel(elemento_focado):
            return True, nome_app, elemento_focado

        return False, nome_app, elemento_focado
    except Exception:
        return False, nome_app, None
