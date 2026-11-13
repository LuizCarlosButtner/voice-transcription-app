import json
import os
from pathlib import Path
from typing import Any, Optional

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, model_validator

# Diretórios e arquivos base de armazenamento local
DIRETORIO_BASE_APP = Path.home() / ".voice-transcription"
DIRETORIO_AUDIOS = DIRETORIO_BASE_APP / "audio"
ARQUIVO_CONFIGURACOES = DIRETORIO_BASE_APP / "settings.json"
ARQUIVO_BANCO_HISTORICO = DIRETORIO_BASE_APP / "history.db"

MODOS_ACIONAMENTO_VALIDOS = ("hibrido", "segurar", "alternar")


def _normalizar_modo_acionamento(valor: Any) -> str:
    """Normaliza valores legados ou da API para os modos canônicos em português."""
    if not isinstance(valor, str):
        return "hibrido"
    texto = valor.strip().lower()
    mapeamento = {
        "hibrido": "hibrido",
        "híbrido": "hibrido",
        "hybrid": "hibrido",
        "hybrid_tap_hold": "hibrido",
        "segurar": "segurar",
        "push_and_hold": "segurar",
        "push-and-hold": "segurar",
        "hold": "segurar",
        "alternar": "alternar",
        "alternado": "alternar",
        "toggle": "alternar",
    }
    return mapeamento.get(texto, "hibrido")


class Configuracoes(BaseModel):
    """Modelo central de configurações com suporte bidirecional a chaves PT-BR e JSON legado."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    # Atalho e modo de acionamento
    atalho: str = Field(default="Alt", alias="hotkey")
    modo_acionamento: str = Field(default="hibrido")
    modo_alternar: bool = Field(default=False, alias="toggle_mode")
    limiar_toque_segundos: float = Field(default=0.35, alias="tap_threshold_seconds")

    # Transcrição e idioma
    idioma: str = Field(default="pt", alias="language")
    provedor: str = Field(default="groq", alias="provider")
    provedor_contingencia: str = Field(default="sensevoice", alias="fallback_provider")
    modelo_stt_groq: str = Field(default="whisper-large-v3-turbo", alias="groq_stt_model")
    modelo_llm_groq: str = Field(default="qwen/qwen3.8-27b", alias="groq_llm_model")

    # Estilo de saída e tons de voz
    tom: str = Field(default="verbatim", alias="tone")
    tons_disponiveis: list[str] = Field(
        default=["verbatim", "colloquial", "semiformal", "formal"],
        alias="available_tones",
    )
    correcao_gramatical: bool = Field(default=True, alias="grammar_correction")

    # Tradução instantânea PT -> EN
    traduzir_para_ingles: bool = Field(default=False, alias="translate_to_english")
    apps_traducao_automatica: list[str] = Field(default=[], alias="translate_auto_apps")

    # Inserção de texto e busca de campo editável
    adicionar_no_cursor: bool = Field(default=True, alias="append_at_cursor")
    metodo_insercao: str = Field(default="clipboard_paste", alias="insertion_method")
    cacar_input_automatico: bool = Field(default=True, alias="auto_hunt_input")
    clicar_para_focar_input: bool = Field(default=True, alias="click_to_focus_input")
    profundidade_busca_ax: int = Field(default=18, alias="ax_search_depth")

    # Backup em fatias contínuas e proteção anti-perda
    backup_fatias_ativo: bool = Field(default=True, alias="chunk_backup_enabled")
    inicio_fatias_segundos: int = Field(default=40, alias="chunk_start_seconds")
    duracao_fatia_segundos: int = Field(default=30, alias="chunk_seconds")
    parada_silencio_segundos: int = Field(default=60, alias="silence_auto_stop_seconds")

    # Sistema e rede
    endereco_host: str = Field(default="127.0.0.1", alias="host")
    porta: int = Field(default=8100, alias="port")
    iniciar_no_login: bool = Field(default=True, alias="auto_start_login")

    @model_validator(mode="before")
    @classmethod
    def _sincronizar_modos_entrada(cls, dados: Any) -> Any:
        """Sincroniza `modo_acionamento` e `modo_alternar` ao carregar ou instanciar."""
        if not isinstance(dados, dict):
            return dados

        copia_dados = dict(dados)
        modo_explicito = copia_dados.get("modo_acionamento")

        if modo_explicito is not None:
            modo_normalizado = _normalizar_modo_acionamento(modo_explicito)
            copia_dados["modo_acionamento"] = modo_normalizado
            deve_alternar = modo_normalizado == "alternar"
            copia_dados["modo_alternar"] = deve_alternar
            copia_dados.pop("toggle_mode", None)
        else:
            valor_alternar = copia_dados.get(
                "modo_alternar",
                copia_dados.get("toggle_mode", False),
            )
            if bool(valor_alternar):
                copia_dados["modo_acionamento"] = "alternar"
                copia_dados["modo_alternar"] = True
            else:
                copia_dados["modo_acionamento"] = "hibrido"
                copia_dados["modo_alternar"] = False
            copia_dados.pop("toggle_mode", None)

        return copia_dados

    def __setattr__(self, nome_atributo: str, valor: Any) -> None:
        if nome_atributo == "modo_acionamento" and "modo_acionamento" in self.__dict__:
            modo_normalizado = _normalizar_modo_acionamento(valor)
            super().__setattr__("modo_acionamento", modo_normalizado)
            super().__setattr__("modo_alternar", modo_normalizado == "alternar")
            return
        if nome_atributo == "modo_alternar" and "modo_alternar" in self.__dict__:
            booleano = bool(valor)
            super().__setattr__("modo_alternar", booleano)
            modo_corrente = getattr(self, "modo_acionamento", "hibrido")
            if booleano and modo_corrente != "alternar":
                super().__setattr__("modo_acionamento", "alternar")
            elif not booleano and modo_corrente == "alternar":
                super().__setattr__("modo_acionamento", "hibrido")
            return
        super().__setattr__(nome_atributo, valor)

    def para_dicionario_api(self) -> dict:
        """Retorna dicionário com todas as chaves JSON esperadas pela API e pelo painel web."""
        return {
            "hotkey": self.atalho,
            "modo_acionamento": self.modo_acionamento,
            "toggle_mode": self.modo_alternar,
            "tap_threshold_seconds": self.limiar_toque_segundos,
            "language": self.idioma,
            "provider": self.provedor,
            "active_provider": self.provedor,
            "fallback_provider": self.provedor_contingencia,
            "groq_stt_model": self.modelo_stt_groq,
            "groq_llm_model": self.modelo_llm_groq,
            "tone": self.tom,
            "available_tones": list(self.tons_disponiveis),
            "grammar_correction": self.correcao_gramatical,
            "translate_to_english": self.traduzir_para_ingles,
            "translate_auto_apps": list(self.apps_traducao_automatica),
            "append_at_cursor": self.adicionar_no_cursor,
            "insertion_method": self.metodo_insercao,
            "auto_hunt_input": self.cacar_input_automatico,
            "click_to_focus_input": self.clicar_para_focar_input,
            "ax_search_depth": self.profundidade_busca_ax,
            "chunk_backup_enabled": self.backup_fatias_ativo,
            "chunk_start_seconds": self.inicio_fatias_segundos,
            "chunk_seconds": self.duracao_fatia_segundos,
            "silence_auto_stop_seconds": self.parada_silencio_segundos,
            "host": self.endereco_host,
            "port": self.porta,
            "auto_start_login": self.iniciar_no_login,
        }


def resolver_chave_api(nome_chave: str) -> Optional[str]:
    """
    Resolve chaves de API em ordem segura de precedência:
    1. Variáveis de ambiente ativas do processo (`os.environ`)
    2. Arquivo `.env` local na raiz do projeto
    3. Arquivo central `~/.dsh/.env`
    4. Arquivos de perfil do shell (`~/.zshenv` e `~/.zshrc`)
    """
    valor = os.environ.get(nome_chave)
    if valor and valor.strip():
        return valor.strip()

    env_projeto = Path(__file__).resolve().parent.parent / ".env"
    if env_projeto.exists():
        carregado = dotenv_values(env_projeto)
        valor = carregado.get(nome_chave)
        if valor and valor.strip():
            return valor.strip()

    env_central = Path.home() / ".dsh" / ".env"
    if env_central.exists():
        carregado = dotenv_values(env_central)
        valor = carregado.get(nome_chave)
        if valor and valor.strip():
            return valor.strip()

    for arquivo_rc in (Path.home() / ".zshenv", Path.home() / ".zshrc"):
        if arquivo_rc.exists():
            carregado = dotenv_values(arquivo_rc)
            valor = carregado.get(nome_chave)
            if valor and valor.strip():
                return valor.strip()

    return None


class GerenciadorConfiguracoes:
    """Gerencia leitura, cache em memória e persistência atômica de `settings.json`."""

    def __init__(self) -> None:
        self._configuracoes: Optional[Configuracoes] = None
        self._caminho_carregado: Optional[Path] = None

    def _carregar_configuracoes(self) -> Configuracoes:
        caminho_atual = ARQUIVO_CONFIGURACOES
        if caminho_atual.exists():
            try:
                with open(caminho_atual, "r", encoding="utf-8") as arquivo:
                    dados = json.load(arquivo)
                configuracoes = Configuracoes(**dados)
                self._configuracoes = configuracoes
                self._caminho_carregado = caminho_atual
                return configuracoes
            except Exception:
                pass

        padrao = Configuracoes()
        self.salvar_configuracoes(padrao)
        return padrao

    def obter_configuracoes(self) -> Configuracoes:
        if self._configuracoes is None or self._caminho_carregado != ARQUIVO_CONFIGURACOES:
            return self._carregar_configuracoes()
        return self._configuracoes

    def salvar_configuracoes(self, novas_configuracoes: Configuracoes) -> None:
        caminho_atual = ARQUIVO_CONFIGURACOES
        caminho_atual.parent.mkdir(parents=True, exist_ok=True)
        self._configuracoes = novas_configuracoes
        self._caminho_carregado = caminho_atual
        with open(caminho_atual, "w", encoding="utf-8") as arquivo:
            arquivo.write(novas_configuracoes.model_dump_json(indent=2, by_alias=True))

    def atualizar(self, atualizacoes: dict) -> Configuracoes:
        atuais = self.obter_configuracoes().model_dump()

        mapa_aliases: dict[str, str] = {}
        for nome_campo, info_campo in Configuracoes.model_fields.items():
            if info_campo.alias:
                mapa_aliases[info_campo.alias] = nome_campo

        entradas_normalizadas: dict[str, Any] = {}
        for chave, valor in (atualizacoes or {}).items():
            if valor is None:
                continue
            chave_canonica = mapa_aliases.get(chave, chave)
            entradas_normalizadas[chave_canonica] = valor

        modo_acionamento_informado = "modo_acionamento" in entradas_normalizadas
        modo_alternar_informado = "modo_alternar" in entradas_normalizadas

        atuais.update(entradas_normalizadas)

        if modo_acionamento_informado:
            modo_norm = _normalizar_modo_acionamento(entradas_normalizadas["modo_acionamento"])
            atuais["modo_acionamento"] = modo_norm
            atuais["modo_alternar"] = modo_norm == "alternar"
        elif modo_alternar_informado:
            deve_alternar = bool(entradas_normalizadas["modo_alternar"])
            atuais["modo_alternar"] = deve_alternar
            if deve_alternar:
                atuais["modo_acionamento"] = "alternar"
            elif atuais.get("modo_acionamento") == "alternar":
                atuais["modo_acionamento"] = "hibrido"

        atualizadas = Configuracoes(**atuais)
        self.salvar_configuracoes(atualizadas)
        return atualizadas


gerenciador_configuracoes = GerenciadorConfiguracoes()


def obter_configuracoes() -> Configuracoes:
    """Retorna a instância ativa de configurações."""
    return gerenciador_configuracoes.obter_configuracoes()


def atualizar_configuracoes(atualizacoes: dict) -> Configuracoes:
    """Atualiza e persiste configurações aceitando chaves em PT-BR ou aliases JSON."""
    return gerenciador_configuracoes.atualizar(atualizacoes)


def obter_chave_groq() -> Optional[str]:
    """Obtém a chave `GROQ_API_KEY` nos ambientes configurados do usuário."""
    return resolver_chave_api("GROQ_API_KEY")
