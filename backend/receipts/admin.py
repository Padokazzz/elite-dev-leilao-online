from django.contrib import admin

from .models import Receipt


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ("public_uuid", "amount_cents", "settled_at")
    ordering = ("-settled_at",)
