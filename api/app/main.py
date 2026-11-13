from fastapi import FastAPI, Depends, HTTPException, status, Form, Request
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import create_engine, select, update, delete
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Float
from typing import Optional, List
from datetime import datetime, timedelta
import os

# Configuración y constantes
AUTH_SECRET = os.getenv("AUTH_SECRET", "secret-key-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 días

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./app.db"
)

# Intentar conectar a PostgreSQL, fallback a SQLite si falla
try:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
    # Probar conexión
    with engine.connect() as conn:
        conn.execute("SELECT 1")
except Exception:
    # Fallback a SQLite local
    DATABASE_URL = "sqlite:///./app.db"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI(root_path="/api")

# CORS (permitir frontend local y producción)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Ajustar en producción
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MODELOS SQLALCHEMY

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(128), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

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

# Crear tablas si no existen
Base.metadata.create_all(bind=engine)

# UTILIDADES

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

# DEPENDENCIAS

def get_current_user(token: str = Depends(lambda request: request.headers.get("Authorization", "").replace("Bearer ", "")), db: Session = Depends(get_db)) -> User:
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

# ESQUEMAS Pydantic

from pydantic import BaseModel, Field

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)

class UserOut(BaseModel):
    id: int
    username: str
    is_active: bool
    created_at: datetime

    class Config:
        orm_mode = True

class Token(BaseModel):
    access_token: str
    token_type: str

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

    class Config:
        orm_mode = True

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

    class Config:
        orm_mode = True

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

    class Config:
        orm_mode = True

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

    class Config:
        orm_mode = True

# RUTAS

@app.get("/health")
def health():
    return {"status": "ok"}

# AUTH

@app.post("/auth/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user_exists = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user_exists:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El usuario ya existe")
    hashed_password = get_password_hash(password)
    user = User(username=username, hashed_password=hashed_password)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

@app.post("/auth/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.username == form_data.username)).scalar_one_or_none()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario o contraseña incorrectos")
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/auth/me", response_model=UserOut)
def read_me(current_user: User = Depends(get_current_user)):
    return current_user

# CRUD Cotizaciones

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

# CRUD Proyectos

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

# CRUD Gastos

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

# CRUD Bitacora

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