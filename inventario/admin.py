from django.contrib import admin
from .models import Insumo, Proveedor


@admin.register(Proveedor)
class ProveedorAdmin(admin.ModelAdmin):
    list_display = ("id", "nombre")
    search_fields = ("nombre",)


@admin.register(Insumo)
class InsumoAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "nombre",
        "unidad",
        "stock_actual",
        "stock_minimo",
        "costo_unitario",
        "proveedor",
        "estado_display",
    )
    list_filter = ("unidad", "proveedor")
    search_fields = ("nombre",)

    def estado_display(self, obj):
        return "Bajo mínimo" if obj.estado == "BAJO_MINIMO" else "OK"

    estado_display.short_description = "Estado"
