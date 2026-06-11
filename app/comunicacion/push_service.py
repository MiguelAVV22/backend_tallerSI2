import firebase_admin
from firebase_admin import messaging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.comunicacion.models import DeviceToken
import logging

logger = logging.getLogger(__name__)

async def enviar_notificacion_push(
    usuario_id: int,
    titulo: str,
    cuerpo: str,
    data: dict = None,
    db: AsyncSession = None
) -> None:
    if db is None:
        logger.error("[PushService] Se requiere una sesión de base de datos activa.")
        return

    # Guardar en la base de datos para la bandeja de entrada
    try:
        from app.comunicacion.models import Notificacion
        payload = data or {}
        tipo = payload.get("screen", "general")
        if "/chat" in tipo:
            tipo = "chat"
        elif "seguimiento" in tipo:
            tipo = "estado"

        new_notif = Notificacion(
            user_id=usuario_id,
            incidente_id=int(payload["incidente_id"]) if "incidente_id" in payload and payload["incidente_id"] else None,
            titulo=titulo,
            mensaje=cuerpo,
            tipo=tipo,
            leida=False
        )
        db.add(new_notif)
        await db.commit()
        logger.info(f"[PushService] Notificación guardada en DB para el usuario {usuario_id}.")
    except Exception as db_err:
        logger.error(f"[PushService] Error al guardar notificación en DB: {db_err}")

    # Buscar los tokens registrados para el usuario
    result = await db.execute(
        select(DeviceToken).where(DeviceToken.usuario_id == usuario_id)
    )
    tokens_db = result.scalars().all()
    if not tokens_db:
        logger.info(f"[PushService] El usuario {usuario_id} no tiene tokens de dispositivo registrados.")
        return

    tokens = [t.token for t in tokens_db]
    logger.info(f"[PushService] Enviando push a {len(tokens)} dispositivo(s) del usuario {usuario_id}...")

    # Crear el mensaje multicast
    payload = data or {}
    # Convertir todos los valores a string para cumplir con el protocolo de FCM data payload
    string_payload = {k: str(v) for k, v in payload.items()}

    message = messaging.MulticastMessage(
        notification=messaging.Notification(
            title=titulo,
            body=cuerpo,
        ),
        data=string_payload,
        tokens=tokens,
    )

    try:
        # Enviar de forma síncrona usando la API moderna
        response = messaging.send_each_for_multicast(message)
        logger.info(f"[PushService] Notificación enviada. Éxitos: {response.success_count}, Fallos: {response.failure_count}")

        # Limpiar tokens inválidos o no registrados
        if response.failure_count > 0:
            deleted_any = False
            for idx, resp in enumerate(response.responses):
                if not resp.success:
                    error_type = type(resp.exception).__name__
                    logger.info(f"[PushService] Fallo en el token {tokens[idx]}: {error_type}")
                    if "Unregistered" in error_type or "Invalid" in error_type:
                        token_to_remove = tokens_db[idx]
                        await db.delete(token_to_remove)
                        deleted_any = True
            if deleted_any:
                await db.commit()

    except Exception as e:
        logger.error(f"[PushService] Error al enviar notificación push: {e}")
