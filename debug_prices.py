import os
import django
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'inventario_backend.settings')
django.setup()

from inventario.models import Producto, PrecioProducto, Impuesto
from django.db.models import Sum, F, DecimalField, OuterRef, Subquery, ExpressionWrapper, Value
from django.db.models.functions import Coalesce

def debug_product_prices():
    # Try to find a product to test. The user screenshot showed some products. 
    # Let's list top 5 products and their calculated values.
    
    decimal_field = DecimalField(max_digits=20, decimal_places=4)

    # Replicate the logic from filters.py
    base_sq = Subquery(
        PrecioProducto.objects.filter(
            producto=OuterRef('pk'),
            es_descuento=False
        ).values('producto').annotate(
            sum_val=Sum('valor')
        ).values('sum_val')[:1],
        output_field=decimal_field
    )

    desc_sq = Subquery(
        PrecioProducto.objects.filter(
            producto=OuterRef('pk'),
            es_descuento=True
        ).values('producto').annotate(
            sum_val=Sum('valor')
        ).values('sum_val')[:1],
        output_field=decimal_field
    )

    # The suspected problematic query for Taxes
    tax_sq = Subquery(
        Impuesto.objects.filter(
            productos=OuterRef('pk')
        ).values('productos').annotate(
            sum_val=Sum('valor')
        ).values('sum_val')[:1],
        output_field=decimal_field
    )

    qs = Producto.objects.all().annotate(
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

    print(f"{'SKU':<10} | {'Base':<10} | {'Desc':<10} | {'Tax%':<10} | {'Total(Calc)':<15}")
    print("-" * 70)
    
    for p in qs[:10]:
        print(f"{p.codigo_sku:<10} | {p._base_val:<10} | {p._desc_val:<10} | {p._tax_pct:<10} | {p._calculated_total:<15}")

if __name__ == "__main__":
    debug_product_prices()
