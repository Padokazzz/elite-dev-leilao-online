def auction_group(auction_id: int) -> str:
    """Nome do grupo da sala. Contrato entre quem publica e quem escuta.

    Precisa casar com ^[a-zA-Z\\d\\-_.]+$ do channel layer.
    """
    return f"auction.{auction_id}"
