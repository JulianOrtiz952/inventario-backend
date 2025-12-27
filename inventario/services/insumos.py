from decimal import Decimal
from django.db import transaction
from rest_framework.exceptions import ValidationError
from inventario.models import Insumo, InsumoMovimiento

def aplicar_movimiento_insumo(
    *,
    insumo,
    tercero,
    tipo,
    cantidad,
    costo_unitario=None,
    bodega=None,
    factura="",
    observacion="",
    nota_ensamble=None,
):
    cantidad = Decimal(str(cantidad))
    if cantidad <= 0:
        raise ValidationError({"cantidad": "Debe ser mayor a 0"})

    if costo_unitario is None:
        costo_unitario = insumo.costo_unitario or Decimal("0.00")
    else:
        costo_unitario = Decimal(str(costo_unitario))

    total = (cantidad * costo_unitario).quantize(Decimal("0.01"))

    with transaction.atomic():
        insumo.refresh_from_db()

        if tipo in ("SALIDA", "CONSUMO_ENSAMBLE"):
            if insumo.cantidad < cantidad:
                raise ValidationError({"cantidad": "Stock insuficiente"})
            insumo.cantidad -= cantidad
        else:  # ENTRADA, CREACION, AJUSTE
            insumo.cantidad += cantidad

        insumo.save(update_fields=["cantidad"])

        movimiento = InsumoMovimiento.objects.create(
            insumo=insumo,
            tercero=tercero,
            bodega=bodega or insumo.bodega,
            tipo=tipo,
            cantidad=cantidad,
            unidad_medida=insumo.unidad_medida,
            costo_unitario=costo_unitario,
            total=total,
            saldo_resultante=insumo.cantidad,
            factura=factura or insumo.factura,
            observacion=observacion,
            nota_ensamble=nota_ensamble,
        )

    return movimiento
