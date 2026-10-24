from django.urls import path

from .views import DepositView, WalletTransactionsView, WalletView

urlpatterns = [
    path("", WalletView.as_view(), name="wallet"),
    path("deposit/", DepositView.as_view(), name="wallet-deposit"),
    path(
        "transactions/",
        WalletTransactionsView.as_view(),
        name="wallet-transactions",
    ),
]