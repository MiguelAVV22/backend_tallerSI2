from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional


class TecnicoCreate(BaseModel):
    nombre: str
    especialidad: str
    telefono: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None

    @field_validator("nombre")
    @classmethod
    def nombre_valido(cls, v: str) -> str:
        if len(v.strip()) < 2:
            raise ValueError("El nombre debe tener al menos 2 caracteres")
        return v.strip()

    @field_validator("especialidad")
    @classmethod
    def especialidad_valida(cls, v: str) -> str:
        if len(v.strip()) < 2:
            raise ValueError("La especialidad debe tener al menos 2 caracteres")
        return v.strip()


class TecnicoUpdate(BaseModel):
    nombre: Optional[str] = None
    especialidad: Optional[str] = None
    telefono: Optional[str] = None
    estado: Optional[str] = None


class TecnicoResponse(BaseModel):
    id: int
    taller_id: int
    nombre: str
    especialidad: str
    telefono: Optional[str]
    estado: str
    activo: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AsignacionResponse(BaseModel):
    id: int
    incidente_id: int
    taller_id: int
    tecnico_id: Optional[int]
    unidad_auxilio_id: Optional[int] = None
    estado: str
    eta: Optional[int]
    observacion: Optional[str]
    created_at: datetime
    es_sos: bool = False
    incidente_latitud: Optional[float] = None
    incidente_longitud: Optional[float] = None

    model_config = {"from_attributes": True}


class AsignarTecnicoPayload(BaseModel):
    tecnico_id: int
    unidad_auxilio_id: Optional[int] = None


# ── CU15 · Estado del servicio ─────────────────────────────
TRANSICIONES_VALIDAS: dict[str, set[str]] = {
    "aceptado":      {"en_camino", "cancelado"},
    "en_camino":     {"en_sitio",  "cancelado"},
    "en_sitio":      {"en_reparacion"},
    "en_reparacion": {"finalizado"},
}


class AsignacionEstadoUpdate(BaseModel):
    estado: str
    observacion: Optional[str] = None

    @field_validator("estado")
    @classmethod
    def estado_valido(cls, v: str) -> str:
        validos = {"en_camino", "en_sitio", "en_reparacion", "finalizado", "cancelado"}
        if v not in validos:
            raise ValueError(f"Estado inválido: {v}")
        return v


# ── CU22 · Servicio Realizado ──────────────────────────────
class RepuestoItem(BaseModel):
    descripcion: str
    cantidad: int

    @field_validator("cantidad")
    @classmethod
    def cant_positiva(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("La cantidad debe ser mayor a 0")
        return v


class ServicioRealizadoCreate(BaseModel):
    asignacion_id: int
    descripcion_trabajo: str
    repuestos: Optional[list[RepuestoItem]] = None
    observaciones: Optional[str] = None

    @field_validator("descripcion_trabajo")
    @classmethod
    def desc_valida(cls, v: str) -> str:
        if len(v.strip()) < 5:
            raise ValueError("La descripción debe tener al menos 5 caracteres")
        return v.strip()


class ServicioRealizadoResponse(BaseModel):
    id: int
    asignacion_id: int
    descripcion_trabajo: str
    repuestos: Optional[str]
    observaciones: Optional[str]
    fecha_cierre: datetime

    model_config = {"from_attributes": True}


# ── CU16 · Disponibilidad & Ubicación ────────────────────────
class DisponibilidadUpdate(BaseModel):
    disponible: bool


class TallerUpdatePayload(BaseModel):
    nombre: Optional[str] = None
    direccion: Optional[str] = None
    telefono: Optional[str] = None
    email_comercial: Optional[str] = None
    latitud: Optional[float] = None
    longitud: Optional[float] = None


class TallerInfoResponse(BaseModel):
    id: int
    nombre: str
    direccion: str
    telefono: Optional[str]
    email_comercial: Optional[str]
    disponible: bool
    estado: str
    rating: float
    total_tecnicos: int
    tecnicos_disponibles: int
    tecnicos_ocupados: int
    latitud: Optional[float] = None
    longitud: Optional[float] = None

    model_config = {"from_attributes": True}


class UnidadAuxilioCreate(BaseModel):
    placa: str
    modelo: str
    tipo: str
    capacidad_carga_kg: int

    @field_validator("placa")
    @classmethod
    def placa_valida(cls, v: str) -> str:
        v = v.strip().upper()
        if len(v) < 5:
            raise ValueError("La placa debe tener al menos 5 caracteres")
        return v

    @field_validator("capacidad_carga_kg")
    @classmethod
    def cap_positiva(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("La capacidad debe ser mayor a 0 kg")
        return v


class UnidadAuxilioResponse(BaseModel):
    id: int
    taller_id: int
    placa: str
    modelo: str
    tipo: str
    capacidad_carga_kg: int
    estado: str
    activo: bool
    created_at: datetime

    model_config = {"from_attributes": True}
