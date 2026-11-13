"""Alerta modal nativo do macOS para seleção manual de destino da transcrição."""

import subprocess
import time

import pyperclip

try:
    from inserter import inseridor
except ImportError:
    from backend.inserter import inseridor


def exibir_alerta_selecao_campo(texto_para_inserir: str) -> bool:
    """Exibe alerta nativo quando não há campo de texto em foco, oferecendo colar, copiar ou salvar."""
    if not texto_para_inserir or not texto_para_inserir.strip():
        return False

    texto_linear = texto_para_inserir.strip().replace("\r", " ").replace("\n", " ")
    previa = (texto_linear[:60] + "...") if len(texto_linear) > 60 else texto_linear
    previa_escapada = previa.replace("\\", "\\\\").replace('"', '\\"')

    roteiro_applescript = (
        'display alert "Voice Transcription: Nenhum campo de texto em foco" '
        f'message "Sua fala foi transcrita com sucesso:\\n\\"{previa_escapada}\\"\\n\\n'
        'Deseja colocar este texto em algum campo agora?" '
        'buttons {"Apenas Salvar", "Copiar Texto", "Colar no Cursor"} '
        'default button "Colar no Cursor"'
    )

    try:
        resultado = subprocess.run(
            ["osascript", "-e", roteiro_applescript],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if resultado.returncode == 0:
            botao_escolhido = resultado.stdout.strip()
            if "Colar no Cursor" in botao_escolhido:
                time.sleep(2.5)
                return inseridor.inserir_texto(texto_para_inserir)
            if "Copiar Texto" in botao_escolhido:
                pyperclip.copy(texto_para_inserir)
                return True
    except Exception:
        pass

    return False
