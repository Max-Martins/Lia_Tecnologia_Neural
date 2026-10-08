# LIA — Tecnologia Neural

Versão modificada do **MARK LV — JARVIS**, de **FatihMakes**
(Copyright © 2026 FatihMakes), distribuída sob a licença
[Creative Commons Atribuição-NãoComercial 4.0 Internacional (CC BY-NC 4.0)](https://creativecommons.org/licenses/by-nc/4.0/).
O texto completo da licença está em [LICENSE](LICENSE). Uso comercial não é permitido.

O material é fornecido "no estado em que se encontra", sem garantias — veja a
Seção 5 da licença.

## O que foi modificado

- **HUD de rede neural** (`core/neural_net.py`, `ui.py`): novo estilo central —
  uma malha 3D de neurônios cujas sinapses pulsam de acordo com a conversa
  (entrada do usuário, respostas da assistente, voz, estado de raciocínio).
- **Português do Brasil**: a assistente sempre fala em pt-BR (`core/prompt.txt`,
  `main.py`), e toda a interface e as mensagens de registro foram traduzidas.
- **Pastas reais do usuário** (`core/known_folders.py`): "área de trabalho",
  "documentos" etc. agora seguem o local real do Windows, inclusive o OneDrive.
- **Integração com o Claude Code** (`plugins/claude_code.py`): a assistente pode
  delegar tarefas complexas ao Claude Code e anunciar o resultado por voz.
- **`.gitignore`**: corrigidas regras que não funcionavam por causa de
  comentários na mesma linha.
