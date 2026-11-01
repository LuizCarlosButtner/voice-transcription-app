import os
import json
from pathlib import Path
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from dotenv import dotenv_values, load_dotenv

# Diretórios base de armazenamento local
BASE_APP_DIR = Path.home() / ".voice-transcription"
AUDIO_STORAGE_DIR = BASE_APP_DIR / "audio"
SETTINGS_FILE = BASE_APP_DIR / "settings.json"
HISTORY_DB_FILE = BASE_APP_DIR / "history.db"

# Garantir existência dos diretórios fundamentais
BASE_APP_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

class Settings(BaseModel):
    # Atalho e disparo
    hotkey: str = Field(default="Alt", description="Tecla modificadora de ativação (Alt/Option, Control, etc.)")
    toggle_mode: bool = Field(default=False, description="Se true, um toque liga e outro desliga. Se false, push-and-hold")
    
    # Transcrição e idioma
    language: str = Field(default="pt", description="Código de idioma de reconhecimento de voz")
    provider: str = Field(default="groq", description="Provedor de STT primário (groq, sensevoice)")
    fallback_provider: str = Field(default="sensevoice", description="Provedor de STT de fallback offline")
    groq_stt_model: str = Field(default="whisper-large-v3-turbo", description="Modelo Whisper na nuvem Groq")
    groq_llm_model: str = Field(default="qwen/qwen3.8-27b", description="Modelo LLM Groq para ajuste de tom e gramática")
    
    # Estilo de saída e tons de voz
    tone: str = Field(default="verbatim", description="Tom ativo: verbatim (sem filtro), colloquial, semiformal, formal")
    available_tones: list[str] = Field(default=["verbatim", "colloquial", "semiformal", "formal"])
    grammar_correction: bool = Field(default=True, description="Correção automática de gramática e pontuação")
    
    # Tradução instantânea PT -> EN
    translate_to_english: bool = Field(default=False, description="Se ativo, traduz a fala em português diretamente para inglês no input")
    translate_auto_apps: list[str] = Field(default=[], description="Lista de apps que ativam tradução para inglês automaticamente (ex: 'Terminal', 'iTerm2')")
    
    # Inserção de texto
    append_at_cursor: bool = Field(default=True, description="Inserir no cursor atual sem apagar seleção a menos que selecionado")
    insertion_method: str = Field(default="clipboard_paste", description="clipboard_paste ou keystroke")
    
    # Sistema e Rede
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8100)
    auto_start_login: bool = Field(default=True, description="Inicializar automaticamente com o macOS")

def resolve_api_key(key_name: str) -> Optional[str]:
    """
    Resolve chaves de API sem exigir que o usuário digite ou salve em código.
    Ordem de precedência segura:
    1. os.environ (ambiente ativo do processo)
    2. .env local do projeto
    3. ~/.dsh/.env (ambiente central seguro de IA)
    4. ~/.zshenv e ~/.zshrc (exportações de shell do usuário)
    """
    # 1. os.environ
    val = os.environ.get(key_name)
    if val and val.strip():
        return val.strip()
    
    # 2. .env local do projeto
    project_env = Path(__file__).resolve().parent.parent / ".env"
    if project_env.exists():
        loaded = dotenv_values(project_env)
        val = loaded.get(key_name)
        if val and val.strip():
            return val.strip()
            
    # 3. ~/.dsh/.env
    dsh_env = Path.home() / ".dsh" / ".env"
    if dsh_env.exists():
        loaded = dotenv_values(dsh_env)
        val = loaded.get(key_name)
        if val and val.strip():
            return val.strip()
            
    # 4. ~/.zshenv e ~/.zshrc
    for rc in [Path.home() / ".zshenv", Path.home() / ".zshrc"]:
        if rc.exists():
            loaded = dotenv_values(rc)
            val = loaded.get(key_name)
            if val and val.strip():
                return val.strip()
                
    return None

class ConfigManager:
    def __init__(self):
        self._settings = self._load_settings()

    def _load_settings(self) -> Settings:
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return Settings(**data)
            except Exception:
                pass
        # Salva o arquivo de configurações padrão na primeira execução
        defaults = Settings()
        self.save_settings(defaults)
        return defaults

    def get_settings(self) -> Settings:
        return self._settings

    def save_settings(self, new_settings: Settings) -> None:
        self._settings = new_settings
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            f.write(new_settings.model_dump_json(indent=2))

    def update(self, updates: Dict[str, Any]) -> Settings:
        current = self._settings.model_dump()
        current.update(updates)
        updated = Settings(**current)
        self.save_settings(updated)
        return updated

config_manager = ConfigManager()

def get_settings() -> Settings:
    return config_manager.get_settings()

def update_settings(updates: Dict[str, Any]) -> Settings:
    return config_manager.update(updates)

def get_groq_key() -> Optional[str]:
    return resolve_api_key("GROQ_API_KEY")
