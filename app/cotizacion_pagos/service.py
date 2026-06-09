import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException

from app.cotizacion_pagos.models import Cotizacion, Pago
from app.talleres_tecnicos.models import Asignacion
from app.acceso_registro.models import Taller
from app.cotizacion_pagos.schemas import (
    CotizacionCreate, IncidenteDisponibleResponse,
    PagoCreate, ComisionItem, ComisionesResponse,
)

_TASA_COMISION = 0.10  # 10 % plataforma


# ── CU20 · Incidentes disponibles para cotizar ─────────────
async def listar_incidentes_disponibles(taller_id: int, db: AsyncSession) -> list[IncidenteDisponibleResponse]:
    result = await db.execute(
        select(Asignacion).where(
            Asignacion.taller_id == taller_id,
            Asignacion.estado == "aceptado",
        )
    )
    asignaciones = list(result.scalars().all())

    result = await db.execute(
        select(Cotizacion.incidente_id).where(Cotizacion.taller_id == taller_id)
    )
    ya_cotizados = {row for row in result.scalars().all()}

    return [
        IncidenteDisponibleResponse(
            asignacion_id=a.id,
            incidente_id=a.incidente_id,
            estado_asignacion=a.estado,
            created_at=a.created_at,
        )
        for a in asignaciones
        if a.incidente_id not in ya_cotizados
    ]


# ── CU20 · Generar cotización ──────────────────────────────
async def generar_cotizacion(taller_id: int, data: CotizacionCreate, db: AsyncSession) -> Cotizacion:
    result = await db.execute(
        select(Asignacion).where(
            Asignacion.incidente_id == data.incidente_id,
            Asignacion.taller_id == taller_id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Este incidente no está asignado a tu taller")

    result = await db.execute(
        select(Cotizacion).where(
            Cotizacion.incidente_id == data.incidente_id,
            Cotizacion.taller_id == taller_id,
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Ya existe una cotización para este incidente")

    monto_total  = sum(item.cantidad * item.precio_unitario for item in data.items)
    detalle_json = json.dumps([item.model_dump() for item in data.items], ensure_ascii=False)

    cotizacion = Cotizacion(
        incidente_id=data.incidente_id,
        taller_id=taller_id,
        monto_estimado=round(monto_total, 2),
        detalle=detalle_json,
    )
    db.add(cotizacion)
    await db.commit()
    await db.refresh(cotizacion)
    return cotizacion


# ── CU20 · Listar cotizaciones del taller ─────────────────
async def listar_cotizaciones(taller_id: int, db: AsyncSession) -> list[Cotizacion]:
    result = await db.execute(
        select(Cotizacion)
        .where(Cotizacion.taller_id == taller_id)
        .order_by(Cotizacion.created_at.desc())
    )
    return list(result.scalars().all())


# ── CU20 · Mis cotizaciones (cliente) ─────────────────────
async def listar_mis_cotizaciones(usuario_id: int, db: AsyncSession) -> list[Cotizacion]:
    from app.emergencias.models import Incidente
    result = await db.execute(
        select(Cotizacion)
        .join(Incidente, Cotizacion.incidente_id == Incidente.id)
        .where(Incidente.usuario_id == usuario_id)
        .order_by(Cotizacion.created_at.desc())
    )
    return list(result.scalars().all())


# ── CU20 · Ver cotización por ID ───────────────────────────
async def get_cotizacion(cotizacion_id: int, db: AsyncSession) -> Cotizacion:
    result = await db.execute(select(Cotizacion).where(Cotizacion.id == cotizacion_id))
    cotizacion = result.scalar_one_or_none()
    if not cotizacion:
        raise HTTPException(status_code=404, detail="Cotización no encontrada")
    return cotizacion


# ── CU20 · Confirmar / Rechazar ────────────────────────────
async def actualizar_estado(cotizacion_id: int, nuevo_estado: str, db: AsyncSession) -> Cotizacion:
    cotizacion = await get_cotizacion(cotizacion_id, db)
    if cotizacion.estado != "pendiente":
        raise HTTPException(status_code=400, detail="Solo se pueden confirmar cotizaciones en estado pendiente")
    cotizacion.estado = nuevo_estado
    await db.commit()
    await db.refresh(cotizacion)
    return cotizacion


# ── CU20 · Realizar pago (cliente) ────────────────────────
async def realizar_pago(usuario_id: int, data: PagoCreate, db: AsyncSession) -> Pago:
    cotizacion = await get_cotizacion(data.cotizacion_id, db)

    from app.emergencias.models import Incidente
    result = await db.execute(
        select(Incidente).where(
            Incidente.id == cotizacion.incidente_id,
            Incidente.usuario_id == usuario_id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="No tienes permiso para pagar esta cotización")

    if cotizacion.estado != "aceptada":
        raise HTTPException(status_code=400, detail="Solo se puede pagar una cotización aceptada")

    existing = await db.execute(select(Pago).where(Pago.cotizacion_id == data.cotizacion_id))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Esta cotización ya fue pagada")

    pago = Pago(
        cotizacion_id=data.cotizacion_id,
        usuario_id=usuario_id,
        monto=cotizacion.monto_estimado,
        comision=round(cotizacion.monto_estimado * 0.10, 2),
        metodo=data.metodo,
        estado="completado",
    )
    db.add(pago)
    cotizacion.estado = "pagada"
    await db.commit()
    await db.refresh(pago)
    return pago


# ── CU26 · Comisiones del taller ──────────────────────────
async def listar_comisiones(taller_id: int, db: AsyncSession) -> ComisionesResponse:
    result = await db.execute(
        select(Cotizacion, Pago)
        .join(Pago, Pago.cotizacion_id == Cotizacion.id)
        .where(Cotizacion.taller_id == taller_id)
        .order_by(Pago.created_at.desc())
    )
    rows = result.all()

    items: list[ComisionItem] = []
    for cotizacion, pago in rows:
        comision = round(pago.monto * _TASA_COMISION, 2)
        items.append(ComisionItem(
            pago_id=pago.id,
            cotizacion_id=cotizacion.id,
            incidente_id=cotizacion.incidente_id,
            monto_bruto=round(pago.monto, 2),
            comision=comision,
            monto_neto=round(pago.monto - comision, 2),
            metodo=pago.metodo,
            fecha=pago.created_at,
        ))

    bruto = sum(i.monto_bruto for i in items)
    return ComisionesResponse(
        taller_id=taller_id,
        total_servicios=len(items),
        ingresos_brutos=round(bruto, 2),
        tasa_comision=_TASA_COMISION,
        comision_plataforma=round(bruto * _TASA_COMISION, 2),
        ingresos_netos=round(bruto * (1 - _TASA_COMISION), 2),
        pagos=items,
    )


async def obtener_resumen_pago(incidente_id: int, db: AsyncSession) -> dict:
    result = await db.execute(
        select(Cotizacion).where(
            Cotizacion.incidente_id == incidente_id,
            Cotizacion.estado.in_(["aceptada", "pagada"])
        )
    )
    cotizacion = result.scalar_one_or_none()
    if not cotizacion:
        raise HTTPException(status_code=404, detail="No hay cotización aceptada o pagada para este incidente")

    from app.emergencias.models import Incidente
    res_inc = await db.execute(select(Incidente).where(Incidente.id == incidente_id))
    incidente = res_inc.scalar_one_or_none()
    descripcion_incidente = incidente.descripcion if incidente else "—"

    taller_nombre = "Taller"
    if cotizacion.taller_id:
        result_taller = await db.execute(select(Taller).where(Taller.id == cotizacion.taller_id))
        t = result_taller.scalar_one_or_none()
        if t:
            taller_nombre = t.nombre

    # Check if already paid
    res_pago = await db.execute(select(Pago).where(Pago.cotizacion_id == cotizacion.id))
    pago = res_pago.scalar_one_or_none()
    ya_pagada = pago is not None

    return {
        "cotizacion": {
            "id": cotizacion.id,
            "monto_estimado": round(cotizacion.monto_estimado, 2),
        },
        "descripcion_incidente": descripcion_incidente,
        "taller_nombre": taller_nombre,
        "ya_pagada": ya_pagada
    }
