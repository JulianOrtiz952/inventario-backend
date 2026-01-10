from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from decimal import Decimal
from django.db import transaction
from rest_framework.decorators import action
from django.db.models import Sum, Count, Q, F, Case, When, DecimalField
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from openpyxl import Workbook, load_workbook
from .renderers import XLSXRenderer
import io
from datetime import datetime
from django.utils import timezone


from .models import (
    Insumo, Proveedor, Producto, Bodega, Impuesto, PrecioProducto,
    Tercero, DatosAdicionalesProducto, Talla,
    NotaEnsamble, ProductoInsumo, NotaEnsambleDetalle, NotaEnsambleInsumo,
    TrasladoProducto, NotaSalidaProducto, InsumoMovimiento,
    ProductoTerminadoMovimiento
)
from .filters import InsumoFilter, ProductoFilter
from .serializers import (
    InsumoSerializer, ProveedorSerializer, ProductoSerializer, BodegaSerializer,
    ImpuestoSerializer, ProductoPrecioWriteSerializer,
    TerceroSerializer, DatosAdicionalesWriteSerializer,
    TallaSerializer, NotaEnsambleSerializer, ProductoInsumoSerializer,
    TrasladoProductoSerializer, NotaSalidaProductoSerializer, InsumoMovimientoSerializer, InsumoMovimientoInputSerializer,
    ProductoTerminadoMovimientoSerializer
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

def _decimal(v, field_name):
    try:
        return Decimal(str(v))
    except Exception:
        raise ValidationError({field_name: "Valor inválido"})

def registrar_movimiento_sin_afectar_stock(*, insumo, tercero, tipo, cantidad, costo_unitario, bodega=None, factura="", observacion="", nota_ensamble=None):
    """
    Registra historial SIN modificar stock (útil para CREACION cuando ya guardaste la cantidad en Insumo).
    """
    cantidad = _decimal(cantidad, "cantidad")
    if cantidad < 0:
        raise ValidationError({"cantidad": "No puede ser negativa"})

    costo_unitario = _decimal(costo_unitario, "costo_unitario")
    total = (cantidad * costo_unitario).quantize(Decimal("0.01"))

    mov = InsumoMovimiento.objects.create(
        insumo=insumo,
        tercero=tercero,
        bodega=bodega or insumo.bodega,
        tipo=tipo,
        cantidad=cantidad,
        unidad_medida=getattr(insumo, "unidad_medida", "") or "",
        costo_unitario=costo_unitario,
        total=total,
        saldo_resultante=insumo.cantidad,  # ya está guardado
        factura=factura or getattr(insumo, "factura", "") or "",
        observacion=observacion or "",
        nota_ensamble=nota_ensamble,
    )
    return mov

def aplicar_movimiento_insumo(*, insumo, tercero, tipo, cantidad, costo_unitario=None, bodega=None, factura="", observacion="", nota_ensamble=None):
    """
    Modifica stock + registra historial en una transacción.
    Para ENTRADA/SALIDA/AJUSTE/CONSUMO_ENSAMBLE.
    """
    cantidad = _decimal(cantidad, "cantidad")
    if cantidad <= 0:
        raise ValidationError({"cantidad": "Debe ser mayor a 0"})

    if costo_unitario is None or str(costo_unitario) == "":
        costo_unitario = insumo.costo_unitario or Decimal("0.00")
    else:
        costo_unitario = _decimal(costo_unitario, "costo_unitario")

    total = (cantidad * costo_unitario).quantize(Decimal("0.01"))

    with transaction.atomic():
        insumo.refresh_from_db()

        if tipo in ("SALIDA", "CONSUMO_ENSAMBLE"):
            if insumo.cantidad < cantidad:
                raise ValidationError({"cantidad": "Stock global insuficiente"})
            
            # Validar stock de BODEGA específica (si se especifica bodega)
            if bodega:
                qs = InsumoMovimiento.objects.filter(insumo=insumo, bodega=bodega)
                agg = qs.aggregate(
                    total_entradas=Sum(
                        Case(
                            When(tipo__in=["CREACION", "ENTRADA", "AJUSTE"], then=F("cantidad")),
                            default=0,
                            output_field=DecimalField()
                        )
                    ),
                    total_salidas=Sum(
                        Case(
                            When(tipo__in=["SALIDA", "CONSUMO_ENSAMBLE"], then=F("cantidad")),
                            default=0,
                            output_field=DecimalField()
                        )
                    )
                )
                entradas = agg["total_entradas"] or Decimal("0")
                salidas = agg["total_salidas"] or Decimal("0")
                stock_bodega = entradas - salidas
                
                if stock_bodega < cantidad:
                    raise ValidationError({"cantidad": f"Stock insuficiente en bodega {bodega.nombre}. Disponible: {stock_bodega}"})

            insumo.cantidad = (insumo.cantidad - cantidad)
        elif tipo in ("ENTRADA", "AJUSTE"):
            insumo.cantidad = (insumo.cantidad + cantidad)
        else:
            raise ValidationError({"tipo": "Tipo inválido"})

        insumo.save(update_fields=["cantidad"])

        mov = InsumoMovimiento.objects.create(
            insumo=insumo,
            tercero=tercero,
            bodega=bodega or insumo.bodega,
            tipo=tipo,
            cantidad=cantidad,
            unidad_medida=getattr(insumo, "unidad_medida", "") or "",
            costo_unitario=costo_unitario,
            total=total,
            saldo_resultante=insumo.cantidad,
            factura=factura or getattr(insumo, "factura", "") or "",
            observacion=observacion or "",
            nota_ensamble=nota_ensamble,
        )

    return mov

def _parse_decimal(v, field):
    try:
        if v is None or str(v).strip() == "":
            return None
        return Decimal(str(v).replace(",", ".")).quantize(Decimal("0.001"))
    except Exception:
        raise ValidationError({field: f"Valor inválido: {v}"})


def _parse_date(v, field):
    if v is None or str(v).strip() == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if hasattr(v, "year") and hasattr(v, "month") and hasattr(v, "day"):
        return v
    # strings
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    raise ValidationError({field: f"Fecha inválida: {v}. Formatos: YYYY-MM-DD o DD/MM/YYYY"})

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
    # Ordenar por activos primero
    queryset = Proveedor.objects.all().order_by("-es_activo", "id")
    serializer_class = ProveedorSerializer
    ordering_fields = ["nombre", "es_activo"]

    def perform_destroy(self, instance):
        # Soft delete
        instance.es_activo = False
        instance.save(update_fields=["es_activo"])


class BodegaViewSet(viewsets.ModelViewSet):
    queryset = Bodega.objects.all().order_by("nombre")
    serializer_class = BodegaSerializer
    filterset_fields = ["ubicacion"]
    search_fields = ["nombre", "codigo"]
    ordering_fields = ["nombre", "codigo"]

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
    search_fields = ["nombre", "codigo"]
    ordering_fields = ["nombre"]


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
    filterset_class = ProductoFilter
    search_fields = ["nombre", "codigo_sku", "codigo_barras"]
    ordering_fields = ["nombre", "creado_en"]

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


class InsumoViewSet(viewsets.ModelViewSet):
    # Ordenar primero por activos vs inactivos (-es_activo: True=1, False=0), luego nombre
    queryset = Insumo.objects.select_related("bodega", "proveedor", "tercero").order_by("-es_activo", "nombre")
    serializer_class = InsumoSerializer
    filterset_class = InsumoFilter
    search_fields = ["nombre", "codigo", "referencia", "observacion"]
    ordering_fields = ["nombre", "cantidad", "costo_unitario", "creado_en", "es_activo"]

    def perform_destroy(self, instance):
        # Soft delete: Marcar como inactivo en lugar de borrar
        instance.es_activo = False
        instance.save(update_fields=["es_activo"])

    def perform_update(self, serializer):
        insumo = serializer.save()
        # Registrar EDICION en historial (sin afectar stock)
        tercero = insumo.tercero
        registrar_movimiento_sin_afectar_stock(
            insumo=insumo,
            tercero=tercero,  # puede ser None, pero la función lo maneja o fallará si el modelo lo exige (el modelo InsumoMovimiento.tercero NO es null=True, ojo)
            # Pero Insumo.tercero es null=True? models.py dice: tercero = models.ForeignKey("Tercero", ..., null=True, blank=True)
            # InsumoMovimiento.tercero NO es null=True.
            # Necesitamos un tercero para el historial. Si el insumo no tiene tercero, ¿qué hacemos?
            # Usar uno por defecto o validar.
            # REVISAR models.py: InsumoMovimiento line 424: tercero = models.ForeignKey("Tercero", on_delete=models.PROTECT) -> NO NULL.
            # PROBABLE BUG IF INSUMO HAS NO TERCERO.
            # Veamos perform_create:
            #   tercero = insumo.tercero
            #   if tercero:
            #       registrar_...
            # O sea solo registra si tiene tercero. Mantengamos esa lógica.
            tipo="EDICION",
            cantidad=Decimal("0.000"),
            costo_unitario=insumo.costo_unitario,
            bodega=insumo.bodega,
            factura=getattr(insumo, "factura", "") or "",
            observacion="Actualización de datos",
        ) if insumo.tercero else None

    def perform_create(self, serializer):
        insumo = serializer.save()

        # Registra "CREACION" en historial (sin afectar stock) usando el tercero del insumo.
        # Esto evita doble conteo porque el insumo ya quedó con cantidad guardada.
        tercero = insumo.tercero
        if tercero:
            registrar_movimiento_sin_afectar_stock(
                insumo=insumo,
                tercero=tercero,
                tipo="CREACION",
                cantidad=insumo.cantidad,
                costo_unitario=insumo.costo_unitario,
                bodega=insumo.bodega,
                factura=getattr(insumo, "factura", "") or "",
                observacion="Creación de insumo",
            )

    @action(detail=True, methods=["get"], url_path="movimientos")
    def movimientos(self, request, pk=None):
        """
        GET /insumos/{codigo}/movimientos/?page=... (paginación la da DRF si la tienes global)
        """
        insumo = self.get_object()
        qs = InsumoMovimiento.objects.select_related("insumo", "tercero", "bodega").filter(insumo=insumo)

        tipo = request.query_params.get("tipo")
        if tipo:
            qs = qs.filter(tipo=tipo)

        tercero_id = request.query_params.get("tercero_id")
        if tercero_id:
            qs = qs.filter(tercero_id=tercero_id)

        bodega_id = request.query_params.get("bodega_id")
        if bodega_id:
            qs = qs.filter(bodega_id=bodega_id)

        # paginación DRF
        page = self.paginate_queryset(qs.order_by("-fecha", "-id"))
        if page is not None:
            ser = InsumoMovimientoSerializer(page, many=True)
            return self.get_paginated_response(ser.data)

        return Response(InsumoMovimientoSerializer(qs, many=True).data)

    @action(detail=True, methods=["get"], url_path="stock_por_bodega")
    def stock_por_bodega(self, request, pk=None):
        """
        Retorna el stock calculado por bodega basado en el historial de movimientos.
        """
        insumo = self.get_object()
        
        # Agrupar por bodega y sumarizar
        # ENTRADA, AJUSTE, CREACION suman (o ajustan)
        # SALIDA, CONSUMO_ENSAMBLE restan
        
        from django.db.models import Sum, Case, When, F, DecimalField, Value
        
        # Primero, obtenemos todas las bodegas que han tenido movimiento con este insumo
        movs = InsumoMovimiento.objects.filter(insumo=insumo).values("bodega", "bodega__nombre")
        
        results = movs.annotate(
            total_entradas=Sum(
                Case(
                    When(tipo__in=["CREACION", "ENTRADA", "AJUSTE"], then=F("cantidad")),
                    default=0,
                    output_field=DecimalField()
                )
            ),
            total_salidas=Sum(
                Case(
                    When(tipo__in=["SALIDA", "CONSUMO_ENSAMBLE"], then=F("cantidad")),
                    default=0,
                    output_field=DecimalField()
                )
            )
        ).order_by("bodega__nombre")
        
        # Procesar resultados
        data = []
        for r in results:
            bodega_nombre = r["bodega__nombre"]
            if not bodega_nombre:
                bodega_nombre = "Sin Bodega"
                
            stock = (r["total_entradas"] or 0) - (r["total_salidas"] or 0)
            
            # Solo mostrar si hay algo relevante (o si es 0 pero hubo movs)
            data.append({
                "bodega_id": r["bodega"],
                "bodega_nombre": bodega_nombre,
                "stock": stock
            })
            
        return Response(data)
    @action(detail=True, methods=["post"], url_path="movimiento")
    def movimiento(self, request, pk=None):
        """
        POST /insumos/{codigo}/movimiento/
        Body: { tipo: ENTRADA|SALIDA|AJUSTE, tercero_id, cantidad, costo_unitario?, bodega_id?, factura?, observacion? }
        """
        insumo = self.get_object()
        
        inp = InsumoMovimientoInputSerializer(data=request.data)
        inp.is_valid(raise_exception=True)
        data = inp.validated_data

        tipo = data["tipo"]
        tercero = Tercero.objects.get(id=data["tercero_id"])
        bodega = None
        if data.get("bodega_id"):
            bodega = Bodega.objects.get(id=data["bodega_id"])

        # ENTRADA/SALIDA/AJUSTE afectan stock
        mov = aplicar_movimiento_insumo(
            insumo=insumo,
            tercero=tercero,
            tipo=tipo,
            cantidad=data["cantidad"],
            costo_unitario=data.get("costo_unitario", None),
            bodega=bodega,
            factura=data.get("factura", ""),
            observacion=data.get("observacion", ""),
        )

        return Response(InsumoMovimientoSerializer(mov).data, status=status.HTTP_201_CREATED)



class TallaViewSet(viewsets.ModelViewSet):
    queryset = Talla.objects.all().order_by("nombre")
    serializer_class = TallaSerializer
    search_fields = ["nombre"]
    ordering_fields = ["nombre"]
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

class InsumoMovimientoViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Kardex global:
    GET /insumo-movimientos/?insumo=INS-001&tipo=ENTRADA&tercero_id=1&bodega_id=2
    """
    queryset = InsumoMovimiento.objects.select_related("insumo", "tercero", "bodega").all()
    serializer_class = InsumoMovimientoSerializer

    def get_queryset(self):
        qs = super().get_queryset()

        insumo_codigo = self.request.query_params.get("insumo")
        if insumo_codigo:
            qs = qs.filter(insumo_id=insumo_codigo)

        tipo = self.request.query_params.get("tipo")
        if tipo:
            qs = qs.filter(tipo=tipo)

        tercero_id = self.request.query_params.get("tercero_id")
        if tercero_id:
            qs = qs.filter(tercero_id=tercero_id)

        bodega_id = self.request.query_params.get("bodega_id")
        if bodega_id:
            qs = qs.filter(bodega_id=bodega_id)

        return qs.order_by("-fecha", "-id")

class ExcelImportViewSet(viewsets.ViewSet):
    """
    Endpoints:
      GET  /api/excel/plantilla-insumos/
      POST /api/excel/importar-insumos/         (multipart: file)
      GET  /api/excel/plantilla-terminado/
      POST /api/excel/importar-terminado/       (multipart: file)

      GET  /api/excel/kardex-terminado/?sku=...&bodega_id=...&tercero_id=...
    """

    @action(detail=False, methods=["get"], url_path="plantilla-insumos", renderer_classes=[XLSXRenderer])
    def plantilla_insumos(self, request):
        wb = Workbook()
        ws = wb.active
        ws.title = "Insumos"

        headers = [
            "codigo", "nombre", "bodega_id",
            "cantidad_entrada", "costo_unitario",
            "tercero_id",
            "referencia", "factura", "unidad_medida", "color", "stock_minimo", "observacion",
        ]
        ws.append(headers)
        ws.append([
            "INS-001", "Tela", 1,
            "10.000", "2500.00",
            1,
            "REF-TELA-01", "FAC-98451", "M", "Blanco", "2.000", "Lote para camisas"
        ])

        buf = io.BytesIO()
        wb.save(buf)
        content = buf.getvalue()

        resp = Response(content, content_type=XLSXRenderer.media_type)
        resp["Content-Disposition"] = 'attachment; filename="plantilla_insumos.xlsx"'
        return resp

    @action(detail=False, methods=["post"], url_path="importar-insumos")
    @transaction.atomic
    def importar_insumos(self, request):
        file = request.FILES.get("file")
        if not file:
            raise ValidationError({"file": "Debe enviar un archivo .xlsx en multipart/form-data con key 'file'."})

        file = request.FILES.get("file")
        if not file:
            raise ValidationError({"file": "Debe enviar un .xlsx con key 'file'."})

        # ✅ 1) tamaño
        if getattr(file, "size", 0) == 0:
            raise ValidationError({"file": "El archivo llegó vacío (0 bytes). Revisa el FormData en el frontend."})

        # ✅ 2) validar firma ZIP: XLSX empieza por bytes 'PK'
        head = file.read(4)
        file.seek(0)
        if head[:2] != b"PK":
            raise ValidationError({
                "file": (
                    "El archivo no parece ser un .xlsx real (debe ser Excel ZIP). "
                    "No lo renombres: descárgalo como 'Microsoft Excel (.xlsx)'."
                )
            })

        # ✅ 3) intentar leer
        try:
            wb = load_workbook(filename=file, data_only=True)
        except Exception as e:
            raise ValidationError({"file": f"No se pudo leer el Excel: {str(e)}"})

        if "Insumos" in wb.sheetnames:
            ws = wb["Insumos"]
        else:
            ws = wb.active

        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            raise ValidationError({"file": "El Excel está vacío."})

        header = [str(x).strip() if x is not None else "" for x in rows[0]]
        required = ["codigo", "nombre", "bodega_id", "cantidad_entrada", "costo_unitario", "tercero_id"]
        missing = [h for h in required if h not in header]
        if missing:
            raise ValidationError({"headers": f"Faltan columnas requeridas: {missing}"})

        idx = {h: header.index(h) for h in header if h}

        ok = 0
        errores = []
        movimientos_creados = []

        for i, r in enumerate(rows[1:], start=2):
            try:
                codigo = str(r[idx["codigo"]]).strip()
                nombre = str(r[idx["nombre"]]).strip()

                bodega_id = r[idx["bodega_id"]]
                tercero_id = r[idx["tercero_id"]]

                cantidad_entrada = _parse_decimal(r[idx["cantidad_entrada"]], "cantidad_entrada")
                costo_unitario = _parse_decimal(r[idx["costo_unitario"]], "costo_unitario")

                if not codigo:
                    raise ValidationError({"codigo": "Vacío"})
                if cantidad_entrada is None or cantidad_entrada <= 0:
                    raise ValidationError({"cantidad_entrada": "Debe ser > 0"})

                bodega = Bodega.objects.get(id=int(bodega_id))
                tercero = Tercero.objects.get(id=int(tercero_id))

                referencia = (r[idx["referencia"]] if "referencia" in idx else None)
                factura = (r[idx["factura"]] if "factura" in idx else "")
                unidad_medida = (r[idx["unidad_medida"]] if "unidad_medida" in idx else "")
                color = (r[idx["color"]] if "color" in idx else "")
                stock_minimo = _parse_decimal(r[idx["stock_minimo"]], "stock_minimo") if "stock_minimo" in idx else None
                observacion = (r[idx["observacion"]] if "observacion" in idx else "")

                insumo = Insumo.objects.filter(codigo=codigo).first()
                if not insumo:
                    insumo = Insumo.objects.create(
                        codigo=codigo,
                        nombre=nombre,
                        bodega=bodega,
                        referencia=str(referencia).strip() if referencia else codigo,
                        factura=str(factura or "").strip(),
                        unidad_medida=str(unidad_medida or "").strip(),
                        color=str(color or "").strip(),
                        stock_minimo=stock_minimo if stock_minimo is not None else Decimal("0"),
                        observacion=str(observacion or "").strip(),
                        costo_unitario=(costo_unitario.quantize(Decimal("0.01")) if costo_unitario else Decimal("0.00")),
                        cantidad=Decimal("0.000"),
                        tercero=tercero,
                    )
                    # Registrar CREACION (sin afectar stock) si quieres dejarlo marcado
                    registrar_movimiento_sin_afectar_stock(
                        insumo=insumo,
                        tercero=tercero,
                        tipo="CREACION",
                        cantidad=Decimal("0.000"),
                        costo_unitario=insumo.costo_unitario,
                        bodega=bodega,
                        factura=insumo.factura,
                        observacion="Creación por importación Excel",
                    )
                else:
                    # actualiza metadata sin tocar cantidad aún (la cantidad la suma el movimiento)
                    insumo.nombre = nombre or insumo.nombre
                    insumo.bodega = bodega
                    insumo.tercero = tercero
                    if referencia:
                        insumo.referencia = str(referencia).strip()
                    if factura is not None:
                        insumo.factura = str(factura or "").strip()
                    if unidad_medida is not None:
                        insumo.unidad_medida = str(unidad_medida or "").strip()
                    if color is not None:
                        insumo.color = str(color or "").strip()
                    if stock_minimo is not None:
                        insumo.stock_minimo = stock_minimo
                    if observacion is not None:
                        insumo.observacion = str(observacion or "").strip()
                    # si viene costo_unitario en el excel, puedes actualizar el “último” costo del insumo
                    if costo_unitario is not None:
                        insumo.costo_unitario = costo_unitario.quantize(Decimal("0.01"))
                    insumo.save()

                mov = aplicar_movimiento_insumo(
                    insumo=insumo,
                    tercero=tercero,
                    tipo="ENTRADA",
                    cantidad=cantidad_entrada,
                    costo_unitario=costo_unitario.quantize(Decimal("0.01")) if costo_unitario else None,
                    bodega=bodega,
                    factura=str(factura or "").strip(),
                    observacion=f"Entrada por importación Excel (fila {i})",
                )
                movimientos_creados.append(mov.id)
                ok += 1

            except Exception as e:
                errores.append({"fila": i, "error": str(e)})

        return Response(
            {
                "ok": True,
                "procesadas_ok": ok,
                "errores": errores,
                "movimientos_ids": movimientos_creados,
            },
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=["get"], url_path="plantilla-terminado", renderer_classes=[XLSXRenderer])
    def plantilla_terminado(self, request):
        wb = Workbook()
        ws = wb.active
        ws.title = "ProductoTerminado"

        headers = [
            "fecha", "bodega_id", "tercero_id", "observacion",
            "producto_sku", "talla", "cantidad", "costo_unitario",
        ]
        ws.append(headers)
        ws.append([
            "2025-12-27", 1, 1, "Ingreso inicial por Excel",
            "CAM-001", "M", "12.000", "45000.00",
        ])

        buf = io.BytesIO()
        wb.save(buf)
        content = buf.getvalue()

        resp = Response(content, content_type=XLSXRenderer.media_type)
        resp["Content-Disposition"] = 'attachment; filename="plantilla_producto_terminado.xlsx"'
        return resp

    @action(detail=False, methods=["post"], url_path="importar-terminado")
    def importar_terminado(self, request):
        file = request.FILES.get("file")
        if not file:
            raise ValidationError({"file": "Debe enviar un archivo .xlsx en multipart/form-data con key 'file'."})

        try:
            wb = load_workbook(filename=file, data_only=True)
        except Exception as e:
            raise ValidationError({"file": f"No se pudo leer el Excel: {str(e)}"})

        ws = wb["ProductoTerminado"] if "ProductoTerminado" in wb.sheetnames else wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            raise ValidationError({"file": "El Excel está vacío."})

        header = [str(x).strip() if x is not None else "" for x in rows[0]]
        required = ["fecha", "bodega_id", "tercero_id", "producto_sku", "cantidad"]
        missing = [h for h in required if h not in header]
        if missing:
            raise ValidationError({"headers": f"Faltan columnas requeridas: {missing}"})

        idx = {h: header.index(h) for h in header if h}

        ok = 0
        errores = []
        movimientos = []

        # cache de notas: key -> nota_id (guardamos ID para evitar objetos “fantasma” si una fila falla)
        notas_cache = {}  # key=(fecha,bodega_id,tercero_id,obs) -> nota_id

        for i, r in enumerate(rows[1:], start=2):
            try:
                # ✅ transacción por fila (si falla, no rompe el resto)
                with transaction.atomic():

                    fecha = _parse_date(r[idx["fecha"]], "fecha") or timezone.now().date()

                    bodega = Bodega.objects.get(id=int(r[idx["bodega_id"]]))
                    tercero = Tercero.objects.get(id=int(r[idx["tercero_id"]]))

                    obs = str(r[idx["observacion"]] or "").strip() if "observacion" in idx else ""
                    producto_sku = str(r[idx["producto_sku"]]).strip()

                    talla_txt = str(r[idx["talla"]] or "").strip() if "talla" in idx else ""
                    cantidad = _parse_decimal(r[idx["cantidad"]], "cantidad")
                    if cantidad is None or cantidad <= 0:
                        raise ValidationError({"cantidad": "Debe ser > 0"})

                    costo_unitario = _parse_decimal(r[idx["costo_unitario"]], "costo_unitario") if "costo_unitario" in idx else None
                    costo_unitario = (costo_unitario.quantize(Decimal("0.01")) if costo_unitario else Decimal("0.00"))

                    producto = Producto.objects.get(codigo_sku=producto_sku)

                    talla_obj = None
                    if talla_txt:
                        talla_obj = Talla.objects.filter(nombre=talla_txt).first()
                        if not talla_obj:
                            raise ValidationError({"talla": f"La talla '{talla_txt}' no existe. Créala antes o deja vacío."})

                    key = (str(fecha), bodega.id, tercero.id, obs)

                    nota_id = notas_cache.get(key)
                    if nota_id:
                        nota = NotaEnsamble.objects.get(id=nota_id)
                    else:
                        nota = NotaEnsamble.objects.create(
                            bodega=bodega,
                            tercero=tercero,
                            fecha_elaboracion=fecha,
                            observaciones=(obs or "Ingreso por importación Excel (producto terminado)")
                        )
                        notas_cache[key] = nota.id

                    # ✅ en vez de CREATE siempre, hacemos UPSERT: si existe, sumamos
                    det, created = NotaEnsambleDetalle.objects.get_or_create(
                        nota=nota,
                        producto=producto,
                        talla=talla_obj,
                        bodega_actual=bodega,
                        defaults={"cantidad": cantidad},
                    )
                    if not created:
                        det.cantidad = (Decimal(str(det.cantidad or 0)) + Decimal(str(cantidad))).quantize(Decimal("0.001"))
                        det.save(update_fields=["cantidad"])

                    # stock global
                    datos = DatosAdicionalesProducto.objects.filter(producto=producto).first()
                    if not datos:
                        datos = DatosAdicionalesProducto.objects.create(
                            producto=producto,
                            referencia="N/A",
                            unidad=producto.unidad_medida or "",
                            stock=Decimal("0.000"),
                            stock_minimo=Decimal("0"),
                            descripcion="",
                            marca="",
                            modelo="",
                            codigo_arancelario="",
                        )
                    datos.stock = (Decimal(str(datos.stock or 0)) + Decimal(str(cantidad))).quantize(Decimal("0.001"))
                    datos.save(update_fields=["stock"])

                    mov = ProductoTerminadoMovimiento.objects.create(
                        fecha=timezone.now(),
                        bodega=bodega,
                        tercero=tercero,
                        tipo=ProductoTerminadoMovimiento.Tipo.INGRESO_EXCEL,
                        producto=producto,
                        talla=talla_obj,
                        cantidad=cantidad,
                        costo_unitario=costo_unitario,
                        saldo_global_resultante=datos.stock,
                        nota_ensamble=nota,
                        observacion=f"{obs} (fila {i})".strip(),
                    )

                    movimientos.append(mov.id)
                    ok += 1

            except Exception as e:
                errores.append({"fila": i, "error": str(e)})

        return Response(
            {
                "ok": True,
                "procesadas_ok": ok,
                "errores": errores,
                "movimientos_ids": movimientos,
                "notas_creadas": sorted(set(notas_cache.values())),
            },
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=["get"], url_path="kardex-terminado")
    def kardex_terminado(self, request):
        qs = ProductoTerminadoMovimiento.objects.select_related("producto", "talla", "tercero", "bodega", "nota_ensamble").all()

        sku = (request.query_params.get("sku") or "").strip()
        if sku:
            qs = qs.filter(producto__codigo_sku=sku)

        bodega_id = request.query_params.get("bodega_id")
        if bodega_id and str(bodega_id).isdigit():
            qs = qs.filter(bodega_id=int(bodega_id))

        tercero_id = request.query_params.get("tercero_id")
        if tercero_id and str(tercero_id).isdigit():
            qs = qs.filter(tercero_id=int(tercero_id))

        qs = qs.order_by("-fecha", "-id")[:200]  # límite seguro

        return Response(ProductoTerminadoMovimientoSerializer(qs, many=True).data)