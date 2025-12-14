from rest_framework import serializers
from .models import (
    Insumo, Proveedor, Producto, Bodega, Impuesto, PrecioProducto,
    Tercero, DatosAdicionalesProducto, Talla, NotaEnsamble,
    ProductoInsumo, NotaEnsambleDetalle, NotaEnsambleInsumo
)
from django.db import transaction
from .services.pricing import calculate_product_prices
from decimal import Decimal


class ProveedorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Proveedor
        fields = ["id", "nombre"]


class BodegaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bodega
        fields = [
            "id", "codigo", "nombre", "descripcion", "ubicacion",
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
    class Meta:
        model = DatosAdicionalesProducto
        fields = [
            "referencia", "unidad",
            "stock", "stock_minimo", "descripcion",
            "marca", "modelo", "codigo_arancelario"
        ]


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
            "descripcion",
            "referencia",
            "bodega",
            "bodega_id",
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
    bodega_id = serializers.PrimaryKeyRelatedField(queryset=Bodega.objects.all(), source="bodega", write_only=True)
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

    @transaction.atomic
    def create(self, validated_data):
        detalles_data = validated_data.pop("detalles_input", [])
        insumos_data = validated_data.pop("insumos_input", [])

        nota = NotaEnsamble.objects.create(**validated_data)

        # detalles
        NotaEnsambleDetalle.objects.bulk_create(
            [NotaEnsambleDetalle(nota=nota, **d) for d in detalles_data]
        )

        # insumos manuales
        if insumos_data:
            insumo_objs = []
            insumos_map = {i.codigo: i for i in Insumo.objects.filter(codigo__in=[x["insumo_codigo"] for x in insumos_data])}

            for i in insumos_data:
                ins = insumos_map.get(i["insumo_codigo"])
                if not ins:
                    raise serializers.ValidationError({"insumos_input": f"Insumo {i['insumo_codigo']} no existe."})

                insumo_objs.append(
                    NotaEnsambleInsumo(
                        nota=nota,
                        insumo=ins,
                        cantidad=i["cantidad"]
                    )
                )
            NotaEnsambleInsumo.objects.bulk_create(insumo_objs)

        return nota
