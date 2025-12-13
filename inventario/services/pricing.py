from decimal import Decimal


def _d(x):
    return x if isinstance(x, Decimal) else Decimal(str(x or "0"))


def calculate_product_prices(producto):
    """
    Retorna el desglose completo de precios del producto.
    Reglas:
    - base = suma de precios no descuento
    - descuentos = suma de precios con es_descuento=True
    - neto = base - descuentos
    - impuestos (%) = suma de impuestos asociados
    - iva_valor = neto * (impuestos/100)
    - total = neto + iva_valor
    """

    # Prefetch recomendado: producto.precios.all(), producto.impuestos.all()
    precios = list(producto.precios.all())
    impuestos = list(producto.impuestos.all())

    base = sum((_d(p.valor) for p in precios if not p.es_descuento), Decimal("0"))
    descuentos_total = sum((_d(p.valor) for p in precios if p.es_descuento), Decimal("0"))
    neto = base - descuentos_total

    porcentaje_impuestos = sum((_d(i.valor) for i in impuestos), Decimal("0"))
    iva_valor = (neto * porcentaje_impuestos) / Decimal("100")
    total = neto + iva_valor

    descuentos = [
        {"id": p.id, "nombre": p.nombre, "valor": str(_d(p.valor))}
        for p in precios if p.es_descuento
    ]
    recargos = [
        {"id": p.id, "nombre": p.nombre, "valor": str(_d(p.valor))}
        for p in precios if not p.es_descuento
    ]

    return {
        "precio_base": str(base),
        "precio_sin_iva_sin_descuentos": str(base),
        "descuentos": descuentos,
        "total_descuentos": str(descuentos_total),
        "precio_sin_iva_con_descuentos": str(neto),
        "porcentaje_impuestos": str(porcentaje_impuestos),
        "valor_iva": str(iva_valor),
        "precio_con_iva": str(total),
        "valor_producto_sin_iva": str(neto),   # alias útil
        "valor_producto_con_iva": str(total),  # alias útil
        "total": str(total),
        "recargos": recargos,
    }
