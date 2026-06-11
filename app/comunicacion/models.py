from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from app.db.base import Base


class Mensaje(Base):
    __tablename__ = "mensajes"

    id            = Column(Integer, primary_key=True, index=True)
    asignacion_id = Column(Integer, ForeignKey("asignaciones.id"), nullable=False)
    usuario_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    contenido     = Column(String(2000), nullable=False)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())


class DeviceToken(Base):
    __tablename__ = "device_tokens"

    id         = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token      = Column(String(500), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Notificacion(Base):
    __tablename__ = "notificaciones"

    id           = Column(Integer, primary_key=True, index=True)
    user_id      = Column(Integer, ForeignKey("users.id"), nullable=False)
    incidente_id = Column(Integer, ForeignKey("incidentes.id"), nullable=True)
    titulo       = Column(String(255), nullable=False)
    mensaje      = Column(String(1000), nullable=False)
    tipo         = Column(String(50), nullable=True)
    leida        = Column(Boolean, default=False)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())


