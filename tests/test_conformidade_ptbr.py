"""Verificação estática via AST e tokenize de sintaxe e conformidade ao Português (PT-BR)."""

import ast
import io
import re
import tokenize
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
PASTAS_ALVO = ("backend", "packaging", "tests")

# Métodos de protocolo exigidos pelos frameworks Cocoa / AppKit / PyObjC no macOS
METODOS_PROTOCOLO_COCOA = {
    "init",
    "initWithFrame_",
    "drawRect_",
    "isOpaque",
    "isFlipped",
    "wantsUpdateLayer",
    "updateLayer",
    "acceptsFirstResponder",
    "canBecomeKeyWindow",
    "canBecomeMainWindow",
    "orderFrontRegardless",
}

# Identificadores legados em inglês que foram banidos na refatoração para PT-BR
IDENTIFICADORES_LEGADOS_PROIBIDOS = {
    # Classes antigas
    "Settings",
    "ConfigManager",
    "AudioRecorder",
    "VoiceDaemon",
    "HistoryManager",
    "TextInserter",
    "TranscribeRequest",
    "RewriteRequest",
    "SettingsUpdate",
    "BaseSTTProvider",
    "GroqSTTProvider",
    "SenseVoiceProvider",
    "TranscriptionManager",
    "TextRewriter",
    "VoiceTrayApp",
    "NativeFloatingOverlay",
    "SiriOrbView",
    # Funções e métodos antigos
    "resolve_api_key",
    "get_settings",
    "update_settings",
    "get_groq_key",
    "save_settings",
    "_load_settings",
    "is_autostart_installed",
    "install_autostart",
    "uninstall_autostart",
    "_pick_input_device",
    "save_audio_file",
    "get_macos_microphone_status",
    "request_macos_microphone_permission",
    "inject_synthetic_audio",
    "_audio_callback",
    "_callback_audio",
    "_watchdog_loop",
    "_maybe_auto_stop",
    "_maybe_flush_chunk",
    "on_press",
    "on_release",
    "start_listening",
    "stop_listening",
    "recover_and_insert",
    "_handle_start",
    "_handle_stop",
    "_handle_cancel",
    "_handle_auto_stop",
    "_process_pipeline",
    "_is_hotkey",
    "_set_status",
    "is_accessibility_trusted",
    "get_frontmost_app",
    "has_focused_text_input",
    "find_focused_editable",
    "_role_of",
    "_is_editable",
    "_children_of",
    "_walk_ax",
    "hunt_visible_input",
    "focus_element",
    "_screen_bounds",
    "_element_frame",
    "_is_visible",
    "_visible_editable_inputs",
    "insert_text",
    "_insert_via_clipboard",
    "_insert_via_keystrokes",
    "_post_cmd_v_quartz",
    "_post_unicode_string_quartz",
    "show_input_selection_prompt",
    "get_connection",
    "init_db",
    "create_pending_entry",
    "mark_sent",
    "mark_success",
    "mark_written_not_sent",
    "mark_partial",
    "mark_error",
    "mark_empty",
    "mark_cancelled",
    "list_recoverable",
    "get_entry",
    "list_entries",
    "delete_entry",
    "recover_orphaned_chunks",
    "get_stats",
    "transcribe",
    "rewrite",
    "is_available",
    "get_provider",
    "get_active_chain",
    "health_check",
    "get_status",
    "list_history",
    "get_history_entry",
    "transcribe_audio",
    "rewrite_text",
    "retry_transcription",
    "save_settings_endpoint",
    "get_audio_file",
    "kill_zombie_port",
    "run_server",
    "run_app",
    "on_startup",
    "on_shutdown",
    "create_tray_app",
    "update_status",
    "set_mode",
    "build_app_bundle",
    "generate_app_icon",
}

PREFIXOS_PORTINGLES_PROIBIDOS = (
    "get_",
    "set_",
    "update_",
    "delete_",
    "create_",
    "fetch_",
    "load_",
    "save_",
    "handle_",
    "start_",
    "stop_",
    "check_",
    "build_",
    "generate_",
    "run_",
    "list_",
    "mark_",
    "is_",
    "has_",
    "find_",
    "hunt_",
    "pick_",
    "walk_",
    "post_",
)

PADRAO_CAMEL_PORTINGLES = re.compile(
    r"^(get|set|update|delete|create|fetch|load|save|handle|generate)[A-Z]"
)

TRECHOS_COMENTARIOS_INGLES_PROIBIDOS = (
    "providers package",
    "push-and-hold estrito",
    "key down command",
    "key up v",
)


def _coletar_arquivos_python() -> list[Path]:
    """Lista todos os arquivos .py rastreáveis nas pastas backend/, packaging/ e tests/."""
    arquivos_encontrados: list[Path] = []
    for nome_pasta in PASTAS_ALVO:
        diretorio = RAIZ_PROJETO / nome_pasta
        if not diretorio.exists():
            continue
        for arquivo in sorted(diretorio.rglob("*.py")):
            if "__pycache__" in arquivo.parts:
                continue
            arquivos_encontrados.append(arquivo)
    return arquivos_encontrados


def _eh_seletor_protocolo_cocoa(nome_definicao: str) -> bool:
    """Identifica métodos nativos exigidos por subclasses PyObjC/AppKit."""
    if nome_definicao in METODOS_PROTOCOLO_COCOA:
        return True
    # Seletores Objective-C convertidos para Python terminam com '_' e usam camelCase
    if nome_definicao.endswith("_") and any(letra.isupper() for letra in nome_definicao):
        return True
    return False


def _inspecionar_arvore_ast(
    arvore: ast.AST, caminho_relativo: str, em_pasta_testes: bool = False
) -> list[str]:
    """Percorre definições class/def/atribuição na AST e retorna violações de idioma."""
    violacoes: list[str] = []

    for no_ast in ast.walk(arvore):
        if isinstance(no_ast, ast.Assign):
            for alvo in no_ast.targets:
                if isinstance(alvo, ast.Name):
                    # Preserva a exceção explícita do apelido de compatibilidade em packaging/build_app.py
                    if (
                        alvo.id == "build_app_bundle"
                        and caminho_relativo.endswith("packaging/build_app.py")
                    ):
                        continue
                    if alvo.id in IDENTIFICADORES_LEGADOS_PROIBIDOS:
                        violacoes.append(
                            f"{caminho_relativo}:{no_ast.lineno} -> atribuição legada proibida '{alvo.id}'"
                        )
            continue

        if not isinstance(no_ast, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        nome = no_ast.name

        # Ignora métodos especiais nativos do Python (__init__, __getitem__, etc.)
        if nome.startswith("__") and nome.endswith("__"):
            continue

        # Ignora métodos de protocolo do Cocoa/PyObjC
        if isinstance(no_ast, (ast.FunctionDef, ast.AsyncFunctionDef)) and _eh_seletor_protocolo_cocoa(nome):
            continue

        if nome in IDENTIFICADORES_LEGADOS_PROIBIDOS:
            violacoes.append(
                f"{caminho_relativo}:{no_ast.lineno} -> definição legada proibida '{nome}'"
            )
            continue

        nome_sem_sublinhado = nome.lstrip("_")
        if em_pasta_testes and nome_sem_sublinhado.startswith("test_"):
            nome_sem_sublinhado = nome_sem_sublinhado[len("test_") :]

        if nome_sem_sublinhado.startswith(PREFIXOS_PORTINGLES_PROIBIDOS) or PADRAO_CAMEL_PORTINGLES.match(
            nome_sem_sublinhado
        ):
            violacoes.append(
                f"{caminho_relativo}:{no_ast.lineno} -> nomenclatura em inglês/Portinglês '{nome}'"
            )

    return violacoes


def _inspecionar_comentarios_codigo(codigo_fonte: str, caminho_relativo: str) -> list[str]:
    """Analisa comentários inline via tokenize e detecta comentários residuais em inglês."""
    violacoes: list[str] = []
    fluxo_leitura = io.StringIO(codigo_fonte).readline
    for tipo_token, texto_token, (linha, _coluna), _fim, _linha_bruta in tokenize.generate_tokens(
        fluxo_leitura
    ):
        if tipo_token != tokenize.COMMENT:
            continue
        comentario_limpo = texto_token.lstrip("#").strip().lower()
        # Ignora diretivas técnicas padrão de interpretador ou ferramentas (#!, noqa, type:)
        if comentario_limpo.startswith(("!", "noqa", "type:", "pragma:")):
            continue
        for trecho_proibido in TRECHOS_COMENTARIOS_INGLES_PROIBIDOS:
            if trecho_proibido in comentario_limpo:
                violacoes.append(
                    f"{caminho_relativo}:{linha} -> comentário em inglês proibido '{texto_token.strip()}'"
                )
                break
    return violacoes


def test_sintaxe_python_valida_em_todos_arquivos():
    """Garante que todos os arquivos .py de backend/, packaging/ e tests/ compilam na AST."""
    arquivos = _coletar_arquivos_python()
    assert len(arquivos) >= 10, "Quantidade inesperadamente baixa de arquivos .py encontrados"

    erros_sintaxe: list[str] = []
    for caminho_arquivo in arquivos:
        relativo = str(caminho_arquivo.relative_to(RAIZ_PROJETO))
        try:
            codigo = caminho_arquivo.read_text(encoding="utf-8")
            ast.parse(codigo, filename=relativo)
        except SyntaxError as erro:
            erros_sintaxe.append(f"{relativo}:{erro.lineno}: {erro.msg}")

    assert erros_sintaxe == [], "Erros de sintaxe detectados:\n" + "\n".join(erros_sintaxe)


def test_conformidade_nomenclatura_e_comentarios_ptbr():
    """Verifica ausência de definições e comentários em inglês legado ou Portinglês."""
    arquivos = _coletar_arquivos_python()
    todas_violacoes: list[str] = []

    for caminho_arquivo in arquivos:
        relativo = str(caminho_arquivo.relative_to(RAIZ_PROJETO))
        codigo = caminho_arquivo.read_text(encoding="utf-8")
        arvore = ast.parse(codigo, filename=relativo)
        em_testes = caminho_arquivo.is_relative_to(RAIZ_PROJETO / "tests")
        todas_violacoes.extend(
            _inspecionar_arvore_ast(arvore, relativo, em_pasta_testes=em_testes)
        )
        todas_violacoes.extend(_inspecionar_comentarios_codigo(codigo, relativo))

    assert todas_violacoes == [], (
        "Foram encontradas violações ao padrão estrito PT-BR:\n"
        + "\n".join(todas_violacoes)
    )


def test_detector_ast_reconhece_violacoes_comentarios_e_excecoes_cocoa():
    """Autoteste do analisador AST/tokenize para Portinglês, comentários e isenção Cocoa."""
    codigo_exemplo = """# Providers package
class VoiceDaemon:
    pass

class VisaoBrilho:
    def initWithFrame_(self, quadro):
        return self
    def isOpaque(self):
        return False
    def drawRect_(self, retangulo):
        pass
    def atualizar_brilho(self):
        pass

def get_settings():
    pass

def generate_app_icon():
    pass

def getCarros():
    pass
"""
    arvore = ast.parse(codigo_exemplo, filename="exemplo_sintetico.py")
    violacoes = _inspecionar_arvore_ast(arvore, "exemplo_sintetico.py", em_pasta_testes=False)
    violacoes.extend(_inspecionar_comentarios_codigo(codigo_exemplo, "exemplo_sintetico.py"))

    texto_unificado = "\n".join(violacoes)
    assert "VoiceDaemon" in texto_unificado
    assert "get_settings" in texto_unificado
    assert "generate_app_icon" in texto_unificado
    assert "getCarros" in texto_unificado
    assert "Providers package" in texto_unificado
    assert "initWithFrame_" not in texto_unificado
    assert "isOpaque" not in texto_unificado
    assert "drawRect_" not in texto_unificado
    assert "atualizar_brilho" not in texto_unificado
