class LedgerImmutableError(Exception):
    """Tentativa de alterar ou apagar um registro do ledger.

    O ledger é append-only: é a prova de cada movimentação de dinheiro.
    Corrigir um registro errado significa criar um NOVO registro que o
    compense (ex.: um estorno) — nunca sobrescrever o histórico.
    """