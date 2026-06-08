from pydantic import BaseModel
from typing import Optional

class SeguimientoMessage(BaseModel):
    tipo: str
    incidente_id: int
    tecnico_id: int
    latitud: float
    longitud: float
    estado: str
    eta_minutos: Optional[int] = None
