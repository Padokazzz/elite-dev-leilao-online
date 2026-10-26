from rest_framework import serializers

class PlaceBidSerializer(serializers.Serializer):
    """Apenas a FORMA do payload.

    Regras de valor (<= 0, abaixo do mínimo, saldo) vivem em place_bid(),
    para que HTTP, WebSocket e worker devolvam exatamente o mesmo código —
    e para que um único lugar decida o que é um lance inválido.
    """

    amount_cents = serializers.IntegerField()