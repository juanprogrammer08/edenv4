# -*- coding: utf-8 -*-
"""Autenticación y roles de EDÉN: JWT y dependencias de FastAPI."""
from fastapi import Depends, HTTPException, Request, status
from jose import JWTError, jwt
from sqlalchemy import select
from datetime import datetime, timedelta
from typing import Optional
import time

from app.config import AUTH_SECRET, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from app.db import get_db
from app.modelos import User


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta if expires_delta else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, AUTH_SECRET, algorithm=ALGORITHM)


def get_current_user(request: Request, db=Depends(get_db)) -> User:
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token de autorización no proporcionado")
    try:
        payload = jwt.decode(token, AUTH_SECRET, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Usuario no encontrado o inactivo")
    return user


def require_dueno(current_user: User = Depends(get_current_user)) -> User:
    """Operaciones exclusivas del DUEÑO."""
    if current_user.rol != "dueno":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Solo el dueño puede realizar esta operación")
    return current_user


# Límite de intentos de login (en memoria, por proceso)
_login_intentos: dict = {}


def login_permitido(ip: str) -> bool:
    from app.config import LOGIN_RATE_LIMIT, LOGIN_WINDOW_SECONDS
    ahora = time.time()
    intentos = [t for t in _login_intentos.get(ip, []) if ahora - t < LOGIN_WINDOW_SECONDS]
    _login_intentos[ip] = intentos
    return len(intentos) < LOGIN_RATE_LIMIT


def registrar_intento_login(ip: str):
    from app.config import LOGIN_WINDOW_SECONDS
    ahora = time.time()
    intentos = [t for t in _login_intentos.get(ip, []) if ahora - t < LOGIN_WINDOW_SECONDS]
    intentos.append(ahora)
    _login_intentos[ip] = intentos


def cliente_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""
