"""Reescrita de texto transcrito para ajuste de pontuação, tom de voz e tradução."""

import time
from typing import Any, Optional

import httpx

from config import obter_chave_groq, obter_configuracoes

URL_CHAT_GROQ = "https://api.groq.com/openai/v1/chat/completions"

INSTRUCOES_TOM_PTBR: dict[str, str] = {
    "verbatim": """Você é um pontuador gramatical estrito de transcrição de voz em português brasileiro.
Sua ÚNICA função é adicionar pontuação correta (pontos, vírgulas, interrogações) e ajustar maiúsculas iniciais.
REGRAS CRÍTICAS INVIOLÁVEIS:
1. NUNCA altere, substitua, resuma ou remova NENHUMA palavra.
2. NUNCA censure ou filtre gírias, palavrões ou expressões coloquiais. Deixe-as exatamente como faladas.
3. Retorne APENAS o texto pontuado, sem explicações, comentários ou aspas adicionais.""",
    "colloquial": """Você é um assistente de estilo para texto falado em português brasileiro.
Transforme a transcrição em um tom descontraído, natural e coloquial.
REGRAS CRÍTICAS:
1. Reaproveite as próprias palavras e vocabulário do usuário, tornando a frase mais fluida e natural.
2. NÃO adicione polidez falsa ou formalismo engessado.
3. Mantenha gírias ou termos espontâneos usados pelo usuário.
4. Retorne APENAS o texto reescrito, sem introduções ou aspas.""",
    "semiformal": """Você é um assistente de comunicação profissional em português brasileiro.
Ajuste a transcrição para um tom semiformal equilibrado, claro, objetivo e respeitoso para mensagens e e-mails profissionais do dia a dia.
REGRAS CRÍTICAS:
1. Corrija concordância e pontuação mantendo a naturalidade.
2. Reaproveite a essência das palavras do usuário sem soar artificial ou burocrático.
3. Retorne APENAS o texto final pronto para envio, sem comentários ou aspas.""",
    "formal": """Você é um assistente de redação formal e polida em português brasileiro.
Ajuste a transcrição para um tom formal, sofisticado e preciso.
REGRAS CRÍTICAS:
1. Eleve o registro linguístico escolhendo palavras adequadas e elegantes, preservando exatamente o significado original.
2. NÃO injete chavões vazios ou polidez robótica desnecessária.
3. Retorne APENAS o texto final reescrito, sem comentários ou aspas.""",
}

INSTRUCOES_TRADUCAO_INGLES: dict[str, str] = {
    "verbatim": """Você é um tradutor direto de fala do português brasileiro para o inglês natural e fiel.
Traduza a fala para o inglês preservando integralmente o sentido bruto, o tom e eventuais gírias ou expressões informais.
REGRAS CRÍTICAS:
1. Traduza com precisão para o inglês natural sem suavizar nem censurar nada.
2. Caso o usuário utilize termos técnicos de programação ou linha de comando, use o vocabulário técnico padrão em inglês.
3. Retorne APENAS o texto traduzido em inglês, sem explicações, comentários ou aspas.""",
    "colloquial": """Você é um tradutor de português brasileiro para inglês conversacional, fluido e descontraído.
REGRAS CRÍTICAS:
1. Mantenha o tom casual, amigável e natural em inglês.
2. Retorne APENAS o texto traduzido em inglês, sem explicações ou aspas.""",
    "semiformal": """Você é um tradutor profissional de português brasileiro para inglês corporativo claro e bem estruturado.
REGRAS CRÍTICAS:
1. Equilibre clareza, gramática correta e fluidez natural para mensagens de trabalho e revisões técnicas.
2. Retorne APENAS o texto traduzido em inglês, sem explicações ou aspas.""",
    "formal": """Você é um tradutor executivo de português brasileiro para inglês formal, polido e gramaticalmente impecável.
REGRAS CRÍTICAS:
1. Utilize vocabulário elevado adequado a documentação formal e correspondência internacional.
2. Retorne APENAS o texto traduzido em inglês, sem explicações ou aspas.""",
}


class ReescritorTexto:
    """Aplica pontuação, estilo de tom e tradução opcional via modelo LLM na Groq."""

    def __init__(self, chave_api: Optional[str] = None) -> None:
        self._chave_explicita = chave_api

    def _obter_chave(self) -> Optional[str]:
        return self._chave_explicita or obter_chave_groq()

    async def reescrever(
        self,
        texto_bruto: str,
        tom: Optional[str] = None,
        correcao_gramatical: Optional[bool] = None,
        traduzir_para_ingles: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Processa o texto bruto conforme o tom, gramática e opção de tradução."""
        inicio = time.time()
        if not texto_bruto or not texto_bruto.strip():
            return {
                "ok": True,
                "text": texto_bruto,
                "tone": tom or "verbatim",
                "grammar_fixed": False,
                "translated": False,
                "took_ms": 0,
                "fallback_used": False,
                "warning": None,
            }

        configuracoes = obter_configuracoes()
        tom_selecionado = (tom or configuracoes.tom or "verbatim").lower()
        if tom_selecionado not in INSTRUCOES_TOM_PTBR:
            tom_selecionado = "verbatim"

        deve_traduzir = (
            configuracoes.traduzir_para_ingles
            if traduzir_para_ingles is None
            else bool(traduzir_para_ingles)
        )
        aplicar_gramatica = (
            configuracoes.correcao_gramatical
            if correcao_gramatical is None
            else bool(correcao_gramatical)
        )

        if not deve_traduzir and tom_selecionado == "verbatim" and not aplicar_gramatica:
            return {
                "ok": True,
                "text": texto_bruto.strip(),
                "tone": tom_selecionado,
                "grammar_fixed": False,
                "translated": False,
                "took_ms": 0,
                "fallback_used": False,
                "warning": None,
            }

        chave_api = self._obter_chave()
        if not chave_api:
            return {
                "ok": True,
                "text": texto_bruto.strip(),
                "tone": tom_selecionado,
                "grammar_fixed": False,
                "translated": False,
                "took_ms": 0,
                "fallback_used": True,
                "warning": "GROQ_API_KEY ausente para reescrita; mantido texto bruto",
            }

        if deve_traduzir:
            instrucao_sistema = INSTRUCOES_TRADUCAO_INGLES.get(
                tom_selecionado,
                INSTRUCOES_TRADUCAO_INGLES["verbatim"],
            )
        else:
            instrucao_sistema = INSTRUCOES_TOM_PTBR[tom_selecionado]

        modelo = configuracoes.modelo_llm_groq or "qwen/qwen3.8-27b"

        try:
            async with httpx.AsyncClient(timeout=10.0) as cliente:
                carga_requisicao = {
                    "model": modelo,
                    "messages": [
                        {"role": "system", "content": instrucao_sistema},
                        {"role": "user", "content": texto_bruto.strip()},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1024,
                }
                cabecalhos = {
                    "Authorization": f"Bearer {chave_api}",
                    "Content-Type": "application/json",
                }
                resposta = await cliente.post(
                    URL_CHAT_GROQ,
                    headers=cabecalhos,
                    json=carga_requisicao,
                )
                tempo_ms = int((time.time() - inicio) * 1000)

                if resposta.status_code == 200:
                    dados_resposta = resposta.json()
                    texto_transformado = (
                        dados_resposta["choices"][0]["message"]["content"].strip()
                    )
                    if (
                        texto_transformado.startswith('"')
                        and texto_transformado.endswith('"')
                        and len(texto_transformado) > 2
                    ):
                        texto_transformado = texto_transformado[1:-1].strip()
                    return {
                        "ok": True,
                        "text": texto_transformado,
                        "tone": tom_selecionado,
                        "grammar_fixed": True,
                        "translated": deve_traduzir,
                        "took_ms": tempo_ms,
                        "fallback_used": False,
                        "warning": None,
                    }

                return {
                    "ok": True,
                    "text": texto_bruto.strip(),
                    "tone": tom_selecionado,
                    "grammar_fixed": False,
                    "translated": False,
                    "took_ms": tempo_ms,
                    "fallback_used": True,
                    "warning": f"HTTP {resposta.status_code} na API LLM; mantido texto bruto",
                }
        except Exception as erro:
            tempo_ms = int((time.time() - inicio) * 1000)
            return {
                "ok": True,
                "text": texto_bruto.strip(),
                "tone": tom_selecionado,
                "grammar_fixed": False,
                "translated": False,
                "took_ms": tempo_ms,
                "fallback_used": True,
                "warning": f"Exceção {erro}; mantido texto bruto",
            }


reescritor = ReescritorTexto()
