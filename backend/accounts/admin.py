from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("email", "username", "role", "is_active", "date_joined")
    list_filter = ("role", "is_active")
    search_fields = ("email", "username")
    ordering = ("email",)

    # O UserAdmin padrão do Django assume "username" como campo
    # de identificação. Nosso sistema identifica por EMAIL.
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        (None, {"fields": ("email", "role")}),
    )
    fieldsets = BaseUserAdmin.fieldsets + (
        (None, {"fields": ("role",)}),
    )