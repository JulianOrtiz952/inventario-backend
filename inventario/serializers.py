from rest_framework import serializers
from .models import Insumo, Proveedor, Producto, Receta, RecetaItem, Produccion


class ProveedorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Proveedor
        fields = ["id", "nombre"]


class InsumoSerializer(serializers.ModelSerializer):
    # Para lectura: objeto proveedor completo
    proveedor = ProveedorSerializer(read_only=True)

    # Para escritura: solo el id del proveedor
    proveedor_id = serializers.PrimaryKeyRelatedField(
        queryset=Proveedor.objects.all(),
        source="proveedor",
        write_only=True
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

class RecetaSerializer(serializers.ModelSerializer):
    items = RecetaItemSerializer(many=True)

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

        # Campos simples
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Items (reemplazamos todos)
        if items_data is not None:
            instance.items.all().delete()
            for item in items_data:
                RecetaItem.objects.create(receta=instance, **item)

        return instance

class ProductoSerializer(serializers.ModelSerializer):
    # Receta anidada solo lectura
    receta = RecetaSerializer(read_only=True)

    # Para escritura, recibimos receta_id
    receta_id = serializers.PrimaryKeyRelatedField(
        queryset=Receta.objects.all(),
        source="receta",
        write_only=True,
        required=False,
        allow_null=True,
    )

    class Meta:
        model = Producto
        fields = [
            "id",
            "codigo",
            "nombre",
            "descripcion",
            "receta",       # read-only
            "receta_id",    # write-only
            "tela",
            "color",
            "talla",
            "marca",
            "creado_en",
            "actualizado_en",
        ]

    def create(self, validated_data):
        receta = validated_data.get("receta")

        # Si viene una receta y no se mandaron explícitamente tela/color/..., los copiamos
        if receta:
            for attr in ["tela", "color", "talla", "marca"]:
                if attr not in validated_data or not validated_data.get(attr):
                    validated_data[attr] = getattr(receta, attr, "")

        return super().create(validated_data)

    def update(self, instance, validated_data):
        receta = validated_data.get("receta", getattr(instance, "receta", None))

        # Si cambiaron de receta y no enviaron atributos, los copiamos de la nueva
        if receta and not any(
            field in validated_data for field in ["tela", "color", "talla", "marca"]
        ):
            for attr in ["tela", "color", "talla", "marca"]:
                validated_data[attr] = getattr(receta, attr, "")

        return super().update(instance, validated_data)

class ProduccionSerializer(serializers.ModelSerializer):
    receta_nombre = serializers.CharField(source="receta.nombre", read_only=True)
    receta_codigo = serializers.CharField(source="receta.codigo", read_only=True)

    class Meta:
        model = Produccion
        fields = ["id", "receta", "receta_nombre", "receta_codigo", "cantidad", "creado_en"]
        read_only_fields = ["id", "creado_en"]
