# -*- coding: utf-8 -*-
"""EDÉN — Módulo Comercial (FASE 4): catálogo de servicios, clientes y
cotizaciones con ítems reales, límites del dueño e indicadores.
- Catálogo: el DUEÑO lo administra; todos lo consultan. Los ítems de una
  cotización guardan precio/costo SNAPSHOT.
- Clientes: registros comerciales SIN cuenta de usuario; los manejan
  administradores y dueño.
- Cotizaciones: numeración automática COT-AAAA-#####; cálculo central
  (subtotal, descuento, IVA, costo, utilidad, margen); límites de descuento
  y margen mínimo definidos por el dueño (ConfigComercial).
- Estados: borrador → pendiente/enviada → aprobada → convertida (además
  rechazada, vencida). Solo una cotización aprobada se convierte en proyecto.
- PDF: reutiliza el motor de plantillas de la FASE 3.
"""
import re
import json
import os
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.config import ROL_DUENO, ROL_ADMIN
from app.db import get_db, registrar_auditoria
from app.modelos import (
    Cotizacion, CotizacionItem, Servicio, Cliente, ConfigComercial,
    Proyecto, Gasto, Documento, User, Empresa, Marca,
)
from app.seguridad import get_current_user, require_dueno

router = APIRouter()

ESTADOS_VALIDOS = ("borrador", "pendiente", "enviada", "aprobada", "rechazada", "vencida", "convertida")


# ============================================================
# Configuración comercial (límites del dueño)
# ============================================================

def _config_comercial(db: Session) -> ConfigComercial:
    fila = db.execute(select(ConfigComercial).where(ConfigComercial.id == 1)).scalar_one_or_none()
    if not fila:
        fila = ConfigComercial(id=1)
        db.add(fila)
        db.commit()
        db.refresh(fila)
    return fila


@router.get("/config-comercial")
def get_config_comercial(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = _config_comercial(db)
    return {"descuento_max_pct": c.descuento_max_pct, "margen_minimo_pct": c.margen_minimo_pct}


class ConfigComercialIn(BaseModel):
    descuento_max_pct: float = Field(..., ge=0, le=100)
    margen_minimo_pct: float = Field(..., ge=0, le=100)


@router.put("/config-comercial")
def put_config_comercial(datos: ConfigComercialIn, current_user: User = Depends(require_dueno),
                         db: Session = Depends(get_db)):
    c = _config_comercial(db)
    c.descuento_max_pct = datos.descuento_max_pct
    c.margen_minimo_pct = datos.margen_minimo_pct
    db.commit()
    registrar_auditoria(db, "config_comercial_actualizada", usuario=current_user,
                        detalle=f"descuento_max {datos.descuento_max_pct}%, margen_min {datos.margen_minimo_pct}%")
    return {"descuento_max_pct": c.descuento_max_pct, "margen_minimo_pct": c.margen_minimo_pct}


# ============================================================
# Catálogo de servicios
# ============================================================

class ServicioIn(BaseModel):
    codigo: Optional[str] = Field(None, max_length=20)  # si falta se genera por categoría
    nombre: str = Field(..., min_length=1, max_length=150)
    descripcion: str = Field("", max_length=2000)
    categoria: str = Field("servicio", max_length=60)  # servicio | material (desplegable)
    unidad: str = Field("und", max_length=30)
    marca_id: Optional[int] = None
    # material en paquete (rollo/caja): cuántos metros trae cada unidad de venta
    contenido_cantidad: Optional[float] = Field(None, gt=0)
    contenido_unidad: str = Field("metro", max_length=20)
    precio_venta: float = Field(..., ge=0)
    costo_materiales: float = Field(0, ge=0)
    costo_mano_obra: float = Field(0, ge=0)
    tiempo_estimado_horas: float = Field(0, ge=0)
    activo: bool = True


def _siguiente_codigo_servicio(db: Session, categoria: str) -> str:
    prefijo = {"servicio": "SER-", "material": "MAT-"}.get((categoria or "").lower(), "GEN-")
    ultimo = db.execute(select(Servicio.codigo).where(Servicio.codigo.like(prefijo + "%"))
                        .order_by(Servicio.codigo.desc()).limit(1)).scalar()
    n = int(ultimo.split("-")[-1]) + 1 if ultimo else 1
    return f"{prefijo}{n:04d}"


def _servicio_out(s: Servicio, db: Session) -> dict:
    costo = (s.costo_materiales or 0) + (s.costo_mano_obra or 0)
    margen = ((s.precio_venta - costo) / s.precio_venta * 100) if s.precio_venta else 0
    marca = None
    if s.marca_id:
        fila = db.execute(select(Marca).where(Marca.id == s.marca_id)).scalar_one_or_none()
        marca = fila.nombre if fila else None
    precio_por_contenido = None
    if s.contenido_cantidad and s.contenido_cantidad > 0:
        precio_por_contenido = round((s.precio_venta or 0) / s.contenido_cantidad, 2)
    return {
        "id": s.id, "codigo": s.codigo, "nombre": s.nombre, "descripcion": s.descripcion,
        "categoria": s.categoria, "unidad": s.unidad, "marca_id": s.marca_id,
        "marca": marca,
        "contenido_cantidad": s.contenido_cantidad,
        "contenido_unidad": s.contenido_unidad or "metro",
        "precio_por_contenido": precio_por_contenido,
        "precio_venta": s.precio_venta,
        "costo_materiales": s.costo_materiales, "costo_mano_obra": s.costo_mano_obra,
        "costo_total": costo, "margen_pct": round(margen, 1),
        "tiempo_estimado_horas": s.tiempo_estimado_horas, "activo": s.activo,
    }


@router.get("/marcas")
def listar_marcas(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [{"id": m.id, "nombre": m.nombre}
            for m in db.execute(select(Marca).order_by(Marca.nombre)).scalars().all()]


class MarcaIn(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=120)


@router.post("/marcas", status_code=status.HTTP_201_CREATED)
def crear_marca(datos: MarcaIn, current_user: User = Depends(require_dueno),
                db: Session = Depends(get_db)):
    if db.execute(select(Marca).where(Marca.nombre == datos.nombre)).scalar_one_or_none():
        raise HTTPException(400, detail="Ya existe esa marca")
    m = Marca(nombre=datos.nombre.strip()[:120])
    db.add(m)
    db.commit()
    db.refresh(m)
    registrar_auditoria(db, "marca_creada", usuario=current_user, detalle=m.nombre)
    return {"id": m.id, "nombre": m.nombre}


@router.delete("/marcas/{mid}")
def eliminar_marca(mid: int, current_user: User = Depends(require_dueno),
                   db: Session = Depends(get_db)):
    m = db.execute(select(Marca).where(Marca.id == mid)).scalar_one_or_none()
    if not m:
        raise HTTPException(404, detail="Marca no encontrada")
    usada = db.execute(select(Servicio).where(Servicio.marca_id == mid)).first()
    if usada:
        raise HTTPException(409, detail="La marca está en uso por servicios del catálogo")
    db.delete(m)
    db.commit()
    registrar_auditoria(db, "marca_eliminada", usuario=current_user, detalle=m.nombre)
    return {"ok": True}


@router.get("/servicios")
def listar_servicios(q: Optional[str] = None, categoria: Optional[str] = None,
                     only_active: bool = False,
                     current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(Servicio).order_by(Servicio.categoria, Servicio.nombre)
    if q:
        query = query.where(Servicio.nombre.contains(q) | Servicio.codigo.contains(q))
    if categoria:
        query = query.where(Servicio.categoria == categoria)
    if only_active:
        query = query.where(Servicio.activo == True)  # noqa: E712
    return [_servicio_out(s, db) for s in db.execute(query).scalars().all()]


@router.post("/servicios", status_code=status.HTTP_201_CREATED)
def crear_servicio(datos: ServicioIn, current_user: User = Depends(require_dueno),
                   db: Session = Depends(get_db)):
    codigo = (datos.codigo or "").strip() or _siguiente_codigo_servicio(db, datos.categoria)
    if db.execute(select(Servicio).where(Servicio.codigo == codigo)).scalar_one_or_none():
        raise HTTPException(400, detail="Ya existe un servicio con ese código")
    if datos.marca_id and not db.execute(select(Marca).where(Marca.id == datos.marca_id)).scalar_one_or_none():
        raise HTTPException(400, detail="La marca indicada no existe")
    s = Servicio(creado_por_id=current_user.id, codigo=codigo, **datos.model_dump(exclude={"codigo"}))
    db.add(s)
    db.commit()
    db.refresh(s)
    registrar_auditoria(db, "servicio_creado", usuario=current_user, detalle=f"{s.codigo} {s.nombre}")
    return _servicio_out(s, db)


@router.put("/servicios/{sid}")
def editar_servicio(sid: int, datos: ServicioIn, current_user: User = Depends(require_dueno),
                    db: Session = Depends(get_db)):
    s = db.execute(select(Servicio).where(Servicio.id == sid)).scalar_one_or_none()
    if not s:
        raise HTTPException(404, detail="Servicio no encontrado")
    datos_dict = datos.model_dump()
    if datos_dict.get("marca_id") is not None:
        if datos_dict["marca_id"] and not db.execute(
                select(Marca).where(Marca.id == datos_dict["marca_id"])).scalar_one_or_none():
            raise HTTPException(400, detail="La marca indicada no existe")
    if datos_dict.get("codigo"):
        otro = db.execute(select(Servicio).where(Servicio.codigo == datos_dict["codigo"],
                                                 Servicio.id != sid)).scalar_one_or_none()
        if otro:
            raise HTTPException(400, detail="Ya existe un servicio con ese código")
    else:
        datos_dict.pop("codigo", None)
    for campo, valor in datos_dict.items():
        if campo == "codigo" and valor is None:
            continue
        setattr(s, campo, valor)
    db.commit()
    db.refresh(s)
    registrar_auditoria(db, "servicio_editado", usuario=current_user, detalle=f"{s.codigo}")
    return _servicio_out(s, db)


@router.delete("/servicios/{sid}")
def eliminar_servicio(sid: int, current_user: User = Depends(require_dueno),
                      db: Session = Depends(get_db)):
    s = db.execute(select(Servicio).where(Servicio.id == sid)).scalar_one_or_none()
    if not s:
        raise HTTPException(404, detail="Servicio no encontrado")
    usado = db.execute(select(CotizacionItem).where(CotizacionItem.servicio_id == sid)).first()
    if usado:
        s.activo = False
        db.commit()
        registrar_auditoria(db, "servicio_desactivado_por_historial", usuario=current_user, detalle=s.codigo)
        raise HTTPException(409, detail="El servicio se usó en cotizaciones: se desactivó para conservar el historial.")
    db.delete(s)
    db.commit()
    registrar_auditoria(db, "servicio_eliminado", usuario=current_user, detalle=s.codigo)
    return {"ok": True}


# ============================================================
# Clientes
# ============================================================

class ClienteIn(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=200)
    nit: str = Field("", max_length=50)
    contacto: str = Field("", max_length=100)
    telefono: str = Field("", max_length=50)
    correo: str = Field("", max_length=120)
    direccion: str = Field("", max_length=200)
    ciudad: str = Field("", max_length=100)
    descripcion: str = Field("", max_length=2000)
    activo: bool = True


def _cliente_out(c: Cliente) -> dict:
    return {"id": c.id, "nombre": c.nombre, "nit": c.nit, "contacto": c.contacto,
            "telefono": c.telefono, "correo": c.correo, "direccion": c.direccion,
            "ciudad": c.ciudad, "descripcion": c.descripcion, "activo": c.activo,
            "creado_en": c.creado_en.isoformat() if c.creado_en else None}


@router.get("/clientes")
def listar_clientes(q: Optional[str] = None, current_user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    query = select(Cliente).order_by(Cliente.nombre)
    if q:
        query = query.where(Cliente.nombre.contains(q) | Cliente.nit.contains(q))
    return [_cliente_out(c) for c in db.execute(query).scalars().all()]


@router.post("/clientes", status_code=status.HTTP_201_CREATED)
def crear_cliente(datos: ClienteIn, current_user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    if db.execute(select(Cliente).where(Cliente.nombre == datos.nombre)).scalar_one_or_none():
        raise HTTPException(400, detail="Ya existe un cliente con ese nombre")
    c = Cliente(creado_por_id=current_user.id, **datos.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    registrar_auditoria(db, "cliente_creado", usuario=current_user, detalle=c.nombre)
    return _cliente_out(c)


@router.get("/clientes/{cid}")
def get_cliente(cid: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.execute(select(Cliente).where(Cliente.id == cid)).scalar_one_or_none()
    if not c:
        raise HTTPException(404, detail="Cliente no encontrado")
    return _cliente_out(c)


@router.put("/clientes/{cid}")
def editar_cliente(cid: int, datos: ClienteIn, current_user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    c = db.execute(select(Cliente).where(Cliente.id == cid)).scalar_one_or_none()
    if not c:
        raise HTTPException(404, detail="Cliente no encontrado")
    otro = db.execute(select(Cliente).where(Cliente.nombre == datos.nombre,
                                            Cliente.id != cid)).scalar_one_or_none()
    if otro:
        raise HTTPException(400, detail="Ya existe un cliente con ese nombre")
    for campo, valor in datos.model_dump().items():
        setattr(c, campo, valor)
    db.commit()
    registrar_auditoria(db, "cliente_editado", usuario=current_user, detalle=c.nombre)
    return _cliente_out(c)


@router.delete("/clientes/{cid}")
def eliminar_cliente(cid: int, current_user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    c = db.execute(select(Cliente).where(Cliente.id == cid)).scalar_one_or_none()
    if not c:
        raise HTTPException(404, detail="Cliente no encontrado")
    usado = db.execute(select(Cotizacion).where(Cotizacion.cliente_id == cid)).first()
    if usado:
        c.activo = False
        db.commit()
        registrar_auditoria(db, "cliente_desactivado_por_historial", usuario=current_user, detalle=c.nombre)
        raise HTTPException(409, detail="El cliente tiene cotizaciones: se desactivó para conservar el historial.")
    db.delete(c)
    db.commit()
    registrar_auditoria(db, "cliente_eliminado", usuario=current_user, detalle=c.nombre)
    return {"ok": True}


@router.get("/clientes/{cid}/cotizaciones")
def cotizaciones_de_cliente(cid: int, current_user: User = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    c = db.execute(select(Cliente).where(Cliente.id == cid)).scalar_one_or_none()
    if not c:
        raise HTTPException(404, detail="Cliente no encontrado")
    filas = db.execute(select(Cotizacion).where(Cotizacion.cliente_id == cid)
                       .order_by(Cotizacion.id.desc())).scalars().all()
    return [_cotizacion_resumen(x) for x in filas]


# ============================================================
# Cotizaciones
# ============================================================

class ItemIn(BaseModel):
    servicio_id: Optional[int] = None
    descripcion: str = Field(..., min_length=1, max_length=500)
    cantidad: float = Field(..., gt=0)
    unidad: str = Field("und", max_length=30)
    precio_unitario: float = Field(..., ge=0)
    costo_unitario: float = Field(0, ge=0)


class CotizacionIn(BaseModel):
    cliente_id: Optional[int] = None
    cliente: Optional[str] = Field(None, max_length=200)
    descripcion: str = Field("", max_length=2000)
    items: List[ItemIn] = Field(..., min_length=1)
    descuento_pct: float = Field(0, ge=0, le=100)
    iva_pct: float = Field(0, ge=0, le=100)
    tiempo_ejecucion: str = Field("", max_length=120)
    forma_pago: str = Field("", max_length=200)
    vigencia_cotizacion: str = Field("", max_length=120)
    observaciones: str = Field("", max_length=2000)
    estado: str = Field("borrador", pattern="^(borrador|pendiente|enviada)$")


class CotizacionEdit(BaseModel):
    """Reemplazo completo de los datos editables de una cotización."""
    descripcion: str = Field("", max_length=2000)
    items: List[ItemIn] = Field(..., min_length=1)
    descuento_pct: float = Field(0, ge=0, le=100)
    iva_pct: float = Field(0, ge=0, le=100)
    tiempo_ejecucion: str = Field("", max_length=120)
    forma_pago: str = Field("", max_length=200)
    vigencia_cotizacion: str = Field("", max_length=120)
    observaciones: str = Field("", max_length=2000)


class EstadoIn(BaseModel):
    estado: str = Field(..., pattern="^(borrador|pendiente|enviada|aprobada|rechazada|vencida)$")


def _siguiente_numero(db: Session) -> str:
    año = datetime.now().year
    prefijo = f"COT-{año}-"
    ultimo = db.execute(
        select(Cotizacion.numero).where(Cotizacion.numero.like(prefijo + "%"))
        .order_by(Cotizacion.numero.desc()).limit(1)
    ).scalar()
    n = int(ultimo.split("-")[-1]) + 1 if ultimo else 1
    return f"{prefijo}{n:05d}"


def _calcular(items: List[ItemIn], descuento_pct: float, iva_pct: float) -> dict:
    subtotal = sum(i.cantidad * i.precio_unitario for i in items)
    costo = sum(i.cantidad * i.costo_unitario for i in items)
    descuento_valor = subtotal * descuento_pct / 100
    base = subtotal - descuento_valor
    iva_valor = base * iva_pct / 100
    total = base + iva_valor
    utilidad = base - costo
    margen = (utilidad / base * 100) if base > 0 else 0
    return {"subtotal": subtotal, "costo_estimado": costo, "descuento_valor": descuento_valor,
            "iva_valor": iva_valor, "total": total, "utilidad": utilidad, "margen_pct": margen}


def _aplicar_limites(user: User, datos_descuento: float, margen_pct: float, db: Session):
    c = _config_comercial(db)
    if datos_descuento > c.descuento_max_pct:
        raise HTTPException(400, detail=f"El descuento {datos_descuento}% supera el máximo del dueño ({c.descuento_max_pct}%).")
    if user.rol != ROL_DUENO and c.margen_minimo_pct > 0 and margen_pct < c.margen_minimo_pct:
        raise HTTPException(400, detail=f"El margen {margen_pct:.1f}% está por debajo del mínimo del dueño ({c.margen_minimo_pct}%).")


def _guardar_items(db: Session, cot: Cotizacion, items: List[ItemIn]):
    for viejo in db.execute(select(CotizacionItem).where(CotizacionItem.cotizacion_id == cot.id)).scalars().all():
        db.delete(viejo)
    for orden, it in enumerate(items, start=1):
        db.add(CotizacionItem(cotizacion_id=cot.id, servicio_id=it.servicio_id, orden=orden,
                              descripcion=it.descripcion[:500], cantidad=it.cantidad,
                              unidad=it.unidad[:30], precio_unitario=it.precio_unitario,
                              costo_unitario=it.costo_unitario))


def _cotizacion_resumen(c: Cotizacion) -> dict:
    return {
        "id": c.id, "numero": c.numero, "cliente": c.cliente, "cliente_id": c.cliente_id,
        "descripcion": c.descripcion, "estado": c.estado, "subtotal": c.subtotal,
        "descuento_pct": c.descuento_pct, "descuento_valor": c.descuento_valor,
        "iva_pct": c.iva_pct, "iva_valor": c.iva_valor, "total": c.total,
        "costo_estimado": c.costo_estimado, "utilidad": c.utilidad,
        "creado_por_id": c.creado_por_id,
        "creado_en": c.creado_en.isoformat() if c.creado_en else None,
        "documento_id": c.documento_id, "plantilla_id": c.plantilla_id,
    }


def _cotizacion_completa(db: Session, c: Cotizacion) -> dict:
    items = db.execute(select(CotizacionItem).where(CotizacionItem.cotizacion_id == c.id)
                       .order_by(CotizacionItem.orden)).scalars().all()
    salida = _cotizacion_resumen(c)
    salida.update({
        "tiempo_ejecucion": c.tiempo_ejecucion, "forma_pago": c.forma_pago,
        "vigencia_cotizacion": c.vigencia_cotizacion, "observaciones": c.observaciones,
        "plantilla_version": c.plantilla_version,
        "items": [{
            "id": i.id, "servicio_id": i.servicio_id, "orden": i.orden, "descripcion": i.descripcion,
            "cantidad": i.cantidad, "unidad": i.unidad, "precio_unitario": i.precio_unitario,
            "costo_unitario": i.costo_unitario,
        } for i in items],
    })
    return salida


@router.post("/cotizaciones", status_code=status.HTTP_201_CREATED)
def crear_cotizacion(datos: CotizacionIn, current_user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    # cliente: por id o por nombre en texto
    nombre_cliente = datos.cliente
    if datos.cliente_id:
        cliente = db.execute(select(Cliente).where(Cliente.id == datos.cliente_id)).scalar_one_or_none()
        if not cliente:
            raise HTTPException(400, detail="El cliente indicado no existe")
        nombre_cliente = cliente.nombre
    if not nombre_cliente:
        raise HTTPException(400, detail="Indica el cliente (id o nombre)")
    calc = _calcular(datos.items, datos.descuento_pct, datos.iva_pct)
    _aplicar_limites(current_user, datos.descuento_pct, calc["margen_pct"], db)
    cot = Cotizacion(
        numero=_siguiente_numero(db), cliente=nombre_cliente[:200], cliente_id=datos.cliente_id,
        descripcion=datos.descripcion, estado=datos.estado,
        subtotal=calc["subtotal"], descuento_pct=datos.descuento_pct,
        descuento_valor=calc["descuento_valor"], iva_pct=datos.iva_pct,
        iva_valor=calc["iva_valor"], total=calc["total"],
        costo_estimado=calc["costo_estimado"], utilidad=calc["utilidad"],
        tiempo_ejecucion=datos.tiempo_ejecucion, forma_pago=datos.forma_pago,
        vigencia_cotizacion=datos.vigencia_cotizacion, observaciones=datos.observaciones,
        creado_por_id=current_user.id,
    )
    db.add(cot)
    db.commit()
    db.refresh(cot)
    _guardar_items(db, cot, datos.items)
    db.commit()
    registrar_auditoria(db, "cotizacion_creada", usuario=current_user,
                        detalle=f"{cot.numero} {cot.cliente} total {cot.total:,.0f}")
    return _cotizacion_completa(db, cot)


@router.get("/cotizaciones")
def listar_cotizaciones(estado: Optional[str] = None, cliente_id: Optional[int] = None,
                        skip: int = 0, limit: int = 100,
                        current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(Cotizacion).order_by(Cotizacion.id.desc())
    if estado:
        query = query.where(Cotizacion.estado == estado)
    if cliente_id:
        query = query.where(Cotizacion.cliente_id == cliente_id)
    filas = db.execute(query.offset(skip).limit(max(1, min(limit, 200)))).scalars().all()
    return [_cotizacion_resumen(c) for c in filas]


@router.get("/cotizaciones/{cid}")
def get_cotizacion(cid: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.execute(select(Cotizacion).where(Cotizacion.id == cid)).scalar_one_or_none()
    if not c:
        raise HTTPException(404, detail="Cotización no encontrada")
    return _cotizacion_completa(db, c)


@router.put("/cotizaciones/{cid}")
def editar_cotizacion(cid: int, datos: CotizacionEdit,
                      current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.execute(select(Cotizacion).where(Cotizacion.id == cid)).scalar_one_or_none()
    if not c:
        raise HTTPException(404, detail="Cotización no encontrada")
    if c.estado in ("aprobada", "convertida"):
        raise HTTPException(409, detail=f"La cotización está {c.estado}: no se edita. Duplica si necesitas una nueva versión.")
    calc = _calcular(datos.items, datos.descuento_pct, datos.iva_pct)
    _aplicar_limites(current_user, datos.descuento_pct, calc["margen_pct"], db)
    c.descripcion = datos.descripcion
    c.subtotal, c.costo_estimado = calc["subtotal"], calc["costo_estimado"]
    c.descuento_pct, c.descuento_valor = datos.descuento_pct, calc["descuento_valor"]
    c.iva_pct, c.iva_valor = datos.iva_pct, calc["iva_valor"]
    c.total, c.utilidad = calc["total"], calc["utilidad"]
    c.tiempo_ejecucion, c.forma_pago = datos.tiempo_ejecucion, datos.forma_pago
    c.vigencia_cotizacion, c.observaciones = datos.vigencia_cotizacion, datos.observaciones
    _guardar_items(db, c, datos.items)
    db.commit()
    registrar_auditoria(db, "cotizacion_editada", usuario=current_user, detalle=f"{c.numero}")
    return _cotizacion_completa(db, c)


@router.post("/cotizaciones/{cid}/estado")
def cambiar_estado(cid: int, datos: EstadoIn, current_user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    c = db.execute(select(Cotizacion).where(Cotizacion.id == cid)).scalar_one_or_none()
    if not c:
        raise HTTPException(404, detail="Cotización no encontrada")
    if c.estado == "convertida":
        raise HTTPException(409, detail="La cotización ya es un proyecto")
    c.estado = datos.estado
    db.commit()
    registrar_auditoria(db, "cotizacion_estado", usuario=current_user,
                        detalle=f"{c.numero} -> {datos.estado}")
    return _cotizacion_resumen(c)


@router.post("/cotizaciones/{cid}/duplicar")
def duplicar_cotizacion(cid: int, current_user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    c = db.execute(select(Cotizacion).where(Cotizacion.id == cid)).scalar_one_or_none()
    if not c:
        raise HTTPException(404, detail="Cotización no encontrada")
    original = c.numero
    nueva = Cotizacion(
        numero=_siguiente_numero(db), cliente=c.cliente, cliente_id=c.cliente_id,
        descripcion=c.descripcion, estado="borrador",
        subtotal=c.subtotal, descuento_pct=c.descuento_pct, descuento_valor=c.descuento_valor,
        iva_pct=c.iva_pct, iva_valor=c.iva_valor, total=c.total,
        costo_estimado=c.costo_estimado, utilidad=c.utilidad,
        tiempo_ejecucion=c.tiempo_ejecucion, forma_pago=c.forma_pago,
        vigencia_cotizacion=c.vigencia_cotizacion, observaciones=c.observaciones,
        creado_por_id=current_user.id,
    )
    db.add(nueva)
    db.commit()
    db.refresh(nueva)
    for it in db.execute(select(CotizacionItem).where(CotizacionItem.cotizacion_id == cid)
                         .order_by(CotizacionItem.orden)).scalars().all():
        db.add(CotizacionItem(cotizacion_id=nueva.id, servicio_id=it.servicio_id, orden=it.orden,
                              descripcion=it.descripcion, cantidad=it.cantidad, unidad=it.unidad,
                              precio_unitario=it.precio_unitario, costo_unitario=it.costo_unitario))
    db.commit()
    registrar_auditoria(db, "cotizacion_duplicada", usuario=current_user,
                        detalle=f"{original} -> {nueva.numero}")
    return _cotizacion_completa(db, nueva)


def _siguiente_codigo_proyecto(db: Session) -> str:
    ultimo = db.execute(select(Proyecto.codigo).where(Proyecto.codigo.isnot(None))
                        .order_by(Proyecto.codigo.desc()).limit(1)).scalar()
    n = int(ultimo.split("-")[-1]) + 1 if ultimo and ultimo.startswith("PRY-") else 1
    return f"PRY-{n:05d}"


@router.post("/cotizaciones/{cid}/convertir")
def convertir_en_proyecto(cid: int, current_user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    c = db.execute(select(Cotizacion).where(Cotizacion.id == cid)).scalar_one_or_none()
    if not c:
        raise HTTPException(404, detail="Cotización no encontrada")
    if c.estado != "aprobada":
        raise HTTPException(409, detail="Solo las cotizaciones aprobadas se convierten en proyectos")
    if db.execute(select(Proyecto).where(Proyecto.cotizacion_id == cid)).scalar_one_or_none():
        raise HTTPException(409, detail="Esta cotización ya generó un proyecto")
    proy = Proyecto(
        codigo=_siguiente_codigo_proyecto(db),
        nombre=f"{c.numero} — {c.cliente}"[:150], cotizacion_id=cid,
        cliente_id=c.cliente_id, cliente=c.cliente[:200],
        descripcion=c.descripcion or "", presupuesto=c.total or 0.0,
        estado="activo",
    )
    db.add(proy)
    db.commit()
    db.refresh(proy)
    c.estado = "convertida"
    db.commit()
    registrar_auditoria(db, "cotizacion_convertida", usuario=current_user,
                        detalle=f"{c.numero} -> proyecto {proy.codigo}")
    return {"ok": True, "proyecto_id": proy.id, "proyecto_codigo": proy.codigo, "estado": c.estado}


# ---- Generación de PDF con la plantilla (FASE 3) ----

class PdfIn(BaseModel):
    plantilla_id: Optional[int] = None


@router.post("/cotizaciones/{cid}/pdf")
def generar_pdf_cotizacion(cid: int, datos: PdfIn | None = None,
                           current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.execute(select(Cotizacion).where(Cotizacion.id == cid)).scalar_one_or_none()
    if not c:
        raise HTTPException(404, detail="Cotización no encontrada")
    from app.plantillas import (_fila_plantilla, _generar_archivos, _empresa_de_bd,
                                DatosDocumento, ItemEntrada)
    datos_in = datos or PdfIn()
    if datos_in.plantilla_id:
        plantilla = _fila_plantilla(db, datos_in.plantilla_id)
    else:
        plantilla = _predeterminada(db)
    if plantilla is None:
        raise HTTPException(400, detail="No hay plantilla: el dueño debe subir una en la sección Plantillas")
    cliente = db.execute(select(Cliente).where(Cliente.id == c.cliente_id)).scalar_one_or_none() if c.cliente_id else None
    items_db = db.execute(select(CotizacionItem).where(CotizacionItem.cotizacion_id == cid)
                          .order_by(CotizacionItem.orden)).scalars().all()
    doc_in = DatosDocumento(
        numero_cotizacion=c.numero, nombre_cliente=c.cliente,
        documento_cliente=cliente.nit if cliente else "",
        telefono_cliente=cliente.telefono if cliente else "",
        correo_cliente=cliente.correo if cliente else "",
        direccion_cliente=cliente.direccion if cliente else "",
        descripcion_proyecto=c.descripcion or "",
        items=[ItemEntrada(descripcion=i.descripcion, cantidad=i.cantidad, unidad=i.unidad,
                           precio_unitario=i.precio_unitario) for i in items_db],
        descuento_pct=c.descuento_pct, iva_pct=c.iva_pct,
        tiempo_ejecucion=c.tiempo_ejecucion or "", forma_pago=c.forma_pago or "",
        vigencia_cotizacion=c.vigencia_cotizacion or "", observaciones=c.observaciones or "",
    )
    empresa = _empresa_de_bd(db)
    resultado = _generar_archivos(plantilla, doc_in, empresa)
    doc = Documento(
        plantilla_id=plantilla.id, plantilla_version=plantilla.version, tipo="cotizacion",
        numero_cotizacion=c.numero, datos_json=c.numero,
        archivo_docx=resultado["ruta_docx"], archivo_html=resultado["ruta_html"],
        archivo_pdf=resultado["ruta_pdf"], pdf_ok=resultado["pdf_ok"],
        creado_por_id=current_user.id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    c.plantilla_id, c.plantilla_version, c.documento_id = plantilla.id, plantilla.version, doc.id
    db.commit()
    registrar_auditoria(db, "cotizacion_pdf", usuario=current_user,
                        detalle=f"{c.numero} con {plantilla.nombre} v{plantilla.version}")
    return {"documento_id": doc.id, "plantilla": plantilla.nombre,
            "plantilla_version": plantilla.version, "pdf_ok": resultado["pdf_ok"],
            "mensaje": resultado["mensaje"],
            "nombre_archivo_docx": os.path.basename(resultado["ruta_docx"]) if resultado["ruta_docx"] else None,
            "nombre_archivo_pdf": os.path.basename(resultado["ruta_pdf"]) if resultado["ruta_pdf"] else None,
            "documento": doc.id}


def _predeterminada(db: Session):
    from app.modelos import Plantilla
    return db.execute(select(Plantilla).where(Plantilla.es_predeterminada == True,  # noqa: E712
                                              Plantilla.activa == True)).scalar_one_or_none()  # noqa: E712


# ============================================================
# Indicadores reales (sin datos simulados)
# ============================================================

@router.get("/indicadores")
def indicadores(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cot_total = db.execute(select(func.count(Cotizacion.id))).scalar() or 0
    cot_aprobadas = db.execute(select(func.count(Cotizacion.id))
                               .where(Cotizacion.estado == "aprobada")).scalar() or 0
    valor_cotizado = db.execute(select(func.coalesce(func.sum(Cotizacion.total), 0.0))).scalar() or 0.0
    valor_aprobado = db.execute(select(func.coalesce(func.sum(Cotizacion.total), 0.0))
                                .where(Cotizacion.estado == "aprobada")).scalar() or 0.0
    proy_activos = db.execute(select(func.count(Proyecto.id))
                              .where(Proyecto.estado == "activo")).scalar() or 0
    proy_finalizados = db.execute(select(func.count(Proyecto.id))
                                  .where(Proyecto.estado == "finalizado")).scalar() or 0
    gastos_total = db.execute(select(func.coalesce(func.sum(Gasto.monto), 0.0))).scalar() or 0.0
    clientes_total = db.execute(select(func.count(Cliente.id))).scalar() or 0
    # servicios más solicitados del catálogo (por uso en cotizaciones)
    top = db.execute(
        select(CotizacionItem.servicio_id, func.count(CotizacionItem.id).label("usos"))
        .where(CotizacionItem.servicio_id.isnot(None))
        .group_by(CotizacionItem.servicio_id).order_by(func.count(CotizacionItem.id).desc()).limit(5)
    ).all()
    servicios = {s.id: s for s in db.execute(select(Servicio)).scalars().all()}
    mas_solicitados = [{"nombre": servicios[sid].nombre if sid in servicios else "?", "usos": usos}
                       for sid, usos in top]
    return {
        "cotizaciones": {"total": cot_total, "aprobadas": cot_aprobadas,
                         "valor_cotizado": valor_cotizado, "valor_aprobado": valor_aprobado},
        "proyectos": {"activos": proy_activos, "finalizados": proy_finalizados},
        "gastos_total": gastos_total, "clientes_total": clientes_total,
        "servicios_mas_solicitados": mas_solicitados,
    }
