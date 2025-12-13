from rest_framework import viewsets, status
from .models import (
    Insumo, Proveedor, Producto, Bodega, Impuesto, PrecioProducto,
    Tercero, DatosAdicionalesProducto, Talla, NotaEnsamble
)
from .serializers import (
    InsumoSerializer, ProveedorSerializer, ProductoSerializer, BodegaSerializer,
    ImpuestoSerializer, ProductoPrecioWriteSerializer,
    TerceroSerializer, DatosAdicionalesWriteSerializer,
    TallaSerializer, NotaEnsambleSerializer
)
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import action
from decimal import Decimal
from django.db import transaction

class DebugValidationMixin:
    """
    Devuelve detalles completos cuando hay 400 por validación.
    Útil para DEV con frontend.
    """
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return Response(
                {
                    "detail": "Error de validación (DEBUG).",
                    "errors": e.detail,          # errores por campo
                    "received": request.data,    # payload que llegó
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return Response(
                {
                    "detail": "Error de validación (DEBUG).",
                    "errors": e.detail,
                    "received": request.data,
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        self.perform_update(serializer)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ProveedorViewSet(viewsets.ModelViewSet):
    queryset = Proveedor.objects.all().order_by("id")
    serializer_class = ProveedorSerializer


class BodegaViewSet(viewsets.ModelViewSet):
    queryset = Bodega.objects.all().order_by("nombre")
    serializer_class = BodegaSerializer


class TerceroViewSet(viewsets.ModelViewSet):
    queryset = Tercero.objects.all().order_by("codigo")
    serializer_class = TerceroSerializer


class ImpuestoViewSet(viewsets.ModelViewSet):
    queryset = Impuesto.objects.all().order_by("codigo")
    serializer_class = ImpuestoSerializer


class ProductoViewSet(viewsets.ModelViewSet):
    queryset = (
        Producto.objects
        .select_related("tercero")
        .prefetch_related("impuestos", "precios")
        .order_by("-creado_en")
    )
    serializer_class = ProductoSerializer


class PrecioProductoViewSet(viewsets.ModelViewSet):
    queryset = PrecioProducto.objects.select_related("producto").order_by("-id")
    serializer_class = ProductoPrecioWriteSerializer


class DatosAdicionalesProductoViewSet(DebugValidationMixin, viewsets.ModelViewSet):
    queryset = DatosAdicionalesProducto.objects.select_related("producto").order_by("-id")
    serializer_class = DatosAdicionalesWriteSerializer


class InsumoViewSet(DebugValidationMixin,viewsets.ModelViewSet):
    queryset = (
        Insumo.objects
        .select_related("bodega", "proveedor", "tercero")
        .order_by("nombre")
    )
    serializer_class = InsumoSerializer


class TallaViewSet(viewsets.ModelViewSet):
    queryset = Talla.objects.all().order_by("nombre")
    serializer_class = TallaSerializer


class NotaEnsambleViewSet(viewsets.ModelViewSet):
    queryset = NotaEnsamble.objects.select_related("producto", "bodega", "talla", "tercero").order_by("-id")
    serializer_class = NotaEnsambleSerializer

    def _get_datos_adicionales(self, producto):
        # Si no existe, lo crea con stock en 0 (evita AttributeError)
        datos, _ = DatosAdicionalesProducto.objects.get_or_create(
            producto=producto,
            defaults={"stock": Decimal("0")}
        )
        return datos

    @transaction.atomic
    def perform_create(self, serializer):
        instance = serializer.save()

        datos = self._get_datos_adicionales(instance.producto)
        datos.stock = (datos.stock or Decimal("0")) + (instance.cantidad or Decimal("0"))
        datos.save(update_fields=["stock"])

    @transaction.atomic
    def perform_update(self, serializer):
        # Estado anterior (antes de guardar)
        old_instance = self.get_object()
        old_producto = old_instance.producto
        old_cantidad = old_instance.cantidad or Decimal("0")

        # Guardar cambios
        instance = serializer.save()
        new_producto = instance.producto
        new_cantidad = instance.cantidad or Decimal("0")

        # Caso 1: mismo producto → sumar delta
        if old_producto == new_producto:
            delta = new_cantidad - old_cantidad
            if delta != 0:
                datos = self._get_datos_adicionales(new_producto)
                datos.stock = (datos.stock or Decimal("0")) + delta
                datos.save(update_fields=["stock"])
            return

        # Caso 2: cambió el producto → revertir en el viejo y sumar en el nuevo
        datos_old = self._get_datos_adicionales(old_producto)
        datos_old.stock = (datos_old.stock or Decimal("0")) - old_cantidad
        datos_old.save(update_fields=["stock"])

        datos_new = self._get_datos_adicionales(new_producto)
        datos_new.stock = (datos_new.stock or Decimal("0")) + new_cantidad
        datos_new.save(update_fields=["stock"])

    @transaction.atomic
    def perform_destroy(self, instance):
        # Al borrar, revertimos stock
        datos = self._get_datos_adicionales(instance.producto)
        datos.stock = (datos.stock or Decimal("0")) - (instance.cantidad or Decimal("0"))
        datos.save(update_fields=["stock"])

        instance.delete()