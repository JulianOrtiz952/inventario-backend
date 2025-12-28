# inventario/reportes_urls.py
from django.urls import path
from inventario.reportes import (
    ReporteResumenAPIView,
    ReporteInsumosTopCompradosAPIView,
    ReporteInsumosTopConsumidosAPIView,
    ReporteProductosTopVendidosAPIView,
    ReporteProductosSerieVentasAPIView,
    ReporteProduccionTopProducidosAPIView,
    ReporteBodegasStockAPIView,
    ReporteNotasSalidasResumenAPIView,
)

urlpatterns = [
    path("resumen/", ReporteResumenAPIView.as_view()),
    path("insumos/top-comprados/", ReporteInsumosTopCompradosAPIView.as_view()),
    path("insumos/top-consumidos/", ReporteInsumosTopConsumidosAPIView.as_view()),
    path("productos/top-vendidos/", ReporteProductosTopVendidosAPIView.as_view()),
    path("productos/serie-ventas/", ReporteProductosSerieVentasAPIView.as_view()),
    path("produccion/top-producidos/", ReporteProduccionTopProducidosAPIView.as_view()),
    path("bodegas/stock/", ReporteBodegasStockAPIView.as_view()),
    path("notas/salidas/resumen/", ReporteNotasSalidasResumenAPIView.as_view()),
]
