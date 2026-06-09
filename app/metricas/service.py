import math
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func, and_, exists, or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.talleres_tecnicos.models import Tecnico, Asignacion, ServicioRealizado
from app.emergencias.models import Incidente
from app.acceso_registro.models import Taller

def normalizar_estado(estado_bd: str) -> str:
    est = (estado_bd or "").strip().lower()
    if est == "pendiente":
        return "Pendiente"
    if est == "aceptado":
        return "Aceptado"
    if est in ("en_camino", "en camino"):
        return "En camino"
    if est in ("en_sitio", "llegada"):
        return "Llegada"
    if est in ("en_reparacion", "reparando"):
        return "Reparando"
    if est == "finalizado":
        return "Finalizado"
    if est == "cancelado":
        return "Cancelado"
    return est.capitalize()

async def obtener_dashboard_taller(taller_id: int, db: AsyncSession) -> dict:
    # 1. incidentes_activos: active assignments for this workshop
    activos_res = await db.execute(
        select(func.count(Asignacion.id))
        .where(
            Asignacion.taller_id == taller_id,
            Asignacion.estado.in_(["aceptado", "en_camino", "en_sitio", "llegada", "en_reparacion", "reparando"])
        )
    )
    incidentes_activos = activos_res.scalar() or 0

    # 2. incidentes_finalizados: finalized assignments for this workshop
    finalizados_res = await db.execute(
        select(func.count(Asignacion.id))
        .where(
            Asignacion.taller_id == taller_id,
            Asignacion.estado == "finalizado"
        )
    )
    incidentes_finalizados = finalizados_res.scalar() or 0

    # 3. solicitudes_pendientes: global pending incident reports with no active assignment
    _ESTADOS_CERRADOS = ["cancelado", "finalizado"]
    tiene_asignacion_activa = (
        exists()
        .where(
            and_(
                Asignacion.incidente_id == Incidente.id,
                Asignacion.estado.notin_(_ESTADOS_CERRADOS),
            )
        )
        .correlate(Incidente)
    )
    
    pendientes_res = await db.execute(
        select(func.count(Incidente.id))
        .where(
            Incidente.estado == "pendiente",
            ~tiene_asignacion_activa,
        )
    )
    solicitudes_pendientes = pendientes_res.scalar() or 0

    # 4 & 5. tecnicos_disponibles and tecnicos_ocupados
    tecnicos_res = await db.execute(
        select(Tecnico.id, Tecnico.estado)
        .where(
            Tecnico.taller_id == taller_id,
            Tecnico.activo.is_(True)
        )
    )
    tecnicos = tecnicos_res.all()

    active_asig_res = await db.execute(
        select(Asignacion.tecnico_id)
        .where(
            Asignacion.taller_id == taller_id,
            Asignacion.estado.in_(["aceptado", "en_camino", "en_sitio", "llegada", "en_reparacion", "reparando"]),
            Asignacion.tecnico_id.isnot(None)
        )
    )
    tecnicos_con_asignacion_activa = {row[0] for row in active_asig_res.all()}

    tecnicos_ocupados = 0
    tecnicos_disponibles = 0

    for tec_id, tec_estado in tecnicos:
        is_ocupado = (tec_id in tecnicos_con_asignacion_activa) or (tec_estado == "ocupado")
        if is_ocupado:
            tecnicos_ocupados += 1
        else:
            tecnicos_disponibles += 1

    # 6. promedio_tiempo_asignacion_min
    tiempos_res = await db.execute(
        select(Asignacion.created_at, Incidente.created_at)
        .join(Incidente, Asignacion.incidente_id == Incidente.id)
        .where(Asignacion.taller_id == taller_id)
    )
    tiempos = tiempos_res.all()
    
    promedio_tiempo_asignacion_min = 0.0
    if tiempos:
        diferencias = []
        for asig_time, inc_time in tiempos:
            if asig_time and inc_time:
                diff = (asig_time - inc_time).total_seconds() / 60.0
                diferencias.append(max(0.0, diff))
        if diferencias:
            promedio_tiempo_asignacion_min = sum(diferencias) / len(diferencias)

    # 7. promedio_tiempo_llegada_min
    eta_res = await db.execute(
        select(Asignacion.eta)
        .where(
            Asignacion.taller_id == taller_id,
            Asignacion.eta.isnot(None)
        )
    )
    etas = [row[0] for row in eta_res.all()]
    promedio_tiempo_llegada_min = 0.0
    if etas:
        promedio_tiempo_llegada_min = sum(etas) / len(etas)

    # 8. incidentes_por_estado
    estado_group_res = await db.execute(
        select(Asignacion.estado, func.count(Asignacion.id))
        .where(Asignacion.taller_id == taller_id)
        .group_by(Asignacion.estado)
    )
    
    incidentes_por_estado = {
        "Pendiente": 0,
        "Aceptado": 0,
        "En camino": 0,
        "Llegada": 0,
        "Reparando": 0,
        "Finalizado": 0,
        "Cancelado": 0
    }
    
    for estado_bd, cant in estado_group_res.all():
        norm = normalizar_estado(estado_bd)
        if norm in incidentes_por_estado:
            incidentes_por_estado[norm] = incidentes_por_estado.get(norm, 0) + cant

    # 9. incidentes_por_tipo
    tipo_group_res = await db.execute(
        select(Incidente.tipo_incidente, func.count(Incidente.id))
        .join(Asignacion, Asignacion.incidente_id == Incidente.id)
        .where(Asignacion.taller_id == taller_id)
        .group_by(Incidente.tipo_incidente)
    )
    incidentes_por_tipo = {}
    for tipo, cant in tipo_group_res.all():
        tipo_str = (tipo or "Otros").strip().capitalize()
        if tipo_str == "Mecanico":
            tipo_str = "Mecánico"
        elif tipo_str == "Electrico":
            tipo_str = "Eléctrico"
        elif tipo_str == "Neumatico":
            tipo_str = "Neumático"
        elif tipo_str == "Bateria":
            tipo_str = "Batería"
        elif tipo_str == "Choque":
            tipo_str = "Choque"
        elif tipo_str == "Otros":
            tipo_str = "Otros"
        elif not tipo_str:
            tipo_str = "Otros"
        
        incidentes_por_tipo[tipo_str] = incidentes_por_tipo.get(tipo_str, 0) + cant

    return {
        "incidentes_activos": incidentes_activos,
        "incidentes_finalizados": incidentes_finalizados,
        "solicitudes_pendientes": solicitudes_pendientes,
        "tecnicos_disponibles": tecnicos_disponibles,
        "tecnicos_ocupados": tecnicos_ocupados,
        "promedio_tiempo_asignacion_min": round(promedio_tiempo_asignacion_min, 1),
        "promedio_tiempo_llegada_min": round(promedio_tiempo_llegada_min, 1),
        "incidentes_por_estado": incidentes_por_estado,
        "incidentes_por_tipo": incidentes_por_tipo
    }

async def obtener_kpis_taller(taller_id: int, periodo: str | None, db: AsyncSession) -> dict:
    ahora = datetime.now(timezone.utc)
    fecha_inicio = None
    if periodo:
        p = periodo.strip().lower()
        if p == "semana":
            fecha_inicio = ahora - timedelta(days=7)
        elif p == "mes":
            fecha_inicio = ahora - timedelta(days=30)
        elif p == "trimestre":
            fecha_inicio = ahora - timedelta(days=90)
        elif p == "anio":
            fecha_inicio = ahora - timedelta(days=365)

    # Base query for assignments of this workshop
    query_asig = select(Asignacion).where(Asignacion.taller_id == taller_id)
    if fecha_inicio:
        query_asig = query_asig.where(Asignacion.created_at >= fecha_inicio)
        
    asig_res = await db.execute(query_asig)
    asignaciones = list(asig_res.scalars().all())
    
    total_asig = len(asignaciones)
    
    # Fetch related incidents
    inc_ids = [a.incidente_id for a in asignaciones]
    incidentes = {}
    if inc_ids:
        inc_res = await db.execute(select(Incidente).where(Incidente.id.in_(inc_ids)))
        incidentes = {i.id: i for i in inc_res.scalars().all()}
        
    # Fetch related servicios realizados
    asig_ids = [a.id for a in asignaciones]
    servicios = {}
    if asig_ids:
        serv_res = await db.execute(select(ServicioRealizado).where(ServicioRealizado.asignacion_id.in_(asig_ids)))
        servicios = {s.asignacion_id: s for s in serv_res.scalars().all()}
        
    tiempos_asignacion = []
    tiempos_llegada = []
    tiempos_resolucion = []
    cumple_sla_count = 0
    cancelados_count = 0
    finalizados_count = 0
    
    incidentes_por_tipo = {}
    
    meses_nombres = {
        1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun",
        7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"
    }
    incidentes_por_mes = {name: 0 for name in meses_nombres.values()}
    
    # For monthly SLA compliance
    sla_total_por_mes = {name: 0 for name in meses_nombres.values()}
    sla_cumple_por_mes = {name: 0 for name in meses_nombres.values()}
    
    for a in asignaciones:
        # Group by month
        if a.created_at:
            m_num = a.created_at.month
            m_name = meses_nombres.get(m_num)
            if m_name:
                incidentes_por_mes[m_name] += 1
                sla_total_por_mes[m_name] += 1
                
        inc = incidentes.get(a.incidente_id)
        if inc:
            # 1. Asignacion delay (minutes)
            if a.created_at and inc.created_at:
                diff = (a.created_at - inc.created_at).total_seconds() / 60.0
                diff = max(0.0, diff)
                tiempos_asignacion.append(diff)
                # SLA compliance: response time <= 15 minutes
                if diff <= 15.0:
                    cumple_sla_count += 1
                    if a.created_at:
                        m_num = a.created_at.month
                        m_name = meses_nombres.get(m_num)
                        if m_name:
                            sla_cumple_por_mes[m_name] += 1
            
            # Category grouping
            tipo = (inc.tipo_incidente or "Otros").strip().capitalize()
            if tipo == "Mecanico":
                tipo = "Mecánico"
            elif tipo == "Electrico":
                tipo = "Eléctrico"
            elif tipo == "Neumatico":
                tipo = "Neumático"
            elif tipo == "Bateria":
                tipo = "Batería"
            elif tipo == "Choque":
                tipo = "Choque"
            elif tipo == "Otros":
                tipo = "Otros"
            elif not tipo:
                tipo = "Otros"
            incidentes_por_tipo[tipo] = incidentes_por_tipo.get(tipo, 0) + 1
            
        # 2. Arrival / ETA delay
        if a.eta is not None:
            tiempos_llegada.append(float(a.eta))
            
        # 3. Resolution time (from ServicioRealizado)
        serv = servicios.get(a.id)
        if serv and serv.fecha_cierre and a.created_at:
            diff = (serv.fecha_cierre - a.created_at).total_seconds() / 60.0
            tiempos_resolucion.append(max(0.0, diff))
            
        # 4. Status flags
        if a.estado == "cancelado":
            cancelados_count += 1
        elif a.estado == "finalizado":
            finalizados_count += 1

    # Compute averages and ratios
    tiempo_promedio_asignacion = sum(tiempos_asignacion) / len(tiempos_asignacion) if tiempos_asignacion else 0.0
    tiempo_promedio_llegada = sum(tiempos_llegada) / len(tiempos_llegada) if tiempos_llegada else 0.0
    tiempo_promedio_resolucion = sum(tiempos_resolucion) / len(tiempos_resolucion) if tiempos_resolucion else 0.0
    
    porcentaje_cumplimiento_sla = (cumple_sla_count / total_asig * 100.0) if total_asig > 0 else 0.0
    tasa_cancelacion = (cancelados_count / total_asig * 100.0) if total_asig > 0 else 0.0
    tasa_resolucion = (finalizados_count / total_asig * 100.0) if total_asig > 0 else 0.0

    # Calculate monthly SLA compliance rates
    sla_por_mes = {}
    for m_name in meses_nombres.values():
        total_m = sla_total_por_mes[m_name]
        cumple_m = sla_cumple_por_mes[m_name]
        sla_por_mes[m_name] = round((cumple_m / total_m * 100.0), 1) if total_m > 0 else 0.0

    return {
        "tiempo_promedio_asignacion": round(tiempo_promedio_asignacion, 1),
        "tiempo_promedio_llegada": round(tiempo_promedio_llegada, 1),
        "tiempo_promedio_resolucion": round(tiempo_promedio_resolucion, 1),
        "porcentaje_cumplimiento_sla": round(porcentaje_cumplimiento_sla, 1),
        "tasa_cancelacion": round(tasa_cancelacion, 1),
        "tasa_resolucion": round(tasa_resolucion, 1),
        "incidentes_por_tipo": incidentes_por_tipo,
        "incidentes_por_mes": incidentes_por_mes,
        "sla_por_mes": sla_por_mes
    }

async def obtener_desempeno_tecnicos(taller_id: int, periodo: str | None, db: AsyncSession) -> list[dict]:
    ahora = datetime.now(timezone.utc)
    fecha_inicio = None
    if periodo:
        p = periodo.strip().lower()
        if p == "semana":
            fecha_inicio = ahora - timedelta(days=7)
        elif p == "mes":
            fecha_inicio = ahora - timedelta(days=30)
        elif p == "trimestre":
            fecha_inicio = ahora - timedelta(days=90)
        elif p == "anio":
            fecha_inicio = ahora - timedelta(days=365)

    # 1. Fetch technicians belonging to this workshop
    tec_res = await db.execute(
        select(Tecnico).where(Tecnico.taller_id == taller_id, Tecnico.activo.is_(True))
    )
    tecnicos = list(tec_res.scalars().all())
    
    if not tecnicos:
        return []
        
    tecnicos_ids = [t.id for t in tecnicos]
    
    # 2. Fetch assignments of these technicians in the period
    query_asig = select(Asignacion).where(
        Asignacion.taller_id == taller_id,
        Asignacion.tecnico_id.in_(tecnicos_ids)
    )
    if fecha_inicio:
        query_asig = query_asig.where(Asignacion.created_at >= fecha_inicio)
        
    asig_res = await db.execute(query_asig)
    asignaciones = list(asig_res.scalars().all())
    
    # Group assignments by technician
    asig_by_tec: dict[int, list[Asignacion]] = {tid: [] for tid in tecnicos_ids}
    for a in asignaciones:
        if a.tecnico_id in asig_by_tec:
            asig_by_tec[a.tecnico_id].append(a)
            
    # Fetch related incidents for SLA calculations
    inc_ids = [a.incidente_id for a in asignaciones]
    incidentes = {}
    if inc_ids:
        inc_res = await db.execute(select(Incidente).where(Incidente.id.in_(inc_ids)))
        incidentes = {i.id: i for i in inc_res.scalars().all()}
        
    # Fetch related servicios realizados for repair time
    asig_ids = [a.id for a in asignaciones]
    servicios = {}
    if asig_ids:
        serv_res = await db.execute(select(ServicioRealizado).where(ServicioRealizado.asignacion_id.in_(asig_ids)))
        servicios = {s.asignacion_id: s for s in serv_res.scalars().all()}
        
    results = []
    
    for t in tecnicos:
        t_asigs = asig_by_tec.get(t.id, [])
        servicios_atendidos = len(t_asigs)
        servicios_finalizados = 0
        
        tiempos_llegada = []
        tiempos_reparacion = []
        sla_cumple_count = 0
        
        for a in t_asigs:
            if a.estado == "finalizado":
                servicios_finalizados += 1
                
            # ETA arrival time
            if a.eta is not None:
                tiempos_llegada.append(float(a.eta))
                
            # Repair time
            serv = servicios.get(a.id)
            if serv and serv.fecha_cierre and a.created_at:
                diff = (serv.fecha_cierre - a.created_at).total_seconds() / 60.0
                tiempos_reparacion.append(max(0.0, diff))
                
            # SLA compliance: response time <= 15 minutes
            inc = incidentes.get(a.incidente_id)
            if inc and a.created_at and inc.created_at:
                diff = (a.created_at - inc.created_at).total_seconds() / 60.0
                if diff <= 15.0:
                    sla_cumple_count += 1
                    
        # Compute averages
        tiempo_promedio_llegada_min = sum(tiempos_llegada) / len(tiempos_llegada) if tiempos_llegada else 0.0
        tiempo_promedio_reparacion_min = sum(tiempos_reparacion) / len(tiempos_reparacion) if tiempos_reparacion else 0.0
        calificacion_promedio = 0.0 # No table exists, so default to 0.0
        
        # Calculate sub-scores (0.0 to 100.0)
        finalizados_pct = (servicios_finalizados / servicios_atendidos * 100.0) if servicios_atendidos > 0 else 0.0
        
        if tiempo_promedio_llegada_min == 0.0:
            llegada_pct = 100.0
        elif tiempo_promedio_llegada_min <= 20.0:
            llegada_pct = 100.0
        else:
            llegada_pct = max(0.0, 100.0 - (tiempo_promedio_llegada_min - 20.0) * 2.5)
            
        sla_pct = (sla_cumple_count / servicios_atendidos * 100.0) if servicios_atendidos > 0 else 0.0
        
        # Performance calculation (with weight redistribution if calificacion is 0)
        if calificacion_promedio > 0.0:
            rating_score = (calificacion_promedio / 5.0) * 100.0
            puntaje_desempeno = (0.4 * rating_score) + (0.3 * finalizados_pct) + (0.2 * llegada_pct) + (0.1 * sla_pct)
        else:
            # 40% finalizados, 30% llegada, 30% SLA
            puntaje_desempeno = (0.4 * finalizados_pct) + (0.3 * llegada_pct) + (0.3 * sla_pct)
            
        results.append({
            "tecnico_id": t.id,
            "nombre": t.nombre,
            "especialidad": t.especialidad,
            "estado": t.estado or "disponible",
            "servicios_atendidos": servicios_atendidos,
            "servicios_finalizados": servicios_finalizados,
            "tiempo_promedio_llegada_min": round(tiempo_promedio_llegada_min, 1),
            "tiempo_promedio_reparacion_min": round(tiempo_promedio_reparacion_min, 1),
            "calificacion_promedio": round(calificacion_promedio, 1),
            "porcentaje_cumplimiento": round(sla_pct, 1),
            "puntaje_desempeno": round(puntaje_desempeno, 1),
            "posicion_ranking": 0 # Assigned below
        })
        
    # 3. Sort by performance descending and assign rank positions
    results.sort(key=lambda x: x["puntaje_desempeno"], reverse=True)
    for index, item in enumerate(results):
        item["posicion_ranking"] = index + 1
        
    return results
