from django.db import models
from django.utils import timezone
from decimal import Decimal
from django.core.exceptions import ValidationError

class Proveedor(models.Model):
    nombre = models.CharField(max_length=100)

    def __str__(self):
        return self.nombre


class Tercero(models.Model):
    codigo = models.CharField(max_length=50, unique=True)
    nombre = models.CharField(max_length=150)

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"


class Bodega(models.Model):
    codigo = models.CharField(max_length=50, unique=True)
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True)
    ubicacion = models.CharField(max_length=200, blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"


class Impuesto(models.Model):
    nombre = models.CharField(max_length=100)
    codigo = models.CharField(max_length=50, unique=True)
    valor = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text="Porcentaje. Ej: 19.00"
    )

    def __str__(self):
        return f"{self.codigo} - {self.nombre} ({self.valor}%)"


class Producto(models.Model):
    # ✅ PK: Código_SKU ingresable
    codigo_sku = models.CharField(max_length=50, primary_key=True)

    nombre = models.CharField(max_length=150)

    # ✅ único, puede ser null
    codigo_barras = models.CharField(max_length=100, unique=True, null=True, blank=True)

    # ✅ se guarda como texto (después validamos DIAN si quieres)
    unidad_medida = models.CharField(max_length=50)

    # ✅ puede ser null (blank=True)
    impuestos = models.ManyToManyField(Impuesto, blank=True, related_name="productos")

    tercero = models.ForeignKey(
        Tercero, on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="productos"
    )

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.codigo_sku} - {self.nombre}"

    @property
    def subtotal_sin_impuestos(self):
        total = Decimal("0")
        for p in self.precios.all():
            v = p.valor or Decimal("0")
            total += (-v if p.es_descuento else v)
        return total

    @property
    def total_impuestos_porcentaje(self):
        total = Decimal("0")
        for i in self.impuestos.all():
            total += (i.valor or Decimal("0"))
        return total

    @property
    def precio_total(self):
        subtotal = self.subtotal_sin_impuestos or Decimal("0")
        porcentaje = self.total_impuestos_porcentaje or Decimal("0")

        # todo Decimal
        factor = Decimal("1") + (Decimal(porcentaje) / Decimal("100"))
        return subtotal * factor


class DatosAdicionalesProducto(models.Model):
    producto = models.OneToOneField(
        Producto,
        on_delete=models.CASCADE,
        related_name="datos_adicionales"
    )
    

    referencia = models.CharField(max_length=100, null=True, blank=True)
    unidad = models.CharField(max_length=50, null=True, blank=True)
    stock = models.DecimalField(              
        max_digits=12,
        decimal_places=3,
        default=0
    )
    stock_minimo = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    descripcion = models.TextField(null=True, blank=True)
    marca = models.CharField(max_length=100, null=True, blank=True)
    modelo = models.CharField(max_length=100, null=True, blank=True)
    codigo_arancelario = models.CharField(max_length=50, null=True, blank=True)

    def __str__(self):
        return f"DatosAdicionales({self.producto.codigo_sku})"


class PrecioProducto(models.Model):
    producto = models.ForeignKey(
        Producto,
        on_delete=models.CASCADE,
        related_name="precios"
    )
    nombre = models.CharField(max_length=100)
    valor = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    es_descuento = models.BooleanField(default=False)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        signo = "-" if self.es_descuento else "+"
        return f"{self.producto.codigo_sku} {signo}{self.valor} ({self.nombre})"


class Talla(models.Model):
    nombre = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.nombre


class Insumo(models.Model):
    # ✅ PK: Código ingresable
    codigo = models.CharField(max_length=50, primary_key=True)

    nombre = models.CharField(max_length=100)
    observacion = models.TextField(blank=True, default="")  # antes: descripcion
    factura = models.CharField(max_length=120, blank=True, default="")

    # ✅ si no llega, se copia del código; referencia no se puede repetir
    referencia = models.CharField(max_length=50, unique=True)

    stock_minimo = models.DecimalField(max_digits=12, decimal_places=3, default=0)

    bodega = models.ForeignKey(
        Bodega,
        on_delete=models.PROTECT,
        related_name="insumos"
    )

    cantidad = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    costo_unitario = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Proveedor se mantiene (no lo pediste explícito, pero lo dejé porque ya existía)
    proveedor = models.ForeignKey(
        Proveedor,
        on_delete=models.PROTECT,
        related_name="insumos",
        null=True,
        blank=True,
    )

    tercero = models.ForeignKey(          # 👈 NUEVO
        Tercero,
        on_delete=models.PROTECT,
        related_name="insumos",
        null=True,
        blank=True
    )

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        # si referencia viene vacía (por seguridad), se setea al código
        if not self.referencia:
            self.referencia = self.codigo
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"


class NotaEnsamble(models.Model):
    bodega = models.ForeignKey("Bodega", on_delete=models.PROTECT, related_name="notas_ensamble")
    tercero = models.ForeignKey("Tercero", on_delete=models.PROTECT, null=True, blank=True, related_name="notas_ensamble")
    fecha_elaboracion = models.DateField(default=timezone.now)
    observaciones = models.TextField(null=True, blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"NotaEns#{self.id}"


#class NotaEnsambleDetalle(models.Model):
#    nota = models.ForeignKey(NotaEnsamble, on_delete=models.CASCADE, related_name="detalles")
#    producto = models.ForeignKey("Producto", on_delete=models.PROTECT, related_name="ensambles_detalle")
#    talla = models.ForeignKey("Talla", on_delete=models.PROTECT, null=True, blank=True, related_name="ensambles_detalle")
#    cantidad = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0"))
#
#    class Meta:
#        unique_together = ("nota", "producto", "talla")

class ProductoInsumo(models.Model):
    """
    Relación Producto -> Insumo (BOM/Receta)
    Indica cuánto insumo se consume por cada 1 unidad del producto.
    """
    producto = models.ForeignKey(
        "Producto",
        on_delete=models.CASCADE,
        related_name="bom_insumos",
    )
    insumo = models.ForeignKey(
        "Insumo",
        on_delete=models.PROTECT,
        related_name="usado_en_productos",
    )
    cantidad_por_unidad = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    # opcional: merma/porcentaje extra
    merma_porcentaje = models.DecimalField(max_digits=6, decimal_places=2, default=0)

    class Meta:
        unique_together = ("producto", "insumo")
        verbose_name = "Insumo por Producto (BOM)"
        verbose_name_plural = "Insumos por Producto (BOM)"

    def clean(self):
        if self.cantidad_por_unidad is None or self.cantidad_por_unidad <= Decimal("0"):
            raise ValidationError({"cantidad_por_unidad": "Debe ser mayor que 0."})
        if self.merma_porcentaje is None or self.merma_porcentaje < Decimal("0"):
            raise ValidationError({"merma_porcentaje": "No puede ser negativa."})

        # regla recomendada: receta debe usar insumos de la misma bodega del ensamble
        # (no lo validamos aquí porque la bodega está en la Nota de Ensamble, no en producto)

    def __str__(self):
        return f"{self.producto} -> {self.insumo} ({self.cantidad_por_unidad})"

class NotaEnsambleInsumo(models.Model):
    nota = models.ForeignKey(NotaEnsamble, on_delete=models.CASCADE, related_name="insumos")
    insumo = models.ForeignKey("Insumo", on_delete=models.PROTECT, related_name="ensambles_insumo")
    cantidad = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0"))

    class Meta:
        unique_together = ("nota", "insumo")

class NotaEnsambleDetalle(models.Model):
    nota = models.ForeignKey(NotaEnsamble, on_delete=models.CASCADE, related_name="detalles")
    producto = models.ForeignKey("Producto", on_delete=models.PROTECT, related_name="ensambles_detalle")
    talla = models.ForeignKey("Talla", on_delete=models.PROTECT, null=True, blank=True, related_name="ensambles_detalle")
    cantidad = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0"))

    bodega_actual = models.ForeignKey(
        "Bodega",
        on_delete=models.PROTECT,
        related_name="productos_detalle",
        null=True,
        blank=True
    )

    class Meta:
        unique_together = ("nota", "producto", "talla", "bodega_actual")

    def save(self, *args, **kwargs):
        # si no viene bodega_actual, por defecto es la bodega de la nota
        if self.bodega_actual_id is None and self.nota_id is not None:
            self.bodega_actual = self.nota.bodega
        super().save(*args, **kwargs)

# models.py
class TrasladoProducto(models.Model):
    creado_en = models.DateTimeField(auto_now_add=True)

    tercero = models.ForeignKey(
        "Tercero",
        on_delete=models.PROTECT,
        related_name="traslados_producto"
    )

    bodega_origen = models.ForeignKey(
        "Bodega",
        on_delete=models.PROTECT,
        related_name="traslados_salida"
    )

    bodega_destino = models.ForeignKey(
        "Bodega",
        on_delete=models.PROTECT,
        related_name="traslados_entrada"
    )

    producto = models.ForeignKey(
        "Producto",
        on_delete=models.PROTECT,
        related_name="traslados"
    )

    talla = models.ForeignKey(
        "Talla",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="traslados"
    )

    cantidad = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0"))

    # Para “no perder vínculo con la nota”: guardamos referencia al detalle original
    detalle = models.ForeignKey(
        "NotaEnsambleDetalle",
        on_delete=models.PROTECT,
        related_name="traslados",
        null=True,
        blank=True
    )

    def __str__(self):
        return f"Traslado {self.id} {self.producto_id} {self.cantidad} {self.bodega_origen_id}->{self.bodega_destino_id}"

class NotaSalidaProducto(models.Model):
    """
    Historial / documento de salida de producto terminado.
    """
    numero = models.CharField(max_length=30, unique=True, blank=True)  # se llena al guardar
    fecha = models.DateField(default=timezone.now)

    bodega = models.ForeignKey("Bodega", on_delete=models.PROTECT, related_name="salidas")
    tercero = models.ForeignKey("Tercero", on_delete=models.PROTECT, null=True, blank=True, related_name="salidas")

    observacion = models.TextField(blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado_en"]

    def __str__(self):
        return self.numero or f"SALIDA-{self.id}"

    def save(self, *args, **kwargs):
        creating = self.pk is None
        super().save(*args, **kwargs)

        # Genera consecutivo tipo: NS-20251226-000123
        if creating and not self.numero:
            self.numero = f"NS-{self.fecha.strftime('%Y%m%d')}-{self.id:06d}"
            super().save(update_fields=["numero"])


class NotaSalidaProductoDetalle(models.Model):
    salida = models.ForeignKey(NotaSalidaProducto, on_delete=models.CASCADE, related_name="detalles")

    producto = models.ForeignKey("Producto", on_delete=models.PROTECT)
    talla = models.CharField(max_length=20, blank=True)

    cantidad = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0.000"))

    costo_unitario = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.cantidad is None or self.cantidad <= 0:
            raise ValidationError("La cantidad de salida debe ser mayor a 0.")

    @property
    def total(self):
        if self.costo_unitario is None:
            return None
        return (self.cantidad or Decimal("0")) * (self.costo_unitario or Decimal("0"))


class NotaSalidaAfectacionStock(models.Model):
    """
    Traza EXACTAMENTE de qué NotaEnsambleDetalle se descontó stock (FIFO).
    """
    salida_detalle = models.ForeignKey(
        NotaSalidaProductoDetalle, on_delete=models.CASCADE, related_name="afectaciones"
    )
    detalle_stock = models.ForeignKey(
        "NotaEnsambleDetalle", on_delete=models.PROTECT, related_name="salidas_afectadas"
    )

    cantidad = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0.000"))
    creado_en = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.cantidad is None or self.cantidad <= 0:
            raise ValidationError("La cantidad afectada debe ser mayor a 0.")