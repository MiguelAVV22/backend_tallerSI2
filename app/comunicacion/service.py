from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import undefer
from sqlalchemy.ext.asyncio import AsyncSession

from app.acceso_registro.models import Taller, User
from app.comunicacion.models import Mensaje, DeviceToken
from app.comunicacion.schemas import (
    MensajeCreate, MensajeResponse,
    UbicacionTecnicoResponse, UbicacionTecnicoUpdate,
)
from app.emergencias.models import Incidente
from app.talleres_tecnicos.models import Asignacion, Tecnico


# ── CU17 · Ubicación ──────────────────────────────────────────

async def actualizar_ubicacion_tecnico(
    user_id: int, data: UbicacionTecnicoUpdate, db: AsyncSession
) -> dict:
    result = await db.execute(
        select(Tecnico).where(Tecnico.usuario_id == user_id, Tecnico.activo.is_(True))
    )
    tecnico = result.scalar_one_or_none()
    if not tecnico:
        raise HTTPException(status_code=404, detail="Técnico no encontrado")

    tecnico.latitud = data.latitud
    tecnico.longitud = data.longitud
    tecnico.ultima_actualizacion = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True}


async def obtener_ubicacion_tecnico(
    asignacion_id: int, usuario_id: int, db: AsyncSession
) -> UbicacionTecnicoResponse:
    result = await db.execute(
        select(Asignacion).where(Asignacion.id == asignacion_id)
    )
    asignacion = result.scalar_one_or_none()
    if not asignacion:
        raise HTTPException(status_code=404, detail="Asignación no encontrada")

    res_inc = await db.execute(
        select(Incidente).where(
            Incidente.id == asignacion.incidente_id,
            Incidente.usuario_id == usuario_id,
        )
    )
    if not res_inc.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="No tienes permiso para ver esta asignación")

    if not asignacion.tecnico_id:
        raise HTTPException(status_code=404, detail="Aún no hay técnico asignado")

    res_tec = await db.execute(
        select(Tecnico)
        .options(
            undefer(Tecnico.latitud),
            undefer(Tecnico.longitud),
            undefer(Tecnico.ultima_actualizacion),
        )
        .where(Tecnico.id == asignacion.tecnico_id)
    )
    tecnico = res_tec.scalar_one_or_none()
    if not tecnico:
        raise HTTPException(status_code=404, detail="Técnico no encontrado")

    return UbicacionTecnicoResponse(
        tecnico_id=tecnico.id,
        nombre=tecnico.nombre,
        latitud=tecnico.latitud,
        longitud=tecnico.longitud,
        ultima_actualizacion=tecnico.ultima_actualizacion,
        estado_asignacion=asignacion.estado,
        eta=asignacion.eta,
    )


# ── CU18 · Chat ───────────────────────────────────────────────

async def _verificar_acceso_chat(
    user_id: int, role: str, asignacion: Asignacion, db: AsyncSession
) -> None:
    if role == "taller":
        res = await db.execute(select(Taller).where(Taller.usuario_id == user_id))
        taller = res.scalar_one_or_none()
        if not taller or asignacion.taller_id != taller.id:
            raise HTTPException(status_code=403, detail="No tienes acceso a esta conversación")
    elif role == "cliente":
        res = await db.execute(
            select(Incidente).where(
                Incidente.id == asignacion.incidente_id,
                Incidente.usuario_id == user_id,
            )
        )
        if not res.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="No tienes acceso a esta conversación")
    elif role == "tecnico":
        res = await db.execute(
            select(Tecnico).where(Tecnico.usuario_id == user_id, Tecnico.activo.is_(True))
        )
        tecnico = res.scalar_one_or_none()
        if not tecnico or asignacion.tecnico_id != tecnico.id:
            raise HTTPException(status_code=403, detail="No tienes acceso a esta conversación")
    else:
        raise HTTPException(status_code=403, detail="Acceso denegado")


async def enviar_mensaje(
    user_id: int, role: str, data: MensajeCreate, db: AsyncSession
) -> MensajeResponse:
    res_asig = await db.execute(
        select(Asignacion).where(Asignacion.id == data.asignacion_id)
    )
    asignacion = res_asig.scalar_one_or_none()
    if not asignacion:
        raise HTTPException(status_code=404, detail="Asignación no encontrada")

    await _verificar_acceso_chat(user_id, role, asignacion, db)

    mensaje = Mensaje(
        asignacion_id=data.asignacion_id,
        usuario_id=user_id,
        contenido=data.contenido,
    )
    db.add(mensaje)
    await db.commit()
    await db.refresh(mensaje)

    res_u = await db.execute(select(User).where(User.id == user_id))
    user = res_u.scalar_one()

    # Enviar notificación push al destinatario del mensaje en segundo plano
    try:
        destinatario_id = None
        if role == "cliente":
            if asignacion.tecnico_id:
                res_t = await db.execute(
                    select(Tecnico).where(Tecnico.id == asignacion.tecnico_id)
                )
                tecnico = res_t.scalar_one_or_none()
                if tecnico:
                    destinatario_id = tecnico.usuario_id
        else:
            res_i = await db.execute(
                select(Incidente).where(Incidente.id == asignacion.incidente_id)
            )
            incidente = res_i.scalar_one_or_none()
            if incidente:
                destinatario_id = incidente.usuario_id

        if destinatario_id:
            from app.comunicacion.push_service import enviar_notificacion_push
            remitente_nombre = user.full_name or user.username
            await enviar_notificacion_push(
                usuario_id=destinatario_id,
                titulo=f"Chat: {remitente_nombre}",
                cuerpo=mensaje.contenido,
                data={
                    "screen": "/comunicacion/chat",
                    "asignacion_id": str(asignacion.id),
                    "nombreContacto": remitente_nombre,
                },
                db=db
            )
    except Exception as e:
        print(f"[PushService] Error al disparar push del chat: {e}")

    return MensajeResponse(
        id=mensaje.id,
        asignacion_id=mensaje.asignacion_id,
        usuario_id=mensaje.usuario_id,
        remitente=user.full_name or user.username,
        rol=user.role,
        contenido=mensaje.contenido,
        created_at=mensaje.created_at,
    )


async def listar_mensajes(
    asignacion_id: int, user_id: int, role: str, db: AsyncSession
) -> list[MensajeResponse]:
    res_asig = await db.execute(
        select(Asignacion).where(Asignacion.id == asignacion_id)
    )
    asignacion = res_asig.scalar_one_or_none()
    if not asignacion:
        raise HTTPException(status_code=404, detail="Asignación no encontrada")

    await _verificar_acceso_chat(user_id, role, asignacion, db)

    result = await db.execute(
        select(Mensaje, User)
        .join(User, Mensaje.usuario_id == User.id)
        .where(Mensaje.asignacion_id == asignacion_id)
        .order_by(Mensaje.created_at)
    )
    return [
        MensajeResponse(
            id=m.id,
            asignacion_id=m.asignacion_id,
            usuario_id=m.usuario_id,
            remitente=u.full_name or u.username,
            rol=u.role,
            contenido=m.contenido,
            created_at=m.created_at,
        )
        for m, u in result.all()
    ]


async def registrar_token_fcm(user_id: int, token: str, db: AsyncSession) -> dict:
    result = await db.execute(
        select(DeviceToken).where(DeviceToken.token == token)
    )
    db_token = result.scalar_one_or_none()
    
    if db_token:
        if db_token.usuario_id != user_id:
            db_token.usuario_id = user_id
            await db.commit()
    else:
        new_token = DeviceToken(usuario_id=user_id, token=token)
        db.add(new_token)
        await db.commit()
        
    return {"ok": True}


async def eliminar_token_fcm(user_id: int, token: str, db: AsyncSession) -> dict:
    result = await db.execute(
        select(DeviceToken).where(DeviceToken.usuario_id == user_id, DeviceToken.token == token)
    )
    db_token = result.scalar_one_or_none()
    if db_token:
        await db.delete(db_token)
        await db.commit()
    return {"ok": True}

