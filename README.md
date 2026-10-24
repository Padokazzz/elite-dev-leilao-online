# Elite Dev | Leilão Online

Projeto desenvolvido como parte do processo seletivo Elite Dev.

## Objetivo

Construir uma plataforma de leilões online com gerenciamento de lotes, lances em tempo real, carteiras de usuários e histórico auditável.

## Tecnologias

- **Backend:** Python, Django e Django REST Framework
- **Frontend:** React, TypeScript e Vite
- **Banco de dados:** PostgreSQL
- **Comunicação em tempo real:** Django Channels e WebSockets

## Status do projeto

Em desenvolvimento.

- [x] Estrutura inicial do backend Django
- [x] Endpoint de verificação de saúde da API
- [x] Autenticação e papéis de usuário
- [x] Catálogo de itens (busca e importação da API externa, com cache local)
- [x] Carteiras: saldo total, comprometido e disponível, depósito simulado e ledger de movimentações
- [ ] Validação de lances
- [ ] Gerenciamento de leilões
- [ ] Atualizações em tempo real
- [ ] Auditoria e comprovantes
- [ ] Testes automatizados
- [ ] Deploy público

### Endpoints disponíveis

| Método | Rota | Descrição |
| :--- | :--- | :--- |
| GET | `/api/health` | Verificação de saúde da API |
| POST | `/api/auth/register/` | Registro (papel sempre definido como licitante) |
| POST | `/api/auth/login/` | Login por e-mail, devolve token |
| GET | `/api/auth/me/` | Usuário autenticado |
| POST | `/api/auth/logout/` | Revoga o token |
| GET | `/api/catalog/search/` | Busca obras na API externa |
| POST | `/api/catalog/import/` | Importa uma obra para o catálogo local |
| GET | `/api/wallets/` | Saldo total, comprometido e disponível |
| POST | `/api/wallets/deposit/` | Depósito simulado (aceita `"amount": "50.00"`) |
| GET | `/api/wallets/transactions/` | Extrato (ledger, mais recentes primeiro) |

## Execução local

As instruções de instalação, configuração do banco de dados e execução serão adicionadas conforme a implementação evoluir.

## Uso de inteligência artificial

A utilização de ferramentas de inteligência artificial será declarada de forma transparente na entrega final, incluindo o escopo de apoio utilizado no desenvolvimento.

## Deploy

A aplicação ainda não foi publicada.

## Licença

Definir conforme as condições do teste e a estratégia de distribuição do projeto.