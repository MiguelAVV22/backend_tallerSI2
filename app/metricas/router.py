from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.metricas import service
from app.core.dependencies import require_role

router = APIRouter()


@router.get("/heatmap")
async def get_heatmap(
    current_user = Depends(require_role("taller")),
    db: AsyncSession = Depends(get_db)
):
    """Obtener coordenadas de incidentes para el mapa de calor del tenant del taller."""
    return await service.obtener_heatmap_tenant(current_user.tenant_id, db)

@router.get("/dashboard-taller")
async def dashboard_taller(
    taller_id: int = Query(..., description="ID del taller"),
    db: AsyncSession = Depends(get_db)
):
    """Obtener métricas del dashboard para un taller específico."""
    return await service.obtener_dashboard_taller(taller_id, db)

@router.get("/kpi")
async def kpi(
    taller_id: int = Query(..., description="ID del taller"),
    periodo: str | None = Query(None, description="Periodo (semana, mes, trimestre, anio)"),
    db: AsyncSession = Depends(get_db)
):
    """Obtener KPIs para el taller y periodo solicitado."""
    return await service.obtener_kpis_taller(taller_id, periodo, db)

@router.get("/desempeno-tecnicos")
async def desempeno_tecnicos(
    taller_id: int = Query(..., description="ID del taller"),
    periodo: str | None = Query(None, description="Periodo (semana, mes, trimestre, anio)"),
    db: AsyncSession = Depends(get_db)
):
    """Obtener desempeño de técnicos para el taller y periodo solicitado."""
    return await service.obtener_desempeno_tecnicos(taller_id, periodo, db)
