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



async def seed_initial_data(db: AsyncSession):
    from sqlalchemy import select
    from app.acceso_registro.models import User, Taller, Tenant
    from app.core.security import hash_password

    res = await db.execute(select(User).where(User.email == "admin@taller.com"))
    if res.scalar_one_or_none():
        return

    print("[Seed] Base de datos vacía detectada. Poblando usuarios iniciales de prueba...")

    res_t1 = await db.execute(select(Tenant).where(Tenant.id == 1))
    if not res_t1.scalar_one_or_none():
        db.add(Tenant(id=1, nombre="Red Auxilio Norte", slug="auxilio-norte", activo=True))

    res_t2 = await db.execute(select(Tenant).where(Tenant.id == 2))
    if not res_t2.scalar_one_or_none():
        db.add(Tenant(id=2, nombre="Red Mecánicos Express", slug="mecanicos-express", activo=True))

    await db.flush()

    pass_hash = hash_password("12345678")
    users_data = [
        {"email": "admin@taller.com",    "username": "admin",    "full_name": "Administrador",   "role": "admin",   "tenant_id": 1},
        {"email": "cliente@taller.com",  "username": "cliente",  "full_name": "Carlos Mendoza",  "role": "cliente", "tenant_id": 1},
        {"email": "taller@taller.com",   "username": "taller",   "full_name": "AutoFix Express", "role": "taller",  "tenant_id": 1},
        {"email": "taller2@taller.com",  "username": "taller2",  "full_name": "Mecánica Central","role": "taller",  "tenant_id": 2},
        {"email": "tecnico@taller.com",  "username": "tecnico",  "full_name": "Luis Vargas",     "role": "tecnico", "tenant_id": 1},
        {"email": "tecnico3@taller.com", "username": "tecnico3", "full_name": "Hugo Banzer",    "role": "tecnico", "tenant_id": 1},
    ]

    user_objs = {}
    for u in users_data:
        res_u = await db.execute(select(User).where(User.email == u["email"]))
        existing_user = res_u.scalar_one_or_none()
        if not existing_user:
            new_u = User(
                email=u["email"],
                username=u["username"],
                full_name=u["full_name"],
                hashed_password=pass_hash,
                role=u["role"],
                tenant_id=u["tenant_id"]
            )
            db.add(new_u)
            await db.flush()
            user_objs[u["username"]] = new_u
        else:
            user_objs[u["username"]] = existing_user

    await db.commit()

    if "taller" in user_objs:
        u_t1 = user_objs["taller"]
        res_tal1 = await db.execute(select(Taller).where(Taller.usuario_id == u_t1.id))
        if not res_tal1.scalar_one_or_none():
            db.add(Taller(usuario_id=u_t1.id, nombre="AutoFix Express", direccion="Av. 6 de Agosto #123, La Paz", telefono="71234567", email_comercial="contacto@autofix.bo", latitud=-16.5000, longitud=-68.1500, disponible=True, estado="aprobado", tenant_id=1))

    if "taller2" in user_objs:
        u_t2 = user_objs["taller2"]
        res_tal2 = await db.execute(select(Taller).where(Taller.usuario_id == u_t2.id))
        if not res_tal2.scalar_one_or_none():
            db.add(Taller(usuario_id=u_t2.id, nombre="Mecánica Central", direccion="Calle España #45, Santa Cruz", telefono="77654321", email_comercial="info@mecanicacentral.bo", latitud=-17.7833, longitud=-63.1821, disponible=True, estado="aprobado", tenant_id=2))

    await db.commit()
    print("[Seed] Base de datos poblada perfectamente.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Directorios de uploads para §4.4
    os.makedirs("uploads/fotos", exist_ok=True)
    os.makedirs("uploads/audio", exist_ok=True)

    # Crear / migrar tablas
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Asegurar que existe el Tenant por defecto (ID=1)
        await conn.execute(text(
            "INSERT INTO tenants (id, nombre, slug, activo, created_at) "
            "VALUES (1, 'Red Auxilio General', 'general', true, NOW()) "
            "ON CONFLICT (id) DO NOTHING"
        ))

        # Agregar tenant_id a las tablas operativas
        tablas = [
            "users", "vehiculos", "contactos_emergencia", "talleres", "tecnicos", 
            "asignaciones", "unidades_auxilio", "servicios_realizados", "incidentes", 
            "evidencias", "cotizaciones", "pagos"
        ]
        for t in tablas:
            await conn.execute(text(
                f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES tenants(id) DEFAULT 1"
            ))
            await conn.execute(text(
                f"ALTER TABLE {t} ALTER COLUMN tenant_id SET NOT NULL"
            ))

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

        # Nuevas columnas para vehículos (tipo y peso)
        await conn.execute(text(
            "ALTER TABLE vehiculos ADD COLUMN IF NOT EXISTS tipo VARCHAR(50)"
        ))
        await conn.execute(text(
            "ALTER TABLE vehiculos ADD COLUMN IF NOT EXISTS peso_kg INTEGER"
        ))

        # Nueva columna para asignaciones (unidad_auxilio_id)
        await conn.execute(text(
            "ALTER TABLE asignaciones ADD COLUMN IF NOT EXISTS unidad_auxilio_id INTEGER REFERENCES unidades_auxilio(id)"
        ))

    # Pool warm-up y auto-población limpia de datos si la BD está vacía
    async with AsyncSessionLocal() as session:
        try:
            await seed_initial_data(session)
        except Exception as e:
            print(f"[Seed] Error cargando datos iniciales: {e}")

    # Inicializar Firebase Admin SDK
    import firebase_admin
    from firebase_admin import credentials
    from app.core.config import settings

    if not firebase_admin._apps:
        cred_path = settings.FIREBASE_CREDENTIALS_PATH
        if os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
            print("[Firebase] Inicializado correctamente con la cuenta de servicio.")
        else:
            print(f"[Firebase] ADVERTENCIA: El archivo de credenciales no existe en '{cred_path}'. Las notificaciones push no funcionarán.")

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
app.include_router(seguimiento_router,  prefix="/api/seguimiento",  tags=["Seguimiento en Tiempo Real"])
app.include_router(metricas_router,     prefix="/api/metricas",     tags=["Métricas y Dashboard"])



@app.get("/")
async def root():
    return {"message": "Taller Backend v2.0 — IA activa"}

# reload trigger 1

