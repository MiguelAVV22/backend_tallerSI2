import math
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.dependencies import get_current_user, require_role
from app.acceso_registro.models import User
from app.reportes import schemas, service

router = APIRouter()


# ── CU32 - Recordatorios de mantenimiento ─────────────────
@router.get("/mantenimiento")
async def recordatorios_mantenimiento(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.obtener_recordatorios_mantenimiento(current_user.id, db)


# ── CU28 - Calificar servicio ──────────────────────────────
@router.post("/{solicitud_id}/calificacion")
async def calificar_servicio(solicitud_id: int):
    return {"msg": f"CU28 - calificar servicio {solicitud_id}"}


# ── CU29 - Ver historial de servicios ─────────────────────
@router.get("/historial")
async def historial(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.talleres_tecnicos.models import ServicioRealizado, Asignacion
    from app.cotizacion_pagos.models import Cotizacion
    from app.emergencias.models import Incidente
    from sqlalchemy.orm import undefer as _undefer

    if current_user.role in ("taller", "tecnico"):
        from app.talleres_tecnicos.service import listar_servicios_realizados
        servicios = await listar_servicios_realizados(current_user.id, current_user.role, db)
    elif current_user.role == "cliente":
        res = await db.execute(
            select(ServicioRealizado)
            .join(Asignacion, ServicioRealizado.asignacion_id == Asignacion.id)
            .join(Incidente, Asignacion.incidente_id == Incidente.id)
            .where(Incidente.usuario_id == current_user.id)
            .order_by(ServicioRealizado.fecha_cierre.desc())
        )
        servicios = list(res.scalars().all())
    else:
        servicios = []

    if not servicios:
        return []

    asig_ids = [s.asignacion_id for s in servicios]

    # Mapear asignacion → incidente
    asig_res = await db.execute(
        select(Asignacion.id, Asignacion.incidente_id).where(Asignacion.id.in_(asig_ids))
    )
    asig_to_inc: dict[int, int] = {row[0]: row[1] for row in asig_res.all()}
    inc_ids = list(set(asig_to_inc.values()))

    # Info de incidentes (batch)
    inc_res = await db.execute(
        select(Incidente.id, Incidente.descripcion, Incidente.tipo_incidente)
        .options(_undefer(Incidente.tipo_incidente))
        .where(Incidente.id.in_(inc_ids))
    )
    inc_data: dict[int, dict] = {
        row[0]: {"incidente_id": row[0], "descripcion": row[1], "tipo_incidente": row[2]}
        for row in inc_res.all()
    }

    # Cotizaciones aceptadas/pagadas (batch)
    cot_res = await db.execute(
        select(Cotizacion.incidente_id, Cotizacion.monto_estimado, Cotizacion.estado)
        .where(
            Cotizacion.incidente_id.in_(inc_ids),
            Cotizacion.estado.in_(["aceptada", "pagada"]),
        )
    )
    cot_data: dict[int, float] = {row[0]: row[1] for row in cot_res.all()}

    return [
        {
            "id":                  s.id,
            "asignacion_id":       s.asignacion_id,
            "descripcion_trabajo": s.descripcion_trabajo,
            "repuestos":           s.repuestos,
            "observaciones":       s.observaciones,
            "fecha_cierre":        s.fecha_cierre.isoformat() if s.fecha_cierre else None,
            "monto_cotizacion":    cot_data.get(asig_to_inc.get(s.asignacion_id)),
            **(inc_data.get(asig_to_inc.get(s.asignacion_id, 0), {})),
        }
        for s in servicios
    ]


# ── Métricas del taller ───────────────────────────────────
@router.get("/metricas/taller")
async def metricas_taller(
    desde: Optional[str] = Query(None),
    hasta: Optional[str] = Query(None),
    current_user: User = Depends(require_role("taller")),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select
    from app.cotizacion_pagos.models import Cotizacion, Pago
    from app.talleres_tecnicos.models import Asignacion
    from app.emergencias.models import Incidente
    from app.talleres_tecnicos.service import get_taller_by_user

    taller = await get_taller_by_user(current_user.id, db)

    # Parse optional date filters
    dt_desde: Optional[datetime] = None
    dt_hasta: Optional[datetime] = None
    try:
        if desde:
            dt_desde = datetime.fromisoformat(desde)
        if hasta:
            dt_hasta = datetime.fromisoformat(hasta)
    except ValueError:
        pass

    # All cotizaciones of this workshop
    cot_q = select(Cotizacion).where(Cotizacion.taller_id == taller.id)
    if dt_desde:
        cot_q = cot_q.where(Cotizacion.created_at >= dt_desde)
    if dt_hasta:
        cot_q = cot_q.where(Cotizacion.created_at <= dt_hasta)
    cot_res = await db.execute(cot_q)
    cotizaciones = list(cot_res.scalars().all())

    cot_ids = [c.id for c in cotizaciones]
    cot_map = {c.id: c for c in cotizaciones}
    inc_ids  = list({c.incidente_id for c in cotizaciones})

    # Fetch paid payments for these cotizaciones
    pagos = []
    if cot_ids:
        pag_q = select(Pago).where(Pago.cotizacion_id.in_(cot_ids))
        pag_res = await db.execute(pag_q)
        pagos = list(pag_res.scalars().all())

    # Count finalizados (asignaciones con estado finalizado)
    fin_count = 0
    if inc_ids:
        fin_res = await db.execute(
            select(Asignacion).where(
                Asignacion.taller_id == taller.id,
                Asignacion.estado == "finalizado",
            )
        )
        fin_count = len(fin_res.scalars().all())

    servicios_pagados = len(pagos)
    ingresos_brutos   = round(sum(p.monto for p in pagos), 2)
    comision          = round(sum(p.comision for p in pagos), 2)
    ingresos_netos    = round(ingresos_brutos - comision, 2)
    ticket_promedio   = round(ingresos_brutos / servicios_pagados, 2) if servicios_pagados else 0.0

    detalle_pagos = []
    for p in sorted(pagos, key=lambda x: x.created_at or datetime.min, reverse=True):
        cot = cot_map.get(p.cotizacion_id)
        detalle_pagos.append({
            "pago_id":        p.id,
            "cotizacion_id":  p.cotizacion_id,
            "incidente_id":   cot.incidente_id if cot else None,
            "monto":          round(p.monto, 2),
            "metodo":         p.metodo,
            "fecha":          p.created_at.isoformat() if p.created_at else None,
        })

    return {
        "desde":               desde,
        "hasta":               hasta,
        "total_servicios":     len(cotizaciones),
        "servicios_finalizados": fin_count,
        "servicios_pagados":   servicios_pagados,
        "ingresos_brutos":     ingresos_brutos,
        "comision_plataforma": comision,
        "ingresos_netos":      ingresos_netos,
        "ticket_promedio":     ticket_promedio,
        "promedio_calificacion": None,
        "total_calificaciones": 0,
        "detalle_pagos":       detalle_pagos,
    }


# ── Métricas globales ─────────────────────────────────────
@router.get("/metricas/globales")
async def metricas_globales(
    desde: Optional[str] = Query(None),
    hasta: Optional[str] = Query(None),
    current_user: User = Depends(require_role("admin", "taller")),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select
    from app.cotizacion_pagos.models import Cotizacion, Pago
    from app.talleres_tecnicos.models import Asignacion

    dt_desde: Optional[datetime] = None
    dt_hasta: Optional[datetime] = None
    try:
        if desde:
            dt_desde = datetime.fromisoformat(desde)
        if hasta:
            dt_hasta = datetime.fromisoformat(hasta)
    except ValueError:
        pass

    # All cotizaciones
    cot_q = select(Cotizacion)
    if dt_desde:
        cot_q = cot_q.where(Cotizacion.created_at >= dt_desde)
    if dt_hasta:
        cot_q = cot_q.where(Cotizacion.created_at <= dt_hasta)
    cot_res = await db.execute(cot_q)
    cotizaciones = list(cot_res.scalars().all())
    cot_ids = [c.id for c in cotizaciones]
    cot_map = {c.id: c for c in cotizaciones}

    pagos = []
    if cot_ids:
        pag_res = await db.execute(select(Pago).where(Pago.cotizacion_id.in_(cot_ids)))
        pagos = list(pag_res.scalars().all())

    fin_res = await db.execute(
        select(Asignacion).where(Asignacion.estado == "finalizado")
    )
    fin_count = len(fin_res.scalars().all())

    servicios_pagados = len(pagos)
    ingresos_brutos   = round(sum(p.monto for p in pagos), 2)
    comision          = round(sum(p.comision for p in pagos), 2)
    ingresos_netos    = round(ingresos_brutos - comision, 2)
    ticket_promedio   = round(ingresos_brutos / servicios_pagados, 2) if servicios_pagados else 0.0

    detalle_pagos = []
    for p in sorted(pagos, key=lambda x: x.created_at or datetime.min, reverse=True):
        cot = cot_map.get(p.cotizacion_id)
        detalle_pagos.append({
            "pago_id":       p.id,
            "cotizacion_id": p.cotizacion_id,
            "incidente_id":  cot.incidente_id if cot else None,
            "monto":         round(p.monto, 2),
            "metodo":        p.metodo,
            "fecha":         p.created_at.isoformat() if p.created_at else None,
        })

    return {
        "desde":               desde,
        "hasta":               hasta,
        "total_servicios":     len(cotizaciones),
        "servicios_finalizados": fin_count,
        "servicios_pagados":   servicios_pagados,
        "ingresos_brutos":     ingresos_brutos,
        "comision_plataforma": comision,
        "ingresos_netos":      ingresos_netos,
        "ticket_promedio":     ticket_promedio,
        "promedio_calificacion": None,
        "total_calificaciones": 0,
        "detalle_pagos":       detalle_pagos,
    }


# ── CU35 - Auditoría / Bitácora ────────────────────────────
@router.get("/auditoria", response_model=schemas.AuditoriaListResponse)
async def listar_auditoria(
    desde: Optional[datetime] = Query(None),
    hasta: Optional[datetime] = Query(None),
    accion: Optional[str] = Query(None),
    usuario_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    items, total = await service.listar_eventos(db, desde, hasta, accion, usuario_id, page, size)
    pages = math.ceil(total / size) if total > 0 else 1
    return schemas.AuditoriaListResponse(
        items=[schemas.BitacoraEventoResponse.model_validate(e) for e in items],
        total=total,
        page=page,
        size=size,
        pages=pages,
    )


@router.get("/auditoria/exportar")
async def exportar_auditoria(
    desde: Optional[datetime] = Query(None),
    hasta: Optional[datetime] = Query(None),
    accion: Optional[str] = Query(None),
    usuario_id: Optional[int] = Query(None),
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    csv_content = await service.exportar_csv(db, desde, hasta, accion, usuario_id)
    headers = {
        "Content-Disposition": "attachment; filename=auditoria.csv",
        "Content-Type": "text/csv; charset=utf-8",
    }
    return Response(content=csv_content.encode("utf-8"), headers=headers)


@router.get("/auditoria/{evento_id}", response_model=schemas.BitacoraEventoResponse)
async def detalle_evento(
    evento_id: int,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    evento = await service.obtener_evento(evento_id, db)
    if not evento:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    return schemas.BitacoraEventoResponse.model_validate(evento)
