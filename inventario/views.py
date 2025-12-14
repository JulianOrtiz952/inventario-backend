from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from decimal import Decimal
from django.db import transaction

from .models import (
    Insumo, Proveedor, Producto, Bodega, Impuesto, PrecioProducto,
    Tercero, DatosAdicionalesProducto, Talla,
    NotaEnsamble, ProductoInsumo, NotaEnsambleDetalle, NotaEnsambleInsumo
)
from .serializers import (
    InsumoSerializer, ProveedorSerializer, ProductoSerializer, BodegaSerializer,
    ImpuestoSerializer, ProductoPrecioWriteSerializer,
    TerceroSerializer, DatosAdicionalesWriteSerializer,
    TallaSerializer, NotaEnsambleSerializer, ProductoInsumoSerializer
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
        if getattr(insumo_ref, "bodega_id", None) and insumo_ref.bodega_id != bodega.id:
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
            # Si insumo está por bodega y no coincide, buscar mismo código en la bodega de la nota
            if getattr(ins, "bodega_id", None) and ins.bodega_id != nota.bodega_id:
                ins = Insumo.objects.filter(codigo=ni.insumo.codigo, bodega=nota.bodega).first()

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
