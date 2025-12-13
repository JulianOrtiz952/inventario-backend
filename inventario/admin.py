from django.contrib import admin
from .models import Insumo, Proveedor


@admin.register(Proveedor)
class ProveedorAdmin(admin.ModelAdmin):
    list_display = ("id", "nombre")
    search_fields = ("nombre",)


@admin.register(Insumo)
class InsumoAdmin(admin.ModelAdmin):
    list_display = (
        "codigo",
        "nombre",
        "referencia",
        "bodega",
        "cantidad",
        "costo_unitario",
    )
    search_fields = ("codigo", "nombre", "referencia")
    list_filter = ("bodega",)
