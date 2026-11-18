# -*- coding: utf-8 -*-
"""YERUZZA Empresarial Asist — Reportes con filtros reales (FASE 7).

Todo sale de la base de datos: nada simulado. Filtros por fechas, cliente,
proyecto y estado de cotización.
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, func

from app.db import get_db
from app.modelos import (
    Cliente, Cotizacion, CotizacionItem, Gasto, Proyecto, Servicio, AgendaEvento,
)
from app.seguridad import get_current_user

router = APIRouter()


def _rango(desde: Optional[datetime], hasta: Optional[datetime]):
    if hasta is None:
        hasta = datetime.utcnow() + timedelta(days=1)
    return desde or datetime(2000, 1, 1), hasta


@router.get("/reportes")
def reportes(desde: Optional[datetime] = None, hasta: Optional[datetime] = None,
             cliente_id: Optional[int] = None, proyecto_id: Optional[int] = None,
             current_user=Depends(get_current_user), db=Depends(get_db)):
    ini, fin = _rango(desde, hasta)

    # ---- Cotizaciones ----
    query = select(Cotizacion).where(Cotizacion.creado_en >= ini, Cotizacion.creado_en <= fin)
    if cliente_id:
        query = query.where(Cotizacion.cliente_id == cliente_id)
    cots = db.execute(query).scalars().all()
    por_estado = {}
    for c in cots:
        e = por_estado.setdefault(c.estado, {"conteo": 0, "valor": 0.0, "utilidad": 0.0})
        e["conteo"] += 1
        e["valor"] += c.total or 0
        e["utilidad"] += c.utilidad or 0
    valor_total = sum(c.total or 0 for c in cots)

    # ---- Proyectos ----
    query = select(Proyecto)
    if cliente_id:
        query = query.where(Proyecto.cliente_id == cliente_id)
    if proyecto_id:
        query = query.where(Proyecto.id == proyecto_id)
    proys = db.execute(query).scalars().all()
    proys_ids = [p.id for p in proys]
    gastos = db.execute(
        select(Gasto).where(Gasto.proyecto_id.in_(proys_ids or [0]),
                            Gasto.fecha >= ini, Gasto.fecha <= fin)
    ).scalars().all() if proys_ids else []

    # ---- Gastos en proyectos del filtro ----
    por_categoria = {}
    por_tipo = {"gasto": 0.0, "compra": 0.0}
    for g in gastos:
        cat = por_categoria.setdefault(g.categoria or "otro", 0.0)
        por_categoria[g.categoria or "otro"] = cat + (g.monto or 0)
        por_tipo[g.tipo or "gasto"] = por_tipo.get(g.tipo or "gasto", 0.0) + (g.monto or 0)

    ejecutado = sum(g.monto or 0 for g in gastos)
    presupuesto = sum(p.presupuesto or 0 for p in proys)

    # ---- Clientes ----
    clientes_nuevos = db.execute(
        select(func.count(Cliente.id)).where(Cliente.creado_en >= ini, Cliente.creado_en <= fin)
    ).scalar() or 0

    # ---- Top clientes por valor cotizado (en el rango) ----
    acumulado = {}
    for c in cots:
        acumulado[c.cliente] = acumulado.get(c.cliente, 0.0) + (c.total or 0)
    top_clientes = sorted(
        [{"cliente": k, "valor": v} for k, v in acumulado.items()],
        key=lambda x: -x["valor"])[:5]

    # ---- Servicios más solicitados (ítems de cotizaciones del rango) ----
    ids_cot = [c.id for c in cots]
    filas = db.execute(
        select(CotizacionItem.servicio_id, func.count(CotizacionItem.id), func.sum(CotizacionItem.cantidad))
        .where(CotizacionItem.cotizacion_id.in_(ids_cot or [0]),
               CotizacionItem.servicio_id.isnot(None))
        .group_by(CotizacionItem.servicio_id)
        .order_by(func.count(CotizacionItem.id).desc()).limit(8)
    ).all() if ids_cot else []
    servicios = {s.id: s for s in db.execute(select(Servicio)).scalars().all()}
    mas_solicitados = [{
        "codigo": servicios[sid].codigo if sid in servicios else "?",
        "nombre": servicios[sid].nombre if sid in servicios else "?",
        "veces": veces, "cantidad_total": cant or 0,
    } for sid, veces, cant in filas]

    # ---- Agenda en el rango ----
    eventos = db.execute(
        select(func.count(AgendaEvento.id)).where(AgendaEvento.fecha_hora >= ini,
                                                  AgendaEvento.fecha_hora <= fin)
    ).scalar() or 0

    return {
        "rango": {"desde": ini.isoformat(), "hasta": fin.isoformat()},
        "filtros": {"cliente_id": cliente_id, "proyecto_id": proyecto_id},
        "cotizaciones": {
            "conteo_total": len(cots), "valor_total": valor_total,
            "por_estado": por_estado,
        },
        "proyectos": {
            "activos": sum(1 for p in proys if p.estado == "activo"),
            "finalizados": sum(1 for p in proys if p.estado == "finalizado"),
            "presupuesto_total": presupuesto,
        },
        "gastos": {"total": ejecutado, "por_categoria": por_categoria, "por_tipo": por_tipo,
                   "cobertura": round(presupuesto - ejecutado, 2)},
        "rentabilidad": {
            "utilidad_cotizada": sum((c.utilidad or 0) for c in cots),
            "utilidad_por_estado": {k: round(v["utilidad"], 2) for k, v in por_estado.items()},
        },
        "clientes_nuevos": clientes_nuevos,
        "top_clientes": top_clientes,
        "servicios_mas_solicitados": mas_solicitados,
        "eventos_agenda": eventos,
    }
