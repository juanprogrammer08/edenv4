# -*- coding: utf-8 -*-
"""Modelos de datos de EDÉN."""
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Float
from datetime import datetime

from app.db import Base
from app.config import ROL_ADMIN


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(128), nullable=False)
    # Roles: "dueno" (acceso total) | "admin" (operativo restringido)
    rol = Column(String(20), default=ROL_ADMIN, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Empresa(Base):
    """Configuración general de la empresa (fila única id=1)."""
    __tablename__ = "empresa"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(200), default="")
    nit = Column(String(50), default="")
    direccion = Column(String(200), default="")
    telefono = Column(String(50), default="")
    correo = Column(String(120), default="")
    ciudad = Column(String(100), default="")
    actualizado_en = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Cotizacion(Base):
    __tablename__ = "cotizaciones"
    id = Column(Integer, primary_key=True, index=True)
    numero = Column(String(20), index=True, nullable=True)  # COT-2026-00001
    cliente = Column(String(200), nullable=False)  # snapshot del nombre
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=True)
    descripcion = Column(Text, nullable=True)
    subtotal = Column(Float, default=0.0)
    descuento_pct = Column(Float, default=0.0)
    descuento_valor = Column(Float, default=0.0)
    iva_pct = Column(Float, default=0.0)
    iva_valor = Column(Float, default=0.0)
    total = Column(Float, default=0.0)
    costo_estimado = Column(Float, default=0.0)
    utilidad = Column(Float, default=0.0)
    tiempo_ejecucion = Column(String(120), default="")
    forma_pago = Column(String(200), default="")
    vigencia_cotizacion = Column(String(120), default="")
    observaciones = Column(Text, default="")
    # borrador, pendiente, enviada, aprobada, rechazada, vencida, convertida
    estado = Column(String(20), default="borrador")
    plantilla_id = Column(Integer, nullable=True)
    plantilla_version = Column(Integer, nullable=True)
    documento_id = Column(Integer, nullable=True)
    creado_por_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow)


class CotizacionItem(Base):
    """Ítems de una cotización con precio/costo SNAPSHOT (mutar el catálogo
    después no cambia cotizaciones antiguas)."""
    __tablename__ = "cotizaciones_items"
    id = Column(Integer, primary_key=True, index=True)
    cotizacion_id = Column(Integer, ForeignKey("cotizaciones.id"), index=True, nullable=False)
    servicio_id = Column(Integer, ForeignKey("servicios.id"), nullable=True)
    orden = Column(Integer, default=0)
    descripcion = Column(String(500), nullable=False)
    cantidad = Column(Float, nullable=False)
    unidad = Column(String(30), default="und")
    precio_unitario = Column(Float, nullable=False)
    costo_unitario = Column(Float, default=0.0)


class Servicio(Base):
    """Catálogo de servicios y precios (el dueño lo administra)."""
    __tablename__ = "servicios"
    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(20), unique=True, index=True, nullable=False)
    nombre = Column(String(150), nullable=False)
    descripcion = Column(Text, default="")
    categoria = Column(String(60), default="general")
    unidad = Column(String(30), default="und")
    precio_venta = Column(Float, nullable=False)
    costo_materiales = Column(Float, default=0.0)
    costo_mano_obra = Column(Float, default=0.0)
    tiempo_estimado_horas = Column(Float, default=0.0)
    activo = Column(Boolean, default=True)
    creado_por_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow)


class Cliente(Base):
    """Base comercial centralizada (los clientes NO son usuarios del sistema)."""
    __tablename__ = "clientes"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(200), unique=True, index=True, nullable=False)
    nit = Column(String(50), default="")
    contacto = Column(String(100), default="")
    telefono = Column(String(50), default="")
    correo = Column(String(120), default="")
    direccion = Column(String(200), default="")
    ciudad = Column(String(100), default="")
    descripcion = Column(Text, default="")
    activo = Column(Boolean, default=True)
    creado_por_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow)


class ConfigComercial(Base):
    """Reglas del dueño: límites de descuento y margen mínimo (fila única id=1)."""
    __tablename__ = "config_comercial"
    id = Column(Integer, primary_key=True, index=True)
    descuento_max_pct = Column(Float, default=20.0)
    margen_minimo_pct = Column(Float, default=15.0)
    actualizado_en = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Proyecto(Base):
    __tablename__ = "proyectos"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    cotizacion_id = Column(Integer, ForeignKey("cotizaciones.id"), nullable=False)
    estado = Column(String(20), default="activo")  # activo, finalizado, cancelado
    creado_en = Column(DateTime, default=datetime.utcnow)


class Gasto(Base):
    __tablename__ = "gastos"
    id = Column(Integer, primary_key=True, index=True)
    proyecto_id = Column(Integer, ForeignKey("proyectos.id"), nullable=False)
    descripcion = Column(Text, nullable=False)
    monto = Column(Float, nullable=False)
    fecha = Column(DateTime, default=datetime.utcnow)


class Bitacora(Base):
    __tablename__ = "bitacoras"
    id = Column(Integer, primary_key=True, index=True)
    entidad = Column(String(50), nullable=False)  # cotizacion, proyecto, cliente
    entidad_id = Column(Integer, nullable=False)
    mensaje = Column(Text, nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow)


class Auditoria(Base):
    """Registro de operaciones sensibles: quién, qué, cuándo, desde dónde."""
    __tablename__ = "auditoria"
    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, nullable=True)
    username = Column(String(50), nullable=True)
    accion = Column(String(80), nullable=False)
    detalle = Column(Text, nullable=True)
    ip = Column(String(64), nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow)


# ============================================================
# PLANTILLAS Y DOCUMENTOS (FASE 3)
# ============================================================

class Plantilla(Base):
    """Plantilla de cotización DOCX o HTML (la fila guarda la versión ACTUAL)."""
    __tablename__ = "plantillas"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(120), unique=True, index=True, nullable=False)
    tipo = Column(String(10), nullable=False)  # docx | html
    descripcion = Column(String(500), default="")
    version = Column(Integer, default=1, nullable=False)
    variables = Column(Text, default="[]")  # JSON list detectadas
    es_predeterminada = Column(Boolean, default=False)
    activa = Column(Boolean, default=True)
    archivo_nombre = Column(String(255), default="")
    tamano = Column(Integer, default=0)
    creado_por_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow)
    actualizado_en = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PlantillaVersion(Base):
    """Snapshot histórico de cada versión de una plantilla; los documentos
    quedan amarrados a su versión para que actualizar la plantilla no altere
    documentos históricos."""
    __tablename__ = "plantillas_versiones"
    id = Column(Integer, primary_key=True, index=True)
    plantilla_id = Column(Integer, ForeignKey("plantillas.id"), index=True, nullable=False)
    version = Column(Integer, nullable=False)
    nombre = Column(String(120), default="")
    descripcion = Column(String(500), default="")
    archivo_ruta = Column(String(500), nullable=False)
    creado_por_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow)


class Documento(Base):
    """Documento generado (cotización) con referencia a la plantilla y versión."""
    __tablename__ = "documentos"
    id = Column(Integer, primary_key=True, index=True)
    plantilla_id = Column(Integer, ForeignKey("plantillas.id"), nullable=False)
    plantilla_version = Column(Integer, nullable=False)
    tipo = Column(String(40), default="cotizacion")
    numero_cotizacion = Column(String(60), index=True, nullable=False)
    datos_json = Column(Text, nullable=True)
    archivo_docx = Column(String(500), nullable=True)
    archivo_html = Column(String(500), nullable=True)
    archivo_pdf = Column(String(500), nullable=True)
    pdf_ok = Column(Boolean, default=False)
    enviado_telegram = Column(Boolean, default=False)
    creado_por_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow)


# ============================================================
# TELEGRAM (FASE 2)
# ============================================================

class TelegramConfig(Base):
    """Configuración del bot (fila única id=1). El token se guarda CIFRADO."""
    __tablename__ = "telegram_config"
    id = Column(Integer, primary_key=True, index=True)
    bot_token_cifrado = Column(Text, nullable=True)  # Fernet; nunca sale del backend
    bot_username = Column(String(80), nullable=True)
    bot_id = Column(String(32), nullable=True)
    modo = Column(String(20), default="polling")  # polling | webhook
    webhook_url = Column(String(300), nullable=True)
    webhook_secret = Column(String(64), nullable=True)  # X-Telegram-Bot-Api-Secret-Token
    activo = Column(Boolean, default=False)
    estado_texto = Column(String(200), default="Sin configurar")
    ultima_verificacion = Column(DateTime, nullable=True)
    actualizado_en = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TelegramCuenta(Base):
    """Vinculación segura entre un usuario del panel y un chat de Telegram."""
    __tablename__ = "telegram_cuentas"
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(String(32), unique=True, index=True, nullable=False)
    telegram_username = Column(String(80), nullable=True)
    usuario_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    vinculado_en = Column(DateTime, default=datetime.utcnow)
    activo = Column(Boolean, default=True)


class TelegramCodigo(Base):
    """Códigos temporales de un solo uso para vincular cuentas."""
    __tablename__ = "telegram_codigos"
    id = Column(Integer, primary_key=True, index=True)
    codigo_hash = Column(String(64), index=True, nullable=False)
    usuario_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    expira_en = Column(DateTime, nullable=False)
    usado = Column(Boolean, default=False)
    creado_en = Column(DateTime, default=datetime.utcnow)


class TelegramMensaje(Base):
    """Historial de mensajes del bot (entrada y salida), con adjuntos en disco."""
    __tablename__ = "telegram_mensajes"
    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(String(32), index=True, nullable=False)
    direccion = Column(String(10), nullable=False)  # entrada | salida
    tipo = Column(String(20), default="texto")  # texto | comando | foto | documento
    texto = Column(Text, nullable=True)
    archivo_nombre = Column(String(255), nullable=True)
    archivo_ruta = Column(String(500), nullable=True)
    archivo_tamano = Column(Integer, nullable=True)
    cuenta_id = Column(Integer, ForeignKey("telegram_cuentas.id"), nullable=True)
    entregado = Column(Boolean, default=True)
    error = Column(Text, nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow)
