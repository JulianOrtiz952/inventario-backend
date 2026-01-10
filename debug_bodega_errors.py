import os
import django
import sys
import json

# Setup Django
sys.path.append('/home/volcan/Documentos/dev/cala/inventario-backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from inventario.models import Bodega
from inventario.serializers import BodegaSerializer

# Ensure at least one bodega exists
if not Bodega.objects.exists():
    Bodega.objects.create(nombre="Bodega Test", codigo="TEST001")

existing = Bodega.objects.first()
print(f"Existing Bodega: {existing.nombre} ({existing.codigo})")

# Try to create duplicate via Serializer to simulate API
data = {
    "nombre": existing.nombre,
    "codigo": "UNIQUE_CODE_" + existing.codigo # Different code, same name
}

serializer = BodegaSerializer(data=data)
if not serializer.is_valid():
    print("\nDuplicate Name Error:")
    print(json.dumps(serializer.errors, indent=2))
else:
    print("\nDuplicate Name FAILED to raise error (Unexpected)")

# Try to create duplicate via Serializer (Duplicate Code)
data_code = {
    "nombre": "Unique Name " + existing.nombre,
    "codigo": existing.codigo # Same code
}
serializer_code = BodegaSerializer(data=data_code)
if not serializer_code.is_valid():
    print("\nDuplicate Code Error:")
    print(json.dumps(serializer_code.errors, indent=2))
else:
    print("\nDuplicate Code FAILED to raise error (Unexpected)")
