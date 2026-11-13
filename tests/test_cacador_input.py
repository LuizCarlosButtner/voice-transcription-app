"""Testes de pontuação de relevância, detecção de editáveis, caça AX, foco e inserção."""

from typing import Any, Optional

import ApplicationServices as AS
import pytest


class PontoSimulado:
    """Representa CGPoint compatível tanto com atributos (.x, .y) quanto índice ([0], [1])."""

    def __init__(self, coord_x: float, coord_y: float):
        self.x = float(coord_x)
        self.y = float(coord_y)

    def __getitem__(self, indice: int) -> float:
        return (self.x, self.y)[indice]


class TamanhoSimulado:
    """Representa CGSize compatível tanto com (.width, .height) quanto ([0], [1])."""

    def __init__(self, largura: float, altura: float):
        self.width = float(largura)
        self.height = float(altura)

    def __getitem__(self, indice: int) -> float:
        return (self.width, self.height)[indice]


class QuadroTelaSimulado:
    """Representa NSRect com origin e size para simular NSScreen.frame()."""

    def __init__(self, coord_x: float, coord_y: float, largura: float, altura: float):
        self.origin = PontoSimulado(coord_x, coord_y)
        self.size = TamanhoSimulado(largura, altura)


class TelaSimulada:
    """Dublê de NSScreen para testes determinísticos de visibilidade."""

    def __init__(self, coord_x: float, coord_y: float, largura: float, altura: float):
        self._quadro = QuadroTelaSimulado(coord_x, coord_y, largura, altura)
        self.frame = self._obter_quadro

    def _obter_quadro(self) -> QuadroTelaSimulado:
        return self._quadro


class ElementoAXSimulado:
    """Elemento sintético da árvore de Acessibilidade do macOS para testes isolados."""

    def __init__(
        self,
        nome_identificador: str,
        papel: str,
        quadro: Optional[tuple[float, float, float, float]] = None,
        filhos: Optional[list["ElementoAXSimulado"]] = None,
        descricao: str = "",
        editavel_explicito: Optional[bool] = None,
        valor_definivel: bool = False,
        habilitado: bool = True,
        oculto: bool = False,
        focado: bool = False,
        possui_selecao_texto: bool = False,
        permitir_foco_direto: bool = True,
        permitir_acao_pressionar: bool = True,
    ):
        self.nome_identificador = nome_identificador
        self.atributos: dict[str, Any] = {
            str(AS.kAXRoleAttribute): papel,
            "AXEnabled": habilitado,
            "AXHidden": oculto,
            str(AS.kAXFocusedAttribute): focado,
            str(AS.kAXChildrenAttribute): list(filhos or []),
        }
        if descricao:
            self.atributos["AXDescription"] = descricao
            self.atributos["AXPlaceholderValue"] = descricao
        if editavel_explicito is not None:
            self.atributos["AXEditable"] = editavel_explicito
        if possui_selecao_texto:
            self.atributos[str(AS.kAXSelectedTextRangeAttribute)] = (0, 12)
        if quadro is not None:
            pos_x, pos_y, larg, alt = quadro
            self.atributos[str(AS.kAXPositionAttribute)] = PontoSimulado(pos_x, pos_y)
            self.atributos[str(AS.kAXSizeAttribute)] = TamanhoSimulado(larg, alt)

        self.atributos_definiveis = {
            str(AS.kAXValueAttribute): valor_definivel,
            str(AS.kAXFocusedAttribute): permitir_foco_direto,
        }
        self.permitir_foco_direto = permitir_foco_direto
        self.permitir_acao_pressionar = permitir_acao_pressionar
        self.escritas_atributos: list[tuple[str, Any]] = []
        self.acoes_executadas: list[str] = []


def _instalar_dubles_ax(monkeypatch: pytest.MonkeyPatch, raiz_app: Optional[ElementoAXSimulado] = None):
    """Substitui chamadas nativas de ApplicationServices e NSScreen por equivalentes em memória."""
    import active_app
    import input_hunter

    def copiar_atributo_simulado(elemento, atributo, _padrao=None):
        if isinstance(elemento, ElementoAXSimulado):
            chave = str(atributo)
            if chave in elemento.atributos and elemento.atributos[chave] is not None:
                return 0, elemento.atributos[chave]
        return -25205, None

    def atributo_definivel_simulado(elemento, atributo, _saida=None):
        if isinstance(elemento, ElementoAXSimulado):
            definivel = elemento.atributos_definiveis.get(str(atributo), False)
            return 0, definivel
        return -25205, False

    def definir_atributo_simulado(elemento, atributo, valor):
        if isinstance(elemento, ElementoAXSimulado):
            chave = str(atributo)
            elemento.escritas_atributos.append((chave, valor))
            if chave == str(AS.kAXFocusedAttribute):
                if elemento.permitir_foco_direto:
                    elemento.atributos[chave] = bool(valor)
                    return 0
                return -25200
            elemento.atributos[chave] = valor
            return 0
        return -25200

    def executar_acao_simulada(elemento, acao):
        if isinstance(elemento, ElementoAXSimulado):
            elemento.acoes_executadas.append(str(acao))
            if elemento.permitir_acao_pressionar:
                elemento.atributos[str(AS.kAXFocusedAttribute)] = True
                return 0
        return -25200

    def extrair_valor_ax_simulado(valor_bruto, _tipo_esperado, _saida=None):
        if isinstance(valor_bruto, (PontoSimulado, TamanhoSimulado)):
            return True, valor_bruto
        return False, None

    for modulo_alvo in (active_app.AS, input_hunter.AS):
        monkeypatch.setattr(
            modulo_alvo, "AXUIElementCopyAttributeValue", copiar_atributo_simulado
        )
        monkeypatch.setattr(
            modulo_alvo, "AXUIElementIsAttributeSettable", atributo_definivel_simulado
        )
        monkeypatch.setattr(
            modulo_alvo, "AXUIElementSetAttributeValue", definir_atributo_simulado
        )
        monkeypatch.setattr(
            modulo_alvo, "AXUIElementPerformAction", executar_acao_simulada
        )
        monkeypatch.setattr(modulo_alvo, "AXValueGetValue", extrair_valor_ax_simulado)
        if raiz_app is not None:
            monkeypatch.setattr(
                modulo_alvo, "AXUIElementCreateApplication", lambda _pid: raiz_app
            )

    if hasattr(input_hunter, "NSScreen"):
        class ProvedorTelasSimulado:
            """Substituto puro em Python para NSScreen evitando mutar seletor PyObjC."""

            screens = staticmethod(lambda: [TelaSimulada(0.0, 0.0, 1440.0, 900.0)])

        monkeypatch.setattr(input_hunter, "NSScreen", ProvedorTelasSimulado)


def test_compositor_web_vence_barra_url_e_elementos_minusculos_negativos():
    """Garante que AXTextArea em AXWebArea vence barra de URL e itens < 24x14 são negativos."""
    from input_hunter import calcular_pontuacao_relevancia

    quadro_janela = (0.0, 0.0, 1440.0, 900.0)

    # Elementos minúsculos (< 24 de largura ou < 14 de altura) devem ter pontuação negativa
    pontuacao_largura_pequena = calcular_pontuacao_relevancia(
        papel="AXTextField",
        quadro=(100.0, 100.0, 22.0, 30.0),
        quadro_janela=quadro_janela,
        dentro_area_web=True,
        ja_focado=False,
        descricao="Digite uma mensagem",
    )
    pontuacao_altura_pequena = calcular_pontuacao_relevancia(
        papel="AXTextArea",
        quadro=(100.0, 100.0, 300.0, 12.0),
        quadro_janela=quadro_janela,
        dentro_area_web=True,
        ja_focado=False,
        descricao="Prompt de conversa",
    )
    assert pontuacao_largura_pequena < 0.0
    assert pontuacao_altura_pequena < 0.0

    # Barra de endereço/URL no topo da janela fora da área web
    pontuacao_barra_url = calcular_pontuacao_relevancia(
        papel="AXTextField",
        quadro=(130.0, 42.0, 960.0, 34.0),
        quadro_janela=quadro_janela,
        dentro_area_web=False,
        ja_focado=False,
        descricao="Barra de endereço e pesquisa URL",
    )

    # Compositor de chat/prompt dentro de AXWebArea na metade inferior da janela
    pontuacao_compositor_web = calcular_pontuacao_relevancia(
        papel="AXTextArea",
        quadro=(260.0, 720.0, 760.0, 84.0),
        quadro_janela=quadro_janela,
        dentro_area_web=True,
        ja_focado=False,
        descricao="Digite uma mensagem no chat",
    )

    assert pontuacao_compositor_web > 200.0
    assert pontuacao_compositor_web > pontuacao_barra_url + 250.0


def test_elementos_estaticos_somente_leitura_nao_sao_editaveis(
    monkeypatch: pytest.MonkeyPatch,
):
    """Garante que textos estáticos com AXSelectedTextRange não sejam confundidos com inputs."""
    from active_app import eh_elemento_editavel

    _instalar_dubles_ax(monkeypatch)

    paragrafo_estatico_selecionavel = ElementoAXSimulado(
        nome_identificador="paragrafo_log",
        papel="AXStaticText",
        possui_selecao_texto=True,
        editavel_explicito=False,
        valor_definivel=False,
    )
    botao_acao = ElementoAXSimulado(
        nome_identificador="botao_enviar",
        papel="AXButton",
        valor_definivel=True,
    )
    campo_desabilitado = ElementoAXSimulado(
        nome_identificador="input_bloqueado",
        papel="AXTextField",
        habilitado=False,
    )
    area_texto_ativa = ElementoAXSimulado(
        nome_identificador="compositor_chat",
        papel="AXTextArea",
        habilitado=True,
    )
    editor_rico_web = ElementoAXSimulado(
        nome_identificador="contenteditable_div",
        papel="AXGroup",
        editavel_explicito=True,
        habilitado=True,
    )

    assert eh_elemento_editavel(paragrafo_estatico_selecionavel) is False
    assert eh_elemento_editavel(botao_acao) is False
    assert eh_elemento_editavel(campo_desabilitado) is False
    assert eh_elemento_editavel(area_texto_ativa) is True
    assert eh_elemento_editavel(editor_rico_web) is True


def test_cacar_input_visivel_escolhe_compositor_na_aba_web(
    monkeypatch: pytest.MonkeyPatch,
):
    """Percorre uma árvore AX de navegador completa e escolhe o compositor da aba aberta."""
    import active_app
    import input_hunter

    barra_endereco = ElementoAXSimulado(
        nome_identificador="omnibox_topo",
        papel="AXTextField",
        quadro=(110.0, 38.0, 980.0, 32.0),
        descricao="Pesquisar ou digitar endereço URL",
    )
    icone_oculto = ElementoAXSimulado(
        nome_identificador="input_micro_icone",
        papel="AXTextField",
        quadro=(20.0, 20.0, 14.0, 10.0),
    )
    bloco_leitura = ElementoAXSimulado(
        nome_identificador="historico_mensagens",
        papel="AXStaticText",
        quadro=(250.0, 140.0, 820.0, 500.0),
        possui_selecao_texto=True,
    )
    compositor_aba = ElementoAXSimulado(
        nome_identificador="compositor_principal_chat",
        papel="AXTextArea",
        quadro=(260.0, 730.0, 780.0, 85.0),
        descricao="Envie uma mensagem para o assistente",
    )

    area_web = ElementoAXSimulado(
        nome_identificador="conteudo_aba_ativa",
        papel="AXWebArea",
        quadro=(0.0, 90.0, 1440.0, 810.0),
        filhos=[bloco_leitura, compositor_aba],
    )
    janela_navegador = ElementoAXSimulado(
        nome_identificador="janela_chrome",
        papel="AXWindow",
        quadro=(0.0, 0.0, 1440.0, 900.0),
        filhos=[barra_endereco, icone_oculto, area_web],
    )
    app_navegador = ElementoAXSimulado(
        nome_identificador="app_chrome",
        papel="AXApplication",
        filhos=[janela_navegador],
    )
    app_navegador.atributos[str(AS.kAXFocusedWindowAttribute)] = janela_navegador
    app_navegador.atributos[str(AS.kAXWindowsAttribute)] = [janela_navegador]

    _instalar_dubles_ax(monkeypatch, raiz_app=app_navegador)

    info_navegador = lambda: {
        "name": "Google Chrome",
        "bundle_id": "com.google.Chrome",
        "pid": 8888,
    }
    monkeypatch.setattr(active_app, "obter_aplicativo_ativo", info_navegador)
    monkeypatch.setattr(
        input_hunter, "obter_aplicativo_ativo", info_navegador, raising=False
    )

    escolhido = input_hunter.cacar_input_visivel()
    assert escolhido is compositor_aba


def test_focar_elemento_direto_e_contingencia_clique_restaurando_cursor(
    monkeypatch: pytest.MonkeyPatch,
):
    """Valida foco AX direto e contingência de clique suave via Quartz restaurando o cursor."""
    import input_hunter

    _instalar_dubles_ax(monkeypatch)

    # Caso 1: foco direto via kAXFocusedAttribute funciona na primeira tentativa
    campo_nativo = ElementoAXSimulado(
        nome_identificador="campo_nativo",
        papel="AXTextField",
        quadro=(100.0, 200.0, 400.0, 40.0),
        permitir_foco_direto=True,
    )
    assert input_hunter.focar_elemento(campo_nativo, permitir_clique_fallback=False) is True
    assert campo_nativo.atributos[str(AS.kAXFocusedAttribute)] is True

    # Caso 2: app Electron/Web recusa AXFocused e AXPress -> aciona clique Quartz no centro
    campo_teimoso = ElementoAXSimulado(
        nome_identificador="campo_web_teimoso",
        papel="AXTextArea",
        quadro=(200.0, 400.0, 300.0, 60.0),  # centro esperado: (350.0, 430.0)
        permitir_foco_direto=False,
        permitir_acao_pressionar=False,
    )

    eventos_mouse_postados: list[tuple[int, float, float]] = []
    posicoes_restauradas: list[tuple[float, float]] = []
    posicao_inicial_cursor = PontoSimulado(920.0, 150.0)

    def extrair_coordenadas(ponto_qualquer) -> tuple[float, float]:
        if hasattr(ponto_qualquer, "x") and hasattr(ponto_qualquer, "y"):
            return float(ponto_qualquer.x), float(ponto_qualquer.y)
        return float(ponto_qualquer[0]), float(ponto_qualquer[1])

    def criar_evento_mouse_falso(_fonte, tipo_evento, ponto_alvo, _botao):
        coord_x, coord_y = extrair_coordenadas(ponto_alvo)
        return ("evento_mouse", int(tipo_evento), coord_x, coord_y)

    def postar_evento_falso(_tap, evento):
        if isinstance(evento, tuple) and evento[0] == "evento_mouse":
            eventos_mouse_postados.append((evento[1], evento[2], evento[3]))

    def mover_cursor_falso(ponto_destino):
        posicoes_restauradas.append(extrair_coordenadas(ponto_destino))
        return 0

    if hasattr(input_hunter, "Quartz"):
        modulo_quartz = input_hunter.Quartz
    else:
        import Quartz as modulo_quartz

    monkeypatch.setattr(modulo_quartz, "CGEventCreate", lambda _src: "evento_posicao")
    monkeypatch.setattr(
        modulo_quartz, "CGEventGetLocation", lambda _ev: posicao_inicial_cursor
    )
    monkeypatch.setattr(
        modulo_quartz, "CGEventCreateMouseEvent", criar_evento_mouse_falso
    )
    monkeypatch.setattr(modulo_quartz, "CGEventPost", postar_evento_falso)
    monkeypatch.setattr(
        modulo_quartz, "CGWarpMouseCursorPosition", mover_cursor_falso, raising=False
    )

    # Sem permissão de clique fallback deve retornar False
    assert (
        input_hunter.focar_elemento(campo_teimoso, permitir_clique_fallback=False)
        is False
    )
    assert eventos_mouse_postados == []

    # Com clique fallback habilitado clica em (350.0, 430.0) e restaura (920.0, 150.0)
    assert (
        input_hunter.focar_elemento(campo_teimoso, permitir_clique_fallback=True)
        is True
    )
    assert any(
        abs(cx - 350.0) < 1.0 and abs(cy - 430.0) < 1.0
        for _tipo, cx, cy in eventos_mouse_postados
    )
    foi_restaurado = any(
        abs(rx - 920.0) < 1.0 and abs(ry - 150.0) < 1.0
        for rx, ry in posicoes_restauradas
    ) or any(
        abs(cx - 920.0) < 1.0 and abs(cy - 150.0) < 1.0
        for _tipo, cx, cy in eventos_mouse_postados[-2:]
    )
    assert foi_restaurado is True


def test_inseridor_texto_preserva_area_transferencia_cheia_vazia_e_contingencia_digitacao(
    monkeypatch: pytest.MonkeyPatch,
):
    """Testa preservação da área de transferência (inclusive vazia '') e contingência Unicode."""
    import inserter

    estado_area_transferencia = {"atual": "DADO_IMPORTANTE_DO_USUARIO_123"}
    valores_no_momento_colagem: list[str] = []
    caracteres_digitados: list[str] = []

    def colar_area_simulado() -> str:
        return estado_area_transferencia["atual"]

    def copiar_area_simulado(novo_texto: str) -> None:
        estado_area_transferencia["atual"] = novo_texto

    def criar_evento_teclado_simulado(_fonte, codigo_tecla: int, pressionado: bool):
        return {"codigo": codigo_tecla, "pressionado": pressionado, "texto": ""}

    def definir_flags_simulado(evento: dict, mascara: int) -> None:
        evento["mascara"] = mascara

    def definir_unicode_simulado(evento: dict, _tamanho: int, texto_uni: str) -> None:
        evento["texto"] = texto_uni

    def postar_teclado_simulado(_tap, evento: dict) -> None:
        if evento.get("pressionado") and evento.get("codigo") == 9:
            valores_no_momento_colagem.append(estado_area_transferencia["atual"])
        if evento.get("pressionado") and evento.get("texto"):
            caracteres_digitados.append(evento["texto"])

    monkeypatch.setattr(inserter.pyperclip, "paste", colar_area_simulado)
    monkeypatch.setattr(inserter.pyperclip, "copy", copiar_area_simulado)
    monkeypatch.setattr(inserter.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        inserter.Quartz, "CGEventCreateKeyboardEvent", criar_evento_teclado_simulado
    )
    monkeypatch.setattr(inserter.Quartz, "CGEventSetFlags", definir_flags_simulado)
    monkeypatch.setattr(
        inserter.Quartz, "CGEventKeyboardSetUnicodeString", definir_unicode_simulado
    )
    monkeypatch.setattr(inserter.Quartz, "CGEventPost", postar_teclado_simulado)

    instancia_inseridor = inserter.InseridorTexto()

    # 1. Preservação de conteúdo existente no clipboard
    assert instancia_inseridor.inserir_texto("Olá mundo ditado") is True
    assert valores_no_momento_colagem[-1] == "Olá mundo ditado"
    assert estado_area_transferencia["atual"] == "DADO_IMPORTANTE_DO_USUARIO_123"

    # 2. Preservação quando o clipboard original estava vazio ""
    estado_area_transferencia["atual"] = ""
    assert instancia_inseridor.inserir_texto("continuando a frase") is True
    assert valores_no_momento_colagem[-1].endswith("continuando a frase")
    assert estado_area_transferencia["atual"] == ""

    # 3. Modo explícito de digitação por teclas (keystroke / digitacao)
    caracteres_digitados.clear()
    assert instancia_inseridor.inserir_texto("ABC", metodo="keystroke") is True
    assert "".join(caracteres_digitados).strip() == "ABC"

    # 4. Contingência automática para digitação caso pyperclip.copy falhe
    caracteres_digitados.clear()

    def falha_area_transferencia(_texto: str) -> None:
        raise RuntimeError("Área de transferência bloqueada")

    monkeypatch.setattr(inserter.pyperclip, "copy", falha_area_transferencia)
    assert instancia_inseridor.inserir_texto("XYZ", metodo="clipboard_paste") is True
    assert "".join(caracteres_digitados).strip() == "XYZ"
