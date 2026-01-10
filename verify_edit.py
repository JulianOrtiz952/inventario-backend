import os
import django
import sys
from decimal import Decimal

# Setup Django environment
sys.path.append('/home/volcan/Documentos/dev/cala/inventario-backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from inventario.models import Insumo, Tercero, Bodega, InsumoMovimiento
from rest_framework.test import APIRequestFactory
from inventario.views import InsumoViewSet
from inventario.serializers import InsumoSerializer

def test_edit_history():
    # 1. Create prerequisites
    bodega, _ = Bodega.objects.get_or_create(codigo="TEST_BOD", defaults={"nombre": "Test Bodega"})
    tercero, _ = Tercero.objects.get_or_create(codigo="TEST_TER", defaults={"nombre": "Test Tercero"})
    
    # 2. Create Insumo (force creation)
    insumo_code = "TEST_INS_EDIT"
    Insumo.objects.filter(codigo=insumo_code).delete()
    
    insumo = Insumo.objects.create(
        codigo=insumo_code,
        nombre="Insumo Original",
        tercero=tercero,
        bodega=bodega,
        cantidad=Decimal("10.000"),
        costo_unitario=Decimal("100.00")
    )
    
    print(f"Insumo created: {insumo.nombre}")
    
    # 3. Simulate Edit via ViewSet (to trigger perform_update)
    factory = APIRequestFactory()
    view = InsumoViewSet.as_view({'put': 'update'})
    
    data = {
        "codigo": insumo_code,
        "nombre": "Insumo Editado",
        "tercero": tercero.id,
        "bodega": bodega.id,
        "cantidad": "10.000", # Should not be editable typically via serializer if read_only, but let's see logic
        "costo_unitario": "150.00",
        "observacion": "Edited via test"
    }
    
    request = factory.put(f'/insumos/{insumo_code}/', data, format='json')
    response = view(request, pk=insumo_code)
    
    if response.status_code != 200:
        print(f"Update failed: {response.data}")
        return
        
    print(f"Update status: {response.status_code}")
    
    # 4. Verify History
    movs = InsumoMovimiento.objects.filter(insumo=insumo, tipo="EDICION")
    
    if movs.exists():
        print("SUCCESS: 'EDICION' movement found!")
        for m in movs:
            print(f" - ID: {m.id}, Tipo: {m.tipo}, Cantidad: {m.cantidad}, Obs: {m.observacion}")
    else:
        print("FAILURE: No 'EDICION' movement found.")
        
    # Cleanup
    Insumo.objects.filter(codigo=insumo_code).delete()
    InsumoMovimiento.objects.filter(insumo__codigo=insumo_code).delete()

if __name__ == "__main__":
    test_edit_history()
