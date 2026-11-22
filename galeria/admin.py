from django.contrib import admin

from .models import Foto


@admin.register(Foto)
class FotoAdmin(admin.ModelAdmin):
    list_display = ("id", "codigo_evento", "criado_em")
    list_filter = ("codigo_evento", "criado_em")
    search_fields = ("codigo_evento",)
    ordering = ("-criado_em",)
