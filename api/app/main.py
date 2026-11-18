from fastapi import FastAPI, Depends, HTTPException, status, Form, Request
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import datetime

from app.config import APP_VERSION, CORS_ORIGINS, ROL_DUENO, ROL_ADMIN
from app.db import (
    get_password_hash, verify_password, get_db, registrar_auditoria,
    fernet_desde_secret, inicializar_bd,
)
from app.modelos import (
    User, Empresa, Cotizacion, Proyecto, Gasto, Bitacora, Auditoria,
    TelegramConfig, TelegramCuenta, TelegramCodigo, TelegramMensaje,
    Plantilla, PlantillaVersion, Documento,
)
from app.seguridad import (
    create_access_token, get_current_user, require_dueno,
    login_permitido, registrar_intento_login, cliente_ip,
)
from app.telegram import router as telegram_router, arrancar_telegram
from app.plantillas import router as plantillas_router
from app.comercial import router as comercial_router
from app.ia_core import router as ia_router

# Aviso sin romper el arranque en desarrollo
from app.config import AUTH_SECRET
if AUTH_SECRET == "secret-key-change-me":
    print("ADVERTENCIA: AUTH_SECRET usa el valor por defecto. Defínelo en el entorno antes de producción.")

app = FastAPI(
    title="YERUZZA Empresarial Asist — Plataforma Empresarial Inteligente",
    version=APP_VERSION,
    root_path="/api",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _al_arrancar():
    inicializar_bd()
    await arrancar_telegram()


app.include_router(telegram_router)
app.include_router(plantillas_router)
app.include_router(comercial_router)
app.include_router(ia_router)

# ============================================================
# ESQUEMAS Pydantic
# ============================================================

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=128)

class PasswordChange(BaseModel):
    password: str = Field(..., min_length=8, max_length=128)

class UserOut(BaseModel):
    id: int
    username: str
    rol: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class Token(BaseModel):
    access_token: str
    token_type: str

class EmpresaBase(BaseModel):
    nombre: Optional[str] = Field(None, max_length=200)
    nit: Optional[str] = Field(None, max_length=50)
    direccion: Optional[str] = Field(None, max_length=200)
    telefono: Optional[str] = Field(None, max_length=50)
    correo: Optional[str] = Field(None, max_length=120)
    ciudad: Optional[str] = Field(None, max_length=100)

class EmpresaOut(EmpresaBase):
    id: int
    actualizado_en: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

# Las cotizaciones viven en app/comercial.py (FASE 4): ítems, numeración y estados.

class ProyectoCreate(BaseModel):
    nombre: str
    cotizacion_id: int
    estado: Optional[str] = "activo"

class ProyectoOut(BaseModel):
    id: int
    nombre: str
    cotizacion_id: int
    estado: str
    creado_en: datetime

    model_config = ConfigDict(from_attributes=True)

class GastoCreate(BaseModel):
    proyecto_id: int
    descripcion: str
    monto: float
    fecha: Optional[datetime] = None

class GastoOut(BaseModel):
    id: int
    proyecto_id: int
    descripcion: str
    monto: float
    fecha: datetime

    model_config = ConfigDict(from_attributes=True)

class BitacoraCreate(BaseModel):
    entidad: str
    entidad_id: int
    mensaje: str

class BitacoraOut(BaseModel):
    id: int
    entidad: str
    entidad_id: int
    mensaje: str
    creado_en: datetime

    model_config = ConfigDict(from_attributes=True)

class AuditoriaOut(BaseModel):
    id: int
    usuario_id: Optional[int]
    username: Optional[str]
    accion: str
    detalle: Optional[str]
    ip: Optional[str]
    creado_en: datetime

    model_config = ConfigDict(from_attributes=True)

# ============================================================
# RUTAS
# ============================================================

@app.get("/health")
def health():
    return {"status": "ok", "version": APP_VERSION}

# --- AUTENTICACIÓN ---

@app.post("/auth/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(username: str = Form(...), password: str = Form(...),
             db: Session = Depends(get_db)):
    """Registro cerrado: si ya existe un DUEÑO, nadie más puede registrarse.
    El primer registro crea al dueño de la empresa."""
    hay_dueno = db.execute(select(User).where(User.rol == ROL_DUENO)).scalar_one_or_none()
    if hay_dueno:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El registro está deshabilitado. El dueño crea los administradores desde el panel.",
        )
    user_exists = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user_exists:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El usuario ya existe")
    if len(password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La contraseña debe tener al menos 8 caracteres")
    user = User(username=username, hashed_password=get_password_hash(password), rol=ROL_DUENO)
    db.add(user)
    db.commit()
    db.refresh(user)
    registrar_auditoria(db, "dueño_creado_bootstrap", usuario=user)
    return user

@app.post("/auth/login", response_model=Token)
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    ip = cliente_ip(request)
    if not login_permitido(ip):
        registrar_auditoria(db, "login_bloqueado_rate_limit", username_libre=form_data.username, ip=ip)
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="Demasiados intentos de inicio de sesión. Espera unos minutos.")
    user = db.execute(select(User).where(User.username == form_data.username)).scalar_one_or_none()
    if not user or not verify_password(form_data.password, user.hashed_password):
        registrar_intento_login(ip)
        registrar_auditoria(db, "login_fallido", username_libre=form_data.username, ip=ip,
                            usuario=user if user else None)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario o contraseña incorrectos")
    if not user.is_active:
        registrar_intento_login(ip)
        registrar_auditoria(db, "login_usuario_inactivo", usuario=user, ip=ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="La cuenta está desactivada")
    access_token = create_access_token(data={"sub": user.username, "rol": user.rol})
    registrar_auditoria(db, "login_ok", usuario=user, ip=ip)
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/auth/me", response_model=UserOut)
def read_me(current_user: User = Depends(get_current_user)):
    return current_user

@app.put("/mi/password")
def cambiar_mi_password(cambio: PasswordChange, current_user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    current_user.hashed_password = get_password_hash(cambio.password)
    db.commit()
    registrar_auditoria(db, "password_propia_cambiada", usuario=current_user)
    return {"ok": True}

# --- GESTIÓN DE USUARIOS (SOLO DUEÑO) ---

@app.get("/usuarios", response_model=List[UserOut])
def list_usuarios(current_user: User = Depends(require_dueno), db: Session = Depends(get_db)):
    return db.execute(select(User).order_by(User.id)).scalars().all()

@app.post("/usuarios", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def crear_administrador(datos: UserCreate, current_user: User = Depends(require_dueno),
                        db: Session = Depends(get_db)):
    user_exists = db.execute(select(User).where(User.username == datos.username)).scalar_one_or_none()
    if user_exists:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El usuario ya existe")
    user = User(username=datos.username, hashed_password=get_password_hash(datos.password), rol=ROL_ADMIN)
    db.add(user)
    db.commit()
    db.refresh(user)
    registrar_auditoria(db, "admin_creado", usuario=current_user, detalle=f"nuevo admin: {user.username}")
    return user

@app.put("/usuarios/{usuario_id}/estado", response_model=UserOut)
def cambiar_estado_usuario(usuario_id: int, activo: bool, current_user: User = Depends(require_dueno),
                           db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.id == usuario_id)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    if user.rol == ROL_DUENO:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="El dueño no puede desactivarse a sí mismo")
    if user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes cambiar tu propio estado")
    user.is_active = activo
    db.commit()
    db.refresh(user)
    registrar_auditoria(db, "usuario_estado", usuario=current_user,
                        detalle=f"{user.username} -> {'activo' if activo else 'inactivo'}")
    return user

@app.put("/usuarios/{usuario_id}/password")
def reset_password_usuario(usuario_id: int, cambio: PasswordChange,
                           current_user: User = Depends(require_dueno), db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.id == usuario_id)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    if user.rol == ROL_DUENO:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="El dueño define su contraseña desde /mi/password")
    user.hashed_password = get_password_hash(cambio.password)
    db.commit()
    registrar_auditoria(db, "password_reseteada", usuario=current_user, detalle=f"de: {user.username}")
    return {"ok": True}

@app.delete("/usuarios/{usuario_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_administrador(usuario_id: int, current_user: User = Depends(require_dueno),
                           db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.id == usuario_id)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    if user.rol == ROL_DUENO:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No se puede eliminar al dueño")
    if user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes eliminar tu propia cuenta")
    if db.execute(select(Cotizacion).where(Cotizacion.creado_por_id == usuario_id)).first():
        user.is_active = False
        db.commit()
        registrar_auditoria(db, "usuario_desactivado_por_historial", usuario=current_user, detalle=f"{user.username}")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="El usuario tiene cotizaciones asociadas; se desactivó para conservar el historial")
    db.delete(user)
    db.commit()
    registrar_auditoria(db, "admin_eliminado", usuario=current_user)
    return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content=None)

# --- CONFIGURACIÓN DE EMPRESA ---

def _empresa_fila(db: Session) -> Empresa:
    fila = db.execute(select(Empresa).where(Empresa.id == 1)).scalar_one_or_none()
    if not fila:
        fila = Empresa(id=1)
        db.add(fila)
        db.commit()
        db.refresh(fila)
    return fila

@app.get("/empresa", response_model=EmpresaOut)
def get_empresa(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _empresa_fila(db)

@app.put("/empresa", response_model=EmpresaOut)
def update_empresa(datos: EmpresaBase, current_user: User = Depends(require_dueno),
                   db: Session = Depends(get_db)):
    fila = _empresa_fila(db)
    cambios = []
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        cambios.append(f"{campo}={'***' if campo == 'nit' and valor else valor}")
        setattr(fila, campo, valor)
    db.commit()
    db.refresh(fila)
    registrar_auditoria(db, "empresa_actualizada", usuario=current_user,
                        detalle=", ".join(cambios) if cambios else "sin cambios")
    return fila

# --- AUDITORÍA (SOLO DUEÑO) ---

@app.get("/auditoria", response_model=List[AuditoriaOut])
def list_auditoria(limit: int = 100, action: Optional[str] = None,
                   current_user: User = Depends(require_dueno), db: Session = Depends(get_db)):
    query = select(Auditoria).order_by(Auditoria.id.desc()).limit(max(1, min(limit, 500)))
    if action:
        query = query.where(Auditoria.accion.contains(action))
    return db.execute(query).scalars().all()

# --- CRUD Proyectos ---

@app.post("/proyectos", response_model=ProyectoOut)
def create_proyecto(proyecto: ProyectoCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cot = db.execute(select(Cotizacion).where(Cotizacion.id == proyecto.cotizacion_id)).scalar_one_or_none()
    if not cot:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cotización asociada no existe")
    db_proy = Proyecto(nombre=proyecto.nombre, cotizacion_id=proyecto.cotizacion_id, estado=proyecto.estado)
    db.add(db_proy)
    db.commit()
    db.refresh(db_proy)
    return db_proy

@app.get("/proyectos", response_model=List[ProyectoOut])
def list_proyectos(skip: int = 0, limit: int = 100, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.execute(select(Proyecto).offset(skip).limit(limit)).scalars().all()

@app.get("/proyectos/{proyecto_id}", response_model=ProyectoOut)
def get_proyecto(proyecto_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    proy = db.execute(select(Proyecto).where(Proyecto.id == proyecto_id)).scalar_one_or_none()
    if not proy:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proyecto no encontrado")
    return proy

@app.put("/proyectos/{proyecto_id}", response_model=ProyectoOut)
def update_proyecto(proyecto_id: int, proyecto: ProyectoCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    proy = db.execute(select(Proyecto).where(Proyecto.id == proyecto_id)).scalar_one_or_none()
    if not proy:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proyecto no encontrado")
    proy.nombre = proyecto.nombre
    proy.cotizacion_id = proyecto.cotizacion_id
    proy.estado = proyecto.estado
    db.commit()
    db.refresh(proy)
    return proy

@app.delete("/proyectos/{proyecto_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_proyecto(proyecto_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    proy = db.execute(select(Proyecto).where(Proyecto.id == proyecto_id)).scalar_one_or_none()
    if not proy:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proyecto no encontrado")
    db.delete(proy)
    db.commit()
    return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content=None)

# --- CRUD Gastos ---

@app.post("/gastos", response_model=GastoOut)
def create_gasto(gasto: GastoCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    proy = db.execute(select(Proyecto).where(Proyecto.id == gasto.proyecto_id)).scalar_one_or_none()
    if not proy:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Proyecto asociado no existe")
    db_gasto = Gasto(
        proyecto_id=gasto.proyecto_id,
        descripcion=gasto.descripcion,
        monto=gasto.monto,
        fecha=gasto.fecha or datetime.utcnow()
    )
    db.add(db_gasto)
    db.commit()
    db.refresh(db_gasto)
    return db_gasto

@app.get("/gastos", response_model=List[GastoOut])
def list_gastos(skip: int = 0, limit: int = 100, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.execute(select(Gasto).offset(skip).limit(limit)).scalars().all()

@app.get("/gastos/{gasto_id}", response_model=GastoOut)
def get_gasto(gasto_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    gasto = db.execute(select(Gasto).where(Gasto.id == gasto_id)).scalar_one_or_none()
    if not gasto:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gasto no encontrado")
    return gasto

@app.put("/gastos/{gasto_id}", response_model=GastoOut)
def update_gasto(gasto_id: int, gasto: GastoCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db_gasto = db.execute(select(Gasto).where(Gasto.id == gasto_id)).scalar_one_or_none()
    if not db_gasto:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gasto no encontrado")
    proy = db.execute(select(Proyecto).where(Proyecto.id == gasto.proyecto_id)).scalar_one_or_none()
    if not proy:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Proyecto asociado no existe")
    db_gasto.proyecto_id = gasto.proyecto_id
    db_gasto.descripcion = gasto.descripcion
    db_gasto.monto = gasto.monto
    db_gasto.fecha = gasto.fecha or datetime.utcnow()
    db.commit()
    db.refresh(db_gasto)
    return db_gasto

@app.delete("/gastos/{gasto_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_gasto(gasto_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    gasto = db.execute(select(Gasto).where(Gasto.id == gasto_id)).scalar_one_or_none()
    if not gasto:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gasto no encontrado")
    db.delete(gasto)
    db.commit()
    return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content=None)

# --- CRUD Bitacora ---

@app.post("/bitacoras", response_model=BitacoraOut)
def create_bitacora(bitacora: BitacoraCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db_bit = Bitacora(
        entidad=bitacora.entidad,
        entidad_id=bitacora.entidad_id,
        mensaje=bitacora.mensaje
    )
    db.add(db_bit)
    db.commit()
    db.refresh(db_bit)
    return db_bit

@app.get("/bitacoras", response_model=List[BitacoraOut])
def list_bitacoras(entidad: Optional[str] = None, entidad_id: Optional[int] = None, skip: int = 0, limit: int = 100, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(Bitacora)
    if entidad:
        query = query.where(Bitacora.entidad == entidad)
    if entidad_id:
        query = query.where(Bitacora.entidad_id == entidad_id)
    return db.execute(query.offset(skip).limit(limit)).scalars().all()

@app.get("/bitacoras/{bitacora_id}", response_model=BitacoraOut)
def get_bitacora(bitacora_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bit = db.execute(select(Bitacora).where(Bitacora.id == bitacora_id)).scalar_one_or_none()
    if not bit:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bitácora no encontrada")
    return bit

@app.delete("/bitacoras/{bitacora_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bitacora(bitacora_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bit = db.execute(select(Bitacora).where(Bitacora.id == bitacora_id)).scalar_one_or_none()
    if not bit:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bitácora no encontrada")
    db.delete(bit)
    db.commit()
    return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content=None)
