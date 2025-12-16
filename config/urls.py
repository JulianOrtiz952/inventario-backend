from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from inventario.views import (
    InsumoViewSet, ProveedorViewSet, ProductoViewSet, BodegaViewSet,
    ImpuestoViewSet, PrecioProductoViewSet, TerceroViewSet,
    DatosAdicionalesProductoViewSet, TallaViewSet, NotaEnsambleViewSet, ProductoInsumoViewSet, TrasladoProductoViewSet
)

router = DefaultRouter()

router.register(r"proveedores", ProveedorViewSet, basename="proveedor")
router.register(r"bodegas", BodegaViewSet, basename="bodega")

router.register(r"terceros", TerceroViewSet, basename="tercero")
router.register(r"impuestos", ImpuestoViewSet, basename="impuesto")

router.register(r"productos", ProductoViewSet, basename="producto")
router.register(r"producto-precios", PrecioProductoViewSet, basename="producto-precio")
router.register(r"producto-datos-adicionales", DatosAdicionalesProductoViewSet, basename="producto-datos-adicionales")

router.register(r"insumos", InsumoViewSet, basename="insumo")

router.register(r"tallas", TallaViewSet, basename="talla")
router.register(r"notas-ensamble", NotaEnsambleViewSet, basename="nota-ensamble")

router.register(r"producto-insumos", ProductoInsumoViewSet, basename="producto-insumos")

router.register(r"traslados-producto", TrasladoProductoViewSet, basename="traslados-producto")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(router.urls)),
]
