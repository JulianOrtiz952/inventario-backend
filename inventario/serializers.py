from rest_framework import serializers
from .models import (
    Insumo, Proveedor, Producto, Bodega, Impuesto, PrecioProducto,
    Tercero, DatosAdicionalesProducto, Talla, NotaEnsamble,
    ProductoInsumo, NotaEnsambleDetalle, NotaEnsambleInsumo, TrasladoProducto,
    NotaSalidaProducto, NotaSalidaProductoDetalle, NotaSalidaAfectacionStock, InsumoMovimiento
)
from django.db import transaction
from .services.pricing import calculate_product_prices
from decimal import Decimal
from django.db.models import Q, Sum


class ProveedorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Proveedor
        fields = ["id", "nombre"]


class BodegaSerializer(serializers.ModelSerializer):
    insumos_count = serializers.IntegerField(read_only=True)
    productos_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Bodega
        fields = [
            "id", "codigo", "nombre", "descripcion", "ubicacion",
            "insumos_count", "productos_count",
            "creado_en", "actualizado_en"
        ]


class TerceroSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tercero
        fields = ["id", "codigo", "nombre"]


class ImpuestoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Impuesto
        fields = ["id", "nombre", "codigo", "valor"]


class PrecioProductoSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrecioProducto
        fields = ["id", "nombre", "valor", "es_descuento"]


class DatosAdicionalesProductoSerializer(serializers.ModelSerializer):

    id = serializers.IntegerField(read_only=True)
    producto_id = serializers.PrimaryKeyRelatedField(queryset=Producto.objects.all(), source="producto", write_only=True)
    class Meta:
        model = DatosAdicionalesProducto
        fields = [
            "id",
            "producto",       # 👈 para leer
            "producto_id",    # 👈 para escribir
            "referencia",
            "unidad",
            "stock",
            "stock_minimo",
            "descripcion",
            "marca",
            "modelo",
            "codigo_arancelario",
        ]

    def create(self, validated_data):
        producto_id = validated_data.get('producto_id')
        producto = Producto.objects.get(id=producto_id)
        return DatosAdicionalesProducto.objects.create(producto=producto, **validated_data)

    def update(self, instance, validated_data):
        instance.referencia = validated_data.get('referencia', instance.referencia)
        instance.unidad = validated_data.get('unidad', instance.unidad)
        instance.stock = validated_data.get('stock', instance.stock)
        instance.stock_minimo = validated_data.get('stock_minimo', instance.stock_minimo)
        instance.descripcion = validated_data.get('descripcion', instance.descripcion)
        instance.marca = validated_data.get('marca', instance.marca)
        instance.modelo = validated_data.get('modelo', instance.modelo)
        instance.codigo_arancelario = validated_data.get('codigo_arancelario', instance.codigo_arancelario)
        instance.save()
        return instance



class ProductoSerializer(serializers.ModelSerializer):
    price_breakdown = serializers.SerializerMethodField(read_only=True)
    impuestos = ImpuestoSerializer(many=True, read_only=True)
    impuesto_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Impuesto.objects.all(),
        source="impuestos",
        write_only=True,
        required=False
    )

    tercero = TerceroSerializer(read_only=True)
    tercero_id = serializers.PrimaryKeyRelatedField(
        queryset=Tercero.objects.all(),
        source="tercero",
        write_only=True,
        required=False,
        allow_null=True
    )

    precios = PrecioProductoSerializer(many=True, read_only=True)
    datos_adicionales = DatosAdicionalesProductoSerializer(read_only=True)

    subtotal_sin_impuestos = serializers.SerializerMethodField(read_only=True)
    precio_total = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Producto
        fields = [
            "codigo_sku",
            "nombre",
            "codigo_barras",
            "unidad_medida",
            "tercero",
            "tercero_id",
            "impuestos",
            "impuesto_ids",
            "precios",
            "datos_adicionales",
            "price_breakdown",
            "subtotal_sin_impuestos",
            "precio_total",
            "creado_en",
            "actualizado_en",
        ]

    def get_subtotal_sin_impuestos(self, obj):
        return str(obj.subtotal_sin_impuestos or 0)

    def get_precio_total(self, obj):
        return str(obj.precio_total or 0)

    def get_price_breakdown(self, obj):
        return calculate_product_prices(obj)


class ProductoPrecioWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrecioProducto
        fields = ["id", "producto", "nombre", "valor", "es_descuento"]


class DatosAdicionalesWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = DatosAdicionalesProducto
        fields = [
            "id", "producto", "referencia", "unidad",
            "stock", "stock_minimo",
            "descripcion", "marca", "modelo", "codigo_arancelario"
        ]


class InsumoSerializer(serializers.ModelSerializer):
    bodega = BodegaSerializer(read_only=True)
    bodega_id = serializers.PrimaryKeyRelatedField(
        queryset=Bodega.objects.all(),
        source="bodega",
        write_only=True
    )

    proveedor = ProveedorSerializer(read_only=True)
    proveedor_id = serializers.PrimaryKeyRelatedField(
        queryset=Proveedor.objects.all(),
        source="proveedor",
        write_only=True,
        required=False,
        allow_null=True
    )

    tercero = TerceroSerializer(read_only=True)
    tercero_id = serializers.PrimaryKeyRelatedField(
        queryset=Tercero.objects.all(),
        source="tercero",
        write_only=True,
        required=False,
        allow_null=True
    )

    class Meta:
        model = Insumo
        fields = [
            "codigo",
            "nombre",
            "observacion",
            "factura",
            "referencia",
            "bodega",
            "bodega_id",
            "unidad_medida",
            "color",
            "tercero",
            "tercero_id",
            "cantidad",
            "stock_minimo",
            "costo_unitario",
            "proveedor",
            "proveedor_id",
            "creado_en",
            "actualizado_en",
        ]

    def validate(self, attrs):
        referencia = attrs.get("referencia")
        codigo = attrs.get("codigo") or getattr(self.instance, "codigo", None)
        if not referencia:
            attrs["referencia"] = codigo
        return attrs


class TallaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Talla
        fields = ["id", "nombre"]


class ProductoInsumoSerializer(serializers.ModelSerializer):
    producto = serializers.StringRelatedField(read_only=True)
    insumo = serializers.StringRelatedField(read_only=True)

    producto_id = serializers.PrimaryKeyRelatedField(
        queryset=Producto.objects.all(),
        source="producto",
        write_only=True
    )
    insumo_id = serializers.PrimaryKeyRelatedField(
        queryset=Insumo.objects.all(),
        source="insumo",
        write_only=True
    )

    class Meta:
        model = ProductoInsumo
        fields = [
            "id",
            "producto", "producto_id",
            "insumo", "insumo_id",
            "cantidad_por_unidad",
            "merma_porcentaje",
        ]


# -----------------------------
# ✅ NOTA ENSAMBLE: DETALLES
# -----------------------------
class NotaEnsambleDetalleSerializer(serializers.ModelSerializer):
    producto = ProductoSerializer(read_only=True)
    talla = TallaSerializer(read_only=True)

    class Meta:
        model = NotaEnsambleDetalle
        fields = ["id", "producto", "talla", "cantidad"]


class NotaEnsambleDetalleWriteSerializer(serializers.ModelSerializer):
    producto_id = serializers.PrimaryKeyRelatedField(queryset=Producto.objects.all(), source="producto")
    talla_id = serializers.PrimaryKeyRelatedField(queryset=Talla.objects.all(), source="talla", required=False, allow_null=True)

    class Meta:
        model = NotaEnsambleDetalle
        fields = ["producto_id", "talla_id", "cantidad"]


# -----------------------------
# ✅ NOTA ENSAMBLE: INSUMOS
# -----------------------------
class NotaEnsambleInsumoSerializer(serializers.ModelSerializer):
    """
    ✅ Devuelve el objeto insumo COMPLETO (nombre, unidad, costo_unitario, etc.)
    para que el frontend pueda mostrar: unidad, costo unitario y costo total.
    """
    insumo = InsumoSerializer(read_only=True)

    class Meta:
        model = NotaEnsambleInsumo
        fields = ["id", "insumo", "cantidad"]


class NotaEnsambleInsumoWriteSerializer(serializers.Serializer):
    insumo_codigo = serializers.CharField()
    cantidad = serializers.DecimalField(max_digits=12, decimal_places=3)
    costo_unitario = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, allow_null=True
    )


# -----------------------------
# ✅ NOTA ENSAMBLE: SERIALIZER PRINCIPAL
# -----------------------------
class NotaEnsambleSerializer(serializers.ModelSerializer):
    # --- LECTURA (rico) ---
    detalles = NotaEnsambleDetalleSerializer(many=True, read_only=True)
    insumos = NotaEnsambleInsumoSerializer(many=True, read_only=True)

    bodega = BodegaSerializer(read_only=True)
    tercero = TerceroSerializer(read_only=True)

    # --- ESCRITURA (ids) ---
    bodega_id = serializers.PrimaryKeyRelatedField(
        queryset=Bodega.objects.all(),
        source="bodega",
        write_only=True
    )

    tercero_id = serializers.PrimaryKeyRelatedField(
        queryset=Tercero.objects.all(),
        source="tercero",
        write_only=True,
        required=False,
        allow_null=True
    )

    detalles_input = NotaEnsambleDetalleWriteSerializer(many=True, write_only=True)
    insumos_input = NotaEnsambleInsumoWriteSerializer(many=True, write_only=True, required=False)

    class Meta:
        model = NotaEnsamble
        fields = [
            "id",
            "fecha_elaboracion",
            "observaciones",

            # lectura rica
            "bodega",
            "tercero",
            "detalles",
            "insumos",

            # escritura por ids + payloads
            "bodega_id",
            "tercero_id",
            "detalles_input",
            "insumos_input",
        ]

    def validate(self, attrs):
        insumos_data = attrs.get("insumos_input") or []
        tercero = attrs.get("tercero")  # viene por source="tercero"
        if insumos_data and not tercero:
            raise serializers.ValidationError({
                "tercero_id": "El tercero es obligatorio cuando se consumen insumos en una nota de ensamble."
            })
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        detalles_data = validated_data.pop("detalles_input", [])
        insumos_data = validated_data.pop("insumos_input", [])

        nota = NotaEnsamble.objects.create(**validated_data)

        # 1) Detalles (productos terminados)
        NotaEnsambleDetalle.objects.bulk_create(
            [NotaEnsambleDetalle(nota=nota, **d) for d in detalles_data]
        )

        # 2) Insumos consumidos (guardas el vínculo Nota->Insumo) + Kardex (CONSUMO_ENSAMBLE)
        if insumos_data:
            # Traer y bloquear insumos
            codigos = [x["insumo_codigo"] for x in insumos_data]
            insumos_qs = (
                Insumo.objects
                .select_for_update()
                .filter(codigo__in=codigos)
            )
            insumos_map = {i.codigo: i for i in insumos_qs}

            insumo_objs = []

            for item in insumos_data:
                codigo = item["insumo_codigo"]
                cantidad = item["cantidad"]

                ins = insumos_map.get(codigo)
                if not ins:
                    raise serializers.ValidationError({"insumos_input": f"Insumo {codigo} no existe."})

                if cantidad is None or cantidad <= 0:
                    raise serializers.ValidationError({"cantidad": f"La cantidad debe ser > 0 para {codigo}."})

                # ✅ Validar stock
                if ins.cantidad < cantidad:
                    raise serializers.ValidationError({"cantidad": f"Stock insuficiente para {codigo}."})

                # ✅ Restar stock (esto mantiene lo que ya haces hoy, pero ahora controlado aquí)
                ins.cantidad = (ins.cantidad - cantidad)

                # costo_unitario para el movimiento: si viene en payload úsalo; si no, usa el del insumo
                cu_payload = item.get("costo_unitario", None)
                costo_unitario = (cu_payload if cu_payload is not None else ins.costo_unitario)

                # (opcional) si quieres actualizar el costo_unitario del insumo al último usado:
                # ins.costo_unitario = costo_unitario

                ins.save(update_fields=["cantidad"])  # agrega "costo_unitario" si lo actualizas también

                # ✅ guardar línea de insumo usada en la nota (relación)
                insumo_objs.append(
                    NotaEnsambleInsumo(
                        nota=nota,
                        insumo=ins,
                        cantidad=cantidad
                    )
                )

                # ✅ Registrar movimiento en Kardex
                total = (Decimal(cantidad) * Decimal(costo_unitario)).quantize(Decimal("0.01"))

                InsumoMovimiento.objects.create(
                    insumo=ins,
                    tercero=nota.tercero,     # obligatorio en tu modelo
                    bodega=nota.bodega,
                    tipo=InsumoMovimiento.Tipo.CONSUMO_ENSAMBLE,
                    cantidad=cantidad,
                    unidad_medida=ins.unidad_medida or "",
                    costo_unitario=costo_unitario,
                    total=total,
                    saldo_resultante=ins.cantidad,
                    factura="",  # normalmente no aplica en consumo por ensamble
                    observacion=f"Consumo por nota de ensamble #{nota.id}",
                    nota_ensamble=nota
                )

            NotaEnsambleInsumo.objects.bulk_create(insumo_objs)

        return nota


class TrasladoProductoSerializer(serializers.ModelSerializer):
    tercero = TerceroSerializer(read_only=True)
    bodega_origen = BodegaSerializer(read_only=True)
    bodega_destino = BodegaSerializer(read_only=True)

    tercero_id = serializers.PrimaryKeyRelatedField(queryset=Tercero.objects.all(), source="tercero", write_only=True)
    bodega_origen_id = serializers.PrimaryKeyRelatedField(queryset=Bodega.objects.all(), source="bodega_origen", write_only=True)
    bodega_destino_id = serializers.PrimaryKeyRelatedField(queryset=Bodega.objects.all(), source="bodega_destino", write_only=True)

    producto_id = serializers.PrimaryKeyRelatedField(queryset=Producto.objects.all(), source="producto", write_only=True)
    talla_id = serializers.PrimaryKeyRelatedField(queryset=Talla.objects.all(), source="talla", required=False, allow_null=True, write_only=True)

    producto = ProductoSerializer(read_only=True)
    talla = TallaSerializer(read_only=True)

    class Meta:
        model = TrasladoProducto
        fields = [
            "id", "creado_en",
            "tercero", "tercero_id",
            "bodega_origen", "bodega_origen_id",
            "bodega_destino", "bodega_destino_id",
            "producto", "producto_id",
            "talla", "talla_id",
            "cantidad",
            "detalle",
        ]
        read_only_fields = ["id", "creado_en", "detalle"]

class NotaSalidaProductoDetalleInputSerializer(serializers.Serializer):
    producto_id = serializers.CharField()
    talla = serializers.CharField(required=False, allow_blank=True)
    cantidad = serializers.DecimalField(max_digits=12, decimal_places=3)
    costo_unitario = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, allow_null=True)

    def validate_cantidad(self, v):
        if v is None or v <= 0:
            raise serializers.ValidationError("La cantidad debe ser mayor a 0.")
        return v


class NotaSalidaProductoDetalleSerializer(serializers.ModelSerializer):
    producto = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()

    class Meta:
        model = NotaSalidaProductoDetalle
        fields = ["id", "producto", "talla", "cantidad", "costo_unitario", "total", "creado_en"]

    def get_producto(self, obj):
        return {
            "codigo_sku": obj.producto.codigo_sku,
            "nombre": obj.producto.nombre,
        }

    def get_total(self, obj):
        t = obj.total
        return str(t) if t is not None else None


class NotaSalidaAfectacionStockSerializer(serializers.ModelSerializer):
    detalle_stock_id = serializers.IntegerField(source="detalle_stock.id", read_only=True)
    nota_ensamble_id = serializers.IntegerField(source="detalle_stock.nota.id", read_only=True)

    class Meta:
        model = NotaSalidaAfectacionStock
        fields = ["id", "detalle_stock_id", "nota_ensamble_id", "cantidad", "creado_en"]


class NotaSalidaProductoSerializer(serializers.ModelSerializer):
    bodega_id = serializers.PrimaryKeyRelatedField(queryset=Bodega.objects.all(), source="bodega", write_only=True)
    tercero_id = serializers.PrimaryKeyRelatedField(
        queryset=Tercero.objects.all(), source="tercero", write_only=True, required=False, allow_null=True
    )

    bodega = serializers.SerializerMethodField(read_only=True)
    tercero = serializers.SerializerMethodField(read_only=True)

    detalles = NotaSalidaProductoDetalleSerializer(many=True, read_only=True)
    detalles_input = NotaSalidaProductoDetalleInputSerializer(many=True, write_only=True)

    class Meta:
        model = NotaSalidaProducto
        fields = [
            "id", "numero", "fecha",
            "bodega", "bodega_id",
            "tercero", "tercero_id",
            "observacion",
            "detalles", "detalles_input",
            "creado_en",
        ]

    def get_bodega(self, obj):
        return {"id": obj.bodega.id, "codigo": obj.bodega.codigo, "nombre": obj.bodega.nombre}

    def get_tercero(self, obj):
        if not obj.tercero:
            return None
        return {"id": obj.tercero.id, "codigo": obj.tercero.codigo, "nombre": obj.tercero.nombre}

    @transaction.atomic
    def create(self, validated_data):
        detalles_input = validated_data.pop("detalles_input", [])
        salida = NotaSalidaProducto.objects.create(**validated_data)

        # FIFO: descuenta de NotaEnsambleDetalle en la bodega efectiva
        for d in detalles_input:
            producto = Producto.objects.get(codigo_sku=d["producto_id"])
            talla = (d.get("talla") or "").strip()
            cantidad_req = d["cantidad"]

            # stock en esa bodega: (bodega_actual=bodega) OR (bodega_actual NULL y nota.bodega=bodega)
            bodega = salida.bodega

            qs_stock = (
                NotaEnsambleDetalle.objects
                .select_for_update()
                .filter(producto=producto, talla=talla)
                .filter(
                    Q(bodega_actual=bodega) |
                    Q(bodega_actual__isnull=True, nota__bodega=bodega)
                )
                .order_by("nota__fecha_elaboracion", "id")
            )

            disponible = qs_stock.aggregate(s=Sum("cantidad"))["s"] or Decimal("0")
            if disponible < cantidad_req:
                raise serializers.ValidationError(
                    f"Stock insuficiente para {producto.codigo_sku} talla '{talla or '-'}' en bodega {bodega.nombre}. "
                    f"Disponible: {disponible}, requerido: {cantidad_req}"
                )

            det_salida = NotaSalidaProductoDetalle.objects.create(
                salida=salida,
                producto=producto,
                talla=talla,
                cantidad=cantidad_req,
                costo_unitario=d.get("costo_unitario", None),
            )

            restante = cantidad_req
            for stock_row in qs_stock:
                if restante <= 0:
                    break

                tomar = min(restante, stock_row.cantidad)
                if tomar <= 0:
                    continue

                stock_row.cantidad = (stock_row.cantidad - tomar)
                stock_row.save(update_fields=["cantidad"])

                NotaSalidaAfectacionStock.objects.create(
                    salida_detalle=det_salida,
                    detalle_stock=stock_row,
                    cantidad=tomar,
                )

                restante -= tomar

        return salida
class InsumoMovimientoSerializer(serializers.ModelSerializer):
    insumo_codigo = serializers.CharField(source="insumo.codigo", read_only=True)
    insumo_nombre = serializers.CharField(source="insumo.nombre", read_only=True)

    tercero_nombre = serializers.CharField(source="tercero.nombre", read_only=True)
    bodega_nombre = serializers.CharField(source="bodega.nombre", read_only=True)

    class Meta:
        model = InsumoMovimiento
        fields = [
            "id",
            "fecha",
            "tipo",
            "cantidad",
            "unidad_medida",
            "costo_unitario",
            "total",
            "saldo_resultante",
            "factura",
            "observacion",
            "nota_ensamble",
            "insumo",
            "insumo_codigo",
            "insumo_nombre",
            "tercero",
            "tercero_nombre",
            "bodega",
            "bodega_nombre",
        ]
        read_only_fields = ["id", "fecha", "total", "saldo_resultante"]


class InsumoMovimientoInputSerializer(serializers.Serializer):
    tipo = serializers.ChoiceField(choices=[
        "ENTRADA", "SALIDA", "AJUSTE"
    ])
    tercero_id = serializers.IntegerField()
    cantidad = serializers.DecimalField(max_digits=14, decimal_places=3)
    costo_unitario = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)
    bodega_id = serializers.IntegerField(required=False, allow_null=True)

    factura = serializers.CharField(required=False, allow_blank=True)
    observacion = serializers.CharField(required=False, allow_blank=True)