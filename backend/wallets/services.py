from django.db import transaction

from .models import Wallet, WalletTransaction

MIN_DEPOSIT_CENTS = 100              # R$ 1,00
MAX_DEPOSIT_CENTS = 1_000_000_00     # R$ 1.000.000,00


def get_or_create_wallet(user) -> Wallet:
    wallet, _ = Wallet.objects.get_or_create(user=user)
    return wallet


def lock_wallets(user_ids) -> dict:
    locked = {}
    for user_id in sorted(set(user_ids)):
        wallet, _ = Wallet.objects.select_for_update().get_or_create(
            user_id=user_id
        )
        locked[user_id] = wallet
    return locked


def deposit(*, wallet_id: int, amount_cents: int) -> Wallet:
    if amount_cents < MIN_DEPOSIT_CENTS:
        raise ValueError("O depósito mínimo é de R$ 1,00.")
    if amount_cents > MAX_DEPOSIT_CENTS:
        raise ValueError("O depósito máximo é de R$ 1.000.000,00.")

    with transaction.atomic():
        wallet = Wallet.objects.select_for_update().get(pk=wallet_id)

        wallet.balance_cents += amount_cents
        wallet.save(update_fields=["balance_cents", "updated_at"])

        WalletTransaction.objects.create(
            wallet=wallet,
            kind=WalletTransaction.Kind.DEPOSIT,
            delta_cents=amount_cents,
            description="Depósito simulado",
        )

    return wallet