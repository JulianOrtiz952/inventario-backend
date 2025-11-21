from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from inventario.views import InsumoViewSet, ProveedorViewSet

router = DefaultRouter()
router.register(r"insumos", InsumoViewSet, basename="insumo")
router.register(r"proveedores", ProveedorViewSet, basename="proveedor")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(router.urls)),  
]
