import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.db.session import engine, AsyncSessionLocal
from app.db.base import Base

# Importar todos los modelos para que SQLAlchemy los registre antes de create_all
import app.acceso_registro.models    # noqa: F401  (User, Vehiculo, Taller, PasswordResetCode)
import app.emergencias.models        # noqa: F401  (Incidente, Evidencia)
import app.talleres_tecnicos.models  # noqa: F401  (Tecnico, Asignacion)
import app.cotizacion_pagos.models   # noqa: F401  (Cotizacion, Pago)
import app.comunicacion.models       # noqa: F401  (Mensaje)
import app.reportes.models           # noqa: F401  (BitacoraEvento)

from app.acceso_registro.router  import router as acceso_router
from app.talleres_tecnicos.router import router as talleres_router
from app.emergencias.router      import router as emergencias_router
from app.solicitudes.router      import router as solicitudes_router
from app.cotizacion_pagos.router import router as pagos_router
from app.comunicacion.router     import router as comunicacion_router
from app.reportes.router         import router as reportes_router
from app.ia.router               import router as ia_router
from app.seguimiento.router      import router as seguimiento_router
from app.metricas.router         import router as metricas_router



@asynccontextmanager
async def lifespan(app: FastAPI):
    # Directorios de uploads para §4.4
    os.makedirs("uploads/fotos", exist_ok=True)
    os.makedirs("uploads/audio", exist_ok=True)

    # Crear / migrar tablas
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Columnas deferred de Tecnico (añadidas después del create_all inicial)
        await conn.execute(text(
            "ALTER TABLE tecnicos ADD COLUMN IF NOT EXISTS latitud DOUBLE PRECISION"
        ))
        await conn.execute(text(
            "ALTER TABLE tecnicos ADD COLUMN IF NOT EXISTS longitud DOUBLE PRECISION"
        ))
        await conn.execute(text(
            "ALTER TABLE tecnicos ADD COLUMN IF NOT EXISTS ultima_actualizacion TIMESTAMP WITH TIME ZONE"
        ))

        # §4.5 – Columna tipo_incidente en incidentes (clasificación IA)
        await conn.execute(text(
            "ALTER TABLE incidentes ADD COLUMN IF NOT EXISTS tipo_incidente VARCHAR(50)"
        ))

    # Pool warm-up
    async with AsyncSessionLocal() as session:
        await session.execute(text("SELECT 1"))

    # §4.5 – Inicializar modelos IA en startup
    from app.ia import clasificador
    clasificador.inicializar()

    yield


app = FastAPI(title="Taller Backend", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Servir archivos estáticos de evidencias (§4.4)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

app.include_router(acceso_router,       prefix="/api/acceso",       tags=["Acceso y Registro"])
app.include_router(talleres_router,     prefix="/api/talleres",     tags=["Talleres y Técnicos"])
app.include_router(emergencias_router,  prefix="/api/emergencias",  tags=["Emergencias"])
app.include_router(solicitudes_router,  prefix="/api/solicitudes",  tags=["Solicitudes"])
app.include_router(pagos_router,        prefix="/api/pagos",        tags=["Cotización y Pagos"])
app.include_router(comunicacion_router, prefix="/api/comunicacion", tags=["Comunicación"])
app.include_router(reportes_router,     prefix="/api/reportes",     tags=["Reportes"])
app.include_router(ia_router,           prefix="/api/ia",           tags=["Inteligencia Artificial"])
app.include_router(seguimiento_router,  prefix="/ws",               tags=["Seguimiento en Tiempo Real"])
app.include_router(metricas_router,     prefix="/api/metricas",     tags=["Métricas y Dashboard"])



@app.get("/")
async def root():
    return {"message": "Taller Backend v2.0 — IA activa"}

# reload trigger 1

