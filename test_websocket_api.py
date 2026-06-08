import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from app.main import app
from app.db.session import AsyncSessionLocal
from sqlalchemy import text
import asyncio

def test_websocket():
    # Asegurarse de que el loop de asyncio esté listo para consultas de SQLAlchemy
    # que se ejecutan dentro del endpoint del WebSocket
    client = TestClient(app)
    
    print("Iniciando conexión WebSocket de prueba...")
    with client.websocket_connect("/ws/seguimiento/1") as websocket:
        payload = {
            "tipo": "ubicacion_tecnico",
            "incidente_id": 1,
            "tecnico_id": 5,
            "latitud": -17.7833,
            "longitud": -63.1821,
            "estado": "EN_CAMINO",
            "eta_minutos": 12
        }
        
        print("Enviando coordenadas del técnico...")
        websocket.send_json(payload)
        
        print("Esperando broadcast de vuelta...")
        data = websocket.receive_json()
        print("Mensaje de broadcast recibido:", data)
        
        # Aserciones
        assert data["tipo"] == "ubicacion_tecnico"
        assert data["incidente_id"] == 1
        assert data["tecnico_id"] == 5
        assert data["latitud"] == -17.7833
        assert data["longitud"] == -63.1821
        assert data["estado"] == "EN_CAMINO"
        assert data["eta_minutos"] == 12
        print("\n¡Prueba unitaria de WebSocket completada exitosamente!")

async def verificar_cambios_db():
    print("\nVerificando cambios en la base de datos...")
    from app.db.session import engine
    await engine.dispose()
    async with AsyncSessionLocal() as db:
        # Verificar que el técnico 5 (que en el seed es Pedro Huanca, id del técnico en BD es 2?)
        # Nota: El payload usó tecnico_id = 5. Vamos a consultar el técnico con id 5 en la BD.
        res_tec = await db.execute(text("SELECT id, latitud, longitud FROM tecnicos WHERE id = 5"))
        tec = res_tec.one_or_none()
        print(f"Técnico ID 5 en la BD: {tec}")
        
        # Verificar la asignación correspondiente
        res_asig = await db.execute(text("SELECT id, incidente_id, tecnico_id, estado, eta FROM asignaciones WHERE incidente_id = 1"))
        asig = res_asig.one_or_none()
        print(f"Asignación asociada al incidente 1: {asig}")

if __name__ == "__main__":
    # Ejecutar la prueba del websocket
    test_websocket()
    
    # Consultar los cambios guardados en la BD
    asyncio.run(verificar_cambios_db())
