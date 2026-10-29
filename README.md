# Casa de Leilões Online

Elite Dev · Plataforma de leilões em tempo real com carteiras, lotes,
lances via WebSocket, liquidação automática e cadeia de auditoria
auditável.

Escopo completo definido em [`PLANO.md`](./PLANO.md) — este README é o
guia de setup, execução, decisões técnicas e entrega.

## Status

| Área | Estado |
| :--- | :--- |
| Backend (Django + DRF + Channels) | ✅ Completo — 206 testes |
| Front-end — telas core | ✅ Vitrine, sala ao vivo, carteira, meus lances, comprovantes, auth, dark mode |
| Front-end — painel do leiloeiro | ✅ Busca/importação de catálogo, criar, programar, cancelar, resultado por lote e total recebido |
| Front-end — auditoria pública | ✅ Verificação de cadeia por lote, com deep link e cross-link do comprovante |
| Infraestrutura | ✅ Docker Compose (Postgres, Redis, API, worker, front) · CI (GitHub Actions) · throttles globais · whitenoise |
| Deploy | ⬜ Previsto: Render + Neon + Vercel (§4 do PLANO) |

## Escopo implementado

**Dinheiro e lances** — valores em centavos (`bigint`), nunca float;
incremento mínimo obrigatório; lance só em lote ao vivo; leiloeiro não
dá lance; toda recusa volta com código (`below_min`,
`insufficient_funds`, `already_leading`, `not_started`,
`auction_closed`, `seller_forbidden`) e o front mapeia cada uma em
mensagem amigável.

**Carteira** — saldo total, comprometido e disponível derivados de um
ledger *append-only* (fonte da verdade); depósito simulado; ao ser
superado, o comprometimento é liberado; cancelamento estorna tudo.

**Tempo real** — WebSocket `/ws/auctions/<id>/` com token na query e
origem validada no handshake (recusa antes de qualquer evento);
snapshot inicial com `you_lead`; eventos `bid.placed` (com o pseudônimo
do licitante, nunca a identidade), `auction.closed` e
`auction.cancelled`; anti-snipe: lance no último minuto estende o fim
em 2 minutos; reconexão infinita com backoff capado em 10 s (e
retry imediato quando a aba volta ao foco ou a rede volta), com
fallback de polling a cada 8 s enquanto o WS está fora.

**Encerramento e liquidação** — liquidação idempotente (rodar duas
vezes não debita duas vezes): vencedor debitado, comprovante criado,
vendedor creditado; "lazy settle" ao abrir um lote + worker
`settle_auctions_loop` para a transição automática de status.

**Auditoria e privacidade** — cadeia de hash HMAC por lote (qualquer
`UPDATE`/`DELETE` na sequência é detectável); verificação pública sem
e-mail ou ID real (pseudônimos HMAC); comprovante público por UUID.

**Catálogo e vitrine** — busca e importação do Art Institute of
Chicago com cache local e fallback offline; imagens servidas por
proxy server-side (`/api/catalog/image/<id>/`) com placeholder no
front (o ArtIC fica atrás do Cloudflare); vitrine com busca, faixa de
preço, ordenação, filtro de status e paginação.

**Front-end (React 19 + Vite + TypeScript, sem UI kit)** — rotas `/`,
`/entrar`, `/registrar`, `/carteira`, `/meus-lances`,
`/comprovantes/:uuid`, `/lotes/:id`, `/painel` (leiloeiro) e
`/auditoria` (pública); sala com ficha da obra (atributos do catálogo
em `item_attributes`), histórico por pseudônimo e banner final para
lote que terminou sem lances; carteira com extrato derivado do ledger
(sem linha de variação zero); dark mode com variáveis CSS e script
anti-flash; estados de loading/vazio/erro em todas as telas; login
volta para a página de origem; no mobile: menu hambúrguer, bottom
sheet de ações e prévias dos lotes.

## Como executar

Requisitos: **Docker** (compose), ou **Python 3.11+** e **Node 20.19+**
para rodar por fora.

### Com Docker Compose (recomendado)

```bash
docker compose up --build
# Postgres (localhost:5434), API em http://localhost:8000,
# front em http://localhost:5173 — migrations e worker sobem sozinhos.

docker compose exec backend python manage.py seed_demo
```

Prefere rodar o front por fora? Suba só `db`, `redis`, `migrate`,
`backend` e `worker` e use o modo manual abaixo.

### Manual — backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env    # o settings.py lê somente backend/.env
python manage.py migrate
python manage.py seed_demo

python manage.py runserver          # ASGI via daphne (WebSockets inclusos)
python manage.py settle_auctions_loop --interval 5   # worker, em outro terminal
```

Sem o worker, o fim do lote corrige quando você abre o lote (lazy
settle) e o início só muda no banco quando o primeiro lance é aceito —
a sala, porém, já se comporta como ao vivo assim que o relógio bate, e
o worker deixa vitrine e filtros verdadeiros em até 5 s.

### Manual — front

```bash
cd front
npm install
cp .env.example .env   # VITE_API_URL=http://localhost:8000
npm run dev            # http://localhost:5173
```

O CORS local libera apenas a origem `http://localhost:5173`.

## Seed

`python manage.py seed_demo` é idempotente e cria:

- `leiloeiro@demo.com`, `licitante1@demo.com`, `licitante2@demo.com`
  — senha `demo12345` para todos;
- carteiras com R$ 5.000,00 para os licitantes;
- quatro lotes: **ao vivo**, **agendado**, **encerrado** (com arremate
  e comprovante) e **cancelado** (com estorno);

Tenta buscar títulos e imagens no ArtIC e, sem rede, cai num fallback
local. Reexecutar reposiciona os horários dos lotes de demonstração.

## Testes

```bash
# backend — 206 testes
cd backend && ./.venv/bin/python manage.py test --noinput

# front — vitest + typecheck + lint
cd front && npm run test && npm run build && npm run lint
```

A cultura do repositório: suíte verde antes de qualquer commit, e
**sabotagem obrigatória** — quebrar a função de propósito e ver o
teste falhar para provar que ele testa o que deve.

## Decisões técnicas (e o porquê)

- **Centavos em `bigint`** — float soma errado; centavos é exato.
- **Ledger append-only como fonte da verdade** — saldo disponível é
  derivado; movimentação nunca se edita, só se acrescenta.
- **Lock transacional com ordem fixa** — lances simultâneos sem
  deadlock e sem saldo negativo.
- **Anti-snipe de +2 minutos** — impedir o "roubo de segundo".
- **Liquidação idempotente + lazy settle + worker** — encerrar duas
  vezes não debita duas vezes, e a liquidação não depende de um cron.
- **Cadeia de auditoria com HMAC, calculada no domínio** (nunca no
  serializer) — adulteração por `UPDATE`/`DELETE` fica detectável.
- **Pseudônimos HMAC e payloads sem `seller_id`/`winner_id`** — o
  público nunca vê identidade real.
- **WebSocket com origem validada no handshake** — recusa (403)
  acontece antes de qualquer evento chegar ao browser.
- **Imagens via proxy server-side** — a URL vem só do banco (sem
  SSRF), com cache e placeholder se o upstream cair.
- **Front sem UI kit** — CSS com variáveis e tema claro/escuro;
  estados derivados na renderização (nada de `setState` síncrono em
  efeito); dinheiro sempre em centavos até a formatação final.

## Deploy (previsto — ainda não executado)

- **Render**: web service + worker (`daphne config.asgi:application`
  na `${PORT}`), Redis gerenciado;
- **Neon**: PostgreSQL serverless (mapear `DATABASE_URL` nas envs
  `DB_*` que o settings lê);
- **Vercel**: SPA com `VITE_API_URL` no build e rewrite da raiz para
  `index.html` (rotas internas não podem dar 404);
- Env vars de produção: `DJANGO_SECRET_KEY`, `AUDIT_PSEUDO_SECRET`,
  `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`/`CSRF_TRUSTED_ORIGINS` com a
  origem real;
- Smoke final: seed, worker ativo, WS no ar, anti-snipe, estorno.

## Uso de IA

A construção do projeto usou IA (Claude, via agente OpenCode) como
ferramenta principal de execução, com o desenvolvedor no papel de
revisor, decisor e aprendiz. Três frentes:

### Pair programming

Cada etapa foi planejada e executada em diálogo: o *porquê* antes do
*código*, decisões explicadas (por que lock ordenado, por que centavos,
por que 403 no handshake), implementação revisada em conversa e cada
etapa virando um commit pequeno e revisável. O objetivo declarado era
entregar o escopo completo com o tempo e o conhecimento prático
disponíveis — priorizando o obrigatório sempre verde — e, no processo,
aprender de verdade cada escolha em vez de só colar o resultado.

### Conferência de documentação

Toda decisão de API conferida na documentação oficial antes de codar:
Django/DRF (comportamento de token inválido em endpoint público),
Channels (validação de origem no handshake), React/TypeScript e o
`Intl` do JavaScript (formatação BRL e a ambiguidade de parsing de
valores). O `PLANO.md` foi a fonte da verdade do escopo: o que está
nele é implementado e mapeado acima; o que não está, não entra.

### Orquestração e validação de testes

- Suíte de 206 testes no backend rodando a cada etapa, antes de
  qualquer commit; CI (GitHub Actions) reproduz a mesma suíte no
  push/PR — backend contra Postgres real e front com build + lint +
  testes;
- Sabotagem obrigatória: quebrar a função de propósito e confirmar o
  vermelho antes de aceitar o verde;
- No front: `vitest` (dinheiro em centavos, parser de BRL),
  typecheck, lint e smoke visual em browser headless;
- Auditorias de código morto e inadequado — foi assim que um bug de
  R$ 505 (parser `"50.5"` virando 10× o valor) foi achado e virou
  teste de regressão.

O humano mantém as chaves do processo: revisa cada etapa localmente,
decide escopo e aprova commits e pushes.

## Estrutura do repositório

```
backend/             Django + DRF + Channels (API, domínio, worker, testes)
front/               React + Vite + TypeScript (SPA)
.github/workflows/   CI: suíte backend (Postgres) + build/lint/testes do front
backend/.env.example template das envs do backend (copiar para backend/.env)
docker-compose.yml   Postgres, Redis, migrations, API, worker e front
PLANO.md             plano completo: escopo, arquitetura, deploy, testes
```

## Comportamentos conhecidos

Pouco óbvios de propósito, documentados aqui (o escopo pede que
"comportamentos inesperados" sejam mencionados):

- **Lote do seed "pula" de horário a cada reexecução** — `seed_demo`
  reposiciona o fim do lote ao vivo para ~10 min a partir de agora,
  para a demonstração sempre ter janela. Lotes com lance já liquidado
  não são revividos.
- **Começo de lote só efetiva no primeiro lance ou no worker** — sem o
  `settle_auctions_loop`, um lote agendado que venceu a janela de
  início só transiciona para `live` quando o primeiro lance passa pela
  validação (lazy) ou quando o worker roda. A sala, porém, já o trata
  como ao vivo assim que o relógio bate.
- **Catálogo do ArtIC nem sempre traz descrição/atributos** — a fonte
  nem sempre devolve texto; nesse caso a ficha da obra aparece com os
  campos disponíveis e a importação segue.
