from rest_framework import serializers
from .models import (
    Insumo, Proveedor, Producto, Bodega, Impuesto, PrecioProducto,
    Tercero, DatosAdicionalesProducto, Talla, NotaEnsamble
)
from .services.pricing import calculate_product_prices


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
            "stock",  "stock_minimo", "descripcion",
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
    """
    Para crear/editar precios desde un endpoint dedicado.
    """
    class Meta:
        model = PrecioProducto
        fields = ["id", "producto", "nombre", "valor", "es_descuento"]


class DatosAdicionalesWriteSerializer(serializers.ModelSerializer):
    """
    Para crear/editar datos adicionales desde endpoint dedicado.
    """
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

    tercero = TerceroSerializer(read_only=True)   # 👈 NUEVO
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
        # si referencia no viene, usar el código (pk)
        referencia = attrs.get("referencia")
        codigo = attrs.get("codigo") or getattr(self.instance, "codigo", None)

        if not referencia:
            attrs["referencia"] = codigo

        return attrs


class TallaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Talla
        fields = ["id", "nombre"]


class NotaEnsambleSerializer(serializers.ModelSerializer):
    producto = ProductoSerializer(read_only=True)
    producto_id = serializers.PrimaryKeyRelatedField(
        queryset=Producto.objects.all(),
        source="producto",
        write_only=True
    )

    bodega = BodegaSerializer(read_only=True)
    bodega_id = serializers.PrimaryKeyRelatedField(
        queryset=Bodega.objects.all(),
        source="bodega",
        write_only=True
    )

    talla = TallaSerializer(read_only=True)
    talla_id = serializers.PrimaryKeyRelatedField(
        queryset=Talla.objects.all(),
        source="talla",
        write_only=True,
        required=False,
        allow_null=True
    )

    tercero = TerceroSerializer(read_only=True)
    tercero_id = serializers.PrimaryKeyRelatedField(
        queryset=Tercero.objects.all(),
        source="tercero",
        write_only=True
    )

    class Meta:
        model = NotaEnsamble
        fields = [
            "id",
            "producto",
            "producto_id",
            "bodega",
            "bodega_id",
            "cantidad",
            "talla",
            "talla_id",
            "observaciones",
            "tercero",
            "tercero_id",
            "fecha_elaboracion",
            "creado_en",
        ]
        read_only_fields = ["id", "creado_en"]
