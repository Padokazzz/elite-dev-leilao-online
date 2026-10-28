# Casa de Leilões — Front-end

React 19 + TypeScript + Vite da Casa de Leilões online.

## Comandos

```bash
npm install
npm run dev      # dev server em http://localhost:5173
npm run build    # typecheck (tsc -b) + build de produção
npm run lint     # oxlint
npm run test     # vitest (testes de unidade)
```

## Configuração

Copie `.env.example` para `.env` e ajuste conforme necessário:

```
VITE_API_URL=http://localhost:8000
```

O backend precisa estar no ar (`backend/` neste repositório). Fora de
desenvolvimento, libere a origem deste front no `CORS_ALLOWED_ORIGINS`
do backend.

## Estrutura

- `src/api/` — cliente fetch com token e contrato tipado das respostas
- `src/auth/` — sessão (token, papel leiloeiro/licitante)
- `src/hooks/` — WebSocket da sala, contagem regressiva
- `src/pages/` — telas (uma por rota)
- `src/components/` — card de lote, badges, paginação, layout
- `src/lib/` — dinheiro em centavos, datas, mensagens de recusa de lance
- `src/styles/` — tokens claro/escuro e utilitários
- `src/theme.ts` — alternância de tema (persistida em localStorage)
