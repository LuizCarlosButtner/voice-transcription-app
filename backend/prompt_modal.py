import subprocess
import time
from typing import Optional
from active_app import has_focused_text_input, get_frontmost_app
from inserter import inserter

def show_input_selection_prompt(text_to_insert: str) -> bool:
    """
    Exibe um alerta nativo do macOS quando nenhum campo de texto estiver selecionado.
    Permite que o usuário:
    1. Clique em 'Colar no Cursor' -> O app aguarda 2 segundos para o usuário clicar no campo e cola;
    2. Clique em 'Copiar Texto' -> Copia o texto para a área de transferência;
    3. Clique em 'Apenas Salvar' -> Mantém no histórico para uso posterior.
    """
    clean_preview = (text_to_insert[:60] + "...") if len(text_to_insert) > 60 else text_to_insert
    clean_preview = clean_preview.replace('"', '\\"')

    script = f'''
    display alert "Voice Transcription: Nenhum campo de texto em foco" message "Sua fala foi transcrita com sucesso:\\n\\"{clean_preview}\\"\\n\\nDeseja colocar este texto em algum campo agora?" buttons {{"Apenas Salvar", "Copiar Texto", "Colar no Cursor"}} default button "Colar no Cursor"
    '''
    try:
        res = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
        if res.returncode == 0:
            btn_clicked = res.stdout.strip()
            if "Colar no Cursor" in btn_clicked:
                # Dá 2.5 segundos para o usuário clicar no campo desejado
                time.sleep(2.5)
                return inserter.insert_text(text_to_insert)
            elif "Copiar Texto" in btn_clicked:
                import pyperclip
                pyperclip.copy(text_to_insert)
                return True
    except Exception:
        pass
    return False
