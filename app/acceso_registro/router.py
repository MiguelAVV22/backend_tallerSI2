import math
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.acceso_registro import schemas, service
from app.acceso_registro.schemas import UserResponse, VehiculoResponse, TallerResponse, UserListResponse
from app.core.dependencies import get_current_user, require_role, get_current_admin
from app.acceso_registro.models import User

router = APIRouter()


# ── CU01 - Registrarse ─────────────────────────────────────
@router.post("/register", response_model=schemas.Token, status_code=status.HTTP_201_CREATED)
async def register(data: schemas.UserCreate, request: Request, db: AsyncSession = Depends(get_db)):
    token, user = await service.registrar_usuario(data, db)
    from app.reportes.service import log_evento
    await log_evento(db, accion="register", usuario_id=user.id,
                     usuario_nombre=user.username, entidad="User", entidad_id=user.id,
                     ip=request.client.host if request.client else None)
    return schemas.Token(access_token=token, user=UserResponse.model_validate(user))


# ── CU02 - Iniciar sesión ──────────────────────────────────
@router.post("/login", response_model=schemas.Token)
async def login(data: schemas.UserLogin, request: Request, db: AsyncSession = Depends(get_db)):
    token, user = await service.iniciar_sesion(data, db)
    from app.reportes.service import log_evento
    await log_evento(db, accion="login", usuario_id=user.id,
                     usuario_nombre=user.username, entidad="User", entidad_id=user.id,
                     ip=request.client.host if request.client else None)
    return schemas.Token(access_token=token, user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)


@router.post("/change-password", status_code=status.HTTP_200_OK)
async def change_password(
    data: schemas.ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await service.cambiar_contrasena(current_user, data.current_password, data.new_password, db)
    return {"msg": "Contraseña actualizada correctamente"}


@router.post("/request-reset", status_code=status.HTTP_200_OK)
async def request_reset(
    data: schemas.RequestResetRequest,
    db: AsyncSession = Depends(get_db),
):
    await service.solicitar_reset_contrasena(data.email, db)
    return {"msg": "Código enviado al correo registrado"}


@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(
    data: schemas.ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    await service.resetear_contrasena(data.email, data.code, data.new_password, db)
    return {"msg": "Contraseña restablecida correctamente"}


# ── CU03 - Registrar vehículo ──────────────────────────────
@router.post("/vehiculos", response_model=VehiculoResponse, status_code=status.HTTP_201_CREATED)
async def registrar_vehiculo(
    data: schemas.VehiculoCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    vehiculo = await service.crear_vehiculo(data, current_user, db)
    return VehiculoResponse.model_validate(vehiculo)


# ── CU04 - Listar vehículos ────────────────────────────────
@router.get("/vehiculos", response_model=list[VehiculoResponse])
async def listar_vehiculos(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    vehiculos = await service.listar_vehiculos_usuario(current_user.id, db)
    return [VehiculoResponse.model_validate(v) for v in vehiculos]


@router.delete("/vehiculos/{vehiculo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_vehiculo(
    vehiculo_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await service.eliminar_vehiculo(vehiculo_id, current_user.id, db)


# ── CU12 - Registrar taller ────────────────────────────────
@router.post("/talleres", response_model=TallerResponse, status_code=status.HTTP_201_CREATED)
async def registrar_taller(
    data: schemas.TallerCreate,
    current_user: User = Depends(require_role("cliente", "taller")),
    db: AsyncSession = Depends(get_db),
):
    taller = await service.crear_taller(data, current_user, db)
    return TallerResponse.model_validate(taller)


# ── CU27 - Listar usuarios (admin) ────────────────────────
@router.get("/usuarios", response_model=UserListResponse)
async def listar_usuarios(
    role: Optional[str] = Query(None),
    activo: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    usuarios, total = await service.listar_usuarios(db, role, activo, search, page, size)
    pages = math.ceil(total / size) if total > 0 else 1
    return UserListResponse(
        items=[UserResponse.model_validate(u) for u in usuarios],
        total=total, page=page, size=size, pages=pages,
    )


@router.get("/usuarios/{user_id}", response_model=UserResponse)
async def obtener_usuario(
    user_id: int,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await service.obtener_usuario(user_id, db)
    return UserResponse.model_validate(user)


@router.patch("/usuarios/{user_id}", response_model=UserResponse)
async def actualizar_usuario(
    user_id: int,
    data: schemas.UserUpdate,
    request: Request,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    before = await service.obtener_usuario(user_id, db)
    before_data = {"email": before.email, "full_name": before.full_name,
                   "telefono": before.telefono, "role": before.role}
    user = await service.actualizar_usuario(user_id, data, current_user.id, db)
    from app.reportes.service import log_evento
    await log_evento(db, accion="update_user", usuario_id=current_user.id,
                     usuario_nombre=current_user.username, entidad="User", entidad_id=user_id,
                     detalle={"antes": before_data, "despues": data.model_dump(exclude_none=True)},
                     ip=request.client.host if request.client else None)
    return UserResponse.model_validate(user)


@router.patch("/usuarios/{user_id}/activar", response_model=UserResponse)
async def activar_usuario(
    user_id: int,
    request: Request,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await service.toggle_usuario_activo(user_id, True, current_user.id, db)
    from app.reportes.service import log_evento
    await log_evento(db, accion="activate_user", usuario_id=current_user.id,
                     usuario_nombre=current_user.username, entidad="User", entidad_id=user_id,
                     ip=request.client.host if request.client else None)
    return UserResponse.model_validate(user)


@router.patch("/usuarios/{user_id}/desactivar", response_model=UserResponse)
async def desactivar_usuario(
    user_id: int,
    request: Request,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await service.toggle_usuario_activo(user_id, False, current_user.id, db)
    from app.reportes.service import log_evento
    await log_evento(db, accion="deactivate_user", usuario_id=current_user.id,
                     usuario_nombre=current_user.username, entidad="User", entidad_id=user_id,
                     ip=request.client.host if request.client else None)
    return UserResponse.model_validate(user)


# ── CU34 - Aprobar / rechazar taller ──────────────────────
@router.get("/talleres", response_model=list[TallerResponse])
async def listar_talleres(
    estado: Optional[str] = None,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    talleres = await service.listar_talleres(estado, db)
    return [TallerResponse.model_validate(t) for t in talleres]


@router.patch("/talleres/{taller_id}/aprobar", response_model=TallerResponse)
async def aprobar_taller(
    taller_id: int,
    request: Request,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    taller = await service.cambiar_estado_taller(taller_id, "aprobado", db)
    from app.reportes.service import log_evento
    await log_evento(db, accion="approve_taller", usuario_id=current_user.id,
                     usuario_nombre=current_user.username, entidad="Taller", entidad_id=taller_id,
                     ip=request.client.host if request.client else None)
    return TallerResponse.model_validate(taller)


@router.patch("/talleres/{taller_id}/rechazar", response_model=TallerResponse)
async def rechazar_taller(
    taller_id: int,
    request: Request,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    taller = await service.cambiar_estado_taller(taller_id, "rechazado", db)
    from app.reportes.service import log_evento
    await log_evento(db, accion="reject_taller", usuario_id=current_user.id,
                     usuario_nombre=current_user.username, entidad="Taller", entidad_id=taller_id,
                     ip=request.client.host if request.client else None)
    return TallerResponse.model_validate(taller)
