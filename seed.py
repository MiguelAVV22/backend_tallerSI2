"""
Carga datos iniciales en la base de datos con soporte Multi-tenant.
Uso: python seed.py
"""
import asyncio
import json
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, text
from dotenv import load_dotenv
import os

load_dotenv()

from app.acceso_registro.models import User, Vehiculo, Taller, ContactoEmergencia, Tenant
from app.emergencias.models import Incidente
from app.talleres_tecnicos.models import Tecnico, Asignacion, ServicioRealizado, UnidadAuxilio
from app.cotizacion_pagos.models import Cotizacion
from app.db.base import Base
from app.core.security import hash_password

DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# ── Tenants ──────────────────────────────────────────────────────────────────
TENANTS = [
    {"id": 1, "nombre": "Red Auxilio Norte", "slug": "auxilio-norte", "activo": True},
    {"id": 2, "nombre": "Red Mecánicos Express", "slug": "mecanicos-express", "activo": True},
]

# ── Usuarios ─────────────────────────────────────────────────────────────────
USUARIOS = [
    {"email": "admin@taller.com",    "username": "admin",    "full_name": "Administrador",     "password": "12345678", "role": "admin",    "tenant_id": 1},
    {"email": "cliente@taller.com",  "username": "cliente",  "full_name": "Carlos Mendoza",    "password": "12345678", "role": "cliente",  "tenant_id": 1},
    {"email": "cliente2@taller.com", "username": "cliente2", "full_name": "Ana Quispe",        "password": "12345678", "role": "cliente",  "tenant_id": 2},
    {"email": "taller@taller.com",   "username": "taller",   "full_name": "AutoFix Express",   "password": "12345678", "role": "taller",   "tenant_id": 1},
    {"email": "taller2@taller.com",  "username": "taller2",  "full_name": "Mecánica Central",  "password": "12345678", "role": "taller",   "tenant_id": 2},
    {"email": "tecnico@taller.com",  "username": "tecnico",  "full_name": "Luis Vargas",       "password": "12345678", "role": "tecnico",  "tenant_id": 1},
    {"email": "tecnico2@taller.com", "username": "tecnico2", "full_name": "Pedro Huanca",      "password": "12345678", "role": "tecnico",  "tenant_id": 2},
]

async def seed():
    async with engine.begin() as conn:
        # Drop all tables manually with CASCADE to bypass foreign keys
        tablas_drop = [
            "mensajes", "servicios_realizados", "cotizaciones", "pagos", 
            "unidades_auxilio", "asignaciones", "tecnicos", "evidencias", 
            "incidentes", "contactos_emergencia", "talleres", "vehiculos", 
            "users", "tenants", "password_reset_codes", "bitacora_eventos"
        ]
        for t in tablas_drop:
            await conn.execute(text(f"DROP TABLE IF EXISTS {t} CASCADE"))
            
        await conn.run_sync(Base.metadata.create_all)

        # Asegurar que existe el Tenant por defecto (ID=1) antes de alterar tablas
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

    async with AsyncSessionLocal() as db:

        # ── 0. Tenants ───────────────────────────────────────────────────────
        print("\n[0/9] Tenants...")
        tenants: dict[int, Tenant] = {}
        for t_data in TENANTS:
            result = await db.execute(select(Tenant).where(Tenant.id == t_data["id"]))
            t = result.scalar_one_or_none()
            if t:
                print(f"  [skip] Tenant: {t_data['nombre']}")
            else:
                t = Tenant(
                    id=t_data["id"],
                    nombre=t_data["nombre"],
                    slug=t_data["slug"],
                    activo=t_data["activo"]
                )
                db.add(t)
                await db.flush()
                print(f"  [ok]   Tenant: {t_data['nombre']}")
            tenants[t_data["id"]] = t
        await db.commit()
        
        # Reset serial sequence of tenants
        try:
            await db.execute(text("SELECT setval('tenants_id_seq', (SELECT MAX(id) FROM tenants))"))
            await db.commit()
        except Exception:
            pass

        # ── 1. Usuarios ───────────────────────────────────────────────────────
        print("\n[1/9] Usuarios...")
        users: dict[str, User] = {}
        for data in USUARIOS:
            result = await db.execute(select(User).where(User.email == data["email"]))
            u = result.scalar_one_or_none()
            if u:
                print(f"  [skip] {data['email']}")
            else:
                u = User(
                    email=data["email"],
                    username=data["username"],
                    full_name=data["full_name"],
                    hashed_password=hash_password(data["password"]),
                    role=data["role"],
                    tenant_id=data["tenant_id"],
                )
                db.add(u)
                await db.flush()
                print(f"  [ok]   {data['email']} (Tenant #{data['tenant_id']})")
            users[data["username"]] = u
        await db.commit()

        # Recargar IDs tras commit
        for key in users:
            await db.refresh(users[key])

        # ── 2. Vehículos ──────────────────────────────────────────────────────
        print("\n[2/9] Vehículos...")
        VEHICULOS = [
            {"usuario": "cliente",  "placa": "ABC-123", "marca": "Toyota",  "modelo": "Corolla",   "anio": 2019, "color": "Blanco", "tipo": "automovil", "peso_kg": 1300},
            {"usuario": "cliente",  "placa": "DEF-456", "marca": "Honda",   "modelo": "Civic",     "anio": 2021, "color": "Negro", "tipo": "automovil", "peso_kg": 1400},
            {"usuario": "cliente2", "placa": "GHI-789", "marca": "Hyundai", "modelo": "Tucson",    "anio": 2020, "color": "Gris", "tipo": "camioneta", "peso_kg": 1800},
            {"usuario": "cliente2", "placa": "JKL-012", "marca": "Kia",     "modelo": "Sportage",  "anio": 2022, "color": "Rojo", "tipo": "camioneta", "peso_kg": 1700},
        ]
        vehiculos: dict[str, Vehiculo] = {}
        for v in VEHICULOS:
            result = await db.execute(select(Vehiculo).where(Vehiculo.placa == v["placa"]))
            veh = result.scalar_one_or_none()
            if veh:
                print(f"  [skip] {v['placa']}")
            else:
                veh = Vehiculo(
                    tenant_id=users[v["usuario"]].tenant_id,
                    usuario_id=users[v["usuario"]].id,
                    placa=v["placa"],
                    marca=v["marca"],
                    modelo=v["modelo"],
                    anio=v["anio"],
                    color=v["color"],
                    tipo=v["tipo"],
                    peso_kg=v["peso_kg"],
                )
                db.add(veh)
                await db.flush()
                print(f"  [ok]   {v['placa']} ({v['marca']} {v['modelo']})")
            vehiculos[v["placa"]] = veh
        await db.commit()
        for k in vehiculos:
            await db.refresh(vehiculos[k])

        # ── 3. Talleres ───────────────────────────────────────────────────────
        print("\n[3/9] Talleres...")
        TALLERES = [
            {
                "usuario": "taller",
                "nombre": "AutoFix Express",
                "direccion": "Av. Américas 1245, La Paz",
                "telefono": "78901234",
                "email_comercial": "autofix@taller.com",
                "latitud": -16.5000, "longitud": -68.1500,
                "estado": "aprobado", "disponible": True, "rating": 4.5,
            },
            {
                "usuario": "taller2",
                "nombre": "Mecánica Central",
                "direccion": "Calle Comercio 890, Cochabamba",
                "telefono": "71234567",
                "email_comercial": "mecanica@taller.com",
                "latitud": -17.3895, "longitud": -66.1568,
                "estado": "aprobado", "disponible": True, "rating": 4.2,
            },
        ]
        talleres: dict[str, Taller] = {}
        for t in TALLERES:
            result = await db.execute(select(Taller).where(Taller.usuario_id == users[t["usuario"]].id))
            tal = result.scalar_one_or_none()
            if tal:
                print(f"  [skip] {t['nombre']}")
            else:
                tal = Taller(
                    tenant_id=users[t["usuario"]].tenant_id,
                    usuario_id=users[t["usuario"]].id,
                    nombre=t["nombre"],
                    direccion=t["direccion"],
                    telefono=t["telefono"],
                    email_comercial=t["email_comercial"],
                    latitud=t["latitud"],
                    longitud=t["longitud"],
                    estado=t["estado"],
                    disponible=t["disponible"],
                    rating=t["rating"],
                )
                db.add(tal)
                await db.flush()
                print(f"  [ok]   {t['nombre']} ({t['estado']}) - Tenant #{users[t['usuario']].tenant_id}")
            talleres[t["usuario"]] = tal
        await db.commit()
        for k in talleres:
            await db.refresh(talleres[k])

        # ── 4. Técnicos ───────────────────────────────────────────────────────
        print("\n[4/9] Técnicos...")
        TECNICOS = [
            {"nombre": "Luis Vargas",    "especialidad": "Motor y transmisión",   "telefono": "71111111", "estado": "ocupado",     "usuario": "tecnico",  "taller_key": "taller"},
            {"nombre": "Pedro Huanca",   "especialidad": "Eléctrica automotriz",  "telefono": "72222222", "estado": "ocupado",     "usuario": "tecnico2", "taller_key": "taller2"},
            {"nombre": "Jorge Mamani",   "especialidad": "Frenos y suspensión",   "telefono": "73333333", "estado": "disponible",  "usuario": None,       "taller_key": "taller"},
            {"nombre": "Rosa Chávez",    "especialidad": "Carrocería y pintura",  "telefono": "74444444", "estado": "disponible",  "usuario": None,       "taller_key": "taller"},
            {"nombre": "Mario Quispe",   "especialidad": "Diagnóstico OBD",       "telefono": "75555555", "estado": "inactivo",    "usuario": None,       "taller_key": "taller"},
        ]
        tecnicos_dict: dict[str, Tecnico] = {}
        for t in TECNICOS:
            taller_obj = talleres[t["taller_key"]]
            result = await db.execute(
                select(Tecnico).where(
                    Tecnico.taller_id == taller_obj.id,
                    Tecnico.nombre == t["nombre"],
                )
            )
            tec = result.scalar_one_or_none()
            if tec:
                print(f"  [skip] {t['nombre']}")
            else:
                usuario_id = users[t["usuario"]].id if t["usuario"] else None
                tec = Tecnico(
                    tenant_id=taller_obj.tenant_id,
                    taller_id=taller_obj.id,
                    usuario_id=usuario_id,
                    nombre=t["nombre"],
                    especialidad=t["especialidad"],
                    telefono=t["telefono"],
                    estado=t["estado"],
                    activo=t["estado"] != "inactivo",
                )
                db.add(tec)
                await db.flush()
                print(f"  [ok]   {t['nombre']} ({t['estado']}) - Taller: {taller_obj.nombre}")
            tecnicos_dict[t["nombre"]] = tec
        await db.commit()

        # ── 5. Incidentes ─────────────────────────────────────────────────────
        print("\n[5/9] Incidentes...")
        INCIDENTES = [
            # Incidente 1 → asignación finalizada (historial CU22)
            {
                "usuario": "cliente", "placa": "ABC-123",
                "lat": -16.5050, "lon": -68.1480,
                "descripcion": "Vehículo no enciende, batería descargada",
                "estado": "resuelto", "prioridad": "alta",
            },
            # Incidente 2 → asignación finalizada (historial CU22)
            {
                "usuario": "cliente2", "placa": "GHI-789",
                "lat": -16.5100, "lon": -68.1450,
                "descripcion": "Pinchazo de llanta delantera derecha",
                "estado": "resuelto", "prioridad": "media",
            },
            # Incidente 3 → en_reparacion (listo para CU22)
            {
                "usuario": "cliente", "placa": "DEF-456",
                "lat": -16.5200, "lon": -68.1520,
                "descripcion": "Fuga de aceite por el carter, humo blanco",
                "estado": "en_proceso", "prioridad": "alta",
            },
            # Incidente 4 → en_reparacion (listo para CU22)
            {
                "usuario": "cliente2", "placa": "JKL-012",
                "lat": -16.5300, "lon": -68.1400,
                "descripcion": "Frenos no responden correctamente al frenar",
                "estado": "en_proceso", "prioridad": "alta",
            },
            # Incidente 5 → en_camino (activo CU15)
            {
                "usuario": "cliente", "placa": "ABC-123",
                "lat": -16.5150, "lon": -68.1490,
                "descripcion": "Recalentamiento del motor, temperatura muy alta",
                "estado": "en_proceso", "prioridad": "alta",
            },
            # Incidente 6 → aceptado sin técnico (pendiente CU25)
            {
                "usuario": "cliente2", "placa": "GHI-789",
                "lat": -16.5400, "lon": -68.1350,
                "descripcion": "Ruido extraño al acelerar, posible problema en transmisión",
                "estado": "en_proceso", "prioridad": "media",
            },
            # Incidente 7 → pendiente (sin asignación aún)
            {
                "usuario": "cliente", "placa": "DEF-456",
                "lat": -16.5250, "lon": -68.1380,
                "descripcion": "Luces del tablero parpadeando, posible falla eléctrica",
                "estado": "pendiente", "prioridad": "baja",
            },
            # Incidente 8 → para cotización pendiente (CU20)
            {
                "usuario": "cliente2", "placa": "JKL-012",
                "lat": -16.5050, "lon": -68.1600,
                "descripcion": "Cambio de aceite y revisión general preventiva",
                "estado": "en_proceso", "prioridad": "baja",
            },
        ]
        incidentes: list[Incidente] = []
        for inc_data in INCIDENTES:
            user_obj = users[inc_data["usuario"]]
            inc = Incidente(
                tenant_id=user_obj.tenant_id,
                usuario_id=user_obj.id,
                vehiculo_id=vehiculos[inc_data["placa"]].id,
                latitud=inc_data["lat"],
                longitud=inc_data["lon"],
                descripcion=inc_data["descripcion"],
                estado=inc_data["estado"],
                prioridad=inc_data["prioridad"],
            )
            db.add(inc)
            await db.flush()
            incidentes.append(inc)
            print(f"  [ok]   Incidente #{inc.id} (Tenant #{user_obj.tenant_id}) - {inc_data['descripcion'][:50]}...")
        await db.commit()

        # ── 6. Asignaciones ───────────────────────────────────────────────────
        print("\n[6/9] Asignaciones...")
        ASIGNACIONES = [
            {"incidente": incidentes[0], "tecnico": tecnicos_dict["Luis Vargas"],  "estado": "finalizado",    "eta": None, "obs": "Servicio completado exitosamente", "taller_key": "taller"},
            {"incidente": incidentes[1], "tecnico": tecnicos_dict["Pedro Huanca"], "estado": "finalizado",    "eta": None, "obs": "Llanta cambiada sin inconvenientes", "taller_key": "taller2"},
            {"incidente": incidentes[2], "tecnico": tecnicos_dict["Luis Vargas"],  "estado": "en_reparacion", "eta": 30,   "obs": "Diagnóstico completado, en proceso de reparación", "taller_key": "taller"},
            {"incidente": incidentes[3], "tecnico": tecnicos_dict["Pedro Huanca"], "estado": "en_reparacion", "eta": 45,   "obs": "Revisando sistema de frenos", "taller_key": "taller2"},
            {"incidente": incidentes[4], "tecnico": tecnicos_dict["Luis Vargas"],  "estado": "en_camino",     "eta": 15,   "obs": "Técnico en camino al lugar", "taller_key": "taller"},
            {"incidente": incidentes[5], "tecnico": None,                          "estado": "aceptado",      "eta": None, "obs": None, "taller_key": "taller2"},
            {"incidente": incidentes[6], "tecnico": tecnicos_dict["Pedro Huanca"], "estado": "en_sitio",      "eta": 0,    "obs": "Técnico en el lugar evaluando", "taller_key": "taller2"},
            {"incidente": incidentes[7], "tecnico": None,                          "estado": "aceptado",      "eta": None, "obs": None, "taller_key": "taller2"},
        ]
        asignaciones: list[Asignacion] = []
        for a in ASIGNACIONES:
            taller_obj = talleres[a["taller_key"]]
            asig = Asignacion(
                tenant_id=taller_obj.tenant_id,
                incidente_id=a["incidente"].id,
                taller_id=taller_obj.id,
                tecnico_id=a["tecnico"].id if a["tecnico"] else None,
                estado=a["estado"],
                eta=a["eta"],
                observacion=a["obs"],
            )
            db.add(asig)
            await db.flush()
            asignaciones.append(asig)
            tec_nombre = a["tecnico"].nombre if a["tecnico"] else "Sin técnico"
            print(f"  [ok]   Asignación #{asig.id} ({a['estado']}) -> {tec_nombre} (Tenant #{taller_obj.tenant_id})")
        await db.commit()

        # ── 7a. Servicios Realizados (historial CU22) ─────────────────────────
        print("\n[7/9] Servicios realizados...")
        SERVICIOS = [
            {
                "asignacion": asignaciones[0],  # finalizada
                "descripcion": "Se realizó carga completa de batería y revisión del sistema eléctrico. Se verificó alternador y cableado.",
                "repuestos": json.dumps([
                    {"descripcion": "Batería 12V 60Ah", "cantidad": 1},
                    {"descripcion": "Terminales de batería", "cantidad": 2},
                ]),
                "observaciones": "Se recomienda revisión eléctrica completa en 6 meses.",
            },
            {
                "asignacion": asignaciones[1],  # finalizada
                "descripcion": "Cambio de llanta delantera derecha por pinchazo. Se revisaron las demás llantas y se ajustó presión.",
                "repuestos": json.dumps([
                    {"descripcion": "Llanta 195/65 R15", "cantidad": 1},
                    {"descripcion": "Parche vulcanizado", "cantidad": 1},
                ]),
                "observaciones": "Las llantas traseras presentan desgaste irregular, considerar alineación.",
            },
        ]
        for s in SERVICIOS:
            result = await db.execute(
                select(ServicioRealizado).where(ServicioRealizado.asignacion_id == s["asignacion"].id)
            )
            srv = result.scalar_one_or_none()
            if srv:
                print(f"  [skip] ServicioRealizado para asignación #{s['asignacion'].id}")
            else:
                srv = ServicioRealizado(
                    tenant_id=s["asignacion"].tenant_id,
                    asignacion_id=s["asignacion"].id,
                    descripcion_trabajo=s["descripcion"],
                    repuestos=s["repuestos"],
                    observaciones=s["observaciones"],
                )
                db.add(srv)
                await db.flush()
                print(f"  [ok]   ServicioRealizado #{srv.id} (Tenant #{s['asignacion'].tenant_id})")
        await db.commit()

        # ── 7b. Cotizaciones (CU20) ───────────────────────────────────────────
        print("\n[7b/9] Cotizaciones...")
        COTIZACIONES = [
            {
                "incidente": incidentes[2],
                "taller_key": "taller",
                "items": [
                    {"descripcion": "Junta del carter",       "cantidad": 1, "precio_unitario": 85.0},
                    {"descripcion": "Aceite de motor 5W-30",  "cantidad": 4, "precio_unitario": 45.0},
                    {"descripcion": "Mano de obra reparación","cantidad": 1, "precio_unitario": 150.0},
                ],
                "estado": "aceptada",
            },
            {
                "incidente": incidentes[3],
                "taller_key": "taller2",
                "items": [
                    {"descripcion": "Pastillas de freno delanteras", "cantidad": 1, "precio_unitario": 120.0},
                    {"descripcion": "Disco de freno",                "cantidad": 2, "precio_unitario": 200.0},
                    {"descripcion": "Líquido de frenos DOT4",        "cantidad": 1, "precio_unitario": 35.0},
                    {"descripcion": "Mano de obra",                  "cantidad": 1, "precio_unitario": 180.0},
                ],
                "estado": "pendiente",
            },
            {
                "incidente": incidentes[7],
                "taller_key": "taller2",
                "items": [
                    {"descripcion": "Aceite sintético 5W-40",  "cantidad": 4, "precio_unitario": 55.0},
                    {"descripcion": "Filtro de aceite",        "cantidad": 1, "precio_unitario": 30.0},
                    {"descripcion": "Filtro de aire",          "cantidad": 1, "precio_unitario": 40.0},
                    {"descripcion": "Revisión general",        "cantidad": 1, "precio_unitario": 100.0},
                ],
                "estado": "pendiente",
            },
        ]
        for c in COTIZACIONES:
            taller_obj = talleres[c["taller_key"]]
            result = await db.execute(
                select(Cotizacion).where(
                    Cotizacion.incidente_id == c["incidente"].id,
                    Cotizacion.taller_id == taller_obj.id,
                )
            )
            cot = result.scalar_one_or_none()
            if cot:
                print(f"  [skip] Cotización para incidente #{c['incidente'].id}")
            else:
                monto = sum(i["cantidad"] * i["precio_unitario"] for i in c["items"])
                cot = Cotizacion(
                    tenant_id=taller_obj.tenant_id,
                    incidente_id=c["incidente"].id,
                    taller_id=taller_obj.id,
                    monto_estimado=monto,
                    detalle=json.dumps(c["items"]),
                    estado=c["estado"],
                )
                db.add(cot)
                await db.flush()
                print(f"  [ok]   Cotización #{cot.id} Bs.{monto:.2f} (Tenant #{taller_obj.tenant_id})")
        await db.commit()

        # ── 8. Contactos de Emergencia ─────────────────────────────────────────
        print("\n[8/9] Contactos de Emergencia...")
        CONTACTOS = [
            {"usuario": "cliente", "nombre": "Mamá", "telefono": "73690995", "relacion": "mamá"},
            {"usuario": "cliente", "nombre": "Hermano", "telefono": "69048909", "relacion": "hermano"},
        ]
        for cont in CONTACTOS:
            user_obj = users.get(cont["usuario"])
            if user_obj:
                res_c = await db.execute(
                    select(ContactoEmergencia).where(
                        ContactoEmergencia.usuario_id == user_obj.id,
                        ContactoEmergencia.telefono == cont["telefono"]
                    )
                )
                if res_c.scalar_one_or_none():
                    print(f"  [skip] Contacto {cont['nombre']}")
                else:
                    db.add(ContactoEmergencia(
                        tenant_id=user_obj.tenant_id,
                        usuario_id=user_obj.id,
                        nombre=cont["nombre"],
                        telefono=cont["telefono"],
                        relacion=cont["relacion"]
                    ))
                    print(f"  [ok]   Contacto {cont['nombre']} (Tenant #{user_obj.tenant_id})")
        await db.commit()

        # ── 9. Unidades de Auxilio / Grúas ──────────────────────────────────────
        print("\n[9/9] Unidades de Auxilio...")
        UNIDADES = [
            {"taller": "taller", "placa": "123-ABC", "modelo": "Ford F-350", "tipo": "grua_liviana", "capacidad_carga_kg": 2000},
            {"taller": "taller", "placa": "456-DEF", "modelo": "Chevrolet Silverado", "tipo": "grua_plataforma_pesada", "capacidad_carga_kg": 5000},
            {"taller": "taller", "placa": "789-GHI", "modelo": "Honda Cargo", "tipo": "moto_remolque", "capacidad_carga_kg": 500},
            {"taller": "taller2", "placa": "987-XYZ", "modelo": "Toyota Dyna", "tipo": "grua_liviana", "capacidad_carga_kg": 2500},
        ]
        for uni in UNIDADES:
            taller_obj = talleres.get(uni["taller"])
            if taller_obj:
                res_u = await db.execute(
                    select(UnidadAuxilio).where(UnidadAuxilio.placa == uni["placa"])
                )
                if res_u.scalar_one_or_none():
                    print(f"  [skip] Unidad {uni['placa']}")
                else:
                    db.add(UnidadAuxilio(
                        tenant_id=taller_obj.tenant_id,
                        taller_id=taller_obj.id,
                        placa=uni["placa"],
                        modelo=uni["modelo"],
                        tipo=uni["tipo"],
                        capacidad_carga_kg=uni["capacidad_carga_kg"]
                    ))
                    print(f"  [ok]   Unidad {uni['placa']} (Tenant #{taller_obj.tenant_id})")
        await db.commit()

    print("""
+--------------------------------------------------------------+
|                    SEED COMPLETADO (MULTI-TENANT)            |
+--------------------------------------------------------------+
|  TENANTS REGISTRADOS                                         |
|  Tenant 1 -> Red Auxilio Norte                               |
|  Tenant 2 -> Red Mecánicos Express                           |
+--------------------------------------------------------------+
|  CREDENCIALES (password: 12345678 para todos)                |
|  admin@taller.com    -> admin    (Tenant 1)                  |
|  cliente@taller.com  -> cliente  (Tenant 1 - Carlos Mendoza) |
|  cliente2@taller.com -> cliente  (Tenant 2 - Ana Quispe)     |
|  taller@taller.com   -> taller   (Tenant 1 - AutoFix Exp.)   |
|  taller2@taller.com  -> taller   (Tenant 2 - Mecánica Cent.) |
|  tecnico@taller.com  -> tecnico  (Tenant 1 - Luis Vargas)    |
|  tecnico2@taller.com -> tecnico  (Tenant 2 - Pedro Huanca)   |
+--------------------------------------------------------------+
""")


if __name__ == "__main__":
    asyncio.run(seed())
