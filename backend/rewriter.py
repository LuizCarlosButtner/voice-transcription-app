import time
from typing import Dict, Any, Optional
import httpx
from config import get_groq_key, get_settings

GROQ_CHAT_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPTS = {
    "verbatim": """Você é um pontuador gramatical estrito de transcrição de voz em português brasileiro.
Sua ÚNICA função é adicionar pontuação correta (pontos, vírgulas, interrogações) e ajustar maiúsculas iniciais.
REGRAS CRÍTICAS INVIOLÁVEIS:
1. NUNCA altere, substitua, resuma ou remova NENHUMA palavra.
2. NUNCA censure ou filtre gírias, palavrões ou expressões coloquiais (ex: 'mano', 'caralho', 'porra'). Deixe-as exatamente como faladas.
3. Retorne APENAS o texto pontuado, sem explicações, comentários ou aspas adicionais.""",

    "colloquial": """Você é um assistente de estilo para texto falado em português brasileiro.
Transforme a transcrição em um tom descontraído, natural e coloquial ('suave', 'tranquilo').
REGRAS CRÍTICAS:
1. Reaproveite as próprias palavras e vocabulário do usuário, tornando a frase mais fluida e solta.
2. NÃO adicione polidez falsa ou formalismo engessado.
3. Mantenha gírias ou termos espontâneos usados pelo usuário.
4. Retorne APENAS o texto reescrito, sem introduções ou aspas.""",

    "semiformal": """Você é um assistente de comunicação profissional em português brasileiro.
Ajuste a transcrição para um tom semiformal equilibrado, claro, objetivo e respeitoso para uso em mensagens e e-mails profissionais do dia a dia.
REGRAS CRÍTICAS:
1. Corrija concordância e pontuação mantendo a naturalidade.
2. Reaproveite a essência das palavras do usuário sem soar artificial ou burocrático.
3. Retorne APENAS o texto final pronto para envio.""",

    "formal": """Você é um assistente de redação formal e polida em português brasileiro.
Ajuste a transcrição para um tom formal, sofisticado e preciso.
REGRAS CRÍTICAS:
1. Eleve o registro linguístico escolhendo palavras mais adequadas e elegantes, mas preservando exatamente o significado original do usuário.
2. NÃO injete chavões vazios ou polidez robótica desnecessária (evite 'venho por meio desta', 'desde já agradeço').
3. Retorne APENAS o texto final reescrito, sem comentários."""
}

class TextRewriter:
    def __init__(self, api_key: Optional[str] = None):
        self._explicit_key = api_key

    def _get_key(self) -> Optional[str]:
        return self._explicit_key or get_groq_key()

    async def rewrite(
        self,
        raw_text: str,
        tone: Optional[str] = None,
        grammar_correction: Optional[bool] = None
    ) -> Dict[str, Any]:
        """
        Processa o texto transcrito aplicando correção de gramática e tom de voz.
        Se tom for 'verbatim' e grammar_correction for False, devolve raw_text imediatamente.
        Em caso de erro na API do LLM, devolve raw_text para nunca bloquear o usuário.
        """
        start_time = time.time()
        if not raw_text or not raw_text.strip():
            return {
                "ok": True,
                "text": raw_text,
                "tone": tone or "verbatim",
                "grammar_fixed": False,
                "took_ms": 0,
                "fallback_used": False
            }

        settings = get_settings()
        selected_tone = (tone or settings.tone or "verbatim").lower()
        if selected_tone not in SYSTEM_PROMPTS:
            selected_tone = "verbatim"

        apply_grammar = settings.grammar_correction if grammar_correction is None else grammar_correction

        # Otimização: se verbatim e sem correção gramatical pedida, devolve na hora
        if selected_tone == "verbatim" and not apply_grammar:
            return {
                "ok": True,
                "text": raw_text.strip(),
                "tone": selected_tone,
                "grammar_fixed": False,
                "took_ms": 0,
                "fallback_used": False
            }

        api_key = self._get_key()
        if not api_key:
            # Sem chave LLM, entrega o texto bruto sem travar o fluxo
            return {
                "ok": True,
                "text": raw_text.strip(),
                "tone": selected_tone,
                "grammar_fixed": False,
                "took_ms": 0,
                "fallback_used": True,
                "warning": "GROQ_API_KEY ausente para reescrita; mantido texto bruto"
            }

        system_instruction = SYSTEM_PROMPTS[selected_tone]
        model = settings.groq_llm_model or "llama-3.3-70b-versatile"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": raw_text.strip()}
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1024
                }
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }

                resp = await client.post(GROQ_CHAT_ENDPOINT, headers=headers, json=payload)
                took_ms = int((time.time() - start_time) * 1000)

                if resp.status_code == 200:
                    data = resp.json()
                    transformed = data["choices"][0]["message"]["content"].strip()
                    # Remove eventuais aspas que o modelo coloque ao redor do texto
                    if transformed.startswith('"') and transformed.endswith('"') and len(transformed) > 2:
                        transformed = transformed[1:-1].strip()
                    return {
                        "ok": True,
                        "text": transformed,
                        "tone": selected_tone,
                        "grammar_fixed": True,
                        "took_ms": took_ms,
                        "fallback_used": False
                    }
                else:
                    return {
                        "ok": True,
                        "text": raw_text.strip(),
                        "tone": selected_tone,
                        "grammar_fixed": False,
                        "took_ms": took_ms,
                        "fallback_used": True,
                        "warning": f"HTTP {resp.status_code} na API LLM; fallback para verbatim"
                    }

        except Exception as e:
            took_ms = int((time.time() - start_time) * 1000)
            return {
                "ok": True,
                "text": raw_text.strip(),
                "tone": selected_tone,
                "grammar_fixed": False,
                "took_ms": took_ms,
                "fallback_used": True,
                "warning": f"Exceção {e}; fallback para verbatim"
            }

rewriter = TextRewriter()
