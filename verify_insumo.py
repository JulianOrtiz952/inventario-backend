import os
import django
from rest_framework.exceptions import ValidationError

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from inventario.serializers import InsumoSerializer
from inventario.models import Insumo, Bodega

# Mock data
bodega = Bodega.objects.first()
if not bodega:
    print("Warning: No bodega found, creating dummy one for test")
    bodega = Bodega.objects.create(codigo="BOD-TEST", nombre="Bodega Test")

data_valid = {
    "codigo": "INS-ABC-123",
    "nombre": "Insumo Test Valid",
    "bodega_id": bodega.id,
    "referencia": "REF-ABC-123",
    "unidad_medida": "UN",
    "cantidad": 10,
    "costo_unitario": 100
}

data_invalid_char = {
    "codigo": "INS@123", # Invalid char @
    "nombre": "Insumo Test Invalid",
    "bodega_id": bodega.id
}

print("--- TEST 1: Creating Valid Insumo ---")
ser = InsumoSerializer(data=data_valid)
if ser.is_valid():
    print("SUCCESS: Valid data passed validation.")
else:
    print(f"FAILURE: Valid data failed validation: {ser.errors}")

print("\n--- TEST 2: Creating Invalid Insumo (Bad Char) ---")
ser = InsumoSerializer(data=data_invalid_char)
if not ser.is_valid():
    print(f"SUCCESS: Invalid data failed as expected: {ser.errors}")
    if "codigo" in ser.errors and "guión" in str(ser.errors["codigo"][0]):
        print("SUCCESS: Correct error message found.")
else:
    print("FAILURE: Invalid data PASSED validation unexpectedly.")

print("\n--- TEST 3: Updating Insumo Code (Should Fail) ---")
# Create a dummy instance in memory (not saving to DB to avoid pollution if possible, 
# but serializer needs instance to know it's update)
try:
    instance = Insumo(codigo="OLD-CODE", nombre="Old Name", bodega=bodega)
    # We simulate an update by passing instance
    update_data = {"codigo": "NEW-CODE", "nombre": "New Name"}
    
    ser_update = InsumoSerializer(instance, data=update_data, partial=True)
    if not ser_update.is_valid():
        print(f"SUCCESS: Update failed as expected: {ser_update.errors}")
        if "codigo" in ser_update.errors and "No se puede modificar" in str(ser_update.errors["codigo"][0]):
            print("SUCCESS: Correct immutability error message found.")
    else:
        print("FAILURE: Update PASSED validation unexpectedly (Code change allowed).")

except Exception as e:
    print(f"ERROR during Test 3: {e}")
