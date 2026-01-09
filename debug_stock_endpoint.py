
import requests
try:
    r = requests.get("http://localhost:8000/api/insumos/BTN-001/stock_por_bodega/", timeout=5)
    print("Status:", r.status_code)
    print("Body:", r.text)
except Exception as e:
    print("Error:", e)
