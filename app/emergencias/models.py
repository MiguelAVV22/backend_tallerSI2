from sqlalchemy import Boolean, Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import deferred
from sqlalchemy.sql import func
from app.db.base import Base


class Incidente(Base):
    __tablename__ = "incidentes"

    id         = Column(Integer, primary_key=True, index=True)
    tenant_id  = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1, server_default="1")
    usuario_id = Column(Integer, ForeignKey("users.id"),    nullable=False)
    vehiculo_id= Column(Integer, ForeignKey("vehiculos.id"), nullable=False)
    latitud    = Column(Float,  nullable=True)
    longitud   = Column(Float,  nullable=True)
    descripcion= Column(String(1000), nullable=True)
    estado     = Column(String(20),   default="pendiente")  # pendiente|en_proceso|resuelto|cancelado
    prioridad  = Column(String(20),   default="media")      # alta|media|baja
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # Columna añadida vía ALTER TABLE en lifespan (§4.5 - clasificación IA automática)
    tipo_incidente = Column(String(50), nullable=True)


class Evidencia(Base):
    """§4.4 – Tabla de evidencias: fotos y audios de incidentes."""
    __tablename__ = "evidencias"

    id           = Column(Integer, primary_key=True, index=True)
    tenant_id    = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1, server_default="1")
    incidente_id = Column(Integer, ForeignKey("incidentes.id"), nullable=False, index=True)
    tipo         = Column(String(10), nullable=False)       # foto | audio
    ruta         = Column(String(500), nullable=False)      # path en servidor
    url          = Column(String(500), nullable=True)       # URL pública vía StaticFiles
    analisis_ia  = deferred(Column(Text, nullable=True))    # JSON del análisis IA
    transcripcion= deferred(Column(Text, nullable=True))    # Para audio: texto transcrito
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
