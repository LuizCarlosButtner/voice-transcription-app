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

TRANSLATION_SYSTEM_PROMPTS = {
    "verbatim": """You are a direct speech translator from Brazilian Portuguese into natural, accurate English.
Translate the spoken input into English preserving the raw meaning, tone, and informalities/slang/curse words if present.
CRITICAL RULES:
1. Translate accurately into natural English without softening or censoring anything.
2. If the user used technical terms, code commands, or CLI concepts, translate appropriately into standard developer English.
3. Output ONLY the translated English text, without commentary, explanations, or quotes.""",

    "colloquial": """You are an English translator specializing in natural, casual conversational speech.
Translate the Brazilian Portuguese spoken input into casual, smooth, relaxed English.
CRITICAL RULES:
1. Keep the tone conversational, friendly, and natural.
2. Output ONLY the translated English text without quotes or explanations.""",

    "semiformal": """You are a professional translator from Brazilian Portuguese to English.
Translate the spoken input into clear, professional, well-structured English suitable for workplace messaging, code reviews, and communications.
CRITICAL RULES:
1. Balance clarity, grammar, and natural flow.
2. Output ONLY the translated English text without quotes or explanations.""",

    "formal": """You are an executive translator from Brazilian Portuguese to formal English.
Translate the spoken input into polished, sophisticated, and grammatically impeccable English.
CRITICAL RULES:
1. Use elevated vocabulary appropriate for formal documentation or international correspondence.
2. Output ONLY the translated English text without quotes or explanations."""
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
        grammar_correction: Optional[bool] = None,
        translate_to_english: Optional[bool] = None
    ) -> Dict[str, Any]:
        """
        Processa o texto transcrito aplicando correção de gramática, tom de voz e
        opcionalmente tradução direta de Português para Inglês.
        """
        start_time = time.time()
        if not raw_text or not raw_text.strip():
            return {
                "ok": True,
                "text": raw_text,
                "tone": tone or "verbatim",
                "grammar_fixed": False,
                "translated": False,
                "took_ms": 0,
                "fallback_used": False
            }

        settings = get_settings()
        selected_tone = (tone or settings.tone or "verbatim").lower()
        if selected_tone not in SYSTEM_PROMPTS:
            selected_tone = "verbatim"

        should_translate = settings.translate_to_english if translate_to_english is None else translate_to_english
        apply_grammar = settings.grammar_correction if grammar_correction is None else grammar_correction

        # Se não for traduzir, verbatim e sem correção gramatical pedida, devolve na hora
        if not should_translate and selected_tone == "verbatim" and not apply_grammar:
            return {
                "ok": True,
                "text": raw_text.strip(),
                "tone": selected_tone,
                "grammar_fixed": False,
                "translated": False,
                "took_ms": 0,
                "fallback_used": False
            }

        api_key = self._get_key()
        if not api_key:
            return {
                "ok": True,
                "text": raw_text.strip(),
                "tone": selected_tone,
                "grammar_fixed": False,
                "translated": False,
                "took_ms": 0,
                "fallback_used": True,
                "warning": "GROQ_API_KEY ausente para reescrita; mantido texto bruto"
            }

        if should_translate:
            system_instruction = TRANSLATION_SYSTEM_PROMPTS.get(selected_tone, TRANSLATION_SYSTEM_PROMPTS["verbatim"])
        else:
            system_instruction = SYSTEM_PROMPTS[selected_tone]

        model = settings.groq_llm_model or "qwen/qwen3.8-27b"

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
                        "translated": should_translate,
                        "took_ms": took_ms,
                        "fallback_used": False
                    }
                else:
                    return {
                        "ok": True,
                        "text": raw_text.strip(),
                        "tone": selected_tone,
                        "grammar_fixed": False,
                        "translated": False,
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
                "translated": False,
                "took_ms": took_ms,
                "fallback_used": True,
                "warning": f"Exceção {e}; fallback para verbatim"
            }

rewriter = TextRewriter()
