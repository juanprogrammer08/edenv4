# -*- coding: utf-8 -*-
"""Configuración central de EDÉN (variables de entorno)."""
import os

APP_VERSION = "1.5.0-fase5"

# Seguridad general
AUTH_SECRET = os.getenv("AUTH_SECRET", "secret-key-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 días

# Base de datos
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")

# CORS: lista separada por comas; "*" conserva el comportamiento abierto
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

# Límite de intentos de login
LOGIN_RATE_LIMIT = int(os.getenv("LOGIN_RATE_LIMIT", "6"))
LOGIN_WINDOW_SECONDS = int(os.getenv("LOGIN_WINDOW_SECONDS", "300"))

# Almacenamiento de archivos (adjuntos de Telegram y futuros módulos)
MEDIA_DIR = os.getenv("MEDIA_DIR", "./media")

# URL pública del API (para registrar el webhook de Telegram en producción)
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

# Telegram
TG_POLL_SECONDS = int(os.getenv("TG_POLL_SECONDS", "25"))
TG_CODE_TTL_MINUTOS = int(os.getenv("TG_CODE_TTL_MINUTOS", "10"))
TG_MAX_ADJUNTO_MB = int(os.getenv("TG_MAX_ADJUNTO_MB", "20"))
TG_API = "https://api.telegram.org"

ROLES_VALIDOS = ("dueno", "admin")
ROL_DUENO = "dueno"
ROL_ADMIN = "admin"
