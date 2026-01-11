# inventario/reportes.py
from __future__ import annotations

from datetime import datetime, date
from decimal import Decimal

from django.db.models import (
    Sum, Count, F, Value, Q,
    DecimalField,
)
from django.db.models.functions import (
    TruncDay, TruncMonth,
    Coalesce, Cast,
)
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from inventario.models import (
    Insumo, InsumoMovimiento,
    Producto,
    NotaEnsamble, NotaEnsambleDetalle,
    TrasladoProducto,
    NotaSalidaProducto, NotaSalidaProductoDetalle,
)

# ============================================================
# Helpers: tipado DECIMAL (evita mixed types)
# ============================================================

DEC = DecimalField(max_digits=18, decimal_places=2)
DEC3 = DecimalField(max_digits=18, decimal_places=3)

def D0() -> Value:
    return Value(Decimal("0.00"), output_field=DEC)

def D0_3() -> Value:
    return Value(Decimal("0.000"), output_field=DEC3)

def _dec_str(x) -> str:
    if x is None:
        return "0"
    try:
        return str(Decimal(x))
    except Exception:
        return str(x)

def _to_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None

def _get_filters(request):
    fecha_desde = _to_date(request.query_params.get("fecha_desde"))
    fecha_hasta = _to_date(request.query_params.get("fecha_hasta"))
    bodega_id = request.query_params.get("bodega_id")
    tercero_id = request.query_params.get("tercero_id")
    top = int(request.query_params.get("top") or 10)
    group_by = request.query_params.get("group_by") or "dia"

    return {
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "bodega_id": int(bodega_id) if (bodega_id and str(bodega_id).isdigit()) else None,
        "tercero_id": int(tercero_id) if (tercero_id and str(tercero_id).isdigit()) else None,
        "top": top,
        "group_by": group_by,
    }

def _apply_date_range_dt(qs, field_name: str, f):
    """Para DateTimeField (ej: fecha en InsumoMovimiento, creado_en en TrasladoProducto)."""
    if f["fecha_desde"]:
        qs = qs.filter(**{f"{field_name}__date__gte": f["fecha_desde"]})
    if f["fecha_hasta"]:
        qs = qs.filter(**{f"{field_name}__date__lte": f["fecha_hasta"]})
    return qs

def _apply_date_range_date(qs, field_name: str, f):
    """Para DateField (ej: fecha en NotaSalidaProducto, fecha_elaboracion en NotaEnsamble)."""
    if f["fecha_desde"]:
        qs = qs.filter(**{f"{field_name}__gte": f["fecha_desde"]})
    if f["fecha_hasta"]:
        qs = qs.filter(**{f"{field_name}__lte": f["fecha_hasta"]})
    return qs

def _trunc(group_by: str):
    return TruncMonth if group_by == "mes" else TruncDay

def _filters_payload(f):
    return {
        "fecha_desde": f["fecha_desde"].isoformat() if f["fecha_desde"] else None,
        "fecha_hasta": f["fecha_hasta"].isoformat() if f["fecha_hasta"] else None,
        "bodega_id": f["bodega_id"],
        "tercero_id": f["tercero_id"],
        "top": f["top"],
        "group_by": f["group_by"],
    }

def _labels_from_period(qs, field="periodo"):
    out = []
    for x in qs:
        p = x.get(field)
        out.append(p.strftime("%Y-%m-%d") if p else "")
    return out


# ============================================================
# 1) Dashboard / Resumen
# ============================================================

class ReporteResumenAPIView(APIView):
    """
    GET /api/reportes/resumen/
    KPIs globales + series:
    - ventas (salidas) por periodo
    - compras insumos por periodo
    - producción por periodo
    """

    def get(self, request):
        f = _get_filters(request)

        # -------------------------
        # Insumos movimientos
        # -------------------------
        im = InsumoMovimiento.objects.all()
        im = _apply_date_range_dt(im, "fecha", f)
        if f["bodega_id"]:
            im = im.filter(bodega_id=f["bodega_id"])
        if f["tercero_id"]:
            im = im.filter(tercero_id=f["tercero_id"])

        compras = im.filter(tipo__in=["ENTRADA", "CREACION", "AJUSTE"])
        consumos = im.filter(tipo__in=["SALIDA", "CONSUMO_ENSAMBLE"])

        # -------------------------
        # Salidas producto (ventas en unidades/costo)
        # -------------------------
        sal = NotaSalidaProducto.objects.all()
        sal = _apply_date_range_date(sal, "fecha", f)
        if f["bodega_id"]:
            sal = sal.filter(bodega_id=f["bodega_id"])
        if f["tercero_id"]:
            sal = sal.filter(tercero_id=f["tercero_id"])
        sal_det = NotaSalidaProductoDetalle.objects.filter(salida__in=sal)

        # -------------------------
        # Producción (ensamble)
        # -------------------------
        ens = NotaEnsamble.objects.all()
        ens = _apply_date_range_date(ens, "fecha_elaboracion", f)
        if f["bodega_id"]:
            ens = ens.filter(bodega_id=f["bodega_id"])
        if f["tercero_id"]:
            ens = ens.filter(tercero_id=f["tercero_id"])
        ens_det = NotaEnsambleDetalle.objects.filter(nota__in=ens)

        # -------------------------
        # Traslados
        # -------------------------
        tr = TrasladoProducto.objects.all()
        tr = _apply_date_range_dt(tr, "creado_en", f)
        if f["bodega_id"]:
            tr = tr.filter(Q(bodega_origen_id=f["bodega_id"]) | Q(bodega_destino_id=f["bodega_id"]))
        if f["tercero_id"]:
            tr = tr.filter(tercero_id=f["tercero_id"])

        # -------------------------
        # KPIs (con output_field correcto)
        # -------------------------
        compras_cant = compras.aggregate(x=Coalesce(Sum("cantidad"), D0_3(), output_field=DEC3))["x"]
        compras_val = compras.aggregate(x=Coalesce(Sum("total"), D0(), output_field=DEC))["x"]
        consumos_cant = consumos.aggregate(x=Coalesce(Sum("cantidad"), D0_3(), output_field=DEC3))["x"]

        salidas_unidades = sal_det.aggregate(x=Coalesce(Sum("cantidad"), D0_3(), output_field=DEC3))["x"]

        # costo = sum(cantidad * costo_unitario)
        salidas_valor_costo = sal_det.aggregate(
            x=Coalesce(
                Sum(
                    Cast(F("cantidad"), output_field=DEC3) *
                    Cast(Coalesce(F("costo_unitario"), D0(), output_field=DEC), output_field=DEC),
                    output_field=DEC,
                ),
                D0(),
                output_field=DEC,
            )
        )["x"]

        produccion_unidades = ens_det.aggregate(x=Coalesce(Sum("cantidad"), D0_3(), output_field=DEC3))["x"]

        traslados_unidades = tr.aggregate(x=Coalesce(Sum("cantidad"), D0_3(), output_field=DEC3))["x"]

        kpis = {
            "compras_insumos_cantidad": _dec_str(compras_cant),
            "compras_insumos_valor": _dec_str(compras_val),
            "consumos_insumos_cantidad": _dec_str(consumos_cant),
            "notas_salida_count": sal.count(),
            "salidas_unidades": _dec_str(salidas_unidades),
            "salidas_valor_costo": _dec_str(salidas_valor_costo),
            "notas_ensamble_count": ens.count(),
            "produccion_unidades": _dec_str(produccion_unidades),
            "traslados_count": tr.count(),
            "traslados_unidades": _dec_str(traslados_unidades),
        }

        # -------------------------
        # Series (charts)
        # -------------------------
        trunc_fn = _trunc(f["group_by"])

        ventas_serie = (
            sal_det.annotate(periodo=trunc_fn("salida__fecha"))
            .values("periodo")
            .annotate(unidades=Coalesce(Sum("cantidad"), D0_3(), output_field=DEC3))
            .order_by("periodo")
        )

        compras_serie = (
            compras.annotate(periodo=trunc_fn("fecha"))
            .values("periodo")
            .annotate(
                cantidad=Coalesce(Sum("cantidad"), D0_3(), output_field=DEC3),
                valor=Coalesce(Sum("total"), D0(), output_field=DEC),
            )
            .order_by("periodo")
        )

        produccion_serie = (
            ens_det.annotate(periodo=trunc_fn("nota__fecha_elaboracion"))
            .values("periodo")
            .annotate(unidades=Coalesce(Sum("cantidad"), D0_3(), output_field=DEC3))
            .order_by("periodo")
        )

        charts = [
            {
                "id": "ventas_unidades",
                "type": "line",
                "title": "Ventas (unidades)",
                "unit": "unidades",
                "labels": _labels_from_period(ventas_serie),
                "series": [{"name": "Unidades", "data": [_dec_str(x["unidades"]) for x in ventas_serie]}],
            },
            {
                "id": "compras_insumos",
                "type": "bar",
                "title": "Compras de insumos",
                "unit": "mixto",
                "labels": _labels_from_period(compras_serie),
                "series": [
                    {"name": "Cantidad", "data": [_dec_str(x["cantidad"]) for x in compras_serie]},
                    {"name": "Valor", "data": [_dec_str(x["valor"]) for x in compras_serie]},
                ],
            },
            {
                "id": "produccion_unidades",
                "type": "line",
                "title": "Producción (unidades)",
                "unit": "unidades",
                "labels": _labels_from_period(produccion_serie),
                "series": [{"name": "Unidades", "data": [_dec_str(x["unidades"]) for x in produccion_serie]}],
            },
        ]

        return Response(
            {
                "ok": True,
                "filters": _filters_payload(f),
                "kpis": kpis,
                "charts": charts,
                "rows": [],
            },
            status=status.HTTP_200_OK,
        )


# ============================================================
# 2) INSUMOS
# ============================================================

class ReporteInsumosTopCompradosAPIView(APIView):
    """
    GET /api/reportes/insumos/top-comprados/
    Top insumos por cantidad y valor.
    """

    def get(self, request):
        f = _get_filters(request)

        qs = InsumoMovimiento.objects.filter(tipo__in=["ENTRADA", "CREACION", "AJUSTE"])
        qs = _apply_date_range_dt(qs, "fecha", f)
        if f["bodega_id"]:
            qs = qs.filter(bodega_id=f["bodega_id"])
        if f["tercero_id"]:
            qs = qs.filter(tercero_id=f["tercero_id"])

        rows = (
            qs.values("insumo_id", "insumo__codigo", "insumo__nombre")
            .annotate(
                cantidad=Coalesce(Sum("cantidad"), D0_3(), output_field=DEC3),
                valor=Coalesce(Sum("total"), D0(), output_field=DEC),
                movimientos=Count("id"),
            )
            .order_by("-cantidad")[: f["top"]]
        )

        labels = [f'{x["insumo__codigo"]} - {x["insumo__nombre"]}' for x in rows]

        return Response(
            {
                "ok": True,
                "filters": _filters_payload(f),
                "kpis": {},
                "charts": [
                    {
                        "id": "top_insumos_comprados",
                        "type": "bar",
                        "title": "Top insumos comprados",
                        "unit": "mixto",
                        "labels": labels,
                        "series": [
                            {"name": "Cantidad", "data": [_dec_str(x["cantidad"]) for x in rows]},
                            {"name": "Valor", "data": [_dec_str(x["valor"]) for x in rows]},
                        ],
                    }
                ],
                "rows": [
                    {
                        "insumo_id": x["insumo_id"],
                        "codigo": x["insumo__codigo"],
                        "nombre": x["insumo__nombre"],
                        "cantidad": _dec_str(x["cantidad"]),
                        "valor": _dec_str(x["valor"]),
                        "movimientos": x["movimientos"],
                    }
                    for x in rows
                ],
            },
            status=status.HTTP_200_OK,
        )


class ReporteInsumosTopConsumidosAPIView(APIView):
    """
    GET /api/reportes/insumos/top-consumidos/
    Top insumos consumidos (SALIDA + CONSUMO_ENSAMBLE).
    """

    def get(self, request):
        f = _get_filters(request)

        qs = InsumoMovimiento.objects.filter(tipo__in=["SALIDA", "CONSUMO_ENSAMBLE"])
        qs = _apply_date_range_dt(qs, "fecha", f)
        if f["bodega_id"]:
            qs = qs.filter(bodega_id=f["bodega_id"])
        if f["tercero_id"]:
            qs = qs.filter(tercero_id=f["tercero_id"])

        rows = (
            qs.values("insumo_id", "insumo__codigo", "insumo__nombre")
            .annotate(
                cantidad=Coalesce(Sum("cantidad"), D0_3(), output_field=DEC3),
                movimientos=Count("id"),
            )
            .order_by("-cantidad")[: f["top"]]
        )

        labels = [f'{x["insumo__codigo"]} - {x["insumo__nombre"]}' for x in rows]

        return Response(
            {
                "ok": True,
                "filters": _filters_payload(f),
                "kpis": {},
                "charts": [
                    {
                        "id": "top_insumos_consumidos",
                        "type": "bar",
                        "title": "Top insumos consumidos",
                        "unit": "unidades",
                        "labels": labels,
                        "series": [{"name": "Cantidad", "data": [_dec_str(x["cantidad"]) for x in rows]}],
                    }
                ],
                "rows": [
                    {
                        "insumo_id": x["insumo_id"],
                        "codigo": x["insumo__codigo"],
                        "nombre": x["insumo__nombre"],
                        "cantidad": _dec_str(x["cantidad"]),
                        "movimientos": x["movimientos"],
                    }
                    for x in rows
                ],
            },
            status=status.HTTP_200_OK,
        )


# ============================================================
# 3) PRODUCTOS (SALIDAS / "ventas" en unidades)
# ============================================================

class ReporteProductosTopVendidosAPIView(APIView):
    """
    GET /api/reportes/productos/top-vendidos/
    Top productos por unidades vendidas (desde NotaSalidaProductoDetalle).
    """

    def get(self, request):
        f = _get_filters(request)

        sal = NotaSalidaProducto.objects.all()
        sal = _apply_date_range_date(sal, "fecha", f)
        if f["bodega_id"]:
            sal = sal.filter(bodega_id=f["bodega_id"])
        if f["tercero_id"]:
            sal = sal.filter(tercero_id=f["tercero_id"])

        det = NotaSalidaProductoDetalle.objects.filter(salida__in=sal)

        rows = (
            det.values("producto_id", "producto__codigo_sku", "producto__nombre", "talla")
            .annotate(
                unidades=Coalesce(Sum("cantidad"), D0_3(), output_field=DEC3),
                valor_costo=Coalesce(
                    Sum(
                        Cast(F("cantidad"), output_field=DEC3) *
                        Cast(Coalesce(F("costo_unitario"), D0(), output_field=DEC), output_field=DEC),
                        output_field=DEC,
                    ),
                    D0(),
                    output_field=DEC,
                ),
                lineas=Count("id"),
            )
            .order_by("-unidades")[: f["top"]]
        )

        labels = [
            f'{x["producto__codigo_sku"]} - {x["producto__nombre"]} ({x["talla"] or "-"})'
            for x in rows
        ]

        return Response(
            {
                "ok": True,
                "filters": _filters_payload(f),
                "kpis": {},
                "charts": [
                    {
                        "id": "top_productos_vendidos",
                        "type": "bar",
                        "title": "Top productos vendidos",
                        "unit": "mixto",
                        "labels": labels,
                        "series": [
                            {"name": "Unidades", "data": [_dec_str(x["unidades"]) for x in rows]},
                            {"name": "Costo", "data": [_dec_str(x["valor_costo"]) for x in rows]},
                        ],
                    }
                ],
                "rows": [
                    {
                        "producto_id": x["producto_id"],
                        "sku": x["producto__codigo_sku"],
                        "producto_nombre": x["producto__nombre"],
                        "talla": x["talla"] or "",
                        "unidades": _dec_str(x["unidades"]),
                        "valor_costo": _dec_str(x["valor_costo"]),
                        "lineas": x["lineas"],
                    }
                    for x in rows
                ],
            },
            status=status.HTTP_200_OK,
        )


class ReporteProductosSerieVentasAPIView(APIView):
    """
    GET /api/reportes/productos/serie-ventas/?group_by=dia|mes
    Serie temporal de unidades vendidas.
    """

    def get(self, request):
        f = _get_filters(request)
        trunc_fn = _trunc(f["group_by"])

        sal = NotaSalidaProducto.objects.all()
        sal = _apply_date_range_date(sal, "fecha", f)
        if f["bodega_id"]:
            sal = sal.filter(bodega_id=f["bodega_id"])
        if f["tercero_id"]:
            sal = sal.filter(tercero_id=f["tercero_id"])

        det = NotaSalidaProductoDetalle.objects.filter(salida__in=sal)

        serie = (
            det.annotate(periodo=trunc_fn("salida__fecha"))
            .values("periodo")
            .annotate(unidades=Coalesce(Sum("cantidad"), D0_3(), output_field=DEC3))
            .order_by("periodo")
        )

        labels = _labels_from_period(serie)
        data = [_dec_str(x["unidades"]) for x in serie]

        return Response(
            {
                "ok": True,
                "filters": _filters_payload(f),
                "kpis": {
                    "total_unidades": _dec_str(
                        sum((Decimal(x) for x in data), start=Decimal("0.000")) if data else Decimal("0.000")
                    )
                },
                "charts": [
                    {
                        "id": "ventas_serie",
                        "type": "line",
                        "title": "Serie de ventas (unidades)",
                        "unit": "unidades",
                        "labels": labels,
                        "series": [{"name": "Unidades", "data": data}],
                    }
                ],
                "rows": [{"periodo": labels[i], "unidades": data[i]} for i in range(len(labels))],
            },
            status=status.HTTP_200_OK,
        )


# ============================================================
# 4) PRODUCCIÓN (ENSAMBLE)
# ============================================================

class ReporteProduccionTopProducidosAPIView(APIView):
    """
    GET /api/reportes/produccion/top-producidos/
    Top productos producidos desde NotaEnsambleDetalle.
    """

    def get(self, request):
        f = _get_filters(request)

        ens = NotaEnsamble.objects.all()
        ens = _apply_date_range_date(ens, "fecha_elaboracion", f)
        if f["bodega_id"]:
            ens = ens.filter(bodega_id=f["bodega_id"])
        if f["tercero_id"]:
            ens = ens.filter(tercero_id=f["tercero_id"])

        det = NotaEnsambleDetalle.objects.filter(nota__in=ens)

        rows = (
            det.values(
                "producto_id", "producto__codigo_sku", "producto__nombre",
                "talla__nombre",
                "bodega_actual_id", "bodega_actual__nombre",
            )
            .annotate(unidades=Coalesce(Sum("cantidad"), D0_3(), output_field=DEC3))
            .order_by("-unidades")[: f["top"]]
        )

        labels = [
            f'{x["producto__codigo_sku"]} - {x["producto__nombre"]} ({x["talla__nombre"] or "-"}) [{x["bodega_actual__nombre"] or "-"}]'
            for x in rows
        ]

        return Response(
            {
                "ok": True,
                "filters": _filters_payload(f),
                "kpis": {},
                "charts": [
                    {
                        "id": "top_produccion",
                        "type": "bar",
                        "title": "Top producción",
                        "unit": "unidades",
                        "labels": labels,
                        "series": [{"name": "Unidades", "data": [_dec_str(x["unidades"]) for x in rows]}],
                    }
                ],
                "rows": [
                    {
                        "producto_id": x["producto_id"],
                        "sku": x["producto__codigo_sku"],
                        "producto_nombre": x["producto__nombre"],
                        "talla": x["talla__nombre"] or "",
                        "bodega_id": x["bodega_actual_id"],
                        "bodega_nombre": x["bodega_actual__nombre"] or "",
                        "unidades": _dec_str(x["unidades"]),
                    }
                    for x in rows
                ],
            },
            status=status.HTTP_200_OK,
        )


# ============================================================
# 5) BODEGAS / INVENTARIO (snapshot)
# ============================================================

class ReporteBodegasStockAPIView(APIView):
    """
    GET /api/reportes/bodegas/stock/
    Snapshot:
    - Insumos por bodega (Insumo.cantidad)
    - Producto terminado por bodega/talla (NotaEnsambleDetalle.cantidad)
    """

    def get(self, request):
        f = _get_filters(request)

        # Insumos
        ins_qs = Insumo.objects.all()
        if f["bodega_id"]:
            ins_qs = ins_qs.filter(bodega_id=f["bodega_id"])

        # Si tu Insumo.cantidad es Decimal, forzamos decimal output
        ins_rows = (
            ins_qs.values("bodega_id", "bodega__nombre", "codigo", "nombre", "unidad_medida")
            .annotate(cantidad=Coalesce(Sum("cantidad"), D0_3(), output_field=DEC3))
            .order_by("bodega__nombre", "codigo")
        )

        # Producto terminado stock
        prod_det = NotaEnsambleDetalle.objects.all()
        if f["bodega_id"]:
            prod_det = prod_det.filter(bodega_actual_id=f["bodega_id"])

        prod_rows = (
            prod_det.values(
                "bodega_actual_id", "bodega_actual__nombre",
                "producto_id", "producto__codigo_sku", "producto__nombre",
                "talla__nombre",
            )
            .annotate(cantidad=Coalesce(Sum("cantidad"), D0_3(), output_field=DEC3))
            .order_by("bodega_actual__nombre", "producto__codigo_sku")
        )

        # Chart: Distribución de productos por bodega
        bodega_dist = (
            prod_det.values("bodega_actual__nombre")
            .annotate(unidades=Coalesce(Sum("cantidad"), D0_3(), output_field=DEC3))
            .order_by("-unidades")
        )

        charts = [
            {
                "id": "stock_por_bodega",
                "type": "pie",
                "title": "Distribución de stock por bodega",
                "unit": "unidades",
                "labels": [x["bodega_actual__nombre"] or "Sin Bodega" for x in bodega_dist],
                "series": [{"name": "Unidades", "data": [_dec_str(x["unidades"]) for x in bodega_dist]}],
            }
        ]

        return Response(
            {
                "ok": True,
                "filters": {"bodega_id": f["bodega_id"]},
                "kpis": {
                    "insumos_items": len(ins_rows),
                    "productos_items": len(prod_rows),
                },
                "charts": charts,
                "rows": {
                    "insumos": [
                        {
                            "bodega_id": x["bodega_id"],
                            "bodega": x["bodega__nombre"],
                            "codigo": x["codigo"],
                            "nombre": x["nombre"],
                            "unidad_medida": x.get("unidad_medida") or "",
                            "cantidad": _dec_str(x["cantidad"]),
                        }
                        for x in ins_rows
                    ],
                    "productos": [
                        {
                            "bodega_id": x["bodega_actual_id"],
                            "bodega": x["bodega_actual__nombre"],
                            "producto_id": x["producto_id"],
                            "sku": x["producto__codigo_sku"],
                            "producto": x["producto__nombre"],
                            "talla": x["talla__nombre"] or "",
                            "cantidad": _dec_str(x["cantidad"]),
                        }
                        for x in prod_rows
                    ],
                },
            },
            status=status.HTTP_200_OK,
        )


# ============================================================
# 6) NOTAS (salidas resumen)
# ============================================================

class ReporteNotasSalidasResumenAPIView(APIView):
    """
    GET /api/reportes/notas/salidas/resumen/
    KPIs de notas de salida.
    """

    def get(self, request):
        f = _get_filters(request)

        sal = NotaSalidaProducto.objects.all()
        sal = _apply_date_range_date(sal, "fecha", f)
        if f["bodega_id"]:
            sal = sal.filter(bodega_id=f["bodega_id"])
        if f["tercero_id"]:
            sal = sal.filter(tercero_id=f["tercero_id"])

        det = NotaSalidaProductoDetalle.objects.filter(salida__in=sal)

        unidades = det.aggregate(x=Coalesce(Sum("cantidad"), D0_3(), output_field=DEC3))["x"]
        costo_total = det.aggregate(
            x=Coalesce(
                Sum(
                    Cast(F("cantidad"), output_field=DEC3) *
                    Cast(Coalesce(F("costo_unitario"), D0(), output_field=DEC), output_field=DEC),
                    output_field=DEC,
                ),
                D0(),
                output_field=DEC,
            )
        )["x"]

        kpis = {
            "notas": sal.count(),
            "lineas": det.count(),
            "unidades": _dec_str(unidades),
            "costo_total": _dec_str(costo_total),
        }

        # Chart: Ventas por Tercero (Top 10)
        terceros_dist = (
            sal.values("tercero__nombre")
            .annotate(
                valor=Coalesce(
                    Sum(
                        Cast(F("detalles__cantidad"), output_field=DEC3) *
                        Cast(Coalesce(F("detalles__costo_unitario"), D0(), output_field=DEC), output_field=DEC),
                        output_field=DEC,
                    ),
                    D0(),
                    output_field=DEC,
                )
            )
            .order_by("-valor")[:10]
        )

        charts = [
            {
                "id": "ventas_por_tercero",
                "type": "bar",
                "title": "Ventas por Tercero (Valor)",
                "unit": "valor",
                "labels": [x["tercero__nombre"] or "Sin Tercero" for x in terceros_dist],
                "series": [{"name": "Valor", "data": [_dec_str(x["valor"]) for x in terceros_dist]}],
            }
        ]

        return Response(
            {
                "ok": True,
                "filters": _filters_payload(f),
                "kpis": kpis,
                "charts": charts,
                "rows": [],
            },
            status=status.HTTP_200_OK,
        )
