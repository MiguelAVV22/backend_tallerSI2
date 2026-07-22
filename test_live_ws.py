import asyncio
import json
import websockets

async def test_client():
    uri = "wss://backend-tallersi2.onrender.com/api/seguimiento/ws/1"
    print(f"Conectándose a {uri}...")
    try:
        async with websockets.connect(uri) as websocket:
            print("¡Conectado exitosamente!")
            payload = {
                "tipo": "ubicacion_tecnico",
                "incidente_id": 1,
                "tecnico_id": 1,
                "latitud": -17.7833,
                "longitud": -63.1821,
                "estado": "EN_CAMINO",
                "eta_minutos": 12
            }
            await websocket.send(json.dumps(payload))
            print("Enviado. Esperando respuesta...")
            response = await websocket.recv()
            print(f"Recibido: {response}")
    except Exception as e:
        print(f"Error: {e}")

asyncio.run(test_client())
