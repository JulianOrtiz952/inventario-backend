from decimal import Decimal
from django.db import transaction
from django.db.models import Sum, Case, When, Value, F, DecimalField
from rest_framework.exceptions import ValidationError
from inventario.models import (
    Insumo, InsumoMovimiento, NotaEnsamble, NotaEnsambleDetalle,
    NotaEnsambleInsumo, ProductoInsumo, DatosAdicionalesProducto,
    TrasladoProducto, NotaSalidaAfectacionStock
)

def _d(x):
    try:
        return Decimal(str(x))
    except Exception:
        return Decimal("0")

def _round3(d):
    return _d(d).quantize(Decimal('0.001'))

class InventoryService:
    @staticmethod
    def registrar_movimiento_sin_afectar_stock(*, insumo, tercero, tipo, cantidad, costo_unitario, bodega=None, factura="", observacion="", nota_ensamble=None):
        """
        Registra historial SIN modificar stock.
        """
        cantidad = _d(cantidad)
        if cantidad < 0:
            raise ValidationError({"cantidad": "No puede ser negativa"})

        costo_unitario = _d(costo_unitario)
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
            saldo_resultante=insumo.cantidad,
            factura=factura or getattr(insumo, "factura", "") or "",
            observacion=observacion or "",
            nota_ensamble=nota_ensamble,
        )
        return mov

    @staticmethod
    def descontar_insumo_global(codigo, cantidad_total, bodega_preferida, tercero=None, nota_ensamble=None, tipo_movimiento=None, observacion_p=None):
        """
        Descuenta stock de un insumo (por código) buscando en múltiples bodegas.
        Prioriza la bodega_preferida.
        """
        if tipo_movimiento is None:
            tipo_movimiento = InsumoMovimiento.Tipo.CONSUMO_ENSAMBLE

        cantidad_total = _d(cantidad_total)
        if cantidad_total <= 0:
            return

        # 1. Verificar stock total global
        total_global = Insumo.objects.filter(codigo=codigo, es_activo=True).aggregate(total=Sum('cantidad'))['total'] or Decimal('0')
        if total_global < cantidad_total:
            ins_ej = Insumo.objects.filter(codigo=codigo).first()
            nombre = ins_ej.nombre if ins_ej else codigo
            raise ValidationError({
                "stock_insuficiente": {
                    codigo: {
                        "insumo": nombre,
                        "disponible": str(total_global),
                        "requerido": str(cantidad_total),
                        "faltante": str(cantidad_total - total_global),
                    }
                }
            })

        # 2. Descontar priorizando bodega_preferida
        # 🔒 Bloqueo pesimista para evitar race conditions
        insumos_qs = Insumo.objects.select_for_update().filter(codigo=codigo, es_activo=True).order_by(
            Case(When(bodega=bodega_preferida, then=Value(0)), default=Value(1)),
            '-cantidad'
        )

        restante = cantidad_total
        for ins in insumos_qs:
            if restante <= 0:
                break
            cant_en_bodega = _d(ins.cantidad)
            if cant_en_bodega <= 0:
                continue
                
            a_descontar = min(cant_en_bodega, restante)
            nueva_cant = _round3(cant_en_bodega - a_descontar)
            ins.cantidad = nueva_cant
            ins.save(update_fields=['cantidad'])

            # ✅ Registrar movimiento en Kardex para esta bodega
            obs_mov = observacion_p or f"Consumo automático [{ins.bodega.nombre}] por nota #{getattr(nota_ensamble, 'id', 'S/N')}"
            InventoryService.registrar_movimiento_sin_afectar_stock(
                insumo=ins,
                tercero=tercero or getattr(nota_ensamble, "tercero", None),
                bodega=ins.bodega,
                tipo=tipo_movimiento,
                cantidad=a_descontar,
                costo_unitario=ins.costo_unitario,
                nota_ensamble=nota_ensamble,
                observacion=obs_mov
            )

            restante -= a_descontar

    @staticmethod
    def consumir_insumos_por_delta(producto, bodega, cantidad_producto, nota_ensamble=None, observacion_p=None):
        cantidad_producto = _d(cantidad_producto)
        if cantidad_producto == 0:
            return

        lineas_bom = ProductoInsumo.objects.filter(producto=producto).select_related("insumo")
        if not lineas_bom.exists():
            return

        for li in lineas_bom:
            cpu = _d(li.cantidad_por_unidad)
            merma = _d(li.merma_porcentaje)
            requerido = cantidad_producto * cpu * (Decimal("1") + (merma / Decimal("100")))

            if cantidad_producto > 0:
                # Consumir (multi-bodega)
                InventoryService.descontar_insumo_global(
                    li.insumo.codigo, 
                    requerido, 
                    bodega, 
                    nota_ensamble=nota_ensamble,
                    tipo_movimiento=InsumoMovimiento.Tipo.CONSUMO_ENSAMBLE,
                    observacion_p=observacion_p
                )
            else:
                # Reversar (devolver a la bodega de la nota)
                can_abs = abs(requerido)
                # 🔒 Bloqueo pesimista
                ins_pref = Insumo.objects.select_for_update().filter(codigo=li.insumo.codigo, bodega=bodega).first()
                if not ins_pref:
                    # Si no existe en esa bodega, buscamos el original (pero con lock)
                    ins_pref = Insumo.objects.select_for_update().filter(pk=li.insumo.pk).first()
                
                ins_pref.cantidad = _round3(_d(ins_pref.cantidad) + can_abs)
                ins_pref.save(update_fields=['cantidad'])

                # ✅ Registrar movimiento de reversión
                obs_mov = observacion_p or f"Reversión de consumo (BOM) por nota #{getattr(nota_ensamble, 'id', 'S/N')}"
                InventoryService.registrar_movimiento_sin_afectar_stock(
                    insumo=ins_pref,
                    tercero=getattr(nota_ensamble, "tercero", None),
                    bodega=ins_pref.bodega,
                    tipo=InsumoMovimiento.Tipo.AJUSTE,
                    cantidad=can_abs,
                    costo_unitario=ins_pref.costo_unitario,
                    nota_ensamble=nota_ensamble,
                    observacion=obs_mov
                )

    @staticmethod
    def _get_datos_adicionales(producto):
        # Intentar obtener con lock si es posible, o simplemente atomic en la caller
        datos = DatosAdicionalesProducto.objects.filter(producto=producto).first()
        if datos:
            return datos

        return DatosAdicionalesProducto.objects.create(
            producto=producto,
            referencia="N/A",
            unidad="UND",
            stock=Decimal("0"),
            stock_minimo=Decimal("0"),
            descripcion=getattr(producto, "descripcion", "") or "",
            marca="N/A",
            modelo="N/A",
            codigo_arancelario="N/A",
        )

    @staticmethod
    def _total_productos_nota(nota):
        return sum(_d(d.cantidad) for d in nota.detalles.all())

    @staticmethod
    def _aplicar_detalles(nota, detalles, signo=Decimal("1"), observacion_p=None):
        """
        Aplica o revierte:
        - Consumo por receta (BOM)
        - Stock del producto terminado
        """
        for det in detalles:
            producto = det.producto
            cantidad = _d(det.cantidad) * signo

            # BOM
            InventoryService.consumir_insumos_por_delta(producto, nota.bodega, cantidad, nota_ensamble=nota, observacion_p=observacion_p)

            # Stock producto terminado
            # 🔒 Lock para evitar race conditions en stock de producto
            datos = DatosAdicionalesProducto.objects.select_for_update().filter(producto=producto).first()
            if not datos:
                 # Si no existe, crearlo (esto no se puede lockear preventivamente fácil sin lockear tabla o producto, pero asumimos create atomic)
                 # En un mundo ideal lockeamos la tabla o el Producto padre.
                 # Por simplicidad, llamamos _get_datos_adicionales normal, pero al ser nuevo no hay race condition de UPDATE.
                 datos = InventoryService._get_datos_adicionales(producto)
            else:
                 pass # Ya tenemos el objeto con lock

            datos.stock = _d(datos.stock) + cantidad
            datos.save(update_fields=["stock"])

    @staticmethod
    def _aplicar_insumos_manuales(nota, signo=Decimal("1"), observacion_p=None):
        """
        Interpreta ni.cantidad como: cantidad POR UNIDAD de producto terminado.
        Entonces descuenta/devuelve: (ni.cantidad * total_productos_en_nota) * signo
        """
        total_productos = InventoryService._total_productos_nota(nota)
        if total_productos == 0:
            return

        for ni in nota.insumos.all():
            cant_total = _d(ni.cantidad) * _d(total_productos) * signo

            if cant_total > 0:
                # Consumir (multi-bodega)
                InventoryService.descontar_insumo_global(
                    ni.insumo.codigo, 
                    cant_total, 
                    nota.bodega, 
                    tercero=nota.tercero, 
                    nota_ensamble=nota,
                    observacion_p=observacion_p
                )
            else:
                # Reversar (devolver a la bodega de la nota)
                can_abs = abs(cant_total)
                # 🔒 Lock
                ins_pref = Insumo.objects.select_for_update().filter(codigo=ni.insumo.codigo, bodega=nota.bodega).first()
                if not ins_pref:
                    ins_pref = Insumo.objects.select_for_update().get(pk=ni.insumo.pk)
                
                ins_pref.cantidad = _round3(_d(ins_pref.cantidad) + can_abs)
                ins_pref.save(update_fields=['cantidad'])

                # ✅ Registrar movimiento de reversión
                obs_mov = observacion_p or f"Reversión de consumo manual por nota #{nota.id}"
                InventoryService.registrar_movimiento_sin_afectar_stock(
                    insumo=ins_pref,
                    tercero=nota.tercero,
                    bodega=ins_pref.bodega,
                    tipo=InsumoMovimiento.Tipo.AJUSTE,
                    cantidad=can_abs,
                    costo_unitario=ins_pref.costo_unitario,
                    nota_ensamble=nota,
                    observacion=obs_mov
                )

    @staticmethod
    @transaction.atomic
    def create_assembly_note(serializer, validated_data):
        """
        Maneja la creación completa de la nota de ensamble.
        """
        detalles_data = validated_data.pop("detalles_input", [])
        if not detalles_data:
            raise ValidationError({"detalles_input": "Debe enviar al menos un detalle."})

        # 1. Crear Nota (y relaciones M2M de insumos_manuales que el serializer maneja si están en validated_data)
        # OJO: Serializer.create() ya maneja insumos_input si se le pasa.
        # Pero aquí lo estamos desacoplando. El serializer.create por defecto hace `create`.
        # Si queremos control total, lo hacemos manual. 
        # Pero el serializer que vi en views.py llamaba a super().create(), que crea NotaEnsamble.
        # El serializer tiene un create() custom (l 452) que crea detalles e insumos.
        # Debemos DECIDIR: ¿Usamos el create del serializer o lo movemos aquí?
        # PLAN: Moverlo aquí para tener todo en Service.
        
        # Extraer insumos_input si existe
        insumos_data = validated_data.pop("insumos_input", [])
        
        nota = NotaEnsamble.objects.create(**validated_data)

        # 2. Detalles (Productos Terminados)
        NotaEnsambleDetalle.objects.bulk_create(
            [
                NotaEnsambleDetalle(
                    nota=nota,
                    cantidad_disponible=d["cantidad"],
                    bodega_actual=nota.bodega,
                    **d
                )
                for d in detalles_data
            ]
        )

        # 3. Insumos Manuales (Relación)
        if insumos_data:
            codigos = [x["insumo_codigo"] for x in insumos_data]
            insumos_qs = Insumo.objects.filter(codigo__in=codigos)
            insumos_map = {i.codigo: i for i in insumos_qs}

            insumo_objs = []
            for item in insumos_data:
                codigo = item["insumo_codigo"]
                cantidad = item["cantidad"]
                ins = insumos_map.get(codigo)
                if not ins:
                    raise ValidationError(f"Insumo {codigo} no existe.")

                insumo_objs.append(
                    NotaEnsambleInsumo(
                        nota=nota,
                        insumo=ins,
                        cantidad=cantidad
                    )
                )
            NotaEnsambleInsumo.objects.bulk_create(insumo_objs)

        # 4. APLICAR CAMBIOS DE STOCK
        nota.refresh_from_db() # Para cargar relaciones si hace falta, aunque con bulk_create no están cacheadas en el objeto.
        
        # Aplicar receta/stock
        InventoryService._aplicar_detalles(nota, nota.detalles.all(), signo=Decimal("1"))

        # Aplicar insumos manuales
        InventoryService._aplicar_insumos_manuales(nota, signo=Decimal("1"))

        return nota

    @staticmethod
    @transaction.atomic
    def update_assembly_note(nota, serializer, validated_data):
        # 1. Revertir anterior
        InventoryService._aplicar_detalles(nota, list(nota.detalles.all()), signo=Decimal("-1"))
        InventoryService._aplicar_insumos_manuales(nota, signo=Decimal("-1"))
        
        # Limpiar historial movimientos previos de esta nota
        InsumoMovimiento.objects.filter(nota_ensamble=nota).delete()

        # 2. Actualizar Nota (Campos básicos)
        # Extraemos inputs especiales
        detalles_data = validated_data.pop("detalles_input", None)
        insumos_data = validated_data.pop("insumos_input", None)

        for attr, value in validated_data.items():
            setattr(nota, attr, value)
        nota.save()

        # 3. Recrear Detalles si vienen
        if detalles_data is not None:
            nota.detalles.all().delete()
            NotaEnsambleDetalle.objects.bulk_create(
                [
                    NotaEnsambleDetalle(
                        nota=nota,
                        cantidad_disponible=d["cantidad"],
                        bodega_actual=nota.bodega,
                        **d
                    )
                    for d in detalles_data
                ]
            )

        # 4. Recrear Insumos Manuales si vienen
        if insumos_data is not None:
            nota.insumos.all().delete()
            codigos = [x["insumo_codigo"] for x in insumos_data]
            insumos_qs = Insumo.objects.filter(codigo__in=codigos)
            insumos_map = {i.codigo: i for i in insumos_qs}
            
            insumo_objs = []
            for item in insumos_data:
                codigo = item["insumo_codigo"]
                ins = insumos_map.get(codigo)
                if ins:
                    insumo_objs.append(
                        NotaEnsambleInsumo(
                            nota=nota,
                            insumo=ins,
                            cantidad=item["cantidad"]
                        )
                    )
            NotaEnsambleInsumo.objects.bulk_create(insumo_objs)

        # 5. Aplicar Nuevo
        nota.refresh_from_db() # Recargar relaciones
        InventoryService._aplicar_detalles(nota, nota.detalles.all(), signo=Decimal("1"))
        InventoryService._aplicar_insumos_manuales(nota, signo=Decimal("1"))

        return nota
