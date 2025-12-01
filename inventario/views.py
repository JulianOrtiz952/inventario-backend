from rest_framework import viewsets, status 
from .models import Insumo, Proveedor, Producto, Receta, RecetaItem, Produccion, Bodega
from decimal import Decimal
from .serializers import InsumoSerializer, ProveedorSerializer, ProductoSerializer, RecetaSerializer, ProduccionSerializer, BodegaSerializer
from rest_framework.decorators import action
from django.db import transaction
from rest_framework.response import Response
from django.db.models import Count, Sum


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
            requerido = item.cantidad * cantidad
            disponible = insumo.stock_actual

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

        # 👇 NUEVO: determinar la bodega de esta producción
        bodega = None
        bodega_id = request.data.get("bodega_id")

        if bodega_id:
            try:
                bodega = Bodega.objects.get(pk=bodega_id)
            except Bodega.DoesNotExist:
                return Response(
                    {"detail": "La bodega indicada no existe."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            # si no la mandan, usamos la bodega de la receta (si tiene)
            bodega = receta.bodega

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

            produccion = Produccion.objects.create(
                receta=receta,
                bodega=bodega,          # 👈 AQUÍ GUARDAMOS LA BODEGA
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
    queryset = (
        Produccion.objects
        .select_related("receta", "bodega")
        .order_by("-creado_en")
    )
    serializer_class = ProduccionSerializer

class BodegaViewSet(viewsets.ModelViewSet):
    serializer_class = BodegaSerializer

    def get_queryset(self):
        # Cantidad de insumos y recetas distintas producidas en la bodega
        return (
            Bodega.objects
            .annotate(
                insumos_count=Count("insumos", distinct=True),
                recetas_count=Count("producciones__receta", distinct=True),
            )
            .order_by("nombre")
        )

    @action(detail=True, methods=["get"], url_path="contenido")
    def contenido(self, request, pk=None):
        """
        Contenido de la bodega:
        - Insumos asociados directamente a la bodega
        - Recetas producidas en la bodega, con la suma total producida
        """
        bodega = self.get_object()

        # Insumos de la bodega
        insumos = Insumo.objects.filter(bodega=bodega).order_by("nombre")

        # Agregamos producciones por receta dentro de ESTA bodega
        agregados = (
            Produccion.objects
            .filter(bodega=bodega)
            .values("receta_id", "receta__codigo", "receta__nombre")
            .annotate(total_producido=Sum("cantidad"))
            .order_by("receta__codigo")
        )

        # Armamos estructura simple para el front
        productos_data = [
            {
                "id": row["receta_id"],
                "codigo": row["receta__codigo"],
                "nombre": row["receta__nombre"],
                "total_producido": row["total_producido"] or 0,
            }
            for row in agregados
        ]

        insumos_data = InsumoSerializer(insumos, many=True).data

        return Response(
            {
                "bodega": BodegaSerializer(bodega).data,
                "insumos": insumos_data,
                "productos": productos_data,
            }
        )