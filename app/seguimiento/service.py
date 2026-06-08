import logging
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.talleres_tecnicos.models import Tecnico, Asignacion
from app.emergencias.models import Incidente

logger = logging.getLogger(__name__)

async def registrar_actualizacion_tecnico(
    db: AsyncSession,
    incidente_id: int,
    tecnico_id: int,
    latitud: float,
    longitud: float,
    estado_ui: str,
    eta_minutos: int | None
) -> None:
    try:
        # Mapeamos los estados de la UI (EN_CAMINO, LLEGADA, REPARANDO, FINALIZADO, etc.) a los de la DB
        # DB: aceptado | en_camino | en_sitio | en_reparacion | finalizado | cancelado
        mapping = {
            "EN_CAMINO": "en_camino",
            "LLEGADA": "en_sitio",
            "REPARANDO": "en_reparacion",
            "FINALIZADO": "finalizado",
            "ACEPTADO": "aceptado",
            "PENDIENTE": "pendiente",
            "BUSCANDO_TALLER": "pendiente",
        }
        estado_db = mapping.get(estado_ui.upper(), estado_ui.lower())
        
        from sqlalchemy.orm import undefer
        
        tecnico = None
        # 1. Intentar actualizar Tecnico (ubicación y última actualización) usando undefer
        try:
            # Intentamos seleccionar el tecnico cargando explícitamente latitud/longitud
            tec_res = await db.execute(
                select(Tecnico)
                .where(Tecnico.id == tecnico_id)
                .options(
                    undefer(Tecnico.latitud), 
                    undefer(Tecnico.longitud), 
                    undefer(Tecnico.ultima_actualizacion)
                )
            )
            tecnico = tec_res.scalar_one_or_none()
            if tecnico:
                tecnico.latitud = latitud
                tecnico.longitud = longitud
                tecnico.ultima_actualizacion = datetime.now(timezone.utc)
        except Exception as tec_err:
            logger.warning(
                f"No se pudo cargar o actualizar columnas de ubicación en Tecnico (posiblemente no existen en la BD): {tec_err}"
            )
            # Hacemos fallback sin cargar las columnas de ubicación
            try:
                tec_res = await db.execute(select(Tecnico).where(Tecnico.id == tecnico_id))
                tecnico = tec_res.scalar_one_or_none()
            except Exception as fallback_err:
                logger.error(f"Error al buscar técnico en fallback: {fallback_err}")
        
        # 2. Actualizar Asignacion (estado y ETA)
        asig_res = await db.execute(
            select(Asignacion).where(
                Asignacion.incidente_id == incidente_id, 
                Asignacion.tecnico_id == tecnico_id
            )
        )
        asignacion = asig_res.scalar_one_or_none()
        if asignacion:
            if hasattr(asignacion, "estado"):
                asignacion.estado = estado_db
            if hasattr(asignacion, "eta"):
                asignacion.eta = eta_minutos
            
            # Liberar al técnico si finaliza el servicio
            if estado_db in ("finalizado", "cancelado") and tecnico:
                if hasattr(tecnico, "estado"):
                    tecnico.estado = "disponible"
            
            # Si el servicio finaliza o se cancela, actualizar también el estado del incidente
            if estado_db == "finalizado":
                inc_res = await db.execute(select(Incidente).where(Incidente.id == incidente_id))
                inc = inc_res.scalar_one_or_none()
                if inc:
                    inc.estado = "resuelto"
            elif estado_db == "cancelado":
                inc_res = await db.execute(select(Incidente).where(Incidente.id == incidente_id))
                inc = inc_res.scalar_one_or_none()
                if inc:
                    inc.estado = "cancelado"
                
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"Error al guardar actualización de seguimiento en la DB: {e}")
