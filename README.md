# Voice Transcription App

Aplicativo desktop autônomo para macOS que transforma voz em texto em qualquer janela ativa, inspirado no Superwhisper e VocaMac, desenvolvido em Python.

---

## Recursos Principais

- **Ativação Híbrida Inteligente (Hold para Falar OU Toque para Alternar):**
  - **Push-and-Hold:** Pressione e segure o atalho global (`Option/Alt`). Enquanto estiver segurando, ele grava; soltou o dedo, ele encerra a gravação e envia o texto imediatamente.
  - **Tap-to-Toggle (Toque Simples):** Se você apenas der um clique/toque rápido no atalho e soltar, ele ativa a gravação contínua e permanece ligado. Quando terminar de falar, basta pressionar o atalho mais uma vez para encerrar e enviar.
- **Sem Quebra por Pausa:** O áudio é capturado continuamente enquanto a tecla estiver pressionada, sem divisão prematura por silêncio.
- **Inserção Incremental (Append):** Repetidos ciclos de fala adicionam o texto de forma contínua no cursor sem substituir o conteúdo existente.
- **Guarda de Foco:** O aplicativo detecta via Acessibilidade (macOS AXUIElement) se há um campo de texto em foco antes de iniciar a gravação, prevenindo acionamentos acidentais.
- **Tons de Voz e Correção Gramatical:**
  - `Verbatim` (Padrão, sem filtro): Transcrição exata das palavras faladas, sem censura, com pontuação adequada.
  - `Coloquial`: Ajusta vocabulário para estilo descontraído mantendo as ideias do usuário.
  - `Semiformal`: Tom equilibrado para comunicação profissional diária.
  - `Formal`: Tom refinado e polido para documentos e correspondências oficiais.
- **Tradução Instantânea para Inglês (PT ➔ EN):**
  - Fale naturalmente em português brasileiro; o aplicativo transcreve sua voz e insere **diretamente em inglês** no campo de texto ativo (ideal para CLIs como Gemini CLI, Claude Code, chats internacionais ou prompts em inglês).
  - Pode ser ativado ou desativado na hora com um clique no botão azul do painel web ou pelo item `🌐 Traduzir para Inglês` na barra de menus do macOS.
- **Histórico Completo com Áudio de Recuperação:** Todas as sessões (sucessos e falhas) são persistidas em SQLite local (`~/.voice-transcription/history.db`). Em caso de falha de conexão ou erro no provedor, o áudio bruto (`.wav`) permanece salvo para retranscrição imediata (*retry*).
- **Provedor Primário e Fallback Offline:** Groq Cloud (`whisper-large-v3-turbo`) com fallback automático para SenseVoice-ONNX local.
- **Ícone de Status no Menu Bar:** Indicador visual em tempo real (🟢 Ocioso, 🔴 Gravando, 🟡 Processando, ⚠️ Atenção/Erro).
- **Inicialização Automática:** Suporte a inicialização com o sistema via LaunchAgent do macOS.

---

## Permissões Necessárias no macOS

Para operar globalmente sobre outros aplicativos, o macOS requer três permissões em **Ajustes do Sistema > Privacidade e Segurança**:

1. **Microfone:** Para captura de áudio da sua voz.
2. **Acessibilidade:** Para detectar o campo em foco e simular digitação/colagem no cursor do aplicativo ativo.
3. **Monitoramento de Entrada:** Para escutar o atalho global de teclado em segundo plano.

---

## Configuração de Ambiente

O aplicativo busca automaticamente as chaves de API nas variáveis de ambiente do sistema (`os.environ`), como as definidas em `~/.zshenv` ou `~/.zshrc`. Caso prefira isolar, crie um arquivo `.env` na raiz do projeto baseado no `.env.example`:

```bash
cp .env.example .env
```

### Variáveis Suportadas
- `GROQ_API_KEY`: Chave da API Groq (utilizada para transcrição rápida Whisper e processamento de tom).

---

## Instalação e Execução

### Pré-requisitos
- macOS 13+ (Apple Silicon ou Intel)
- Python 3.11+

### Instalação de Dependências
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
```

### Executar em Desenvolvimento
```bash
python3 backend/main.py
```

---

## Licença

MIT License. Consulte o arquivo `LICENSE` para mais detalhes.
