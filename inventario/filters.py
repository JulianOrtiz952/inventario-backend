import django_filters
from decimal import Decimal
from django.db.models import Sum, F, DecimalField, OuterRef, Subquery, ExpressionWrapper, Value
from django.db.models.functions import Coalesce
from .models import Insumo, Producto, PrecioProducto, Impuesto

class InsumoFilter(django_filters.FilterSet):
    costo_unitario_min = django_filters.NumberFilter(field_name="costo_unitario", lookup_expr="gte")
    costo_unitario_max = django_filters.NumberFilter(field_name="costo_unitario", lookup_expr="lte")

    class Meta:
        model = Insumo
        fields = ["bodega", "tercero", "proveedor"]

class ProductoFilter(django_filters.FilterSet):
    precio_min = django_filters.NumberFilter(method='filter_precio_total', label="Precio Total Mínimo")
    precio_max = django_filters.NumberFilter(method='filter_precio_total', label="Precio Total Máximo")
    tercero = django_filters.NumberFilter(field_name="tercero__id")

    class Meta:
        model = Producto
        fields = ["tercero", "impuestos"]

    def filter_precio_total(self, queryset, name, value):
        if value is None:
            return queryset
        
        # Ensure we only annotate once
        if '_calculated_total' not in queryset.query.annotations:
            # Subquery: Base Price
            base_sq = Subquery(
                PrecioProducto.objects.filter(
                    producto=OuterRef('pk'),
                    es_descuento=False
                ).values('producto').annotate(
                    sum_val=Sum('valor')
                ).values('sum_val')[:1],
                output_field=DecimalField()
            )

            # Subquery: Discounts
            desc_sq = Subquery(
                PrecioProducto.objects.filter(
                    producto=OuterRef('pk'),
                    es_descuento=True
                ).values('producto').annotate(
                    sum_val=Sum('valor')
                ).values('sum_val')[:1],
                output_field=DecimalField()
            )

            # Subquery: Taxes
            tax_sq = Subquery(
                Impuesto.objects.filter(
                    productos=OuterRef('pk')
                ).values('productos').annotate(
                    sum_val=Sum('valor')
                ).values('sum_val')[:1],
                output_field=DecimalField()
            )

            # Basic Decimal Field for casting
            decimal_field = DecimalField(max_digits=20, decimal_places=4)

            queryset = queryset.annotate(
                _base_val=Coalesce(base_sq, Value(Decimal("0"), output_field=decimal_field), output_field=decimal_field),
                _desc_val=Coalesce(desc_sq, Value(Decimal("0"), output_field=decimal_field), output_field=decimal_field),
                _tax_pct=Coalesce(tax_sq, Value(Decimal("0"), output_field=decimal_field), output_field=decimal_field),
            ).annotate(
                _neto=ExpressionWrapper(
                    F('_base_val') - F('_desc_val'),
                    output_field=decimal_field
                )
            ).annotate(
                _calculated_total=ExpressionWrapper(
                    F('_neto') * (
                        Value(Decimal("1"), output_field=decimal_field) + 
                        (F('_tax_pct') / Value(Decimal("100"), output_field=decimal_field))
                    ),
                    output_field=decimal_field
                )
            )

        if name == 'precio_min':
            return queryset.filter(_calculated_total__gte=value)
        if name == 'precio_max':
            return queryset.filter(_calculated_total__lte=value)

        return queryset
