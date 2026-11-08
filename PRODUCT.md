# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Uma pessoa só: o operador (Leonardo), dono de vários domínios, que manda e-mail
profissional por **alias** sem pagar uma caixa por endereço. Usa em desktop de tela
larga, redigindo mensagens reais para clientes e contatos, muitas vezes respondendo a
um e-mail que recebeu (importa um `.eml`). Agentes (Claude Code) usam o servidor MCP
(ou a linha de comando) por ssh, não a tela — e é pelo MCP que leem e respondem a
caixa de entrada.

## Product Purpose
Redigir, conferir e enviar (ou agendar) e-mail com o endereço de um alias no `From:`,
autenticando com uma caixa real. Sucesso: o operador vê, enquanto escreve, exatamente
o que o destinatário vai receber, e nada sai sem ter sido conferido.

## Positioning
Não é um cliente de e-mail nem uma plataforma de campanhas: é uma mesa de redação de
usuário único, onde a prévia é o mesmo código que monta o envio. A **tela** não tem
caixa de entrada; ler e responder o que chegou é coisa do agente, pelo MCP.

## Operating Context
App Django renderizado no servidor (templates), sem npm, sem bundler, sem framework de
CSS: um `estilo.css` à mão, JS inline com nonce de CSP, Trix vendorizado como editor.
Telas: entrar (senha + TOTP), redigir/editar, rascunhos, agendados (fila despachada por
cron), detalhe de agendado, histórico, detalhe de envio. Importar `.eml` para responder.
A prévia roda dentro de um iframe `srcdoc` sandbox que herda o CSP da página.

## Capabilities and Constraints
- Tudo em português (UI, comentários, docs). Identificadores de protocolo em inglês.
- A prévia não exige destinatário nem valida endereço; recalcula sobre o mesmo POST.
- Enviar/agendar/salvar alterações só liberam depois de uma prévia cujo `hash_previa`
  bate com o conteúdo; salvar rascunho dispensa a trava.
- A moldura da prévia só existe na tela; o e-mail enviado é o HTML puro.
- A lista de marcadores (`{{ hora }}` etc.) é fechada.
- CSP: scripts só com nonce; `style-src 'unsafe-inline'` (Trix); sem fontes externas.
- Sem API HTTP de envio; não criar uma. O MCP é stdio sobre ssh, nunca HTTP.

## Brand Commitments
Nome "Emailing". Sem logotipo nem identidade anterior que precise ser preservada; o
visual atual é o ponto de partida rejeitado pelo operador ("feio").

## Evidence on Hand
Código e docs em `docs/`. Sem capturas de tela, sem testemunhos, sem dados de uso.

## Product Principles
- A prévia é o produto: sempre à vista, sempre atual, fiel ao que será entregue.
- Nada irreversível sem conferência explícita.
- Operador único e experiente: densidade e velocidade antes de orientação.
- Estados (agendado, falhou, rascunho, enviado) legíveis de relance.

## Accessibility & Inclusion
Foco visível, contraste AA, `prefers-reduced-motion` respeitado, operável só pelo teclado.
