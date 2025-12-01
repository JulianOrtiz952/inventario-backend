from rest_framework import serializers
from .models import Insumo, Proveedor, Producto, Receta, RecetaItem, Produccion, Bodega


class ProveedorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Proveedor
        fields = ["id", "nombre"]

class BodegaSerializer(serializers.ModelSerializer):
    # estos campos los llenaremos desde la vista con annotate
    insumos_count = serializers.IntegerField(read_only=True)
    recetas_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Bodega
        fields = [
            "id",
            "codigo",
            "nombre",
            "descripcion",
            "ubicacion",
            "creado_en",
            "actualizado_en",
            "insumos_count",
            "recetas_count",
        ]

class InsumoSerializer(serializers.ModelSerializer):
    # Para lectura: objeto proveedor completo
    proveedor = ProveedorSerializer(read_only=True)

    # Para escritura: solo el id del proveedor
    proveedor_id = serializers.PrimaryKeyRelatedField(
        queryset=Proveedor.objects.all(),
        source="proveedor",
        write_only=True
    )

    bodega = BodegaSerializer(read_only=True)
    bodega_id = serializers.PrimaryKeyRelatedField(
        queryset=Bodega.objects.all(),
        source="bodega",
        write_only=True,
        required=False,
        allow_null=True,
    )

    class Meta:
        model = Insumo
        fields = [
            "id",
            "codigo", 
            "nombre",
            "unidad",
            "color",         
            "descripcion",
            "stock_actual",
            "stock_minimo",
            "costo_unitario",
            "proveedor",      # read-only (objeto)
            "proveedor_id",   # write-only (id)
            "bodega",        # read-only 👈
            "bodega_id",     # write-only 👈
            "estado",
            "creado_en",
            "actualizado_en",
        ]
    def _generate_codigo(self):
        last = Insumo.objects.order_by("-id").first()
        next_num = (last.id if last else 0) + 1
        return f"INS-{next_num:04d}"

    def create(self, validated_data):
        # Si no viene código, lo generamos
        if not validated_data.get("codigo"):
            validated_data["codigo"] = self._generate_codigo()
        return super().create(validated_data)

    def update(self, instance, validated_data):
        # Permite editar el código si quieres (opcional)
        return super().update(instance, validated_data)


class RecetaItemSerializer(serializers.ModelSerializer):
    insumo = InsumoSerializer(read_only=True)
    insumo_id = serializers.PrimaryKeyRelatedField(
        queryset=Insumo.objects.all(),
        source="insumo",
        write_only=True,
    )
    costo_total = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = RecetaItem
        fields = [
            "id",
            "insumo",
            "insumo_id",
            "cantidad",
            "unidad",
            "costo_unitario",
            "costo_total",
        ]

    def get_costo_total(self, obj):
        return float(obj.costo_total)

class ProductoSerializer(serializers.ModelSerializer):
    # opcional: receta principal solo lectura

    class Meta:
        model = Producto
        fields = [
            "id",
            "codigo",
            "nombre",
            "descripcion",
            "tela",
            "color",
            "talla",
            "marca",
            "creado_en",
            "actualizado_en",
        ]

    def get_receta(self, obj):
        receta = obj.recetas.order_by("id").first()
        if not receta:
            return None
        return RecetaSerializer(receta).data

class ProduccionSerializer(serializers.ModelSerializer):
    receta_nombre = serializers.CharField(source="receta.nombre", read_only=True)
    receta_codigo = serializers.CharField(source="receta.codigo", read_only=True)

    bodega_nombre = serializers.CharField(source="bodega.nombre", read_only=True)
    bodega_codigo = serializers.CharField(source="bodega.codigo", read_only=True)

    class Meta:
        model = Produccion
        fields = [
            "id",
            "receta",
            "receta_nombre",
            "receta_codigo",
            "bodega_codigo",
            "bodega_nombre",
            "cantidad",
            "creado_en",
        ]
        read_only_fields = ["id", "creado_en"]

    def get_bodega_nombre(self, obj):
        bodega = getattr(obj.receta, "bodega", None)
        return bodega.nombre if bodega else None

    def get_bodega_codigo(self, obj):
        bodega = getattr(obj.receta, "bodega", None)
        return bodega.codigo if bodega else None

class RecetaSerializer(serializers.ModelSerializer):
    items = RecetaItemSerializer(many=True)
    # lectura: producto anidado
    producto = ProductoSerializer(read_only=True)
    # escritura: solo id
    producto_id = serializers.PrimaryKeyRelatedField(
        queryset=Producto.objects.all(),
        source="producto",
        write_only=True,
        required=False,
        allow_null=True,
    )

    bodega = BodegaSerializer(read_only=True)
    bodega_id = serializers.PrimaryKeyRelatedField(
        queryset=Bodega.objects.all(),
        source="bodega",
        write_only=True,
        required=False,
        allow_null=True,
    )

    class Meta:
        model = Receta
        fields = [
            "id",
            "codigo",
            "nombre",
            "descripcion",
            "tela",
            "color",
            "talla",
            "marca",
            "producto",      # read-only
            "producto_id",   # write-only
            "bodega",      # read-only
            "bodega_id",   # write-only
            "items",
            "creado_en",
            "actualizado_en",
        ]

    def create(self, validated_data):
        items_data = validated_data.pop("items", [])
        receta = Receta.objects.create(**validated_data)
        for item in items_data:
            RecetaItem.objects.create(receta=receta, **item)
        return receta

    def update(self, instance, validated_data):
        items_data = validated_data.pop("items", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if items_data is not None:
            instance.items.all().delete()
            for item in items_data:
                RecetaItem.objects.create(receta=instance, **item)

        return instance

