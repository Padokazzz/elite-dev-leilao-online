from django.contrib import admin

from .models import Wallet, WalletTransaction


class WalletTransactionInline(admin.TabularInline):
    model = WalletTransaction
    extra = 0
    can_delete = False
    readonly_fields = (
        "kind",
        "delta_cents",
        "committed_delta_cents",
        "auction",
        "description",
        "created_at",
    )


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "balance_cents",
        "committed_cents",
        "available_cents",
        "updated_at",
    )
    search_fields = ("user__email",)
    readonly_fields = ("balance_cents", "committed_cents", "updated_at")
    inlines = [WalletTransactionInline]


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "wallet",
        "kind",
        "delta_cents",
        "committed_delta_cents",
        "auction",
    )
    list_filter = ("kind",)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
    