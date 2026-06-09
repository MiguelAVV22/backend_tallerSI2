from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.dependencies import get_current_user, require_role
from app.acceso_registro.models import User
from app.cotizacion_pagos import schemas, service

router = APIRouter()


# ── CU20 · Incidentes disponibles para cotizar ─────────────
@router.get("/incidentes-disponibles", response_model=list[schemas.IncidenteDisponibleResponse])
async def incidentes_disponibles(
    current_user: User = Depends(require_role("taller")),
    db: AsyncSession = Depends(get_db),
):
    from app.talleres_tecnicos.service import get_taller_by_user
    taller = await get_taller_by_user(current_user.id, db)
    return await service.listar_incidentes_disponibles(taller.id, db)


# ── CU20 · Generar cotización ──────────────────────────────
@router.post("/cotizaciones", response_model=schemas.CotizacionResponse, status_code=status.HTTP_201_CREATED)
async def generar_cotizacion(
    data: schemas.CotizacionCreate,
    current_user: User = Depends(require_role("taller")),
    db: AsyncSession = Depends(get_db),
):
    from app.talleres_tecnicos.service import get_taller_by_user
    taller = await get_taller_by_user(current_user.id, db)
    cotizacion = await service.generar_cotizacion(taller.id, data, db)
    return schemas.CotizacionResponse.model_validate(cotizacion)


# ── CU20 · Listar cotizaciones del taller ─────────────────
@router.get("/cotizaciones", response_model=list[schemas.CotizacionResponse])
async def listar_cotizaciones(
    current_user: User = Depends(require_role("taller")),
    db: AsyncSession = Depends(get_db),
):
    from app.talleres_tecnicos.service import get_taller_by_user
    taller = await get_taller_by_user(current_user.id, db)
    cotizaciones = await service.listar_cotizaciones(taller.id, db)
    return [schemas.CotizacionResponse.model_validate(c) for c in cotizaciones]


# ── CU20 · Mis cotizaciones (cliente) ─────────────────────
@router.get("/mis-cotizaciones", response_model=list[schemas.CotizacionResponse])
async def mis_cotizaciones(
    current_user: User = Depends(require_role("cliente")),
    db: AsyncSession = Depends(get_db),
):
    cotizaciones = await service.listar_mis_cotizaciones(current_user.id, db)
    return [schemas.CotizacionResponse.model_validate(c) for c in cotizaciones]


# ── CU20 · Ver cotización por ID ───────────────────────────
@router.get("/cotizaciones/{cotizacion_id}", response_model=schemas.CotizacionResponse)
async def ver_cotizacion(
    cotizacion_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cotizacion = await service.get_cotizacion(cotizacion_id, db)
    return schemas.CotizacionResponse.model_validate(cotizacion)


# ── CU20 · Confirmar / Rechazar cotización ─────────────────
@router.patch("/cotizaciones/{cotizacion_id}/estado", response_model=schemas.CotizacionResponse)
async def actualizar_estado_cotizacion(
    cotizacion_id: int,
    data: schemas.CotizacionEstadoUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cotizacion = await service.actualizar_estado(cotizacion_id, data.estado, db)
    return schemas.CotizacionResponse.model_validate(cotizacion)


# ── CU20 · Realizar pago (cliente) ────────────────────────
@router.post("/pagos", response_model=schemas.PagoResponse, status_code=status.HTTP_201_CREATED)
@router.post("/pago", response_model=schemas.PagoResponse, status_code=status.HTTP_201_CREATED)
async def realizar_pago(
    data: schemas.PagoCreate,
    current_user: User = Depends(require_role("cliente")),
    db: AsyncSession = Depends(get_db),
):
    pago = await service.realizar_pago(current_user.id, data, db)
    return schemas.PagoResponse.model_validate(pago)


@router.get("/incidente/{incidente_id}/resumen-pago")
async def resumen_pago(
    incidente_id: int,
    current_user: User = Depends(require_role("cliente")),
    db: AsyncSession = Depends(get_db),
):
    return await service.obtener_resumen_pago(incidente_id, db)


# ── CU26 · Ver comisiones del taller ──────────────────────
@router.get("/comisiones", response_model=schemas.ComisionesResponse)
async def ver_comisiones(
    current_user: User = Depends(require_role("taller", "admin")),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role == "admin":
        from sqlalchemy import select as sa_select
        from app.cotizacion_pagos.models import Cotizacion, Pago
        result = await db.execute(
            sa_select(Cotizacion, Pago).join(Pago, Pago.cotizacion_id == Cotizacion.id)
            .order_by(Pago.created_at.desc())
        )
        rows = result.all()
        items = []
        for cot, pago in rows:
            comision = round(pago.monto * 0.10, 2)
            items.append(schemas.ComisionItem(
                pago_id=pago.id, cotizacion_id=cot.id, incidente_id=cot.incidente_id,
                monto_bruto=round(pago.monto, 2), comision=comision,
                monto_neto=round(pago.monto - comision, 2),
                metodo=pago.metodo, fecha=pago.created_at,
            ))
        bruto = sum(i.monto_bruto for i in items)
        return schemas.ComisionesResponse(
            taller_id=0, total_servicios=len(items),
            ingresos_brutos=round(bruto, 2), tasa_comision=0.10,
            comision_plataforma=round(bruto * 0.10, 2),
            ingresos_netos=round(bruto * 0.90, 2), pagos=items,
        )

    from app.talleres_tecnicos.service import get_taller_by_user
    taller = await get_taller_by_user(current_user.id, db)
    return await service.listar_comisiones(taller.id, db)
