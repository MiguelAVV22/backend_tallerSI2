from types import SimpleNamespace
from typing import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.acceso_registro.models import User
from app.db.session import get_db

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Carga el usuario completo desde la BD. Usar solo cuando se necesitan
    atributos adicionales (email, full_name, etc.)."""
    try:
        payload = decode_token(credentials.credentials)
        user_id: str = payload.get("sub")
        if user_id is None:
            raise ValueError
    except (JWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no encontrado")

    return user


async def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado. Se requiere rol: admin",
        )
    return current_user


def require_role(*roles: str) -> Callable:
    """Lee id, role y tenant_id del JWT. Si el rol del token no coincide (ej. recién promovido),
    verifica el rol actualizado en la base de datos."""
    async def checker(
        credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
        db: AsyncSession = Depends(get_db),
    ) -> SimpleNamespace:
        try:
            payload = decode_token(credentials.credentials)
            user_id: str | None = payload.get("sub")
            role: str | None = payload.get("role")
            tenant_id: int | None = payload.get("tenant_id")
            if not user_id or not role:
                raise ValueError("Token sin sub/role — inicia sesión de nuevo")
        except (JWTError, ValueError) as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token inválido o expirado",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if role not in roles:
            result = await db.execute(select(User).where(User.id == int(user_id)))
            db_user = result.scalar_one_or_none()
            if db_user and db_user.role in roles:
                role = db_user.role
                tenant_id = db_user.tenant_id

        if role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Acceso denegado. Se requiere rol: {' o '.join(roles)}",
            )

        t_id = int(tenant_id) if tenant_id is not None else 1
        return SimpleNamespace(id=int(user_id), role=role, tenant_id=t_id)
    return checker
