from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List

from app.db.session import get_db
from app.core.dependencies import require_role
from app.acceso_registro.models import User
from app.talleres_tecnicos.service import get_taller_by_user
from app.metricas import schemas, service

router = APIRouter()

@router.get("/dashboard-taller", response_model=schemas.DashboardTallerResponse)
async def dashboard_taller(
    current_user: User = Depends(require_role("taller")),
    db: AsyncSession = Depends(get_db),
):
    # Verify that the workshop exists and is approved (raises 403 if not)
    taller = await get_taller_by_user(current_user.id, db)
    
    # Calculate metrics
    metrics_data = await service.obtener_dashboard_taller(taller.id, db)
    
    return metrics_data

@router.get("/kpi", response_model=schemas.DashboardKpiResponse)
async def dashboard_kpi(
    periodo: Optional[str] = None,
    current_user: User = Depends(require_role("taller")),
    db: AsyncSession = Depends(get_db),
):
    # Verify that the workshop exists and is approved (raises 403 if not)
    taller = await get_taller_by_user(current_user.id, db)
    
    # Calculate specialized KPIs
    kpi_data = await service.obtener_kpis_taller(taller.id, periodo, db)
    
    return kpi_data

@router.get("/desempeno-tecnicos", response_model=List[schemas.TecnicoDesempenoResponse])
async def desempeno_tecnicos(
    periodo: Optional[str] = None,
    current_user: User = Depends(require_role("taller")),
    db: AsyncSession = Depends(get_db),
):
    # Verify that the workshop exists and is approved (raises 403 if not)
    taller = await get_taller_by_user(current_user.id, db)
    
    # Calculate performance indicators for technicians
    desempeno_data = await service.obtener_desempeno_tecnicos(taller.id, periodo, db)
    
    return desempeno_data
