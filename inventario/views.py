from rest_framework import viewsets, status 
from .models import Insumo, Proveedor, Producto, Receta, RecetaItem, Produccion
from decimal import Decimal
from .serializers import InsumoSerializer, ProveedorSerializer, ProductoSerializer, RecetaSerializer, ProduccionSerializer
from rest_framework.decorators import action
from django.db import transaction
from rest_framework.response import Response


class ProveedorViewSet(viewsets.ModelViewSet):
    queryset = Proveedor.objects.all().order_by("id")
    serializer_class = ProveedorSerializer


class InsumoViewSet(viewsets.ModelViewSet):
    queryset = Insumo.objects.select_related("proveedor").order_by("id")
    serializer_class = InsumoSerializer

class ProductoViewSet(viewsets.ModelViewSet):
    queryset = Producto.objects.all().order_by("-id")
    serializer_class = ProductoSerializer

class RecetaViewSet(viewsets.ModelViewSet):
    queryset = Receta.objects.all().prefetch_related("items__insumo")
    serializer_class = RecetaSerializer

    @action(detail=True, methods=["post"], url_path="producir")
    def producir(self, request, pk=None):
        receta = self.get_object()

        try:
            cantidad_int = int(request.data.get("cantidad", 0))
        except (TypeError, ValueError):
            return Response(
                {"detail": "Cantidad inválida."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if cantidad_int <= 0:
            return Response(
                {"detail": "La cantidad debe ser mayor a 0."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cantidad = Decimal(cantidad_int)

        insuficientes = []
        requerimientos = []  # lista de (insumo, requerido Decimal)

        # Verificar stock
        for item in receta.items.all():
            insumo = item.insumo
            requerido = item.cantidad * cantidad   # Decimal
            disponible = insumo.stock_actual       # Decimal

            requerimientos.append((insumo, requerido))

            if disponible < requerido:
                insuficientes.append(
                    {
                        "id": insumo.id,
                        "nombre": insumo.nombre,
                        "unidad": insumo.unidad,
                        "requerido": float(requerido),
                        "disponible": float(disponible),
                        "faltante": float(requerido - disponible),
                    }
                )

        if insuficientes:
            return Response(
                {
                    "detail": "Stock insuficiente para producir la cantidad solicitada.",
                    "insumos": insuficientes,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Descontar y registrar historial
        with transaction.atomic():
            actualizados = []
            for insumo, requerido in requerimientos:
                insumo.stock_actual = insumo.stock_actual - requerido
                insumo.save(update_fields=["stock_actual"])
                actualizados.append(
                    {
                        "id": insumo.id,
                        "nombre": insumo.nombre,
                        "stock_actual": float(insumo.stock_actual),
                    }
                )

            # 👇 Registrar producción en historial
            produccion = Produccion.objects.create(
                receta=receta,
                cantidad=cantidad_int,
            )

        return Response(
            {
                "detail": "Producción registrada y stock actualizado.",
                "receta_id": receta.id,
                "cantidad_producida": cantidad_int,
                "insumos_actualizados": actualizados,
                "produccion_id": produccion.id,
            },
            status=status.HTTP_201_CREATED,
        )

class ProduccionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Solo lectura: historial de productos creados.
    """
    queryset = Produccion.objects.select_related("receta").order_by("-creado_en")
    serializer_class = ProduccionSerializer