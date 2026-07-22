from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
import logging

from app.seguimiento.websocket_manager import manager
from app.seguimiento.schemas import SeguimientoMessage
from app.seguimiento.service import registrar_actualizacion_tecnico
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

router = APIRouter()

@router.websocket("/ws/{incidente_id}")
async def websocket_endpoint(websocket: WebSocket, incidente_id: int):
    await manager.connect(incidente_id, websocket)
    logger.info(f"WebSocket conectado: Incidente #{incidente_id}")
    try:
        while True:
            # Esperar mensajes JSON
            data = await websocket.receive_json()
            logger.info(f"WebSocket recibió datos para incidente #{incidente_id}: {data}")
            
            try:
                # Validar con Pydantic
                msg = SeguimientoMessage.model_validate(data)
                
                # Actualizar base de datos de manera segura y asíncrona
                async with AsyncSessionLocal() as db:
                    await registrar_actualizacion_tecnico(
                        db=db,
                        incidente_id=msg.incidente_id,
                        tecnico_id=msg.tecnico_id,
                        latitud=msg.latitud,
                        longitud=msg.longitud,
                        estado_ui=msg.estado,
                        eta_minutos=msg.eta_minutos
                    )
                
                # Broadcast del mensaje validado
                await manager.broadcast(incidente_id, msg.model_dump())
                
            except ValidationError as val_err:
                logger.warning(f"Error de validación Pydantic en mensaje recibido: {val_err.errors()}")
                # Enviar mensaje de error de validación al remitente (opcional, pero no rompe la conexión)
                await websocket.send_json({"error": "Formato de mensaje inválido", "details": val_err.errors()})
            except Exception as e:
                logger.error(f"Error procesando mensaje de seguimiento: {e}")
                
    except WebSocketDisconnect:
        manager.disconnect(incidente_id, websocket)
        logger.info(f"WebSocket desconectado: Incidente #{incidente_id}")
    except Exception as exc:
        manager.disconnect(incidente_id, websocket)
        logger.error(f"Error inesperado en WebSocket del incidente #{incidente_id}: {exc}")
