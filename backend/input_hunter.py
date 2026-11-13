"""Caçador inteligente de campos de entrada editáveis visíveis na janela ativa."""

import math
import time
from typing import Any, List, Optional, Tuple

from AppKit import NSScreen
import ApplicationServices as AS
import Quartz

try:
    import config as _modulo_configuracao
    from config import obter_configuracoes
except ImportError:
    from backend import config as _modulo_configuracao
    from backend.config import obter_configuracoes

try:
    import active_app as _modulo_aplicativo_ativo
    from active_app import (
        ativar_acessibilidade_aprimorada,
        eh_elemento_editavel,
        obter_aplicativo_ativo,
        obter_atributo_texto_ax,
        obter_janela_focada_ax,
        obter_papel_ax,
        percorrer_arvore_ax_contextual,
    )
except ImportError:
    from backend import active_app as _modulo_aplicativo_ativo
    from backend.active_app import (
        ativar_acessibilidade_aprimorada,
        eh_elemento_editavel,
        obter_aplicativo_ativo,
        obter_atributo_texto_ax,
        obter_janela_focada_ax,
        obter_papel_ax,
        percorrer_arvore_ax_contextual,
    )

_referencia_inicial_config = obter_configuracoes
_referencia_inicial_app_ativo = obter_aplicativo_ativo


def _ler_configuracoes_atuais() -> Any:
    """Obtém as configurações respeitando substituição em testes tanto neste módulo quanto em config."""
    if obter_configuracoes is not _referencia_inicial_config:
        return obter_configuracoes()
    return _modulo_configuracao.obter_configuracoes()


def _ler_aplicativo_ativo_atual() -> dict:
    """Obtém o aplicativo ativo respeitando substituição em testes neste módulo ou em active_app."""
    if obter_aplicativo_ativo is not _referencia_inicial_app_ativo:
        return obter_aplicativo_ativo()
    return _modulo_aplicativo_ativo.obter_aplicativo_ativo()

_TERMOS_SEMANTICOS_CHAT = (
    "mensagem",
    "message",
    "chat",
    "prompt",
    "digite",
    "pergunt",
    "ask",
    "escrev",
    "reply",
    "resposta",
)

_TERMOS_BARRA_ENDERECO = (
    "address",
    "endereço",
    "endereco",
    "url",
    "omnibox",
    "pesquisar ou digitar",
)

_ATRIBUTOS_DESCRICAO_AX = (
    "AXPlaceholderValue",
    "AXDescription",
    "AXTitle",
    "AXRoleDescription",
    "AXSubrole",
)


def _obter_limites_telas() -> Optional[Tuple[float, float, float, float]]:
    """Retorna (min_x, min_y, max_x, max_y) da união de todas as telas ativas."""
    limites_coletados: List[Tuple[float, float, float, float]] = []

    try:
        funcao_telas_quartz = getattr(Quartz, "CGGetActiveDisplayList", None)
        funcao_quadro_quartz = getattr(Quartz, "CGDisplayBounds", None)
        if funcao_telas_quartz is not None and funcao_quadro_quartz is not None:
            erro, ids_telas, quantidade = funcao_telas_quartz(16, None, None)
            if erro == 0 and ids_telas and quantidade:
                for id_tela in ids_telas[:quantidade]:
                    retangulo = funcao_quadro_quartz(id_tela)
                    ox = float(retangulo.origin.x)
                    oy = float(retangulo.origin.y)
                    largura = float(retangulo.size.width)
                    altura = float(retangulo.size.height)
                    if largura > 0 and altura > 0:
                        limites_coletados.append((ox, oy, ox + largura, oy + altura))
    except Exception:
        pass

    try:
        telas_cocoa = NSScreen.screens()
        if telas_cocoa:
            for tela in telas_cocoa:
                quadro = tela.frame()
                ox = float(quadro.origin.x)
                oy = float(quadro.origin.y)
                largura = float(quadro.size.width)
                altura = float(quadro.size.height)
                if largura > 0 and altura > 0:
                    limites_coletados.append((ox, oy, ox + largura, oy + altura))
    except Exception:
        pass

    if not limites_coletados:
        return None

    menor_x = min(item[0] for item in limites_coletados)
    menor_y = min(item[1] for item in limites_coletados)
    maior_x = max(item[2] for item in limites_coletados)
    maior_y = max(item[3] for item in limites_coletados)
    return (menor_x, menor_y, maior_x, maior_y)


def _extrair_par_numerico(
    valor_ax: Any, tipo_ax: Any, atributos_par: Tuple[str, str]
) -> Optional[Tuple[float, float]]:
    """Converte um AXValue (ou estrutura equivalente em testes) em um par numérico (a, b)."""
    if valor_ax is None:
        return None

    chave_a, chave_b = atributos_par

    try:
        funcao_extrair = getattr(AS, "AXValueGetValue", None)
        if funcao_extrair is not None and tipo_ax is not None:
            sucesso, estrutura = funcao_extrair(valor_ax, tipo_ax, None)
            if sucesso and estrutura is not None:
                if hasattr(estrutura, chave_a) and hasattr(estrutura, chave_b):
                    return (
                        float(getattr(estrutura, chave_a)),
                        float(getattr(estrutura, chave_b)),
                    )
                return (float(estrutura[0]), float(estrutura[1]))
    except Exception:
        pass

    try:
        if hasattr(valor_ax, chave_a) and hasattr(valor_ax, chave_b):
            return (
                float(getattr(valor_ax, chave_a)),
                float(getattr(valor_ax, chave_b)),
            )
        if isinstance(valor_ax, dict) and chave_a in valor_ax and chave_b in valor_ax:
            return (float(valor_ax[chave_a]), float(valor_ax[chave_b]))
        if isinstance(valor_ax, (tuple, list)) and len(valor_ax) >= 2:
            return (float(valor_ax[0]), float(valor_ax[1]))
    except Exception:
        pass

    return None


def _obter_quadro_elemento(
    elemento: Any,
) -> Optional[Tuple[float, float, float, float]]:
    """Extrai (x, y, largura, altura) do elemento via AXPosition e AXSize."""
    if elemento is None:
        return None
    try:
        atributo_pos = getattr(AS, "kAXPositionAttribute", "AXPosition")
        atributo_tam = getattr(AS, "kAXSizeAttribute", "AXSize")
        erro_pos, valor_pos = AS.AXUIElementCopyAttributeValue(
            elemento, atributo_pos, None
        )
        erro_tam, valor_tam = AS.AXUIElementCopyAttributeValue(
            elemento, atributo_tam, None
        )
        if erro_pos != 0 or erro_tam != 0:
            return None

        tipo_ponto = getattr(AS, "kAXValueTypeCGPoint", None)
        tipo_tamanho = getattr(AS, "kAXValueTypeCGSize", None)

        ponto = _extrair_par_numerico(valor_pos, tipo_ponto, ("x", "y"))
        tamanho = _extrair_par_numerico(valor_tam, tipo_tamanho, ("width", "height"))
        if ponto is None or tamanho is None:
            return None

        return (ponto[0], ponto[1], tamanho[0], tamanho[1])
    except Exception:
        return None


def _elemento_esta_focado(elemento: Any) -> bool:
    """Verifica se o atributo AXFocused do elemento é explicitamente verdadeiro."""
    if elemento is None:
        return False
    try:
        atributo_focado = getattr(AS, "kAXFocusedAttribute", "AXFocused")
        erro, focado = AS.AXUIElementCopyAttributeValue(elemento, atributo_focado, None)
        return erro == 0 and bool(focado)
    except Exception:
        return False


def _elemento_esta_visivel(
    elemento: Any,
    quadro: Tuple[float, float, float, float],
    quadro_janela: Optional[Tuple[float, float, float, float]] = None,
) -> bool:
    """Confirma se o elemento não está oculto e possui centro visível na janela ou tela."""
    try:
        erro_oculto, oculto = AS.AXUIElementCopyAttributeValue(
            elemento, "AXHidden", None
        )
        if erro_oculto == 0 and oculto is not None and bool(oculto):
            return False
    except Exception:
        pass

    x, y, largura, altura = quadro
    if largura <= 0 or altura <= 0:
        return False

    centro_x = x + (largura / 2.0)
    centro_y = y + (altura / 2.0)

    if quadro_janela is not None:
        jx, jy, jlargura, jaltura = quadro_janela
        if jlargura > 0 and jaltura > 0:
            if (
                jx - 20.0 <= centro_x <= jx + jlargura + 20.0
                and jy - 20.0 <= centro_y <= jy + jaltura + 20.0
            ):
                return True

    limites = _obter_limites_telas()
    if limites is not None:
        min_x, min_y, max_x, max_y = limites
        if not (
            min_x - 20.0 <= centro_x <= max_x + 20.0
            and min_y - 20.0 <= centro_y <= max_y + 20.0
        ):
            return False

    return True


def _coletar_descricao_elemento(elemento: Any) -> str:
    """Agrega os metadados descritivos curtos do elemento AX para análise semântica."""
    partes: List[str] = []
    for atributo in _ATRIBUTOS_DESCRICAO_AX:
        texto = obter_atributo_texto_ax(elemento, atributo)
        if texto:
            partes.append(texto)
    return " ".join(partes)


def calcular_pontuacao_relevancia(
    papel: str,
    quadro: Tuple[float, float, float, float],
    quadro_janela: Optional[Tuple[float, float, float, float]],
    dentro_area_web: bool,
    ja_focado: bool = False,
    descricao: str = "",
) -> float:
    """Calcula a pontuação de relevância de um candidato a campo de entrada de texto."""
    x, y, largura, altura = quadro
    if largura < 24.0 or altura < 14.0:
        return -1.0

    area_util = float(largura) * float(altura)
    pontuacao = min(110.0, math.log10(max(area_util, 1.0)) * 18.0)

    if ja_focado:
        pontuacao += 500.0

    if dentro_area_web:
        pontuacao += 120.0

    if papel in ("AXTextArea", "AXTextView"):
        pontuacao += 90.0

    descricao_minuscula = (descricao or "").lower()
    if any(termo in descricao_minuscula for termo in _TERMOS_SEMANTICOS_CHAT):
        pontuacao += 75.0

    centro_y = float(y) + (float(altura) / 2.0)

    if not dentro_area_web:
        indicio_barra_endereco = any(
            termo in descricao_minuscula for termo in _TERMOS_BARRA_ENDERECO
        )
        no_topo_janela = False
        if quadro_janela is not None and quadro_janela[3] > 0:
            jy, jaltura = float(quadro_janela[1]), float(quadro_janela[3])
            no_topo_janela = papel in ("AXTextField", "AXComboBox") and (
                -20.0 <= (centro_y - jy) <= 0.12 * jaltura
            )
        if indicio_barra_endereco or no_topo_janela:
            pontuacao -= 220.0

    if quadro_janela is not None and quadro_janela[3] > 0:
        jy, jaltura = float(quadro_janela[1]), float(quadro_janela[3])
        posicao_relativa_y = (centro_y - jy) / jaltura
        if 0.35 <= posicao_relativa_y <= 1.05:
            pontuacao += 35.0

    return pontuacao


def _coletar_candidatos_pontuados(
    raiz: Any,
    profundidade_maxima: int,
    quadro_janela: Optional[Tuple[float, float, float, float]],
) -> List[Tuple[float, Any]]:
    """Percorre a subárvore AX indicada e pontua todos os elementos editáveis visíveis."""
    candidatos: List[Tuple[float, Any]] = []
    if raiz is None:
        return candidatos

    for elemento, dentro_area_web in percorrer_arvore_ax_contextual(
        raiz, profundidade_maxima=profundidade_maxima
    ):
        if not eh_elemento_editavel(elemento):
            continue

        quadro = _obter_quadro_elemento(elemento)
        if quadro is None:
            continue

        if not _elemento_esta_visivel(elemento, quadro, quadro_janela):
            continue

        papel = obter_papel_ax(elemento)
        ja_focado = _elemento_esta_focado(elemento)
        descricao = _coletar_descricao_elemento(elemento)

        pontuacao = calcular_pontuacao_relevancia(
            papel=papel,
            quadro=quadro,
            quadro_janela=quadro_janela,
            dentro_area_web=dentro_area_web,
            ja_focado=ja_focado,
            descricao=descricao,
        )
        if pontuacao > 0.0:
            candidatos.append((pontuacao, elemento))

    return candidatos


def cacar_input_visivel(profundidade_maxima: Optional[int] = None) -> Optional[Any]:
    """Localiza e ordena por relevância o melhor campo editável visível no aplicativo ativo."""
    if profundidade_maxima is None:
        try:
            limite_profundidade = int(
                getattr(_ler_configuracoes_atuais(), "profundidade_busca_ax", 18)
            )
        except Exception:
            limite_profundidade = 18
    else:
        limite_profundidade = int(profundidade_maxima)

    dados_app = _ler_aplicativo_ativo_atual()
    pid = int(dados_app.get("pid") or 0)
    if pid <= 0:
        return None

    try:
        elemento_app = AS.AXUIElementCreateApplication(pid)
    except Exception:
        return None

    ativar_acessibilidade_aprimorada(elemento_app)

    janela_focada = obter_janela_focada_ax(elemento_app)
    quadro_janela = (
        _obter_quadro_elemento(janela_focada) if janela_focada is not None else None
    )

    candidatos: List[Tuple[float, Any]] = []
    if janela_focada is not None:
        candidatos = _coletar_candidatos_pontuados(
            janela_focada, limite_profundidade, quadro_janela
        )

    if not candidatos:
        candidatos = _coletar_candidatos_pontuados(
            elemento_app, limite_profundidade, quadro_janela
        )

    if not candidatos:
        return None

    candidatos.sort(key=lambda item: item[0], reverse=True)
    return candidatos[0][1]


def _clicar_centro_e_restaurar_cursor(centro_x: float, centro_y: float) -> bool:
    """Dispara clique esquerdo suave no ponto alvo e restaura imediatamente o cursor original."""
    posicao_original: Optional[Tuple[float, float]] = None
    try:
        evento_leitura = Quartz.CGEventCreate(None)
        if evento_leitura is not None:
            localizacao = Quartz.CGEventGetLocation(evento_leitura)
            ox = (
                float(localizacao.x)
                if hasattr(localizacao, "x")
                else float(localizacao[0])
            )
            oy = (
                float(localizacao.y)
                if hasattr(localizacao, "y")
                else float(localizacao[1])
            )
            posicao_original = (ox, oy)
    except Exception:
        posicao_original = None

    try:
        ponto_clique = (float(centro_x), float(centro_y))
        evento_pressionar = Quartz.CGEventCreateMouseEvent(
            None,
            Quartz.kCGEventLeftMouseDown,
            ponto_clique,
            Quartz.kCGMouseButtonLeft,
        )
        evento_soltar = Quartz.CGEventCreateMouseEvent(
            None,
            Quartz.kCGEventLeftMouseUp,
            ponto_clique,
            Quartz.kCGMouseButtonLeft,
        )
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, evento_pressionar)
        time.sleep(0.015)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, evento_soltar)

        if posicao_original is not None:
            time.sleep(0.02)
            try:
                funcao_reposicionar = getattr(
                    Quartz, "CGWarpMouseCursorPosition", None
                )
                if funcao_reposicionar is not None:
                    funcao_reposicionar(posicao_original)
                else:
                    evento_mover = Quartz.CGEventCreateMouseEvent(
                        None,
                        Quartz.kCGEventMouseMoved,
                        posicao_original,
                        Quartz.kCGMouseButtonLeft,
                    )
                    Quartz.CGEventPost(Quartz.kCGHIDEventTap, evento_mover)
            except Exception:
                pass
        return True
    except Exception:
        return False


def focar_elemento(
    elemento: Any, permitir_clique_fallback: Optional[bool] = None
) -> bool:
    """Tenta focar o elemento via AXFocused, AXPress ou clique suave com restauração do mouse."""
    if elemento is None:
        return False

    try:
        atributo_focado = getattr(AS, "kAXFocusedAttribute", "AXFocused")
        AS.AXUIElementSetAttributeValue(elemento, atributo_focado, True)
    except Exception:
        pass

    if _elemento_esta_focado(elemento):
        return True

    try:
        acao_pressionar = getattr(AS, "kAXPressAction", "AXPress")
        AS.AXUIElementPerformAction(elemento, acao_pressionar)
    except Exception:
        pass

    if _elemento_esta_focado(elemento):
        return True

    if permitir_clique_fallback is None:
        try:
            permitir_clique = bool(
                getattr(_ler_configuracoes_atuais(), "clicar_para_focar_input", True)
            )
        except Exception:
            permitir_clique = True
    else:
        permitir_clique = bool(permitir_clique_fallback)

    if not permitir_clique:
        return False

    quadro = _obter_quadro_elemento(elemento)
    if quadro is None:
        return False

    x, y, largura, altura = quadro
    if largura <= 0 or altura <= 0:
        return False

    centro_x = float(x) + (float(largura) / 2.0)
    centro_y = float(y) + (float(altura) / 2.0)
    return _clicar_centro_e_restaurar_cursor(centro_x, centro_y)
