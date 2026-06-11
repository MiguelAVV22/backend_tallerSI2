from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional


# ── CU17 · Ubicación ──────────────────────────────────────────

class UbicacionTecnicoUpdate(BaseModel):
    latitud: float
    longitud: float

    @field_validator("latitud")
    @classmethod
    def lat_valida(cls, v: float) -> float:
        if not (-90 <= v <= 90):
            raise ValueError("Latitud debe estar entre -90 y 90")
        return v

    @field_validator("longitud")
    @classmethod
    def lon_valida(cls, v: float) -> float:
        if not (-180 <= v <= 180):
            raise ValueError("Longitud debe estar entre -180 y 180")
        return v


class UbicacionTecnicoResponse(BaseModel):
    tecnico_id: int
    nombre: str
    latitud: Optional[float]
    longitud: Optional[float]
    ultima_actualizacion: Optional[datetime]
    estado_asignacion: str
    eta: Optional[int]

    model_config = {"from_attributes": True}


# ── CU18 · Mensajes de chat ───────────────────────────────────

class MensajeCreate(BaseModel):
    asignacion_id: int
    contenido: str

    @field_validator("contenido")
    @classmethod
    def contenido_valido(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("El mensaje no puede estar vacío")
        if len(v) > 2000:
            raise ValueError("El mensaje no puede superar 2000 caracteres")
        return v.strip()


class MensajeResponse(BaseModel):
    id: int
    asignacion_id: int
    usuario_id: int
    remitente: str
    rol: str
    contenido: str
    created_at: datetime


class TokenRegister(BaseModel):
    token: str


class NotificacionResponse(BaseModel):
    id: int
    user_id: int
    incidente_id: Optional[int] = None
    titulo: str
    mensaje: str
    tipo: Optional[str] = None
    leida: bool
    created_at: datetime

    model_config = {"from_attributes": True}


