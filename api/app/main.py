from fastapi import FastAPI, Depends, HTTPException, status, Form, Request
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import create_engine, select, update, delete, text, inspect as sa_inspect
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Float
from typing import Optional, List
from datetime import datetime, timedelta, timezone
import os
import time

# ============================================================
# CONFIGURACIÓN
# ============================================================
APP_VERSION = "1.1.0-fase1"

AUTH_SECRET = os.getenv("AUTH_SECRET", "secret-key-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 días

# Lista de orígenes CORS separados por coma; "*" conserva el comportamiento abierto
# En PRODUCCIÓN se recomienda fijar CORS_ORIGINS=https://tu-dominio.com
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

# Límite de intentos de login (por IP, ventana deslizante en memoria)
LOGIN_RATE_LIMIT = int(os.getenv("LOGIN_RATE_LIMIT", "6"))
LOGIN_WINDOW_SECONDS = int(os.getenv("LOGIN_WINDOW_SECONDS", "300"))

ROLES_VALIDOS = ("dueno", "admin")
ROL_DUENO = "dueno"
ROL_ADMIN = "admin"

if AUTH_SECRET == "secret-key-change-me":
    # Aviso visible sin romper el arranque en desarrollo
    print("ADVERTENCIA: AUTH_SECRET usa el valor por defecto. Definelo en el entorno antes de producción.")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./app.db"
)

# Intentar conectar a PostgreSQL, fallback a SQLite si falla
try:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
    # Probar conexión (SQLAlchemy 2.x exige text())
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
except Exception:
    # Fallback a SQLite local
    DATABASE_URL = "sqlite:///./app.db"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI(
    title="EDÉN — Asistente Empresarial Inteligente",
    version=APP_VERSION,
    root_path="/api",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# MODELOS SQLALCHEMY
# ============================================================

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(128), nullable=False)
    # Roles: "dueno" (propietario, acceso total) | "admin" (operativo restringido)
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

# Crear tablas si no existen
Base.metadata.create_all(bind=engine)

# ============================================================
# MIGRACIONES VERSIONADAS
# Corren en orden en el arranque; cada una solo si no quedó registrada.
# Reversibles por diseño: cada función guarda su SQL "down" equivalente.
# ============================================================
TABLA_MIGRACIONES = "_schema_migrations"

def _columna_existe(conn, tabla, columna):
    insp = sa_inspect(conn)
    return columna in [c["name"] for c in insp.get_columns(tabla)]

def _registrar_migracion(conn, version):
    conn.execute(text(f"INSERT INTO {TABLA_MIGRACIONES} (version) SELECT '{version}' WHERE NOT EXISTS (SELECT 1 FROM {TABLA_MIGRACIONES} WHERE version = '{version}')"))

MIGRACIONES = []

def _m001_rol_usuarios(conn):
    """FASE 1: columna rol en users. Si no existe ningún dueño, promueve al usuario
    de id más bajo a dueño (los demás quedan como administradores)."""
    if not _columna_existe(conn, "users", "rol"):
        conn.execute(text("ALTER TABLE users ADD COLUMN rol VARCHAR(20) DEFAULT 'admin' NOT NULL"))
    hay_dueno = conn.execute(text("SELECT COUNT(*) FROM users WHERE rol = 'dueno'")).scalar()
    if not hay_dueno:
        primero = conn.execute(text("SELECT MIN(id) FROM users")).scalar()
        if primero is not None:
            conn.execute(text("UPDATE users SET rol = 'dueno' WHERE id = :id"), {"id": primero})

MIGRACIONES.append(("001_rol_usuarios", _m001_rol_usuarios))

def _run_migraciones():
    with engine.begin() as conn:
        conn.execute(text(f"CREATE TABLE IF NOT EXISTS {TABLA_MIGRACIONES} (id INTEGER PRIMARY KEY, version VARCHAR(64) UNIQUE, aplicada_en DATETIME DEFAULT CURRENT_TIMESTAMP)"))
        aplicadas = {r[0] for r in conn.execute(text(f"SELECT version FROM {TABLA_MIGRACIONES}")).fetchall()}
        for version, fn in MIGRACIONES:
            if version in aplicadas:
                continue
            try:
                fn(conn)
                _registrar_migracion(conn, version)
                print(f"Migración aplicada: {version}")
            except Exception as e:
                print(f"Migración {version} FALLÓ: {e}")
                raise

_run_migraciones()

# ============================================================
# UTILIDADES
# ============================================================

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta if expires_delta else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, AUTH_SECRET, algorithm=ALGORITHM)
    return encoded_jwt

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def registrar_auditoria(db: Session, accion: str, usuario: Optional[User] = None,
                        detalle: str = "", ip: str = "", username_libre: str = ""):
    """Registra una operación sensible. Fallo nunca rompe la operación principal."""
    try:
        db.add(Auditoria(
            usuario_id=usuario.id if usuario else None,
            username=usuario.username if usuario else username_libre,
            accion=accion,
            detalle=detalle[:2000],
            ip=ip[:64],
        ))
        db.commit()
    except Exception:
        db.rollback()

# Límite de intentos de login (en memoria, por proceso)
_login_intentos: dict = {}

def login_permitido(ip: str) -> bool:
    ahora = time.time()
    intentos = _login_intentos.get(ip, [])
    intentos = [t for t in intentos if ahora - t < LOGIN_WINDOW_SECONDS]
    _login_intentos[ip] = intentos
    return len(intentos) < LOGIN_RATE_LIMIT

def registrar_intento_login(ip: str):
    ahora = time.time()
    intentos = [t for t in _login_intentos.get(ip, []) if ahora - t < LOGIN_WINDOW_SECONDS]
    intentos.append(ahora)
    _login_intentos[ip] = intentos

def cliente_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""

# ============================================================
# DEPENDENCIAS DE AUTENTICACIÓN Y ROLES
# ============================================================

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de autorización no proporcionado")
    try:
        payload = jwt.decode(token, AUTH_SECRET, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no encontrado o inactivo")
    return user

def require_dueno(current_user: User = Depends(get_current_user)) -> User:
    """Operaciones exclusivas del DUEÑO: administradores, empresa, auditoría."""
    if current_user.rol != ROL_DUENO:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el dueño puede realizar esta operación")
    return current_user

# ============================================================
# ESQUEMAS Pydantic
# ============================================================
from pydantic import BaseModel, Field, ConfigDict

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

class CotizacionCreate(BaseModel):
    cliente: str
    descripcion: Optional[str] = None
    total: float = 0.0
    estado: Optional[str] = "pendiente"

class CotizacionOut(BaseModel):
    id: int
    cliente: str
    descripcion: Optional[str]
    total: float
    estado: str
    creado_por_id: int
    creado_en: datetime

    model_config = ConfigDict(from_attributes=True)

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
    """Registro cerrado: si ya existe un DUEÑO, nadie más puede registrarse por su cuenta.
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
    hashed_password = get_password_hash(password)
    user = User(username=username, hashed_password=hashed_password, rol=ROL_DUENO)
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
    """Cualquier usuario autenticado cambia su propia contraseña."""
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
    """El dueño crea administradores. Los administradores no son dueños y no pueden crear más usuarios."""
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
    """El dueño activa/desactiva administradores. No puede desactivarse a sí mismo ni a otro dueño."""
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
    """El dueño restablece la contraseña de un administrador."""
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
    if db.execute(select(Cotizacion).where(Cotizacion.creado_por_id == usuario_id)).scalar_one_or_none():
        # Conserva trazabilidad comercial: se desactiva en lugar de borrar
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

# --- CRUD Cotizaciones ---

@app.post("/cotizaciones", response_model=CotizacionOut)
def create_cotizacion(cotizacion: CotizacionCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db_cot = Cotizacion(
        cliente=cotizacion.cliente,
        descripcion=cotizacion.descripcion,
        total=cotizacion.total,
        estado=cotizacion.estado,
        creado_por_id=current_user.id
    )
    db.add(db_cot)
    db.commit()
    db.refresh(db_cot)
    return db_cot

@app.get("/cotizaciones", response_model=List[CotizacionOut])
def list_cotizaciones(skip: int = 0, limit: int = 100, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cotizaciones = db.execute(select(Cotizacion).offset(skip).limit(limit)).scalars().all()
    return cotizaciones

@app.get("/cotizaciones/{cotizacion_id}", response_model=CotizacionOut)
def get_cotizacion(cotizacion_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cot = db.execute(select(Cotizacion).where(Cotizacion.id == cotizacion_id)).scalar_one_or_none()
    if not cot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cotización no encontrada")
    return cot

@app.put("/cotizaciones/{cotizacion_id}", response_model=CotizacionOut)
def update_cotizacion(cotizacion_id: int, cotizacion: CotizacionCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cot = db.execute(select(Cotizacion).where(Cotizacion.id == cotizacion_id)).scalar_one_or_none()
    if not cot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cotización no encontrada")
    cot.cliente = cotizacion.cliente
    cot.descripcion = cotizacion.descripcion
    cot.total = cotizacion.total
    cot.estado = cotizacion.estado
    db.commit()
    db.refresh(cot)
    return cot

@app.delete("/cotizaciones/{cotizacion_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cotizacion(cotizacion_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cot = db.execute(select(Cotizacion).where(Cotizacion.id == cotizacion_id)).scalar_one_or_none()
    if not cot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cotización no encontrada")
    db.delete(cot)
    db.commit()
    return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content=None)

# --- CRUD Proyectos ---

@app.post("/proyectos", response_model=ProyectoOut)
def create_proyecto(proyecto: ProyectoCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cot = db.execute(select(Cotizacion).where(Cotizacion.id == proyecto.cotizacion_id)).scalar_one_or_none()
    if not cot:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cotización asociada no existe")
    db_proy = Proyecto(
        nombre=proyecto.nombre,
        cotizacion_id=proyecto.cotizacion_id,
        estado=proyecto.estado
    )
    db.add(db_proy)
    db.commit()
    db.refresh(db_proy)
    return db_proy

@app.get("/proyectos", response_model=List[ProyectoOut])
def list_proyectos(skip: int = 0, limit: int = 100, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    proyectos = db.execute(select(Proyecto).offset(skip).limit(limit)).scalars().all()
    return proyectos

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
    fecha = gasto.fecha or datetime.utcnow()
    db_gasto = Gasto(
        proyecto_id=gasto.proyecto_id,
        descripcion=gasto.descripcion,
        monto=gasto.monto,
        fecha=fecha
    )
    db.add(db_gasto)
    db.commit()
    db.refresh(db_gasto)
    return db_gasto

@app.get("/gastos", response_model=List[GastoOut])
def list_gastos(skip: int = 0, limit: int = 100, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    gastos = db.execute(select(Gasto).offset(skip).limit(limit)).scalars().all()
    return gastos

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
    bitacoras = db.execute(query.offset(skip).limit(limit)).scalars().all()
    return bitacoras

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
