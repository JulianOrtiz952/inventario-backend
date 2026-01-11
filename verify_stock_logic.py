import os
import django
from decimal import Decimal

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from inventario.models import (
    NotaEnsamble, NotaEnsambleDetalle, Producto, Bodega, Tercero, Talla,
    NotaSalidaProducto, NotaSalidaProductoDetalle, NotaSalidaAfectacionStock
)
from django.utils import timezone
from django.db import transaction

def verify_fix():
    print("--- Starting Verification ---")
    
    # 1. Setup data
    bodega = Bodega.objects.first()
    tercero = Tercero.objects.first()
    producto = Producto.objects.first()
    talla = Talla.objects.first()
    
    if not all([bodega, tercero, producto, talla]):
        print("Missing base data (Bodega, Tercero, Producto, or Talla). Please run in a populated DB.")
        return

    print(f"Using Bodega: {bodega.nombre}, Producto: {producto.nombre}, Talla: {talla.nombre}")

    try:
        with transaction.atomic():
            # 2. Create NotaEnsamble (Simulating production of 10 units)
            nota = NotaEnsamble.objects.create(
                bodega=bodega,
                tercero=tercero,
                fecha_elaboracion=timezone.now().date()
            )
            
            detalle = NotaEnsambleDetalle.objects.create(
                nota=nota,
                producto=producto,
                talla=talla,
                cantidad=Decimal("10.000"),
                cantidad_disponible=Decimal("10.000")
            )
            
            print(f"Created NotaEnsamble #{nota.id} with 10 units.")
            print(f"Initial - Cantidad: {detalle.cantidad}, Disponible: {detalle.cantidad_disponible}")

            # 3. Create NotaSalida (Simulating sale of 8 units)
            salida = NotaSalidaProducto.objects.create(
                bodega=bodega,
                tercero=tercero,
                fecha=timezone.now().date()
            )
            
            det_salida = NotaSalidaProductoDetalle.objects.create(
                salida=salida,
                producto=producto,
                talla=talla.nombre,
                cantidad=Decimal("8.000"),
                costo_unitario=Decimal("1000.00")
            )
            
            # Simulate the FIFO deduction logic manually (as updated in serializer)
            detalle.cantidad_disponible -= Decimal("8.000")
            detalle.save(update_fields=["cantidad_disponible"])
            
            NotaSalidaAfectacionStock.objects.create(
                salida_detalle=det_salida,
                detalle_stock=detalle,
                cantidad=Decimal("8.000")
            )
            
            print(f"Performed Sale of 8 units.")
            
            # 4. Verify results
            detalle.refresh_from_db()
            print(f"After Sale - Cantidad (Original): {detalle.cantidad}, Disponible (Stock): {detalle.cantidad_disponible}")
            
            if detalle.cantidad == Decimal("10.000") and detalle.cantidad_disponible == Decimal("2.000"):
                print("✅ SUCCESS: Original quantity preserved, available stock updated correctly.")
            else:
                print("❌ FAILURE: Quantities are incorrect.")
                print(f"Expected: Cantidad=10.0, Disponible=2.0")
                print(f"Got: Cantidad={detalle.cantidad}, Disponible={detalle.cantidad_disponible}")
            
            # Rollback to avoid polluting DB
            transaction.set_rollback(True)
            print("Rollback performed.")
            
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    verify_fix()
