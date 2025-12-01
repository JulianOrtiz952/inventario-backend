from django.db import models


class Proveedor(models.Model):
    nombre = models.CharField(max_length=100)

    def __str__(self):
        return self.nombre


class Insumo(models.Model):
    id = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=100)
    unidad = models.CharField(max_length=20)
    color = models.CharField(max_length=50, blank=True)        # 👈 NUEVO
    descripcion = models.TextField(blank=True)                 # 👈 NUEVO
    stock_actual = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    stock_minimo = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    costo_unitario = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    proveedor = models.ForeignKey(Proveedor, on_delete=models.PROTECT, related_name="insumos")
    bodega = models.ForeignKey(
        "Bodega",
        on_delete=models.PROTECT,
        related_name="insumos",
        null=True,
        blank=True,
    )
    estado = models.CharField(max_length=20, default="OK")
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    codigo = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        null=True,
        help_text="Código interno del insumo (opcional)"
    )

    def __str__(self):
        return self.nombre

class Producto(models.Model):
    codigo = models.CharField(max_length=50, unique=True)
    nombre = models.CharField(max_length=150)
    descripcion = models.TextField(blank=True)

    # 👇 ya NO debe haber este campo:
    # receta = models.ForeignKey("Receta", ...)

    tela = models.CharField(max_length=100, blank=True)
    color = models.CharField(max_length=100, blank=True)
    talla = models.CharField(max_length=50, blank=True)
    marca = models.CharField(max_length=100, blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"
        
class Receta(models.Model):
    codigo = models.CharField(max_length=50, unique=True)
    nombre = models.CharField(max_length=150)
    descripcion = models.TextField(blank=True)

    # 👇 NUEVO: relación correcta
    producto = models.ForeignKey(
        Producto,
        on_delete=models.CASCADE,
        related_name="recetas",
        null=True,
        blank=True,
    )
    bodega = models.ForeignKey(
        "Bodega",
        on_delete=models.PROTECT,
        related_name="recetas",
        null=True,
        blank=True,
    )


    # Atributos opcionales (pueden seguir existiendo aunque no los uses en UI)
    tela = models.CharField(max_length=100, blank=True)
    color = models.CharField(max_length=100, blank=True)
    talla = models.CharField(max_length=50, blank=True)
    marca = models.CharField(max_length=100, blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"

class RecetaItem(models.Model):
    receta = models.ForeignKey(
        Receta,
        on_delete=models.CASCADE,
        related_name="items"
    )
    insumo = models.ForeignKey(
        Insumo,
        on_delete=models.PROTECT,
        related_name="receta_items"
    )
    cantidad = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    unidad = models.CharField(max_length=20)  # normalmente se copia de insumo.unidad
    costo_unitario = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    @property
    def costo_total(self):
        return self.cantidad * self.costo_unitario

    def __str__(self):
        return f"{self.receta.codigo} - {self.insumo.nombre}"

class Produccion(models.Model):
    receta = models.ForeignKey("Receta", on_delete=models.PROTECT, related_name="producciones")
    cantidad = models.PositiveIntegerField()
    creado_en = models.DateTimeField(auto_now_add=True)

    bodega = models.ForeignKey(
        "Bodega",
        on_delete=models.PROTECT,
        related_name="producciones",
        null=True,
        blank=True,
    )

    def __str__(self):
        return f"{self.receta} x {self.cantidad} ({self.creado_en:%Y-%m-%d %H:%M})"

class Bodega(models.Model):
    codigo = models.CharField(max_length=50, unique=True)
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True)
    ubicacion = models.CharField(max_length=200, blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"