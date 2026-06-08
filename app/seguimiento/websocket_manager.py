from typing import Dict, List
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        # Mapea incidente_id -> lista de conexiones WebSocket activas
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, incidente_id: int, websocket: WebSocket):
        await websocket.accept()
        if incidente_id not in self.active_connections:
            self.active_connections[incidente_id] = []
        self.active_connections[incidente_id].append(websocket)

    def disconnect(self, incidente_id: int, websocket: WebSocket):
        if incidente_id in self.active_connections:
            if websocket in self.active_connections[incidente_id]:
                self.active_connections[incidente_id].remove(websocket)
            if not self.active_connections[incidente_id]:
                del self.active_connections[incidente_id]

    async def broadcast(self, incidente_id: int, message: dict):
        if incidente_id in self.active_connections:
            for connection in self.active_connections[incidente_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    # Si falla el envío (conexión rota no detectada), se puede manejar aquí
                    pass

manager = ConnectionManager()
