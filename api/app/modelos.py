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
    cliente = Column(String(100), nullable=False)
    descripcion = Column(Text, nullable=True)
    total = Column(Float, default=0.0)
    estado = Column(String(20), default="pendiente")  # pendiente, aceptada, rechazada
    creado_por_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow)


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
