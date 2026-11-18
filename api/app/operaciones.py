# -*- coding: utf-8 -*-
"""YERUZZA Empresarial Asist — Operaciones (FASE 6): proyectos completos,
gastos y compras, agenda con recordatorios por Telegram, gestor documental
y bóveda de credenciales.
"""
import asyncio
import os
import shutil
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.config import MEDIA_DIR, ROL_DUENO
from app.db import SessionLocal, fernet_desde_secret, registrar_auditoria, get_db
from app.modelos import (
    Proyecto, Gasto, AgendaEvento, Archivo, Credencial,
    Cotizacion, Cliente, User,
)
from app.seguridad import get_current_user, require_dueno

router = APIRouter()
DIR_ARCHIVOS = os.path.join(MEDIA_DIR, "archivos")

ESTADOS_PROYECTO = ("activo", "pausado", "finalizado", "cancelado")


def _nombre_seguro(nombre: str) -> str:
    base = os.path.basename(nombre or "archivo")
    return "".join(c for c in base if c.isalnum() or c in "._- ")[:150] or "archivo"


# ============================================================
# PROYECTOS
# ============================================================

class ProyectoIn(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=150)
    cotizacion_id: Optional[int] = None
    cliente_id: Optional[int] = None
    cliente: Optional[str] = Field(None, max_length=200)
    descripcion: str = Field("", max_length=2000)
    presupuesto: float = Field(0, ge=0)
    fecha_inicio: Optional[datetime] = None


def _proyecto_out(db: Session, p: Proyecto, completo: bool = False) -> dict:
    presupuesto = p.presupuesto or 0.0
    gasto_total = db.execute(
        select(func.coalesce(func.sum(Gasto.monto), 0.0)).where(Gasto.proyecto_id == p.id)
    ).scalar() or 0.0
    salida = {
        "id": p.id, "codigo": p.codigo, "nombre": p.nombre, "estado": p.estado,
        "cliente": p.cliente or "", "cliente_id": p.cliente_id,
        "cotizacion_id": p.cotizacion_id, "presupuesto": presupuesto,
        "gastos_total": gasto_total,
        "saldo": round(presupuesto - gasto_total, 2),
        "avance_pct": p.avance_pct or 0,
        "fecha_inicio": p.fecha_inicio.isoformat() if p.fecha_inicio else None,
        "fecha_fin": p.fecha_fin.isoformat() if p.fecha_fin else None,
        "creado_en": p.creado_en.isoformat() if p.creado_en else None,
    }
    if completo:
        desglose = db.execute(
            select(Gasto.categoria, func.coalesce(func.sum(Gasto.monto), 0.0))
            .where(Gasto.proyecto_id == p.id).group_by(Gasto.categoria)
        ).all()
        cot = db.execute(select(Cotizacion).where(Cotizacion.id == p.cotizacion_id)) \
            .scalar_one_or_none() if p.cotizacion_id else None
        archivos = db.execute(select(func.count(Archivo.id))
                              .where(Archivo.proyecto_id == p.id)).scalar() or 0
        salida.update({
            "descripcion": p.descripcion,
            "desglose_gastos": [{"categoria": cat or "otro", "monto": m} for cat, m in desglose],
            "utilidad_proyectada": round((cot.utilidad if cot else 0), 2),
            "utilidad_real": round(presupuesto - gasto_total, 2),
            "cotizacion": {"numero": cot.numero, "total": cot.total, "estado": cot.estado}
            if cot else None,
            "archivos": archivos,
        })
    return salida


@router.get("/proyectos")
def listar_proyectos(estado: Optional[str] = None,
                     current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(Proyecto).order_by(Proyecto.id.desc())
    if estado:
        query = query.where(Proyecto.estado == estado)
    return [_proyecto_out(db, p) for p in db.execute(query).scalars().all()]


@router.post("/proyectos", status_code=status.HTTP_201_CREATED)
def crear_proyecto(datos: ProyectoIn, current_user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    cliente_nombre = datos.cliente or ""
    if datos.cliente_id:
        cliente = db.execute(select(Cliente).where(Cliente.id == datos.cliente_id)).scalar_one_or_none()
        if not cliente:
            raise HTTPException(400, detail="El cliente indicado no existe")
        cliente_nombre = cliente.nombre
    presupuesto = datos.presupuesto
    cot = db.execute(select(Cotizacion).where(Cotizacion.id == datos.cotizacion_id)) \
        .scalar_one_or_none() if datos.cotizacion_id else None
    if datos.cotizacion_id and not cot:
        raise HTTPException(400, detail="La cotización indicada no existe")
    if cot and not presupuesto:
        presupuesto = cot.total or 0.0
    # numeración
    from app.comercial import _siguiente_codigo_proyecto
    p = Proyecto(
        codigo=_siguiente_codigo_proyecto(db), nombre=datos.nombre[:150],
        cotizacion_id=datos.cotizacion_id,
        cliente_id=datos.cliente_id, cliente=cliente_nombre[:200],
        descripcion=datos.descripcion[:2000], presupuesto=presupuesto,
        fecha_inicio=datos.fecha_inicio, estado="activo",
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    registrar_auditoria(db, "proyecto_creado", usuario=current_user, detalle=f"{p.codigo} {p.nombre}")
    return _proyecto_out(db, p, completo=True)


@router.get("/proyectos/{pid}")
def detalle_proyecto(pid: int, current_user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    p = db.execute(select(Proyecto).where(Proyecto.id == pid)).scalar_one_or_none()
    if not p:
        raise HTTPException(404, detail="Proyecto no encontrado")
    return _proyecto_out(db, p, completo=True)


class ProyectoEdit(BaseModel):
    estado: Optional[str] = Field(None, pattern="^(activo|pausado|finalizado|cancelado)$")
    descripcion: Optional[str] = Field(None, max_length=2000)
    presupuesto: Optional[float] = Field(None, ge=0)
    fecha_fin: Optional[datetime] = None
    avance_pct: Optional[float] = Field(None, ge=0, le=100)


@router.put("/proyectos/{pid}")
def editar_proyecto(pid: int, datos: ProyectoEdit, current_user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    p = db.execute(select(Proyecto).where(Proyecto.id == pid)).scalar_one_or_none()
    if not p:
        raise HTTPException(404, detail="Proyecto no encontrado")
    for campo in ("estado", "descripcion", "presupuesto", "fecha_fin", "avance_pct"):
        valor = getattr(datos, campo)
        if valor is not None:
            setattr(p, campo, valor)
    if datos.estado in ("finalizado", "cancelado") and not p.fecha_fin:
        p.fecha_fin = datetime.utcnow()
    db.commit()
    registrar_auditoria(db, "proyecto_editado", usuario=current_user,
                        detalle=f"{p.codigo}: estado={p.estado}, avance={p.avance_pct}%")
    return _proyecto_out(db, p, completo=True)


# ============================================================
# GASTOS Y COMPRAS
# ============================================================

class GastoIn(BaseModel):
    proyecto_id: int
    descripcion: str = Field(..., min_length=1, max_length=500)
    monto: float = Field(..., gt=0)
    tipo: str = Field("gasto", pattern="^(gasto|compra)$")
    categoria: str = Field("otro", pattern="^(materiales|mano_obra|herramientas|transporte|servicios|otro)$")
    fecha: Optional[datetime] = None


def _gasto_out(g: Gasto) -> dict:
    return {"id": g.id, "proyecto_id": g.proyecto_id, "descripcion": g.descripcion,
            "monto": g.monto, "tipo": g.tipo, "categoria": g.categoria,
            "fecha": g.fecha.isoformat() if g.fecha else None}

@router.post("/gastos", status_code=status.HTTP_201_CREATED)
def crear_gasto(datos: GastoIn, current_user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    p = db.execute(select(Proyecto).where(Proyecto.id == datos.proyecto_id)).scalar_one_or_none()
    if not p:
        raise HTTPException(400, detail="El proyecto indicado no existe")
    g = Gasto(proyecto_id=datos.proyecto_id, descripcion=datos.descripcion[:500],
              monto=datos.monto, tipo=datos.tipo, categoria=datos.categoria,
              fecha=datos.fecha or datetime.utcnow(), creado_por_id=current_user.id)
    db.add(g)
    db.commit()
    db.refresh(g)
    registrar_auditoria(db, "gasto_registrado", usuario=current_user,
                        detalle=f"{p.codigo}: {datos.tipo}/{datos.categoria} {datos.monto:,.0f}")
    return _gasto_out(g)


@router.get("/gastos")
def listar_gastos(proyecto_id: Optional[int] = None, tipo: Optional[str] = None,
                  limit: int = 100, current_user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    query = select(Gasto).order_by(Gasto.id.desc()).limit(max(1, min(limit, 200)))
    if proyecto_id:
        query = query.where(Gasto.proyecto_id == proyecto_id)
    if tipo:
        query = query.where(Gasto.tipo == tipo)
    return [_gasto_out(g) for g in db.execute(query).scalars().all()]


@router.put("/gastos/{gid}")
def editar_gasto(gid: int, datos: GastoIn, current_user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    g = db.execute(select(Gasto).where(Gasto.id == gid)).scalar_one_or_none()
    if not g:
        raise HTTPException(404, detail="Gasto no encontrado")
    p = db.execute(select(Proyecto).where(Proyecto.id == datos.proyecto_id)).scalar_one_or_none()
    if not p:
        raise HTTPException(400, detail="El proyecto indicado no existe")
    g.proyecto_id = datos.proyecto_id
    g.descripcion = datos.descripcion[:500]
    g.monto = datos.monto
    g.tipo = datos.tipo
    g.categoria = datos.categoria
    g.fecha = datos.fecha or g.fecha
    db.commit()
    registrar_auditoria(db, "gasto_editado", usuario=current_user, detalle=f"gasto #{gid}")
    return _gasto_out(g)


# ============================================================
# AGENDA
# ============================================================

class AgendaIn(BaseModel):
    titulo: str = Field(..., min_length=1, max_length=200)
    fecha_hora: datetime
    tipo: str = Field("otro", pattern="^(visita_tecnica|reunion|entrega|vencimiento|seguimiento|otro)$")
    cliente_id: Optional[int] = None
    proyecto_id: Optional[int] = None
    notas: str = Field("", max_length=2000)


def _evento_out(db: Session, e: AgendaEvento) -> dict:
    cliente = db.execute(select(Cliente).where(Cliente.id == e.cliente_id)).scalar_one_or_none() \
        if e.cliente_id else None
    proy = db.execute(select(Proyecto).where(Proyecto.id == e.proyecto_id)).scalar_one_or_none() \
        if e.proyecto_id else None
    return {"id": e.id, "titulo": e.titulo, "tipo": e.tipo,
            "fecha_hora": e.fecha_hora.isoformat() if e.fecha_hora else None,
            "cliente": cliente.nombre if cliente else None,
            "proyecto": proy.nombre if proy else None,
            "notas": e.notas, "recordado": e.recordado,
            "creado_en": e.creado_en.isoformat() if e.creado_en else None}


@router.get("/agenda")
def listar_agenda(dias: int = 7, desde: Optional[datetime] = None,
                  current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    base = desde or datetime.utcnow()
    limite = base + timedelta(days=max(1, min(dias, 90)))
    filas = db.execute(select(AgendaEvento)
                       .where(AgendaEvento.fecha_hora >= base,
                              AgendaEvento.fecha_hora <= limite)
                       .order_by(AgendaEvento.fecha_hora)).scalars().all()
    return [_evento_out(db, e) for e in filas]


@router.post("/agenda", status_code=status.HTTP_201_CREATED)
def crear_evento(datos: AgendaIn, current_user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    e = AgendaEvento(titulo=datos.titulo[:200], fecha_hora=datos.fecha_hora, tipo=datos.tipo,
                     cliente_id=datos.cliente_id, proyecto_id=datos.proyecto_id,
                     notas=datos.notas[:2000], creado_por_id=current_user.id)
    db.add(e)
    db.commit()
    db.refresh(e)
    registrar_auditoria(db, "evento_agenda_creado", usuario=current_user,
                        detalle=f"{datos.titulo} {datos.fecha_hora}")
    return _evento_out(db, e)


@router.delete("/agenda/{eid}")
def eliminar_evento(eid: int, current_user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    e = db.execute(select(AgendaEvento).where(AgendaEvento.id == eid)).scalar_one_or_none()
    if not e:
        raise HTTPException(404, detail="Evento no encontrado")
    db.delete(e)
    db.commit()
    registrar_auditoria(db, "evento_agenda_eliminado", usuario=current_user)
    return {"ok": True}


# ============================================================
# GESTOR DOCUMENTAL
# ============================================================

class ArchivoIn(BaseModel):
    categoria: str = Field("otro", pattern="^(cotizacion|contrato|foto|factura|comprobante|plano|informe|tecnico|cliente|otro)$")
    cliente_id: Optional[int] = None
    proyecto_id: Optional[int] = None
    cotizacion_id: Optional[int] = None


@router.post("/archivos", status_code=status.HTTP_201_CREATED)
async def subir_archivo(archivo: UploadFile = File(...), categoria: str = Form("otro"),
                        cliente_id: Optional[int] = Form(None),
                        proyecto_id: Optional[int] = Form(None),
                        cotizacion_id: Optional[int] = Form(None),
                        current_user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    contenido = await archivo.read()
    if not contenido or len(contenido) > 25 * 1024 * 1024:
        raise HTTPException(400, detail="Archivo vacío o mayor a 25 MB")
    os.makedirs(DIR_ARCHIVOS, exist_ok=True)
    destino = os.path.join(DIR_ARCHIVOS, f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{_nombre_seguro(archivo.filename)}")
    with open(destino, "wb") as f:
        f.write(contenido)
    a = Archivo(nombre=_nombre_seguro(archivo.filename), categoria=categoria,
                archivo_ruta=destino, tamano=len(contenido),
                cliente_id=cliente_id if cliente_id else None,
                proyecto_id=proyecto_id if proyecto_id else None,
                cotizacion_id=cotizacion_id if cotizacion_id else None,
                subido_por_id=current_user.id)
    db.add(a)
    db.commit()
    db.refresh(a)
    registrar_auditoria(db, "archivo_subido", usuario=current_user, detalle=a.nombre)
    return {"id": a.id, "nombre": a.nombre, "categoria": a.categoria, "tamano": a.tamano,
            "cliente_id": a.cliente_id, "proyecto_id": a.proyecto_id,
            "cotizacion_id": a.cotizacion_id}


@router.get("/archivos")
def listar_archivos(cliente_id: Optional[int] = None, proyecto_id: Optional[int] = None,
                    categoria: Optional[str] = None, q: Optional[str] = None,
                    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(Archivo).order_by(Archivo.id.desc()).limit(200)
    if cliente_id:
        query = query.where(Archivo.cliente_id == cliente_id)
    if proyecto_id:
        query = query.where(Archivo.proyecto_id == proyecto_id)
    if categoria:
        query = query.where(Archivo.categoria == categoria)
    if q:
        query = query.where(Archivo.nombre.contains(q))
    return [{
        "id": a.id, "nombre": a.nombre, "categoria": a.categoria, "tamano": a.tamano,
        "cliente_id": a.cliente_id, "proyecto_id": a.proyecto_id, "cotizacion_id": a.cotizacion_id,
        "creado_en": a.creado_en.isoformat() if a.creado_en else None,
    } for a in db.execute(query).scalars().all()]


@router.get("/archivos/{aid}/descarga")
def descargar_archivo(aid: int, current_user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    a = db.execute(select(Archivo).where(Archivo.id == aid)).scalar_one_or_none()
    if not a or not os.path.exists(a.archivo_ruta):
        raise HTTPException(404, detail="Archivo no encontrado")
    registrar_auditoria(db, "archivo_descargado", usuario=current_user, detalle=a.nombre)
    return FileResponse(a.archivo_ruta, filename=a.nombre)


@router.delete("/archivos/{aid}")
def eliminar_archivo(aid: int, current_user: User = Depends(require_dueno),
                     db: Session = Depends(get_db)):
    a = db.execute(select(Archivo).where(Archivo.id == aid)).scalar_one_or_none()
    if not a:
        raise HTTPException(404, detail="Archivo no encontrado")
    db.delete(a)
    db.commit()
    try:
        os.remove(a.archivo_ruta)
    except OSError:
        pass
    registrar_auditoria(db, "archivo_eliminado", usuario=current_user, detalle=a.nombre)
    return {"ok": True}


# ============================================================
# BÓVEDA DE CREDENCIALES (solo dueño; revelar deja huella)
# ============================================================

class CredencialIn(BaseModel):
    plataforma: str = Field(..., min_length=1, max_length=150)
    url: str = Field("", max_length=300)
    usuario_cuenta: str = Field("", max_length=150)
    password: str = Field(..., min_length=4, max_length=200)
    categoria: str = Field("general", max_length=60)
    notas: str = Field("", max_length=2000)


def _credencial_out(c: Credencial) -> dict:
    """Jamás incluye la contraseña."""
    return {"id": c.id, "plataforma": c.plataforma, "url": c.url,
            "usuario_cuenta": c.usuario_cuenta, "categoria": c.categoria,
            "notas": c.notas,
            "creado_en": c.creado_en.isoformat() if c.creado_en else None,
            "actualizado_en": c.actualizado_en.isoformat() if c.actualizado_en else None}


@router.get("/credenciales")
def listar_credenciales(current_user: User = Depends(require_dueno), db: Session = Depends(get_db)):
    return [_credencial_out(c) for c in
            db.execute(select(Credencial).order_by(Credencial.plataforma)).scalars().all()]


@router.post("/credenciales", status_code=status.HTTP_201_CREATED)
def crear_credencial(datos: CredencialIn, current_user: User = Depends(require_dueno),
                     db: Session = Depends(get_db)):
    c = Credencial(plataforma=datos.plataforma[:150], url=datos.url[:300],
                   usuario_cuenta=datos.usuario_cuenta[:150],
                   password_cifrada=fernet_desde_secret().encrypt(datos.password.encode()).decode(),
                   categoria=datos.categoria[:60], notas=datos.notas[:2000])
    db.add(c)
    db.commit()
    db.refresh(c)
    registrar_auditoria(db, "credencial_creada", usuario=current_user, detalle=c.plataforma)
    return _credencial_out(c)


@router.put("/credenciales/{cid}")
def editar_credencial(cid: int, datos: CredencialIn, current_user: User = Depends(require_dueno),
                      db: Session = Depends(get_db)):
    c = db.execute(select(Credencial).where(Credencial.id == cid)).scalar_one_or_none()
    if not c:
        raise HTTPException(404, detail="Credencial no encontrada")
    c.plataforma = datos.plataforma[:150]
    c.url = datos.url[:300]
    c.usuario_cuenta = datos.usuario_cuenta[:150]
    c.password_cifrada = fernet_desde_secret().encrypt(datos.password.encode()).decode()
    c.categoria = datos.categoria[:60]
    c.notas = datos.notas[:2000]
    db.commit()
    registrar_auditoria(db, "credencial_editada", usuario=current_user, detalle=c.plataforma)
    return _credencial_out(c)


@router.delete("/credenciales/{cid}")
def eliminar_credencial(cid: int, current_user: User = Depends(require_dueno),
                        db: Session = Depends(get_db)):
    c = db.execute(select(Credencial).where(Credencial.id == cid)).scalar_one_or_none()
    if not c:
        raise HTTPException(404, detail="Credencial no encontrada")
    db.delete(c)
    db.commit()
    registrar_auditoria(db, "credencial_eliminada", usuario=current_user, detalle=c.plataforma)
    return {"ok": True}


@router.post("/credenciales/{cid}/revelar")
def revelar_credencial(cid: int, current_user: User = Depends(require_dueno),
                       db: Session = Depends(get_db)):
    """Devuelve la contraseña UNA VEZ y queda auditado quién y cuándo."""
    c = db.execute(select(Credencial).where(Credencial.id == cid)).scalar_one_or_none()
    if not c:
        raise HTTPException(404, detail="Credencial no encontrada")
    try:
        clara = fernet_desde_secret().decrypt(c.password_cifrada.encode()).decode()
    except Exception:
        raise HTTPException(500, detail="No se pudo descifrar (¿AUTH_SECRET cambió?): vuelve a guardarla")
    registrar_auditoria(db, "credencial_revelada", usuario=current_user, detalle=c.plataforma)
    return {"password": clara}


# ============================================================
# Recordatorios por Telegram (tarea de fondo)
# ============================================================

_tarea_recordatorios: asyncio.Task | None = None


async def _bucle_recordatorios():
    while True:
        db = SessionLocal()
        try:
            ahora = datetime.utcnow()
            limite = ahora + timedelta(hours=24)
            pendientes = db.execute(
                select(AgendaEvento).where(AgendaEvento.recordado == False,  # noqa: E712
                                           AgendaEvento.fecha_hora >= ahora,
                                           AgendaEvento.fecha_hora <= limite)
            ).scalars().all()
            if pendientes:
                token = _obtener_token_tg(db)
                if token:
                    from app.modelos import TelegramCuenta
                    destino = db.execute(select(TelegramCuenta).where(TelegramCuenta.activo == True)).scalars().all()  # noqa: E712
                    for e in pendientes:
                        texto = (f"⏰ Recordatorio ({e.tipo}): {e.titulo}\n"
                                 f"Fecha: {e.fecha_hora.strftime('%d/%m %H:%M')} UTC")
                        for cuenta in destino:
                            await _enviar_mensaje_tg(token, cuenta.telegram_id, texto, db)
                        e.recordado = True
                    db.commit()
        finally:
            db.close()
        await asyncio.sleep(300)


def _obtener_token_tg(db: Session):
    from app.modelos import TelegramConfig
    from sqlalchemy import select as _sel
    cfg = db.execute(_sel(TelegramConfig).where(TelegramConfig.id == 1)).scalar_one_or_none()
    if not cfg or not cfg.bot_token_cifrado:
        return None
    try:
        return fernet_desde_secret().decrypt(cfg.bot_token_cifrado.encode()).decode()
    except Exception:
        return None


async def _enviar_mensaje_tg(token: str, chat_id: str, texto: str, db: Session) -> bool:
    # reutiliza la del módulo telegram para no duplicar la lógica
    from app.telegram import _enviar_mensaje
    return await _enviar_mensaje(token, chat_id, texto, db)


def arrancar_recordatorios():
    """Reanuda el vigilante de agenda al arrancar la app (idempotente)."""
    global _tarea_recordatorios
    if _tarea_recordatorios is None or _tarea_recordatorios.done():
        _tarea_recordatorios = asyncio.create_task(_bucle_recordatorios())
