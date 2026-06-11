from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.acceso_registro.models import User
from app.comunicacion import schemas, service
from app.core.dependencies import get_current_user, require_role
from app.db.session import get_db

router = APIRouter()


# ── CU17 · Ver técnico en mapa ────────────────────────────────

# Técnico: envía su posición GPS cada ~5 s
@router.patch("/tecnicos/mi-ubicacion", status_code=status.HTTP_200_OK)
async def actualizar_mi_ubicacion(
    data: schemas.UbicacionTecnicoUpdate,
    current_user: User = Depends(require_role("tecnico")),
    db: AsyncSession = Depends(get_db),
):
    return await service.actualizar_ubicacion_tecnico(current_user.id, data, db)


# Cliente: consulta la posición actual del técnico asignado a su incidente
@router.get(
    "/asignaciones/{asignacion_id}/tecnico-ubicacion",
    response_model=schemas.UbicacionTecnicoResponse,
)
async def tecnico_ubicacion(
    asignacion_id: int,
    current_user: User = Depends(require_role("cliente")),
    db: AsyncSession = Depends(get_db),
):
    return await service.obtener_ubicacion_tecnico(asignacion_id, current_user.id, db)


# ── CU18 · Chat en tiempo real ────────────────────────────────

@router.post(
    "/mensajes",
    response_model=schemas.MensajeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def enviar_mensaje(
    data: schemas.MensajeCreate,
    current_user: User = Depends(require_role("taller", "cliente", "tecnico")),
    db: AsyncSession = Depends(get_db),
):
    return await service.enviar_mensaje(current_user.id, current_user.role, data, db)


@router.get(
    "/asignaciones/{asignacion_id}/mensajes",
    response_model=list[schemas.MensajeResponse],
)
async def listar_mensajes(
    asignacion_id: int,
    current_user: User = Depends(require_role("taller", "cliente", "tecnico")),
    db: AsyncSession = Depends(get_db),
):
    return await service.listar_mensajes(asignacion_id, current_user.id, current_user.role, db)


# ── CU22 · Recibir notificaciones ──────────────────────
@router.get("/notificaciones", response_model=list[schemas.NotificacionResponse])
async def listar_notificaciones(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.comunicacion.models import Notificacion
    from sqlalchemy import select
    result = await db.execute(
        select(Notificacion)
        .where(Notificacion.user_id == current_user.id)
        .order_by(Notificacion.created_at.desc())
    )
    return result.scalars().all()


@router.patch("/notificaciones/{id}/leida")
async def marcar_notificacion_leida(
    id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.comunicacion.models import Notificacion
    from fastapi import HTTPException
    from sqlalchemy import select
    result = await db.execute(
        select(Notificacion).where(Notificacion.id == id, Notificacion.user_id == current_user.id)
    )
    notif = result.scalar_one_or_none()
    if not notif:
        raise HTTPException(status_code=404, detail="Notificación no encontrada")
    notif.leida = True
    await db.commit()
    return {"id": id, "leida": True}



@router.post("/notificaciones/token", status_code=status.HTTP_200_OK)
async def registrar_token(
    data: schemas.TokenRegister,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.registrar_token_fcm(current_user.id, data.token, db)


@router.delete("/notificaciones/token", status_code=status.HTTP_200_OK)
async def eliminar_token(
    data: schemas.TokenRegister,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.eliminar_token_fcm(current_user.id, data.token, db)

