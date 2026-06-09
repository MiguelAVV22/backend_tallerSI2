from pydantic import BaseModel
from typing import Dict

class DashboardTallerResponse(BaseModel):
    incidentes_activos: int
    incidentes_finalizados: int
    solicitudes_pendientes: int
    tecnicos_disponibles: int
    tecnicos_ocupados: int
    promedio_tiempo_asignacion_min: float
    promedio_tiempo_llegada_min: float
    incidentes_por_estado: Dict[str, int]
    incidentes_por_tipo: Dict[str, int]

class DashboardKpiResponse(BaseModel):
    tiempo_promedio_asignacion: float
    tiempo_promedio_llegada: float
    tiempo_promedio_resolucion: float
    porcentaje_cumplimiento_sla: float
    tasa_cancelacion: float
    tasa_resolucion: float
    incidentes_por_tipo: Dict[str, int]
    incidentes_por_mes: Dict[str, int]
    sla_por_mes: Dict[str, float]

class TecnicoDesempenoResponse(BaseModel):
    tecnico_id: int
    nombre: str
    especialidad: str
    estado: str
    servicios_atendidos: int
    servicios_finalizados: int
    tiempo_promedio_llegada_min: float
    tiempo_promedio_reparacion_min: float
    calificacion_promedio: float
    porcentaje_cumplimiento: float
    puntaje_desempeno: float
    posicion_ranking: int



