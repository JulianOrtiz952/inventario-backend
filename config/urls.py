from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from inventario.views import InsumoViewSet, ProveedorViewSet, ProductoViewSet, RecetaViewSet, ProduccionViewSet

router = DefaultRouter()
router.register(r"insumos", InsumoViewSet, basename="insumo")
router.register(r"proveedores", ProveedorViewSet, basename="proveedor")
router.register(r"productos", ProductoViewSet, basename="producto")
router.register(r"recetas", RecetaViewSet, basename="receta") 
router.register(r"producciones", ProduccionViewSet, basename="produccion")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(router.urls)),  
    
]
