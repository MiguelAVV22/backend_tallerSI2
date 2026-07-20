import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException

from app.talleres_tecnicos.models import Tecnico, Asignacion, ServicioRealizado, UnidadAuxilio
from app.acceso_registro.models import Taller, User
from app.core.security import hash_password
from app.talleres_tecnicos import schemas
from app.talleres_tecnicos.schemas import (
    TecnicoCreate, TecnicoUpdate, TallerInfoResponse,
    AsignacionEstadoUpdate, TRANSICIONES_VALIDAS,
    ServicioRealizadoCreate, UnidadAuxilioCreate, TallerUpdatePayload
)


async def get_taller_by_user(user_id: int, db: AsyncSession) -> Taller:
    result = await db.execute(
        select(Taller).where(Taller.usuario_id == user_id, Taller.estado == "aprobado")
    )
    taller = result.scalar_one_or_none()
    if not taller:
        raise HTTPException(status_code=403, detail="No tienes un taller aprobado")
    return taller


# ── Técnicos ───────────────────────────────────────────────
async def listar_tecnicos(taller_id: int, db: AsyncSession) -> list[Tecnico]:
    result = await db.execute(
        select(Tecnico).where(Tecnico.taller_id == taller_id, Tecnico.activo.is_(True))
    )
    tecnicos = list(result.scalars().all())

    # Auto-corregir técnicos "ocupado" sin asignación activa real
    ocupados = [t for t in tecnicos if t.estado == "ocupado"]
    if ocupados:
        res = await db.execute(
            select(Asignacion.tecnico_id)
            .where(
                Asignacion.tecnico_id.in_([t.id for t in ocupados]),
                Asignacion.estado.notin_(["cancelado", "finalizado"]),
            )
            .distinct()
        )
        con_asignacion = {row[0] for row in res.all()}
        corregido = False
        for t in ocupados:
            if t.id not in con_asignacion:
                t.estado = "disponible"
                corregido = True
        if corregido:
            await db.commit()

    return tecnicos


async def registrar_tecnico(taller_id: int, data: TecnicoCreate, db: AsyncSession) -> Tecnico:
    taller_res = await db.execute(select(Taller).where(Taller.id == taller_id))
    taller = taller_res.scalar_one_or_none()
    tenant_id = taller.tenant_id if taller else 1

    if data.email and data.password:
        res = await db.execute(select(User).where(User.email == data.email.lower().strip()))
        if res.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="El correo ya está registrado en el sistema")
        
        import random
        base_username = data.email.split("@")[0]
        username = f"{base_username}_{random.randint(100, 999)}"
        new_user = User(
            tenant_id=tenant_id,
            email=data.email.lower().strip(),
            username=username,
            full_name=data.nombre,
            telefono=data.telefono,
            hashed_password=hash_password(data.password),
            role="tecnico",
        )
        db.add(new_user)
        await db.flush()
        user_id_created = new_user.id
    else:
        user_id_created = None

    tecnico = Tecnico(
        tenant_id=tenant_id,
        taller_id=taller_id,
        usuario_id=user_id_created,
        nombre=data.nombre,
        especialidad=data.especialidad,
        telefono=data.telefono,
    )
    db.add(tecnico)
    await db.commit()
    await db.refresh(tecnico)
    return tecnico


async def actualizar_tecnico(
    tecnico_id: int, taller_id: int, data: TecnicoUpdate, db: AsyncSession
) -> Tecnico:
    result = await db.execute(
        select(Tecnico).where(Tecnico.id == tecnico_id, Tecnico.taller_id == taller_id, Tecnico.activo.is_(True))
    )
    tecnico = result.scalar_one_or_none()
    if not tecnico:
        raise HTTPException(status_code=404, detail="Técnico no encontrado")

    if data.nombre is not None:       tecnico.nombre       = data.nombre.strip()
    if data.especialidad is not None: tecnico.especialidad = data.especialidad.strip()
    if data.telefono is not None:     tecnico.telefono     = data.telefono
    if data.estado is not None:       tecnico.estado       = data.estado

    await db.commit()
    await db.refresh(tecnico)
    return tecnico


async def desactivar_tecnico(tecnico_id: int, taller_id: int, db: AsyncSession) -> None:
    result = await db.execute(
        select(Tecnico).where(Tecnico.id == tecnico_id, Tecnico.taller_id == taller_id)
    )
    tecnico = result.scalar_one_or_none()
    if not tecnico:
        raise HTTPException(status_code=404, detail="Técnico no encontrado")
    tecnico.activo = False
    await db.commit()


# ── Asignaciones ───────────────────────────────────────────
async def listar_asignaciones_sin_tecnico(taller_id: int, db: AsyncSession) -> list[Asignacion]:
    result = await db.execute(
        select(Asignacion).where(
            Asignacion.taller_id == taller_id,
            Asignacion.tecnico_id == None,
            Asignacion.estado == "aceptado",
        )
    )
    return list(result.scalars().all())


# ── CU16 · Disponibilidad ──────────────────────────────────
async def get_taller_info(user_id: int, db: AsyncSession) -> TallerInfoResponse:
    result = await db.execute(select(Taller).where(Taller.usuario_id == user_id))
    taller = result.scalar_one_or_none()
    if not taller:
        raise HTTPException(status_code=404, detail="No tienes un taller registrado")

    result = await db.execute(
        select(Tecnico).where(Tecnico.taller_id == taller.id, Tecnico.activo.is_(True))
    )
    tecnicos = list(result.scalars().all())

    return TallerInfoResponse(
        id=taller.id,
        nombre=taller.nombre,
        direccion=taller.direccion,
        telefono=taller.telefono,
        email_comercial=taller.email_comercial,
        disponible=taller.disponible,
        estado=taller.estado,
        rating=taller.rating,
        total_tecnicos=len(tecnicos),
        tecnicos_disponibles=sum(1 for t in tecnicos if t.estado == "disponible"),
        tecnicos_ocupados=sum(1 for t in tecnicos if t.estado == "ocupado"),
        latitud=taller.latitud,
        longitud=taller.longitud,
    )


async def actualizar_disponibilidad(user_id: int, disponible: bool, db: AsyncSession) -> TallerInfoResponse:
    result = await db.execute(select(Taller).where(Taller.usuario_id == user_id))
    taller = result.scalar_one_or_none()
    if not taller:
        raise HTTPException(status_code=404, detail="No tienes un taller registrado")
    if taller.estado != "aprobado":
        raise HTTPException(status_code=400, detail="Tu taller aún no está aprobado por el administrador")

    taller.disponible = disponible
    await db.commit()
    await db.refresh(taller)
    return await get_taller_info(user_id, db)


async def actualizar_taller_info(user_id: int, data: schemas.TallerUpdatePayload, db: AsyncSession) -> TallerInfoResponse:
    result = await db.execute(select(Taller).where(Taller.usuario_id == user_id))
    taller = result.scalar_one_or_none()
    if not taller:
        raise HTTPException(status_code=404, detail="No tienes un taller registrado")

    if data.nombre is not None and data.nombre.strip():
        taller.nombre = data.nombre.strip()
    if data.direccion is not None and data.direccion.strip():
        taller.direccion = data.direccion.strip()
    if data.telefono is not None:
        taller.telefono = data.telefono.strip()
    if data.email_comercial is not None:
        taller.email_comercial = data.email_comercial.strip()
    if data.latitud is not None:
        taller.latitud = data.latitud
    if data.longitud is not None:
        taller.longitud = data.longitud

    await db.commit()
    await db.refresh(taller)
    return await get_taller_info(user_id, db)



# ── CU15 · Estado del servicio ─────────────────────────────
_ESTADOS_ACTIVOS = ["aceptado", "en_camino", "en_sitio", "en_reparacion"]


async def listar_asignaciones_activas(user_id: int, role: str, db: AsyncSession) -> list[Asignacion]:
    if role == "taller":
        taller = await get_taller_by_user(user_id, db)
        result = await db.execute(
            select(Asignacion)
            .where(Asignacion.taller_id == taller.id, Asignacion.estado.in_(_ESTADOS_ACTIVOS))
            .order_by(Asignacion.created_at.desc())
        )
    else:  # tecnico
        result_t = await db.execute(
            select(Tecnico).where(Tecnico.usuario_id == user_id, Tecnico.activo.is_(True))
        )
        tecnico = result_t.scalar_one_or_none()
        if not tecnico:
            user_res = await db.execute(select(User).where(User.id == user_id))
            usr = user_res.scalar_one_or_none()
            if usr:
                res_match = await db.execute(
                    select(Tecnico).where(
                        (Tecnico.nombre == usr.full_name) | (Tecnico.nombre == usr.username),
                        Tecnico.activo.is_(True),
                    )
                )
                tecnico = res_match.scalar_one_or_none()
                if tecnico:
                    tecnico.usuario_id = user_id
                    await db.commit()

        if not tecnico:
            return []
        result = await db.execute(
            select(Asignacion)
            .where(Asignacion.tecnico_id == tecnico.id, Asignacion.estado.in_(_ESTADOS_ACTIVOS))
            .order_by(Asignacion.created_at.desc())
        )
    return list(result.scalars().all())


async def actualizar_estado_asignacion(
    asignacion_id: int, user_id: int, role: str, data: AsignacionEstadoUpdate, db: AsyncSession
) -> Asignacion:
    result = await db.execute(select(Asignacion).where(Asignacion.id == asignacion_id))
    asignacion = result.scalar_one_or_none()
    if not asignacion:
        raise HTTPException(status_code=404, detail="Asignación no encontrada")

    if role == "taller":
        taller = await get_taller_by_user(user_id, db)
        if asignacion.taller_id != taller.id:
            raise HTTPException(status_code=403, detail="No tienes permiso sobre esta asignación")
    else:  # tecnico
        result_t = await db.execute(
            select(Tecnico).where(Tecnico.usuario_id == user_id, Tecnico.activo.is_(True))
        )
        tecnico = result_t.scalar_one_or_none()
        if not tecnico or asignacion.tecnico_id != tecnico.id:
            raise HTTPException(status_code=403, detail="No tienes permiso sobre esta asignación")

    permitidos = TRANSICIONES_VALIDAS.get(asignacion.estado, set())
    if data.estado not in permitidos:
        raise HTTPException(
            status_code=400,
            detail=f"Transición inválida: '{asignacion.estado}' → '{data.estado}'. "
                   f"Permitidos: {', '.join(sorted(permitidos)) or 'ninguno'}",
        )

    asignacion.estado = data.estado
    if data.observacion:
        asignacion.observacion = data.observacion

    # Liberar técnico al finalizar o cancelar
    if data.estado in ("finalizado", "cancelado") and asignacion.tecnico_id:
        res_tec = await db.execute(
            select(Tecnico).where(Tecnico.id == asignacion.tecnico_id)
        )
        tec = res_tec.scalar_one_or_none()
        if tec and tec.estado == "ocupado":
            tec.estado = "disponible"

    await db.commit()

    # Disparar notificaciones push al cliente por cambio de estado
    try:
        from app.comunicacion.push_service import enviar_notificacion_push
        from app.emergencias.models import Incidente
        res_i = await db.execute(
            select(Incidente).where(Incidente.id == asignacion.incidente_id)
        )
        inc = res_i.scalar_one_or_none()
        if inc:
            labels = {
                "pendiente": "Pendiente",
                "buscando_taller": "Buscando Taller",
                "aceptado": "Aceptado",
                "en_camino": "En Camino",
                "llegada": "Llegada",
                "en_sitio": "En Sitio",
                "en_reparacion": "Reparando",
                "finalizado": "Finalizado",
                "cancelado": "Cancelado"
            }
            lbl = labels.get(data.estado.lower(), data.estado)
            await enviar_notificacion_push(
                usuario_id=inc.usuario_id,
                titulo="Actualización de tu Asistencia 🔔",
                cuerpo=f"El estado de tu servicio cambió a: {lbl}",
                data={
                    "screen": "/seguimiento",
                    "incidente_id": str(asignacion.incidente_id),
                },
                db=db
            )
    except Exception as e:
        print(f"[PushService] Error al disparar push de estado: {e}")
    await db.refresh(asignacion)
    return asignacion


# ── CU22 · Servicio Realizado ──────────────────────────────
async def listar_asignaciones_listas(user_id: int, role: str, db: AsyncSession) -> list[Asignacion]:
    """Asignaciones en estado en_reparacion listas para cierre formal."""
    if role == "taller":
        taller = await get_taller_by_user(user_id, db)
        result = await db.execute(
            select(Asignacion)
            .where(Asignacion.taller_id == taller.id, Asignacion.estado == "en_reparacion")
            .order_by(Asignacion.created_at.desc())
        )
    else:  # tecnico
        result_t = await db.execute(
            select(Tecnico).where(Tecnico.usuario_id == user_id, Tecnico.activo.is_(True))
        )
        tecnico = result_t.scalar_one_or_none()
        if not tecnico:
            return []
        result = await db.execute(
            select(Asignacion)
            .where(Asignacion.tecnico_id == tecnico.id, Asignacion.estado == "en_reparacion")
            .order_by(Asignacion.created_at.desc())
        )
    return list(result.scalars().all())


async def registrar_servicio_y_cerrar(
    user_id: int, role: str, data: ServicioRealizadoCreate, db: AsyncSession
) -> ServicioRealizado:
    result = await db.execute(select(Asignacion).where(Asignacion.id == data.asignacion_id))
    asignacion = result.scalar_one_or_none()
    if not asignacion:
        raise HTTPException(status_code=404, detail="Asignación no encontrada")

    # Verificar permiso
    if role == "taller":
        taller = await get_taller_by_user(user_id, db)
        if asignacion.taller_id != taller.id:
            raise HTTPException(status_code=403, detail="No tienes permiso sobre esta asignación")
    else:
        result_t = await db.execute(
            select(Tecnico).where(Tecnico.usuario_id == user_id, Tecnico.activo.is_(True))
        )
        tecnico = result_t.scalar_one_or_none()
        if not tecnico or asignacion.tecnico_id != tecnico.id:
            raise HTTPException(status_code=403, detail="No tienes permiso sobre esta asignación")

    if asignacion.estado not in ("en_reparacion", "en_sitio", "en_camino", "aceptado"):
        raise HTTPException(status_code=400, detail="La asignación no está en un estado activo que permita cierre")

    # Verificar duplicado
    dup = await db.execute(
        select(ServicioRealizado).where(ServicioRealizado.asignacion_id == data.asignacion_id)
    )
    if dup.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Este servicio ya fue registrado y cerrado")

    repuestos_json = (
        json.dumps([r.model_dump() for r in data.repuestos], ensure_ascii=False)
        if data.repuestos else None
    )
    servicio = ServicioRealizado(
        asignacion_id=data.asignacion_id,
        descripcion_trabajo=data.descripcion_trabajo,
        repuestos=repuestos_json,
        observaciones=data.observaciones,
    )
    db.add(servicio)

    asignacion.estado = "finalizado"

    # Liberar al técnico
    if asignacion.tecnico_id:
        result_t2 = await db.execute(
            select(Tecnico).where(Tecnico.id == asignacion.tecnico_id)
        )
        tec = result_t2.scalar_one_or_none()
        if tec:
            tec.estado = "disponible"

    await db.commit()
    await db.refresh(servicio)
    return servicio


async def listar_servicios_realizados(user_id: int, role: str, db: AsyncSession) -> list[ServicioRealizado]:
    if role == "taller":
        taller = await get_taller_by_user(user_id, db)
        sub = select(Asignacion.id).where(Asignacion.taller_id == taller.id)
    else:
        result_t = await db.execute(
            select(Tecnico).where(Tecnico.usuario_id == user_id, Tecnico.activo.is_(True))
        )
        tecnico = result_t.scalar_one_or_none()
        if not tecnico:
            return []
        sub = select(Asignacion.id).where(Asignacion.tecnico_id == tecnico.id)

    result = await db.execute(
        select(ServicioRealizado)
        .where(ServicioRealizado.asignacion_id.in_(sub))
        .order_by(ServicioRealizado.fecha_cierre.desc())
    )
    return list(result.scalars().all())


# ── CU31 · Confirmar llegada del técnico (cliente) ─────────
async def confirmar_llegada_tecnico(
    asignacion_id: int, usuario_id: int, db: AsyncSession
) -> Asignacion:
    from app.emergencias.models import Incidente
    result = await db.execute(select(Asignacion).where(Asignacion.id == asignacion_id))
    asignacion = result.scalar_one_or_none()
    if not asignacion:
        raise HTTPException(status_code=404, detail="Asignación no encontrada")

    # Verificar que el incidente pertenece al usuario
    inc_result = await db.execute(
        select(Incidente).where(
            Incidente.id == asignacion.incidente_id,
            Incidente.usuario_id == usuario_id,
        )
    )
    if not inc_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="No tienes permiso sobre esta asignación")

    if asignacion.estado == "en_sitio":
        raise HTTPException(status_code=400, detail="La llegada del técnico ya fue confirmada")

    if asignacion.estado not in ("aceptado", "en_camino"):
        raise HTTPException(
            status_code=400,
            detail=f"No puedes confirmar llegada en estado '{asignacion.estado}'",
        )

    asignacion.estado = "en_sitio"
    await db.commit()
    await db.refresh(asignacion)

    # Disparar notificación push al cliente
    try:
        from app.comunicacion.push_service import enviar_notificacion_push
        await enviar_notificacion_push(
            usuario_id=usuario_id,
            titulo="El técnico ha llegado 📍",
            cuerpo="Se ha confirmado la llegada del técnico al lugar del incidente.",
            data={
                "screen": "/seguimiento",
                "incidente_id": str(asignacion.incidente_id),
            },
            db=db
        )
    except Exception as e:
        print(f"[PushService] Error al disparar push de llegada cliente: {e}")

    return asignacion


async def asignar_tecnico_a_solicitud(
    asignacion_id: int, taller_id: int, tecnico_id: int, db: AsyncSession, unidad_auxilio_id: Optional[int] = None
) -> Asignacion:
    result = await db.execute(
        select(Asignacion).where(Asignacion.id == asignacion_id, Asignacion.taller_id == taller_id)
    )
    asignacion = result.scalar_one_or_none()
    if not asignacion:
        raise HTTPException(status_code=404, detail="Asignación no encontrada")

    result = await db.execute(
        select(Tecnico).where(
            Tecnico.id == tecnico_id,
            Tecnico.taller_id == taller_id,
            Tecnico.activo.is_(True),
            Tecnico.estado == "disponible",
        )
    )
    tecnico = result.scalar_one_or_none()
    if not tecnico:
        raise HTTPException(status_code=400, detail="Técnico no disponible o no pertenece a tu taller")

    if unidad_auxilio_id:
        result_u = await db.execute(
            select(UnidadAuxilio).where(
                UnidadAuxilio.id == unidad_auxilio_id,
                UnidadAuxilio.taller_id == taller_id,
                UnidadAuxilio.activo.is_(True),
                UnidadAuxilio.estado == "disponible",
            )
        )
        unidad = result_u.scalar_one_or_none()
        if not unidad:
            raise HTTPException(status_code=400, detail="La unidad de auxilio seleccionada no está disponible")

        # VALIDACIÓN DE CAPACIDAD Y COMPATIBILIDAD
        from app.emergencias.models import Incidente
        from app.acceso_registro.models import Vehiculo

        inc_res = await db.execute(select(Incidente).where(Incidente.id == asignacion.incidente_id))
        incidente = inc_res.scalar_one_or_none()
        if incidente:
            veh_res = await db.execute(select(Vehiculo).where(Vehiculo.id == incidente.vehiculo_id))
            vehiculo = veh_res.scalar_one_or_none()
            if vehiculo:
                if vehiculo.peso_kg and unidad.capacidad_carga_kg < vehiculo.peso_kg:
                    raise HTTPException(
                        status_code=400,
                        detail=f"La unidad seleccionada (Placa: {unidad.placa}, Capacidad: {unidad.capacidad_carga_kg} kg) "
                               f"no tiene capacidad de carga suficiente para el vehículo ({vehiculo.marca} {vehiculo.modelo}: {vehiculo.peso_kg} kg)."
                    )
                if vehiculo.tipo in ("camion", "camioneta") and unidad.tipo == "moto_remolque":
                    raise HTTPException(
                        status_code=400,
                        detail=f"No puedes enviar una unidad tipo Moto Remolque para auxiliar un vehículo de tipo {vehiculo.tipo}."
                    )

        asignacion.unidad_auxilio_id = unidad_auxilio_id
        unidad.estado = "ocupado"

    asignacion.tecnico_id = tecnico_id
    tecnico.estado = "ocupado"
    await db.commit()
    await db.refresh(asignacion)

    # Disparar notificaciones push en segundo plano
    try:
        from app.comunicacion.push_service import enviar_notificacion_push
        from app.emergencias.models import Incidente
        from app.acceso_registro.models import Taller

        # 1. Notificar al técnico
        await enviar_notificacion_push(
            usuario_id=tecnico.usuario_id,
            titulo="Nuevo Auxilio Asignado 🛠️",
            cuerpo="Se te ha asignado un nuevo servicio de auxilio mecánico.",
            data={
                "screen": "/seguimiento",
                "incidente_id": str(asignacion.incidente_id),
            },
            db=db
        )

        # 2. Notificar al cliente
        res_i = await db.execute(
            select(Incidente).where(Incidente.id == asignacion.incidente_id)
        )
        inc = res_i.scalar_one_or_none()
        if inc:
            res_tl = await db.execute(
                select(Taller).where(Taller.id == taller_id)
            )
            tl = res_tl.scalar_one_or_none()
            taller_nombre = tl.nombre if tl else "el taller mecánico"
            await enviar_notificacion_push(
                usuario_id=inc.usuario_id,
                titulo="¡Técnico Asignado! 🚗",
                cuerpo=f"El técnico {tecnico.nombre} de {taller_nombre} va en camino.",
                data={
                    "screen": "/seguimiento",
                    "incidente_id": str(asignacion.incidente_id),
                },
                db=db
            )
    except Exception as e:
        print(f"[PushService] Error al disparar notificaciones de asignación: {e}")

    return asignacion


async def listar_unidades(taller_id: int, db: AsyncSession) -> list[UnidadAuxilio]:
    result = await db.execute(
        select(UnidadAuxilio).where(UnidadAuxilio.taller_id == taller_id, UnidadAuxilio.activo.is_(True))
    )
    unidades = list(result.scalars().all())

    # Auto-corregir unidades "ocupado" sin asignación activa real
    ocupadas = [u for u in unidades if u.estado == "ocupado"]
    if ocupadas:
        res = await db.execute(
            select(Asignacion.unidad_auxilio_id)
            .where(
                Asignacion.unidad_auxilio_id.in_([u.id for u in ocupadas]),
                Asignacion.estado.notin_(["cancelado", "finalizado"]),
            )
            .distinct()
        )
        con_asignacion = {row[0] for row in res.all()}
        corregido = False
        for u in ocupadas:
            if u.id not in con_asignacion:
                u.estado = "disponible"
                corregido = True
        if corregido:
            await db.commit()

    return unidades


async def registrar_unidad(taller_id: int, data: UnidadAuxilioCreate, db: AsyncSession) -> UnidadAuxilio:
    taller_res = await db.execute(select(Taller).where(Taller.id == taller_id))
    taller = taller_res.scalar_one_or_none()
    
    unidad = UnidadAuxilio(
        tenant_id=taller.tenant_id if taller else 1,
        taller_id=taller_id,
        placa=data.placa.strip().upper(),
        modelo=data.modelo.strip(),
        tipo=data.tipo.strip(),
        capacidad_carga_kg=data.capacidad_carga_kg,
    )
    db.add(unidad)
    await db.commit()
    await db.refresh(unidad)
    return unidad


async def desactivar_unidad(unidad_id: int, taller_id: int, db: AsyncSession) -> None:
    result = await db.execute(
        select(UnidadAuxilio).where(UnidadAuxilio.id == unidad_id, UnidadAuxilio.taller_id == taller_id)
    )
    unidad = result.scalar_one_or_none()
    if not unidad:
        raise HTTPException(status_code=404, detail="Unidad de auxilio no encontrada")
    unidad.activo = False
    await db.commit()
