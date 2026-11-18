# -*- coding: utf-8 -*-
"""YERUZZA Empresarial Asist — Núcleo de Inteligencia Artificial (FASE 5).

- Proveedor OpenAI-compatible (OpenAI directo u OmniRoute) configurado por el
  dueño desde el panel; clave CIFRADA con Fernet, nunca sale del backend.
- Asistente Principal que ENRUTA por especialidad (agente) a un prompt propio:
  comercial, financiero, proyectos, administrativo, seguridad.
- HERRAMIENTAS REALES sobre la base de datos (lee precios, clientes,
  cotizaciones, indicadores). La IA no inventa datos: los pide por herramientas.
- AUTORIZACIÓN HUMANA: toda herramienta de ESCRITURA (crear cliente,
  cotización, servicio, generar PDF) queda como ACCIÓN PENDIENTE que el
  usuario confirma con /confirmar <id> en Telegram o el botón del panel.
- Sin proveedor configurado el núcleo responde con honestidad (sin inventarse
  capacidades), y las herramientas siguen disponibles para la FASE 6+.
"""
import json
import os
import time
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import ROL_DUENO
from app.db import SessionLocal, fernet_desde_secret, registrar_auditoria, get_db
from app.modelos import (
    Cliente, Cotizacion, CotizacionItem, Servicio, Empresa, Proyecto,
    IAConfig, IAMensaje, IAAccion, User,
)
from app.seguridad import get_current_user, require_dueno

router = APIRouter()

# Fallback por variables de entorno (el panel tiene prioridad de una vez guardado)
ENV_IA_BASE = os.getenv("IA_BASE_URL", "")
ENV_IA_KEY = os.getenv("IA_API_KEY", "")
ENV_IA_MODEL = os.getenv("IA_MODEL", "")

AGENTES = {
    "comercial": "Agente Comercial: cotizaciones, clientes, catálogo, precios y propuestas.",
    "financiero": "Agente Financiero: costos, presupuestos, gastos, rentabilidad e indicadores.",
    "proyectos": "Agente de Proyectos: planificación, ejecución, avances y cierre.",
    "administrativo": "Agente Administrativo: agenda, recordatorios, documentos y comunicaciones.",
    "seguridad": "Agente de Seguridad: credenciales, permisos, alertas e integridad.",
}
AGENTE_DEFECTO = "administrativo"


# ============================================================
# Configuración del proveedor
# ============================================================

def _fila_config(db: Session) -> IAConfig:
    fila = db.execute(select(IAConfig).where(IAConfig.id == 1)).scalar_one_or_none()
    if not fila:
        fila = IAConfig(id=1)
        db.add(fila)
        db.commit()
        db.refresh(fila)
    return fila


def _credenciales(db: Session) -> dict | None:
    """Clave/modelo/base efectivos: panel cifrado primero, env como respaldo."""
    cfg = _fila_config(db)
    base = cfg.api_base or ENV_IA_BASE
    modelo = cfg.modelo or ENV_IA_MODEL
    clave = None
    if cfg.api_key_cifrada:
        try:
            clave = fernet_desde_secret().decrypt(cfg.api_key_cifrada.encode()).decode()
        except Exception:
            clave = None
    if not clave and ENV_IA_KEY:
        clave = ENV_IA_KEY
    if not (base and clave and modelo):
        return None
    return {"base": base.rstrip("/"), "clave": clave, "modelo": modelo}


def _config_publica(db: Session) -> dict:
    cfg = _fila_config(db)
    cred = _credenciales(db)
    return {
        "configurado": cred is not None,
        "activo": bool(cfg.activo),
        "api_base": cfg.api_base or ENV_IA_BASE or "",
        "modelo": cfg.modelo or ENV_IA_MODEL or "",
        "estado_texto": cfg.estado_texto,
        "ultima_prueba": cfg.ultima_prueba.isoformat() if cfg.ultima_prueba else None,
        "clave_guardada": bool(cfg.api_key_cifrada or ENV_IA_KEY),
    }


class IAConfigIn(BaseModel):
    api_base: str = Field(..., max_length=300)
    modelo: str = Field(..., max_length=120)
    api_key: str = Field(..., min_length=4, max_length=200)


@router.get("/ia/config")
def get_ia_config(current_user: User = Depends(require_dueno), db: Session = Depends(get_db)):
    return _config_publica(db)


@router.put("/ia/config")
def put_ia_config(datos: IAConfigIn, current_user: User = Depends(require_dueno),
                  db: Session = Depends(get_db)):
    cfg = _fila_config(db)
    cfg.api_base = datos.api_base.rstrip("/")
    cfg.modelo = datos.modelo
    cfg.api_key_cifrada = fernet_desde_secret().encrypt(datos.api_key.encode()).decode()
    db.commit()
    registrar_auditoria(db, "ia_config_guardada", usuario=current_user,
                        detalle=f"{datos.api_base} modelo {datos.modelo}")
    return _config_publica(db)


class IAActivarIn(BaseModel):
    activo: bool


@router.post("/ia/probar")
async def probar_ia(current_user: User = Depends(require_dueno), db: Session = Depends(get_db)):
    """Ping real al proveedor configurado."""
    cred = _credenciales(db)
    cfg = _fila_config(db)
    if not cred:
        cfg.estado_texto = "Falta proveedor/modelo/clave configurada"
        db.commit()
        registrar_auditoria(db, "ia_prueba", usuario=current_user, detalle="FALLÓ: sin credenciales")
        return {"ok": False, "estado_texto": cfg.estado_texto}
    try:
        texto = await _completar(cred, [
            {"role": "user", "content": 'Responde solo OK'}],
            herramientas=None)
        cfg.estado_texto = f"Conectado ({cred['modelo']})"
        cfg.ultima_prueba = datetime.utcnow()
        db.commit()
        registrar_auditoria(db, "ia_prueba", usuario=current_user, detalle="OK")
        return {"ok": True, "estado_texto": cfg.estado_texto, "respuesta": texto[:80]}
    except IAError as e:
        cfg.estado_texto = f"Prueba falló: {str(e)[:150]}"
        cfg.ultima_prueba = datetime.utcnow()
        db.commit()
        registrar_auditoria(db, "ia_prueba", usuario=current_user, detalle="FALLÓ")
        return {"ok": False, "estado_texto": cfg.estado_texto}


@router.post("/ia/activar")
def activar_ia(datos: IAActivarIn, current_user: User = Depends(require_dueno),
               db: Session = Depends(get_db)):
    cfg = _fila_config(db)
    cred = _credenciales(db)
    if datos.activo and not cred:
        raise HTTPException(400, detail="Configura proveedor, modelo y clave antes de activar")
    cfg.activo = bool(datos.activo)
    cfg.estado_texto = "Activo" if datos.activo else "Desactivado"
    db.commit()
    registrar_auditoria(db, "ia_activada" if datos.activo else "ia_desactivada",
                        usuario=current_user)
    return _config_publica(db)


class IAError(Exception):
    pass


# ============================================================
# Cliente del proveedor (compatible OpenAI /chat/completions)
# ============================================================

async def _completar(cred: dict, mensajes: list, herramientas: list | None,
                     temperatura: float = 0.2) -> dict:
    """Una llamada; devuelve el message crudo (content / tool_calls)."""
    cuerpo = {"model": cred["modelo"], "messages": mensajes, "temperature": temperatura}
    if herramientas:
        cuerpo["tools"] = herramientas
        cuerpo["tool_choice"] = "auto"
    try:
        async with httpx.AsyncClient(timeout=90) as cliente:
            resp = await cliente.post(
                f"{cred['base']}/chat/completions",
                headers={"Authorization": f"Bearer {cred['clave']}"},
                json=cuerpo,
            )
    except httpx.RequestError as e:
        raise IAError(f"Sin conexión con el proveedor de IA ({type(e).__name__})")
    try:
        datos = resp.json()
    except Exception:
        raise IAError(f"Respuesta no válida del proveedor (HTTP {resp.status_code})")
    if resp.status_code != 200 or datos.get("error"):
        descripcion = str(datos.get("error", {}).get("message") if isinstance(datos.get("error"), dict)
                          else datos.get("error") or datos.get("detail") or f"HTTP {resp.status_code}")
        raise IAError(f"El proveedor rechazó la llamada: {descripcion[:200]}")
    try:
        return datos["choices"][0]["message"]
    except (KeyError, IndexError):
        raise IAError("El proveedor no devolvió una respuesta interpretable")


# ============================================================
# HERRAMIENTAS REALES (lecturas; escrituras van a autorización humana)
# ============================================================

def _fmt(v) -> str:
    return f"${float(v or 0):,.0f}".replace(",", ".")


def _lista_servicios(db: Session, args: dict) -> str:
    query = select(Servicio).where(Servicio.activo == True)  # noqa: E712
    if args.get("q"):
        query = query.where(Servicio.nombre.contains(args["q"]))
    filas = db.execute(query.limit(30)).scalars().all()
    if not filas:
        return json.dumps({"servicios": [], "nota": "catálogo vacío o sin coincidencias"}, ensure_ascii=False)
    return json.dumps({"servicios": [{
        "codigo": s.codigo, "nombre": s.nombre, "unidad": s.unidad,
        "precio_venta": s.precio_venta, "costo_total": (s.costo_materiales or 0) + (s.costo_mano_obra or 0),
    } for s in filas]}, ensure_ascii=False)


def _lista_clientes(db: Session, args: dict) -> str:
    query = select(Cliente).where(Cliente.activo == True)  # noqa: E712
    if args.get("q"):
        query = query.where(Cliente.nombre.contains(args["q"]))
    filas = db.execute(query.limit(30)).scalars().all()
    return json.dumps({"clientes": [{
        "id": c.id, "nombre": c.nombre, "nit": c.nit, "ciudad": c.ciudad, "telefono": c.telefono,
    } for c in filas]}, ensure_ascii=False)


def _lista_cotizaciones(db: Session, args: dict) -> str:
    query = select(Cotizacion).order_by(Cotizacion.id.desc()).limit(20)
    if args.get("estado"):
        query = query.where(Cotizacion.estado == args["estado"])
    filas = db.execute(query).scalars().all()
    return json.dumps({"cotizaciones": [{
        "numero": c.numero, "cliente": c.cliente, "estado": c.estado,
        "total": c.total, "total_formateado": _fmt(c.total), "utilidad": c.utilidad,
        "id": c.id,
    } for c in filas]}, ensure_ascii=False)


def _consultar_cotizacion(db: Session, args: dict) -> str:
    numero = (args.get("numero") or "").strip()
    cid = args.get("id")
    query = select(Cotizacion)
    cot = None
    if cid:
        cot = db.execute(query.where(Cotizacion.id == int(cid))).scalar_one_or_none()
    elif numero:
        cot = db.execute(query.where(Cotizacion.numero.contains(numero))).scalar_one_or_none()
    if not cot:
        return json.dumps({"error": "cotización no encontrada"}, ensure_ascii=False)
    items = db.execute(select(CotizacionItem).where(CotizacionItem.cotizacion_id == cot.id)
                       .order_by(CotizacionItem.orden)).scalars().all()
    return json.dumps({
        "numero": cot.numero, "cliente": cot.cliente, "estado": cot.estado,
        "subtotal": cot.subtotal, "descuento_pct": cot.descuento_pct, "iva_pct": cot.iva_pct,
        "total": cot.total, "total_formateado": _fmt(cot.total),
        "costo_estimado": cot.costo_estimado, "utilidad": cot.utilidad,
        "observaciones": cot.observaciones,
        "items": [{"descripcion": i.descripcion, "cantidad": i.cantidad, "unidad": i.unidad,
                   "precio_unitario": i.precio_unitario} for i in items],
    }, ensure_ascii=False)


def _indicadores(db: Session, args: dict) -> str:
    from sqlalchemy import func
    total = db.execute(select(func.coalesce(func.sum(Cotizacion.total), 0.0))).scalar()
    aprobado = db.execute(select(func.coalesce(func.sum(Cotizacion.total), 0.0))
                          .where(Cotizacion.estado == "aprobada")).scalar()
    n_aprob = db.execute(select(func.count(Cotizacion.id))
                         .where(Cotizacion.estado == "aprobada")).scalar()
    proy = db.execute(select(func.count(Proyecto.id)).where(Proyecto.estado == "activo")).scalar()
    clientes = db.execute(select(func.count(Cliente.id))).scalar()
    return json.dumps({
        "valor_cotizado": total, "valor_cotizado_formateado": _fmt(total),
        "valor_aprobado": aprobado, "cotizaciones_aprobadas": n_aprob,
        "proyectos_activos": proy, "clientes": clientes,
    }, ensure_ascii=False)


def _lista_proyectos(db: Session, args: dict) -> str:
    filas = db.execute(select(Proyecto).order_by(Proyecto.id.desc()).limit(20)).scalars().all()
    return json.dumps({"proyectos": [{
        "id": p.id, "nombre": p.nombre, "estado": p.estado,
        "cotizacion_id": p.cotizacion_id,
    } for p in filas]}, ensure_ascii=False)


# --- herramientas de ESCRITURA (siempre requieren autorización humana) ---

def _resumen_crear_cliente(args: dict) -> str:
    return f"Crear cliente: **{args.get('nombre')}** (NIT {args.get('nit') or '—'}, "\
           f"ciudad {args.get('ciudad') or '—'})"


def _ejecutar_crear_cliente(db: Session, args: dict, usuario: User | None) -> dict:
    if not args.get("nombre"):
        return {"ok": False, "error": "falta nombre del cliente"}
    ya = db.execute(select(Cliente).where(Cliente.nombre == args["nombre"])).scalar_one_or_none()
    if ya:
        return {"ok": False, "error": f"ya existe un cliente llamado {args['nombre']}"}
    c = Cliente(nombre=str(args["nombre"])[:200], nit=str(args.get("nit") or "")[:50],
                contacto=str(args.get("contacto") or "")[:100],
                telefono=str(args.get("telefono") or "")[:50],
                correo=str(args.get("correo") or "")[:120],
                ciudad=str(args.get("ciudad") or "")[:100],
                creado_por_id=usuario.id if usuario else None)
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"ok": True, "cliente_id": c.id, "nombre": c.nombre}


def _resumen_crear_cotizacion(args: dict) -> str:
    items = args.get("items", [])
    subtotal = sum(float(i.get("cantidad", 0)) * float(i.get("precio_unitario", 0)) for i in items)
    return (f"Crear cotización para **{args.get('nombre_cliente')}** con {len(items)} ítems "
            f"(subtotal aporox. {_fmt(subtotal)})")


def _ejecutar_crear_cotizacion(db: Session, args: dict, usuario: User | None) -> dict:
    if not usuario:
        return {"ok": False, "error": "sin usuario autorizado"}
    if usuario.rol != ROL_DUENO:
        # los admins pueden cotizar; el límite de margen/descuento se aplica igual que en el API
        pass
    items = args.get("items") or []
    if not args.get("nombre_cliente") or not items:
        return {"ok": False, "error": "falta nombre_cliente o items"}
    descuento = float(args.get("descuento_pct", 0))
    iva = float(args.get("iva_pct", 19))
    subtotal = sum(float(i.get("cantidad", 0)) * float(i.get("precio_unitario", 0)) for i in items)
    costo = sum(float(i.get("cantidad", 0)) * float(i.get("costo_unitario", 0)) for i in items)
    desc = subtotal * descuento / 100
    base = subtotal - desc
    iva_v = base * iva / 100
    total = base + iva_v
    utilidad = base - costo
    margen = (utilidad / base * 100) if base > 0 else 0
    from app.comercial import _siguiente_numero as siguiente, _config_comercial
    cc = _config_comercial(db)
    if cc and descuento > cc.descuento_max_pct:
        return {"ok": False, "error": f"descuento {descuento}% supera el máximo del dueño ({cc.descuento_max_pct}%)"}
    if cc and usuario.rol != ROL_DUENO and margen < cc.margen_minimo_pct:
        return {"ok": False, "error": f"margen {margen:.1f}% bajo el mínimo del dueño ({cc.margen_minimo_pct}%)"}
    cliente = db.execute(
        select(Cliente).where(Cliente.nombre.contains(args["nombre_cliente"]))
        .order_by(Cliente.id).limit(1)
    ).scalars().first()
    cot = Cotizacion(
        numero=siguiente(db), cliente=str(args["nombre_cliente"])[:200],
        cliente_id=cliente.id if cliente else None,
        descripcion=str(args.get("descripcion") or "")[:2000],
        estado="borrador", subtotal=subtotal, descuento_pct=descuento,
        descuento_valor=desc, iva_pct=iva, iva_valor=iva_v, total=total,
        costo_estimado=costo, utilidad=utilidad,
        forma_pago=str(args.get("forma_pago") or "")[:200],
        observaciones=str(args.get("observaciones") or "")[:2000],
        creado_por_id=usuario.id,
    )
    db.add(cot)
    db.commit()
    db.refresh(cot)
    for orden, i in enumerate(items, start=1):
        db.add(CotizacionItem(cotizacion_id=cot.id, orden=orden,
                              descripcion=str(i.get("descripcion", "Ítem"))[:500],
                              cantidad=float(i.get("cantidad", 1)),
                              unidad=str(i.get("unidad", "und"))[:30],
                              precio_unitario=float(i.get("precio_unitario", 0)),
                              costo_unitario=float(i.get("costo_unitario", 0))))
    db.commit()
    registrar_auditoria(db, "ia_cotizacion_creada", usuario=usuario,
                        detalle=f"{cot.numero} via IA autorizada")
    return {"ok": True, "numero": cot.numero, "cotizacion_id": cot.id,
            "total_formateado": _fmt(total), "margen_pct": round(margen, 1)}


def _resumen_generar_pdf(args: dict) -> str:
    return f"Generar documento PDF de la cotización **{args.get('numero')}**"


def _ejecutar_generar_pdf(db: Session, args: dict, usuario: User | None) -> dict:
    numero = (args.get("numero") or "").strip()
    cot = db.execute(select(Cotizacion).where(Cotizacion.numero.contains(numero))).scalar_one_or_none()
    if not cot:
        return {"ok": False, "error": f"cotización {numero or '?'} no encontrada"}
    from app.comercial import _predeterminada
    from app.plantillas import _generar_archivos, _empresa_de_bd, DatosDocumento, ItemEntrada
    plantilla = _predeterminada(db)
    if not plantilla:
        return {"ok": False, "error": "no hay plantilla predeterminada; el dueño debe subir una en Plantillas"}
    cliente = db.execute(select(Cliente).where(Cliente.id == cot.cliente_id)).scalar_one_or_none() \
        if cot.cliente_id else None
    items = db.execute(select(CotizacionItem).where(CotizacionItem.cotizacion_id == cot.id)
                       .order_by(CotizacionItem.orden)).scalars().all()
    doc_in = DatosDocumento(
        numero_cotizacion=cot.numero, nombre_cliente=cot.cliente,
        documento_cliente=cliente.nit if cliente else "",
        telefono_cliente=cliente.telefono if cliente else "",
        correo_cliente=cliente.correo if cliente else "",
        descripcion_proyecto=cot.descripcion or "",
        items=[ItemEntrada(descripcion=i.descripcion, cantidad=i.cantidad, unidad=i.unidad,
                           precio_unitario=i.precio_unitario) for i in items],
        descuento_pct=cot.descuento_pct or 0, iva_pct=cot.iva_pct or 0,
        forma_pago=cot.forma_pago or "", vigencia_cotizacion=cot.vigencia_cotizacion or "",
        observaciones=cot.observaciones or "")
    resultado = _generar_archivos(plantilla, doc_in, _empresa_de_bd(db))
    from app.modelos import Documento
    doc = Documento(plantilla_id=plantilla.id, plantilla_version=plantilla.version, tipo="cotizacion",
                    numero_cotizacion=cot.numero, datos_json=cot.numero,
                    archivo_docx=resultado["ruta_docx"], archivo_pdf=resultado["ruta_pdf"],
                    archivo_html=resultado["ruta_html"], pdf_ok=resultado["pdf_ok"],
                    creado_por_id=usuario.id if usuario else None)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    cot.plantilla_id, cot.plantilla_version, cot.documento_id = plantilla.id, plantilla.version, doc.id
    db.commit()
    return {"ok": True, "documento_id": doc.id, "numero": cot.numero,
            "pdf_ok": resultado["pdf_ok"],
            "archivo_docx": resultado["ruta_docx"], "archivo_pdf": resultado["ruta_pdf"],
            "mensaje": resultado["mensaje"]}


# Registro de herramientas: lectura (ejecuta ya) | escritura (va a autorización)
HERRAMIENTAS = {
    "listar_servicios": {"tipo": "lectura", "fn": _lista_servicios,
                         "desc": "Catálogo de servicios activos con precios y costos vigentes. Args: {q?}.",
                         "schema": {"type": "object", "properties": {"q": {"type": "string"}}}},
    "listar_clientes": {"tipo": "lectura", "fn": _lista_clientes,
                        "desc": "Clientes registrados. Args: {q?}.",
                        "schema": {"type": "object", "properties": {"q": {"type": "string"}}}},
    "listar_cotizaciones": {"tipo": "lectura", "fn": _lista_cotizaciones,
                            "desc": "Últimas cotizaciones. Args: {estado?: borrador|pendiente|enviada|aprobada|rechazada|vencida|convertida}.",
                            "schema": {"type": "object", "properties": {"estado": {"type": "string"}}}},
    "consultar_cotizacion": {"tipo": "lectura", "fn": _consultar_cotizacion,
                             "desc": "Detalle de una cotización por numero o id.",
                             "schema": {"type": "object",
                                        "properties": {"numero": {"type": "string"}, "id": {"type": "integer"}}}},
    "listar_proyectos": {"tipo": "lectura", "fn": _lista_proyectos,
                         "desc": "Proyectos registrados. Sin argumentos relevantes.",
                         "schema": {"type": "object", "properties": {}}},
    "consultar_indicadores": {"tipo": "lectura", "fn": _indicadores,
                              "desc": "Indicadores financieros/comerciales reales: valor cotizado, aprobado, proyectos, clientes.",
                              "schema": {"type": "object", "properties": {}}},
    "crear_cliente": {"tipo": "escritura", "resumen_fn": _resumen_crear_cliente,
                      "ejecutar_fn": _ejecutar_crear_cliente,
                      "desc": "PROPUESTA de creación de cliente (requiere confirmación humana). Args: {nombre, nit?, contacto?, telefono?, correo?, ciudad?}.",
                      "schema": {"type": "object",
                                 "required": ["nombre"],
                                 "properties": {"nombre": {"type": "string"}, "nit": {"type": "string"},
                                                "contacto": {"type": "string"}, "telefono": {"type": "string"},
                                                "correo": {"type": "string"}, "ciudad": {"type": "string"}}}},
    "crear_cotizacion": {"tipo": "escritura", "resumen_fn": _resumen_crear_cotizacion,
                         "ejecutar_fn": _ejecutar_crear_cotizacion,
                         "desc": "PROPUESTA de cotización nueva (requiere confirmación humana). Usa PRECIO REAL del catálogo vía listar_servicios. Args: {nombre_cliente, items:[{descripcion, cantidad, unidad, precio_unitario, costo_unitario?}], descuento_pct?, iva_pct? (=19), forma_pago?, observaciones?}.",
                         "schema": {"type": "object", "required": ["nombre_cliente", "items"],
                                    "properties": {"nombre_cliente": {"type": "string"},
                                                   "descripcion": {"type": "string"},
                                                   "items": {"type": "array", "items": {"type": "object"}},
                                                   "descuento_pct": {"type": "number"},
                                                   "iva_pct": {"type": "number"},
                                                   "forma_pago": {"type": "string"},
                                                   "observaciones": {"type": "string"}}}},
    "generar_pdf_cotizacion": {"tipo": "escritura", "resumen_fn": _resumen_generar_pdf,
                               "ejecutar_fn": _ejecutar_generar_pdf,
                               "desc": "PROPUESTA de generar el documento con la plantilla predeterminada para la cotización numero=...",
                               "schema": {"type": "object", "required": ["numero"],
                                          "properties": {"numero": {"type": "string"}}}},
}

ESQUEMA_HERRAMIENTAS = [{
    "type": "function",
    "function": {"name": nombre, "description": h["desc"], "parameters": h["schema"]}
} for nombre, h in HERRAMIENTAS.items()]


# ============================================================
# Prompts del Asistente Principal + agentes
# ============================================================

BASE_PROMPT = (
    "Eres Yeruzzza, el asistente principal de YERUZZA Empresarial Asist (plataforma de "
    "instalaciones técnicas, redes, eléctricas y mantenimiento). Reglas duras:\n"
    "1. NUNCA inventes precios, costos, clientes, cotizaciones ni datos de la empresa: "
    "usa SIEMPRE las herramientas para leerlos de la base de datos.\n"
    "2. Para crear cliente, cotización o generar PDF solo PRESENTAS la propuesta y llamas a la "
    "herramienta de escritura: el sistema exige autorización humana y el usuario confirmará.\n"
    "3. Si falta información clave (nombre del cliente, cantidades), pregunta antes de proponer.\n"
    "4. Responde en español, breve y profesional, con cifras formateadas. "
    "Si los datos no existen, dilo con honestidad.\n"
)


def _prompt_agente(agente: str) -> str:
    return BASE_PROMPT + f"\nEspecialidad en esta conversación: {AGENTES.get(agente, AGENTES['administrativo'])}\n"


# ============================================================
# El núcleo
# ============================================================

def _conversacion_id(origen: str, usuario, chat_id: str | None) -> str:
    if origen == "telegram":
        return f"tg-{chat_id}"
    return f"panel-{usuario.id}"


def _historial(db: Session, conversacion_id: str, limite: int = 10) -> list:
    filas = db.execute(select(IAMensaje).where(IAMensaje.conversacion_id == conversacion_id)
                       .order_by(IAMensaje.id.desc()).limit(limite)).scalars().all()
    mensajes = []
    for m in reversed(filas):
        if m.rol in ("usuario", "asistente") and m.texto:
            mensajes.append({"role": "user" if m.rol == "usuario" else "assistant",
                             "content": m.texto})
    return mensajes


class ChatIn(BaseModel):
    texto: str = Field(..., min_length=1, max_length=4000)
    origen: str = Field("panel", pattern="^(panel|telegram)$")
    chat_id: str | None = Field(None, max_length=32)
    usuario_id: int | None = None  # solo para telegram (validado en esa capa)


def _determinar_agente_ayuda(texto: str) -> str:
    """Paso 0 sin red: palabras clave por especialidad (respaldo honesto)."""
    t = texto.lower()
    if any(k in t for k in ("cotiz", "cliente", "precio", "venta", "propuesta")):
        return "comercial"
    if any(k in t for k in ("costo", "gasto", "rentabilidad", "presupuesto", "indicador")):
        return "financiero"
    if any(k in t for k in ("proyecto", "obra", "avance")):
        return "proyectos"
    if any(k in t for k in ("contraseña", "permiso", "credencial", "seguridad")):
        return "seguridad"
    return AGENTE_DEFECTO


async def _determinar_agente(cred, texto: str) -> str | None:
    """Paso 0 del Asistente Principal: enruta a la especialidad (agente)."""
    try:
        respuesta = await _completar(cred, [
            {"role": "system", "content": (
                "Clasifica la solicitud en UNA especialidad y responde SOLO con su nombre: "
                + ", ".join(f"{k} ({v})" for k, v in AGENTES.items()))},
            {"role": "user", "content": texto[:600]},
        ], None, temperatura=0.0)
        etiqueta = (respuesta.get("content") or "").strip().lower()
        for nombre in AGENTES:
            if nombre in etiqueta:
                return nombre
    except IAError:
        pass
    return None


async def _nucleo(db, user, args_texto: str, origen: str, chat_id: str | None):
    """Ejecuta un turno completo del núcleo. Devuelve dict con texto, agente,
    herramientas usadas y acciones pendientes creadas."""
    cred = _credenciales(db)
    convid = _conversacion_id(origen, user, chat_id)
    db.add(IAMensaje(conversacion_id=convid, origen=origen,
                     usuario_id=user.id if user else None, chat_id=chat_id,
                     rol="usuario", texto=args_texto))
    db.commit()

    if not cred:
        # Honestidad sin proveedor: sin IA no se promete inteligencia
        texto = ("El núcleo de IA no está configurado todavía. El dueño debe definir proveedor, "
                 "modelo y clave en la sección AI del panel. Las herramientas del negocio siguen "
                 "disponibles desde el panel y por los comandos de Telegram.")
        db.add(IAMensaje(conversacion_id=convid, origen=origen,
                         usuario_id=user.id if user else None, chat_id=chat_id,
                         rol="asistente", texto=texto))
        db.commit()
        return {"texto": texto, "agente": None, "herramientas": [], "acciones": [], "ia_activa": False}

    if not _fila_config(db).activo:
        texto = ("El núcleo de Yeruzzza está desactivado ahora mismo (el dueño lo enciende en la "
                 "sección AI del panel). Todo lo demás sigue funcionando con normalidad.")
        db.add(IAMensaje(conversacion_id=convid, origen=origen,
                         usuario_id=user.id if user else None, chat_id=chat_id,
                         rol="asistente", texto=texto))
        db.commit()
        return {"texto": texto, "agente": None, "herramientas": [], "acciones": [], "ia_activa": False}

    historial = _historial(db, convid)
    agente = await _determinar_agente(cred, args_texto) or _determinar_agente_ayuda(args_texto)
    mensajes = [{"role": "system", "content": _prompt_agente(agente or AGENTE_DEFECTO)}]
    mensajes += historial
    mensajes.append({"role": "user", "content": args_texto})

    usadas = []
    acciones_creadas = []
    for _ in range(6):
        try:
            mensaje = await _completar(cred, mensajes, ESQUEMA_HERRAMIENTAS)
        except IAError as e:
            texto = f"No pude hablar con el proveedor de IA en este momento: {e}"
            break
        llamadas = mensaje.get("tool_calls") or []
        if not llamadas:
            texto = (mensaje.get("content") or "").strip() or "Sin respuesta del proveedor."
            break
        mensajes.append({"role": "assistant",
                         "content": mensaje.get("content") or "",
                         "tool_calls": llamadas})
        for llamada in llamadas:
            nombre = ((llamada.get("function") or {}).get("name") or "")
            try:
                argumentos = json.loads((llamada.get("function") or {}).get("arguments") or "{}")
            except Exception:
                argumentos = {}
            herramienta = HERRAMIENTAS.get(nombre)
            usadas.append(nombre)
            if not herramienta:
                resultado = {"error": f"herramienta {nombre} no existe"}
            elif herramienta["tipo"] == "lectura":
                resultado = json.loads(herramienta["fn"](db, argumentos) or "{}")
            else:
                # ESCRITURA = propuesta que exige autorización humana
                accion = IAAccion(conversacion_id=convid, usuario_id=user.id if user else None,
                                  chat_id=chat_id, herramienta=nombre,
                                  argumentos=json.dumps(argumentos, ensure_ascii=False),
                                  resumen=herramienta["resumen_fn"](argumentos))
                db.add(accion)
                db.commit()
                db.refresh(accion)
                acciones_creadas.append({"id": accion.id, "resumen": accion.resumen})
                resultado = {"ok": True, "propuesto": True,
                             "accion_id": accion.id,
                             "nota": "La acción queda PENDIENTE de autorización humana."}
            mensajes.append({"role": "tool",
                             "tool_call_id": llamada.get("id") or f"{nombre}-{len(usadas)}",
                             "content": json.dumps(resultado, ensure_ascii=False)})
    else:
        texto = "El flujo se detuvo por seguridad (demasiados pasos de herramientas en un turno)."

    if not acciones_creadas and not texto:
        texto = "Sin respuesta del proveedor."
    for a in acciones_creadas:
        texto += f"\n\n· {a['resumen']}\n  CONFIRMA en el panel o responde: /confirmar {a['id']} · Cancela con /cancelar {a['id']}"
    db.add(IAMensaje(conversacion_id=convid, origen=origen,
                     usuario_id=user.id if user else None, chat_id=chat_id,
                     rol="asistente", texto=texto[:4000], agente=agente,
                     herramientas=json.dumps(usadas)))
    db.commit()
    return {"texto": texto[:4000], "agente": agente, "herramientas": usadas,
            "acciones": acciones_creadas, "ia_activa": True}


@router.post("/ia/chat")
async def ia_chat(datos: ChatIn, current_user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    # límite de uso: cada llamada consume crédito del proveedor del dueño
    ahora = time.time()
    ventana = [t for t in _CHAT_USOS.get(current_user.id, [])
               if ahora - t < int(os.getenv("IA_CHAT_WINDOW_SECONDS", "300"))]
    limite = int(os.getenv("IA_CHAT_LIMIT", "40"))
    if len(ventana) >= limite:
        raise HTTPException(429, detail=f"Límite de {limite} mensajes por ventana alcanzado; espera un momento.")
    _CHAT_USOS[current_user.id] = ventana + [ahora]
    return await _nucleo(db, current_user, datos.texto, "panel", None)


_CHAT_USOS: dict = {}


@router.get("/ia/mensajes")
def ia_mensajes(limit: int = 50, current_user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    convid = _conversacion_id("panel", current_user, None)
    filas = db.execute(select(IAMensaje).where(IAMensaje.conversacion_id == convid)
                       .order_by(IAMensaje.id.desc()).limit(max(1, min(limit, 100)))).scalars().all()
    return [{
        "id": m.id, "rol": m.rol, "agente": m.agente, "texto": m.texto,
        "herramientas": json.loads(m.herramientas or "[]"),
        "creado_en": m.creado_en.isoformat() if m.creado_en else None,
    } for m in reversed(filas)]


@router.get("/ia/acciones")
def ia_acciones(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    convid = _conversacion_id("panel", current_user, None)
    filas = db.execute(select(IAAccion).where(IAAccion.conversacion_id == convid)
                       .order_by(IAAccion.id.desc()).limit(20)).scalars().all()
    return [{"id": a.id, "herramienta": a.herramienta, "resumen": a.resumen,
             "estado": a.estado, "creado_en": a.creado_en.isoformat() if a.creado_en else None}
            for a in filas]


def _ejecutar_accion(db: Session, accion: IAAccion, usuario: User):
    herramienta = HERRAMIENTAS.get(accion.herramienta)
    if not herramienta:
        accion.estado, accion.resultado = "fallo", "herramienta ya no existe"
        db.commit()
        return False, accion.resultado, {"ok": False, "error": accion.resultado}
    try:
        args = json.loads(accion.argumentos)
        resultado = herramienta["ejecutar_fn"](db, args, usuario)
        ok = bool(resultado.get("ok"))
        accion.estado = "ejecutada" if ok else "fallo"
        accion.resultado = json.dumps(resultado, ensure_ascii=False)[:2000]
        accion.documento_id = resultado.get("documento_id")
        accion.resuelta_en = datetime.utcnow()
        db.commit()
        return ok, accion.resultado, resultado
    except Exception as e:
        accion.estado, accion.resultado = "fallo", str(e)[:500]
        accion.resuelta_en = datetime.utcnow()
        db.commit()
        return False, accion.resultado


@router.post("/ia/acciones/{aid}/confirmar")
def confirmar_accion(aid: int, current_user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    accion = db.execute(select(IAAccion).where(IAAccion.id == aid)).scalar_one_or_none()
    if not accion:
        raise HTTPException(404, detail="Acción no encontrada")
    convid = _conversacion_id("panel", current_user, None)
    if accion.conversacion_id != convid and accion.usuario_id != current_user.id:
        raise HTTPException(403, detail="Esta acción no es tuya")
    if accion.estado != "pendiente":
        raise HTTPException(409, detail=f"La acción ya está {accion.estado}")
    ok, resultado, completo = _ejecutar_accion(db, accion, current_user)[:3]
    registrar_auditoria(db, "ia_accion_confirmada", usuario=current_user,
                        detalle=f"{accion.herramienta}: {'OK' if ok else 'FALLO'}")
    return {"ok": ok, "resultado": completo if isinstance(completo, dict) else
            json.loads(resultado) if str(resultado).startswith("{") else {"detalle": resultado}}


@router.post("/ia/acciones/{aid}/cancelar")
def cancelar_accion(aid: int, current_user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    accion = db.execute(select(IAAccion).where(IAAccion.id == aid)).scalar_one_or_none()
    if not accion:
        raise HTTPException(404, detail="Acción no encontrada")
    convid = _conversacion_id("panel", current_user, None)
    if accion.conversacion_id != convid and accion.usuario_id != current_user.id:
        raise HTTPException(403, detail="Esta acción no es tuya")
    if accion.estado != "pendiente":
        raise HTTPException(409, detail=f"La acción ya está {accion.estado}")
    accion.estado = "cancelada"
    accion.resuelta_en = datetime.utcnow()
    db.commit()
    registrar_auditoria(db, "ia_accion_cancelada", usuario=current_user)
    return {"ok": True}
