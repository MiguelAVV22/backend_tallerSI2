import asyncio
import json
import sys

try:
    import websockets
except ImportError:
    print("El paquete 'websockets' no está instalado. Instálalo con: pip install websockets")
    sys.exit(1)

async def test_client():
    uri = "ws://127.0.0.1:8000/ws/seguimiento/3"
    print(f"Conectándose a {uri}...")
    
    try:
        async with websockets.connect(uri) as websocket:
            print("¡Conectado exitosamente!")
            
            payload = {
                "tipo": "ubicacion_tecnico",
                "incidente_id": 3,
                "tecnico_id": 1,
                "latitud": -17.7833,
                "longitud": -63.1821,
                "estado": "EN_CAMINO",
                "eta_minutos": 12
            }
            
            print(f"Enviando datos: {json.dumps(payload, indent=2)}")
            await websocket.send(json.dumps(payload))
            
            print("Esperando respuesta del servidor...")
            response = await websocket.recv()
            print(f"Recibido desde el servidor:\n{json.dumps(json.loads(response), indent=2)}")
            
    except Exception as e:
        print(f"Error en la conexión o comunicación: {e}")

if __name__ == "__main__":
    asyncio.run(test_client())
