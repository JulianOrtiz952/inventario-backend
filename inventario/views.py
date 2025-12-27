from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from decimal import Decimal
from django.db import transaction
from rest_framework.decorators import action
from django.db.models import Sum, Count, Q, F
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from .models import (
    Insumo, Proveedor, Producto, Bodega, Impuesto, PrecioProducto,
    Tercero, DatosAdicionalesProducto, Talla,
    NotaEnsamble, ProductoInsumo, NotaEnsambleDetalle, NotaEnsambleInsumo, TrasladoProducto, NotaSalidaProducto
)
from .serializers import (
    InsumoSerializer, ProveedorSerializer, ProductoSerializer, BodegaSerializer,
    ImpuestoSerializer, ProductoPrecioWriteSerializer,
    TerceroSerializer, DatosAdicionalesWriteSerializer,
    TallaSerializer, NotaEnsambleSerializer, ProductoInsumoSerializer, TrasladoProductoSerializer, NotaSalidaProductoSerializer
)

def consumir_insumos_manuales_por_delta(nota, signo=Decimal("1")):
    """
    signo = +1 descuenta los insumos manuales asociados a la nota
    signo = -1 devuelve (reversa)
    """
    # Si todavía no tienes el modelo NotaEnsambleInsumo/related_name="insumos", ajusta esto:
    for ni in nota.insumos.all():
        cantidad = _d(ni.cantidad) * signo

        # buscar insumo en la bodega de la nota (si tu Insumo es por bodega)
        ins = ni.insumo
        if ins.bodega_id != nota.bodega_id:
            ins = Insumo.objects.filter(codigo=ni.insumo.codigo, bodega=nota.bodega).first()

        if not ins:
            raise ValidationError({"detail": f"Insumo {ni.insumo.codigo} no existe en la bodega de la nota."})

        if cantidad > 0 and _d(ins.cantidad) < cantidad:
            raise ValidationError({
                "stock_insuficiente": {
                    ins.codigo: {
                        "insumo": ins.nombre,
                        "disponible": str(_d(ins.cantidad)),
                        "requerido": str(_d(cantidad)),
                        "faltante": str(_d(cantidad) - _d(ins.cantidad)),
                    }
                }
            })

        # aplicar delta
        ins.cantidad = _d(ins.cantidad) - cantidad
        ins.save(update_fields=["cantidad"])

class DebugValidationMixin:
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
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


def _d(x):
    try:
        return Decimal(str(x))
    except Exception:
        return Decimal("0")

def consumir_insumos_por_delta(producto, bodega, cantidad_producto):
    cantidad_producto = _d(cantidad_producto)
    if cantidad_producto == 0:
        return

    lineas_bom = ProductoInsumo.objects.filter(producto=producto).select_related("insumo")
    if not lineas_bom.exists():
        return

    insuficientes = {}
    requeridos = []

    for li in lineas_bom:
        cpu = _d(li.cantidad_por_unidad)
        merma = _d(li.merma_porcentaje)
        requerido = cantidad_producto * cpu * (Decimal("1") + (merma / Decimal("100")))

        insumo_ref = li.insumo
        if insumo_ref.bodega_id != bodega.id:
            insumo_ref = Insumo.objects.filter(codigo=li.insumo.codigo, bodega=bodega).first()

        if not insumo_ref:
            insuficientes[li.insumo.codigo] = {
                "insumo": getattr(li.insumo, "nombre", li.insumo.codigo),
                "disponible": "0",
                "requerido": str(abs(requerido)),
                "faltante": str(abs(requerido)),
            }
            continue

        requeridos.append((insumo_ref, requerido))

    if cantidad_producto > 0:
        for insumo_obj, requerido in requeridos:
            requerido_abs = abs(_d(requerido))
            disponible = _d(insumo_obj.cantidad)
            if disponible < requerido_abs:
                insuficientes[insumo_obj.codigo] = {
                    "insumo": insumo_obj.nombre,
                    "disponible": str(disponible),
                    "requerido": str(requerido_abs),
                    "faltante": str(requerido_abs - disponible),
                }
        if insuficientes:
            raise ValidationError({"stock_insuficiente": insuficientes})

    for insumo_obj, requerido in requeridos:
        delta = abs(_d(requerido))
        if cantidad_producto > 0:
            insumo_obj.cantidad = _d(insumo_obj.cantidad) - delta
        else:
            insumo_obj.cantidad = _d(insumo_obj.cantidad) + delta
        insumo_obj.save(update_fields=["cantidad"])


from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from decimal import Decimal
from django.db import transaction

from .models import (
    Insumo,
    DatosAdicionalesProducto,
    NotaEnsamble,
    ProductoInsumo,
    NotaEnsambleDetalle,
    NotaEnsambleInsumo,  # ✅ asegúrate de importarlo
)
from .serializers import NotaEnsambleSerializer


def _d(x):
    try:
        return Decimal(str(x))
    except Exception:
        return Decimal("0")


def consumir_insumos_por_delta(producto, bodega, cantidad_producto):
    """
    cantidad_producto:
      > 0 => consumir (descontar)
      < 0 => devolver (revertir)
    """
    cantidad_producto = _d(cantidad_producto)
    if cantidad_producto == 0:
        return

    lineas_bom = ProductoInsumo.objects.filter(producto=producto).select_related("insumo")
    if not lineas_bom.exists():
        return

    insuficientes = {}
    requeridos = []

    for li in lineas_bom:
        cpu = _d(li.cantidad_por_unidad)
        merma = _d(li.merma_porcentaje)
        requerido = cantidad_producto * cpu * (Decimal("1") + (merma / Decimal("100")))

        insumo_ref = li.insumo
        if not insumo_ref:
            insuficientes[li.insumo.codigo] = {
            "insumo": getattr(li.insumo, "nombre", li.insumo.codigo),
            "disponible": "0",
            "requerido": str(abs(requerido)),
            "faltante": str(abs(requerido)),
            }
        continue

        requeridos.append((insumo_ref, requerido))

    # Validación solo si consumimos
    if cantidad_producto > 0:
        for insumo_obj, requerido in requeridos:
            requerido_abs = abs(_d(requerido))
            disponible = _d(insumo_obj.cantidad)
            if disponible < requerido_abs:
                insuficientes[insumo_obj.codigo] = {
                    "insumo": insumo_obj.nombre,
                    "disponible": str(disponible),
                    "requerido": str(requerido_abs),
                    "faltante": str(requerido_abs - disponible),
                }
        if insuficientes:
            raise ValidationError({"stock_insuficiente": insuficientes})

    # Aplicar delta
    for insumo_obj, requerido in requeridos:
        delta = abs(_d(requerido))
        if cantidad_producto > 0:
            insumo_obj.cantidad = _d(insumo_obj.cantidad) - delta
        else:
            insumo_obj.cantidad = _d(insumo_obj.cantidad) + delta
        insumo_obj.save(update_fields=["cantidad"])


class NotaEnsambleViewSet(viewsets.ModelViewSet):
    queryset = (
        NotaEnsamble.objects
        .prefetch_related("detalles", "insumos")  # ✅ importante
        .select_related("bodega", "tercero")
        .order_by("-id")
    )
    serializer_class = NotaEnsambleSerializer

    def _get_datos_adicionales(self, producto):
        datos = DatosAdicionalesProducto.objects.filter(producto=producto).first()
        if datos:
            return datos

        # ✅ defaults completos (según tu modelo)
        return DatosAdicionalesProducto.objects.create(
            producto=producto,
            referencia="N/A",
            unidad="UND",
            stock=Decimal("0"),
            stock_minimo=Decimal("0"),
            descripcion=getattr(producto, "descripcion", "") or "",
            marca="N/A",
            modelo="N/A",
            codigo_arn="N/A",
            imagen_url="",
        )

    def _total_productos_nota(self, nota):
        # ✅ sumatoria de cantidades de productos terminados
        return sum(_d(d.cantidad) for d in nota.detalles.all())

    def _aplicar_detalles(self, nota, detalles, signo=Decimal("1")):
        """
        Aplica o revierte:
        - Consumo por receta (BOM)
        - Stock del producto terminado
        """
        for det in detalles:
            producto = det.producto
            cantidad = _d(det.cantidad) * signo

            # BOM
            consumir_insumos_por_delta(producto, nota.bodega, cantidad)

            # Stock producto terminado
            datos = self._get_datos_adicionales(producto)
            datos.stock = _d(datos.stock) + cantidad
            datos.save(update_fields=["stock"])

    def _aplicar_insumos_manuales(self, nota, signo=Decimal("1")):
        """
        Interpreta ni.cantidad como: cantidad POR UNIDAD de producto terminado.
        Entonces descuenta/devuelve: (ni.cantidad * total_productos_en_nota) * signo
        """
        total_productos = self._total_productos_nota(nota)
        if total_productos == 0:
            return

        for ni in nota.insumos.all():
            cant_total = _d(ni.cantidad) * _d(total_productos) * signo

            ins = ni.insumo

            if not ins:
                raise ValidationError({"detail": f"Insumo {ni.insumo.codigo} no existe en la bodega de la nota."})

            if cant_total > 0:
                disponible = _d(ins.cantidad)
                if disponible < cant_total:
                    raise ValidationError({
                        "stock_insuficiente": {
                            ins.codigo: {
                                "insumo": ins.nombre,
                                "disponible": str(disponible),
                                "requerido": str(cant_total),
                                "faltante": str(cant_total - disponible),
                            }
                        }
                    })
                ins.cantidad = disponible - cant_total
            else:
                # devolver
                ins.cantidad = _d(ins.cantidad) + abs(_d(cant_total))

            ins.save(update_fields=["cantidad"])

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """
        Flujo:
        1) Crear nota (serializer.create)
        2) Crear detalles
        3) Aplicar: BOM/stock + insumos manuales
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        detalles_data = serializer.validated_data.pop("detalles_input", [])
        if not detalles_data:
            raise ValidationError({"detalles_input": "Debe enviar al menos un detalle."})

        # ✅ Crear nota (tu serializer.create ya crea insumos manuales si envías insumos_input)
        nota = serializer.save()

        # ✅ Crear detalles
        NotaEnsambleDetalle.objects.bulk_create(
            [NotaEnsambleDetalle(nota=nota, **d) for d in detalles_data]
        )

        nota.refresh_from_db()

        # ✅ Aplicar receta/stock
        self._aplicar_detalles(nota, nota.detalles.all(), signo=Decimal("1"))

        # ✅ Aplicar insumos manuales (multiplicando por total productos)
        self._aplicar_insumos_manuales(nota, signo=Decimal("1"))

        return Response(self.get_serializer(nota).data, status=status.HTTP_201_CREATED)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        """
        Flujo correcto:
        1) Revertir TODO (lo viejo)
        2) Guardar cabecera
        3) Reemplazar detalles + insumos manuales
        4) Aplicar TODO (lo nuevo)
        """
        nota = self.get_object()

            # 🚫 Bloquear si hay detalles fuera de la bodega original de la nota
        if nota.detalles.exclude(bodega_actual=nota.bodega).exists():
            raise ValidationError({
                "detail": (
                    "Esta nota tiene productos trasladados a otra bodega. "
                    "Para evitar inconsistencias, esta nota no se puede editar. "
                    "Crea una nueva nota o revierte los traslados antes de editar."
                ),
                "code": "NOTA_CON_TRASLADOS"
            })

        # 1) Revertir lo anterior (BOM/stock + manuales)
        self._aplicar_detalles(nota, list(nota.detalles.all()), signo=Decimal("-1"))
        self._aplicar_insumos_manuales(nota, signo=Decimal("-1"))

        # 2) Validar payload
        serializer = self.get_serializer(nota, data=request.data, partial=False)
        serializer.is_valid(raise_exception=True)

        detalles_data = serializer.validated_data.pop("detalles_input", [])
        if not detalles_data:
            raise ValidationError({"detalles_input": "Debe enviar al menos un detalle."})

        # ✅ MUY IMPORTANTE: sacar insumos_input aquí para que no rompa serializer.save()
        insumos_data = serializer.validated_data.pop("insumos_input", [])

        # 3) Guardar cabecera
        nota = serializer.save()

        # 4) Reemplazar detalles
        nota.detalles.all().delete()
        NotaEnsambleDetalle.objects.bulk_create(
            [NotaEnsambleDetalle(nota=nota, **d) for d in detalles_data]
        )

        # 5) Reemplazar insumos manuales (si no vienen => queda vacío => “se quitaron”)
        nota.insumos.all().delete()
        if insumos_data:
            objs = []
            # resolver insumos por código (más eficiente)
            codigos = [i["insumo_codigo"] for i in insumos_data]
            mapa = {x.codigo: x for x in Insumo.objects.filter(codigo__in=codigos)}
            for i in insumos_data:
                ins = mapa.get(i["insumo_codigo"])
                if not ins:
                    raise ValidationError({"insumos_input": f"Insumo {i['insumo_codigo']} no existe."})
                objs.append(NotaEnsambleInsumo(
                    nota=nota,
                    insumo=ins,
                    cantidad=i["cantidad"]
                ))
            NotaEnsambleInsumo.objects.bulk_create(objs)

        nota.refresh_from_db()

        # 6) Aplicar lo nuevo
        self._aplicar_detalles(nota, nota.detalles.all(), signo=Decimal("1"))
        self._aplicar_insumos_manuales(nota, signo=Decimal("1"))

        return Response(self.get_serializer(nota).data, status=status.HTTP_200_OK)

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        """
        1) Revertir TODO
        2) Eliminar
        """
        nota = self.get_object()

        self._aplicar_detalles(nota, list(nota.detalles.all()), signo=Decimal("-1"))
        self._aplicar_insumos_manuales(nota, signo=Decimal("-1"))

        return super().destroy(request, *args, **kwargs)
  


class DebugValidationMixin:
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return Response(
                {"detail": "Error de validación (DEBUG).", "errors": e.detail, "received": request.data},
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
                {"detail": "Error de validación (DEBUG).", "errors": e.detail, "received": request.data},
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

    def get_queryset(self):
        return (
            Bodega.objects
            .annotate(
                insumos_count=Count("insumos", distinct=True),

                # Cuenta productos distintos en los detalles cuya bodega efectiva sea esta bodega
                productos_count=Count(
                    "productos_detalle__producto",
                    filter=Q(productos_detalle__cantidad__gt=0),
                    distinct=True
                )
            )
            .order_by("nombre")
        )   

    @action(detail=True, methods=["get"], url_path="stock-terminado")
    def stock_terminado(self, request, pk=None):
        """
        Devuelve el stock de producto terminado en esta bodega, agrupado por SKU + talla.
        Soporta filtro opcional: ?sku=CAM-005
        """
        bodega = self.get_object()
        sku = (request.query_params.get("sku") or "").strip()

        qs = (
            NotaEnsambleDetalle.objects
            .filter(cantidad__gt=0)
            .filter(
                Q(bodega_actual=bodega) |
                Q(bodega_actual__isnull=True, nota__bodega=bodega)
            )
        )

        if sku:
            qs = qs.filter(producto__codigo_sku=sku)

        data = (
            qs.values("producto__codigo_sku", "producto__nombre", "talla")
              .annotate(cantidad=Sum("cantidad"))
              .order_by("producto__codigo_sku", "talla")
        )

        # Normaliza keys a lo que el front consume fácil
        result = [
            {
                "producto_id": row["producto__codigo_sku"],
                "producto_nombre": row["producto__nombre"],
                "talla": row["talla"] or "",
                "cantidad": str(row["cantidad"] or 0),
                "bodega_id": bodega.id,
                "bodega_nombre": bodega.nombre,
            }
            for row in data
        ]

        return Response(result)

    @action(detail=True, methods=["get"], url_path="contenido")
    def contenido(self, request, pk=None):
        bodega = self.get_object()

        # ✅ Insumos de la bodega (tu Insumo tiene FK bodega) :contentReference[oaicite:1]{index=1}
        insumos_qs = (
            Insumo.objects
            .filter(bodega=bodega)
            .order_by("nombre")
        )

        insumos = []
        for i in insumos_qs:
            stock = i.cantidad or 0
            cu = i.costo_unitario or 0
            total = (stock * cu) if stock and cu else 0
            insumos.append({
                "codigo": i.codigo,
                "nombre": i.nombre,
                "stock_actual": str(stock),
                "costo_unitario": str(cu),
                "valor_total": str(total),
            })

        # ✅ Productos producidos en esa bodega:
        # NotaEnsamble tiene FK bodega, y NotaEnsambleDetalle tiene producto + cantidad :contentReference[oaicite:2]{index=2}
        productos_qs = (
            NotaEnsambleDetalle.objects
            .select_related("producto", "nota", "bodega_actual")
            .annotate(bodega_efectiva=Coalesce("bodega_actual_id", "nota__bodega_id"))
            .filter(bodega_efectiva=bodega.id)
            .values("producto__codigo_sku", "producto__nombre")
            .annotate(total_producido=Sum("cantidad"))
            .order_by("producto__nombre")
        )

        productos = []
        for p in productos_qs:
            productos.append({
                "codigo": p["producto__codigo_sku"],
                "nombre": p["producto__nombre"],
                "total_producido": str(p["total_producido"] or 0),
            })

        return Response({
            "bodega": {"id": bodega.id, "codigo": bodega.codigo, "nombre": bodega.nombre},
            "insumos": insumos,
            "productos": productos,
        })


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

    @action(detail=True, methods=["get"], url_path="stock-por-talla")
    def stock_por_talla(self, request, pk=None):
        producto = self.get_object()

        bodega_id = request.query_params.get("bodega_id")
        if bodega_id is not None and not str(bodega_id).isdigit():
            raise ValidationError({"bodega_id": "Debe ser un entero."})

        qs = (
            NotaEnsambleDetalle.objects
            .select_related("talla", "nota", "bodega_actual")
            .filter(producto=producto)
            .annotate(bodega_efectiva=Coalesce("bodega_actual_id", "nota__bodega_id"))
        )

        # ✅ si viene bodega_id, filtra por esa bodega
        if bodega_id:
            qs = qs.filter(bodega_efectiva=int(bodega_id))

        items = (
            qs.values("talla__id", "talla__nombre")
            .annotate(cantidad=Sum("cantidad"))
            .order_by("talla__nombre")
        )

        return Response({
            "producto": {
                "codigo": producto.codigo_sku,
                "nombre": producto.nombre,
            },
            "bodega_id": int(bodega_id) if bodega_id else None,
            "items": [
                {
                    "codigo": producto.codigo_sku,
                    "nombre": producto.nombre,
                    "talla_id": it["talla__id"],
                    "talla": it["talla__nombre"] or "Sin talla",
                    "cantidad": str(it["cantidad"] or 0),
                }
                for it in items
            ],
        })


class PrecioProductoViewSet(viewsets.ModelViewSet):
    queryset = PrecioProducto.objects.select_related("producto").order_by("-id")
    serializer_class = ProductoPrecioWriteSerializer


class DatosAdicionalesProductoViewSet(DebugValidationMixin, viewsets.ModelViewSet):
    queryset = DatosAdicionalesProducto.objects.select_related("producto").order_by("-id")
    serializer_class = DatosAdicionalesWriteSerializer


class InsumoViewSet(DebugValidationMixin, viewsets.ModelViewSet):
    queryset = (
        Insumo.objects
        .select_related("bodega", "proveedor", "tercero")
        .order_by("nombre")
    )
    serializer_class = InsumoSerializer


class TallaViewSet(viewsets.ModelViewSet):
    queryset = Talla.objects.all().order_by("nombre")
    serializer_class = TallaSerializer
    # (Dejo tu lógica específica fuera por ahora porque en tu código original
    #  estabas llamando self._get_datos_adicionales aquí y eso NO existe en TallaViewSet.
    #  Si esa lógica era para otra cosa, me dices y la reubicamos bien.)


class ProductoInsumoViewSet(viewsets.ModelViewSet):
    queryset = ProductoInsumo.objects.select_related("producto", "insumo").all()
    serializer_class = ProductoInsumoSerializer

class TrasladoProductoViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Historial de traslados (GET) y endpoint de ejecutar traslado (POST /traslados-producto/ejecutar/)
    """
    queryset = (
        TrasladoProducto.objects
        .select_related("tercero", "bodega_origen", "bodega_destino", "producto", "talla", "detalle")
        .order_by("-id")
    )
    serializer_class = TrasladoProductoSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        bodega_id = self.request.query_params.get("bodega_id")
        if bodega_id and str(bodega_id).isdigit():
            bodega_id = int(bodega_id)
            qs = qs.filter(
                Q(bodega_origen_id=bodega_id) |
                Q(bodega_destino_id=bodega_id)
            )
        return qs

    @action(detail=False, methods=["post"], url_path="ejecutar")
    @transaction.atomic
    def ejecutar(self, request):
        """
        Payload:
        {
          "tercero_id": 1,
          "bodega_origen_id": 2,
          "bodega_destino_id": 3,
          "producto_id": "SKU-001",
          "talla_id": 5,          // opcional
          "cantidad": "2.000"
        }
        """
        ser = TrasladoProductoSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        v = ser.validated_data

        tercero = v["tercero"]
        b_origen = v["bodega_origen"]
        b_destino = v["bodega_destino"]
        producto = v["producto"]
        talla = v.get("talla", None)
        cantidad = _d(v["cantidad"])

        if b_origen.id == b_destino.id:
            raise ValidationError({"bodega_destino_id": "La bodega destino debe ser diferente a la bodega origen."})

        if cantidad <= 0:
            raise ValidationError({"cantidad": "Debe ser mayor que 0."})

        # Buscar detalles disponibles en la bodega origen (por bodega_actual; si null => nota.bodega)
        qs = (
            NotaEnsambleDetalle.objects
            .select_related("nota", "nota__bodega", "bodega_actual")
            .annotate(bodega_efectiva=Coalesce("bodega_actual_id", "nota__bodega_id"))
            .filter(producto=producto)
            .filter(bodega_efectiva=b_origen.id)
            .order_by("nota__fecha_elaboracion", "id")
        )

        if talla is None:
            qs = qs.filter(talla__isnull=True)
        else:
            qs = qs.filter(talla=talla)

        disponible_total = sum(_d(x.cantidad) for x in qs)
        if disponible_total < cantidad:
            raise ValidationError({
                "stock_insuficiente": {
                    "disponible": str(disponible_total),
                    "requerido": str(cantidad),
                    "faltante": str(cantidad - disponible_total),
                }
            })

        restante = cantidad

        for det in qs:
            if restante <= 0:
                break

            disponible_det = _d(det.cantidad)
            mover = min(disponible_det, restante)
            if mover <= 0:
                continue

            # 1) restar en origen (PERSISTIR)
            nuevo_origen = disponible_det - mover
            if nuevo_origen < 0:
                raise ValidationError("Error interno: cantidad negativa tras traslado.")

            det.cantidad = nuevo_origen
            det.save(update_fields=["cantidad"])  # ✅ CLAVE: guardar la resta

            # 2) sumar/crear en destino manteniendo MISMA nota
            dest_det, _created = NotaEnsambleDetalle.objects.get_or_create(
                nota=det.nota,
                producto=det.producto,
                talla=det.talla,
                bodega_actual=b_destino,
                defaults={"cantidad": Decimal("0")}
            )
            dest_det.cantidad = _d(dest_det.cantidad) + mover
            dest_det.save(update_fields=["cantidad"])

            # 3) historial
            TrasladoProducto.objects.create(
                tercero=tercero,
                bodega_origen=b_origen,
                bodega_destino=b_destino,
                producto=producto,
                talla=talla,
                cantidad=mover,
                detalle=det
            )

            restante -= mover


        return Response({"ok": True, "cantidad_movida": str(cantidad)}, status=status.HTTP_200_OK)

class NotaSalidaProductoViewSet(viewsets.ModelViewSet):
    queryset = NotaSalidaProducto.objects.all().prefetch_related("detalles", "detalles__afectaciones")
    serializer_class = NotaSalidaProductoSerializer

    @action(detail=True, methods=["get"], url_path="pdf")
    def pdf(self, request, pk=None):
        salida = get_object_or_404(
            NotaSalidaProducto.objects.prefetch_related("detalles", "detalles__afectaciones"),
            pk=pk
        )

        response = HttpResponse(content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{salida.numero}.pdf"'

        c = canvas.Canvas(response, pagesize=letter)
        width, height = letter

        y = height - 50
        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, y, f"NOTA DE SALIDA - {salida.numero}")
        y -= 20

        c.setFont("Helvetica", 10)
        c.drawString(50, y, f"Fecha: {salida.fecha}")
        y -= 14
        c.drawString(50, y, f"Bodega: {salida.bodega.codigo} - {salida.bodega.nombre}")
        y -= 14
        tercero_txt = f"{salida.tercero.codigo} - {salida.tercero.nombre}" if salida.tercero else "-"
        c.drawString(50, y, f"Tercero: {tercero_txt}")
        y -= 14

        if salida.observacion:
            c.drawString(50, y, f"Observación: {salida.observacion[:120]}")
            y -= 14

        y -= 10
        c.setFont("Helvetica-Bold", 10)
        c.drawString(50, y, "Detalle")
        y -= 14

        c.setFont("Helvetica-Bold", 9)
        c.drawString(50, y, "SKU")
        c.drawString(120, y, "Producto")
        c.drawString(320, y, "Talla")
        c.drawString(370, y, "Cantidad")
        c.drawString(450, y, "Costo U.")
        c.drawString(520, y, "Total")
        y -= 10
        c.line(50, y, 560, y)
        y -= 12

        c.setFont("Helvetica", 9)
        for d in salida.detalles.all():
            if y < 80:
                c.showPage()
                y = height - 50
                c.setFont("Helvetica-Bold", 9)
                c.drawString(50, y, "SKU")
                c.drawString(120, y, "Producto")
                c.drawString(320, y, "Talla")
                c.drawString(370, y, "Cantidad")
                c.drawString(450, y, "Costo U.")
                c.drawString(520, y, "Total")
                y -= 10
                c.line(50, y, 560, y)
                y -= 12
                c.setFont("Helvetica", 9)

            sku = d.producto.codigo_sku
            nombre = d.producto.nombre[:30]
            talla = d.talla or "-"
            cantidad = str(d.cantidad)
            cu = str(d.costo_unitario) if d.costo_unitario is not None else "-"
            total = str(d.total) if d.total is not None else "-"

            c.drawString(50, y, sku)
            c.drawString(120, y, nombre)
            c.drawString(320, y, talla)
            c.drawRightString(420, y, cantidad)
            c.drawRightString(505, y, cu)
            c.drawRightString(560, y, total)
            y -= 14

        c.showPage()
        c.save()
        return response