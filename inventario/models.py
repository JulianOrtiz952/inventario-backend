from django.db import models
from django.utils import timezone
from decimal import Decimal

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
    descripcion = models.TextField(null=True, blank=True)

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
    # ✅ id autoincremental por defecto
    producto = models.ForeignKey(
        Producto,
        on_delete=models.PROTECT,
        related_name="notas_ensamble"
    )
    bodega = models.ForeignKey(
        Bodega,
        on_delete=models.PROTECT,
        related_name="notas_ensamble"
    )
    cantidad = models.DecimalField(max_digits=12, decimal_places=3, default=0)

    talla = models.ForeignKey(
        Talla,
        on_delete=models.PROTECT,
        related_name="notas_ensamble",
        null=True,
        blank=True,
    )

    observaciones = models.TextField(null=True, blank=True)

    tercero = models.ForeignKey(
        Tercero,
        on_delete=models.PROTECT,
        related_name="notas_ensamble"
    )

    # ✅ solo fecha; si no viene, hoy
    fecha_elaboracion = models.DateField(default=timezone.localdate)

    creado_en = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"NotaEnsamble #{self.id} - {self.producto.codigo_sku}"
