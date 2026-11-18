# -*- coding: utf-8 -*-
"""Infraestructura de base de datos de EDÉN: motor, sesiones, migraciones y utilidades."""
from sqlalchemy import create_engine, text, inspect as sa_inspect
from sqlalchemy.orm import sessionmaker, declarative_base
from passlib.context import CryptContext
from datetime import datetime
import base64
import hashlib
import os

from app.config import DATABASE_URL

# Intentar conectar a PostgreSQL, fallback honesto a SQLite si falla
try:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    )
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
except Exception:
    DATABASE_URL = "sqlite:///./app.db"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def fernet_desde_secret():
    """Fernet con clave derivada de AUTH_SECRET (cifra el token del bot en BD).
    Si se rota AUTH_SECRET, hay que volver a guardar el token desde el panel."""
    from cryptography.fernet import Fernet
    from app.config import AUTH_SECRET
    clave = hashlib.sha256(AUTH_SECRET.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(clave))


def registrar_auditoria(db, accion: str, usuario=None, detalle: str = "", ip: str = "",
                        username_libre: str = ""):
    """Registra una operación sensible. Un fallo del log nunca rompe la operación."""
    from app.modelos import Auditoria
    try:
        db.add(Auditoria(
            usuario_id=usuario.id if usuario else None,
            username=usuario.username if usuario else username_libre,
            accion=accion,
            detalle=(detalle or "")[:2000],
            ip=(ip or "")[:64],
        ))
        db.commit()
    except Exception:
        db.rollback()


def inicializar_bd():
    """Crea tablas y corre migraciones versionadas. Se llama al arrancar la app."""
    import app.modelos  # noqa: F401  (registra todos los modelos en Base)
    Base.metadata.create_all(bind=engine)
    _run_migraciones()


# ---------------- MIGRACIONES VERSIONADAS ----------------
TABLA_MIGRACIONES = "_schema_migrations"

MIGRACIONES = []


def _columna_existe(conn, tabla, columna):
    insp = sa_inspect(conn)
    return columna in [c["name"] for c in insp.get_columns(tabla)]


def _m001_rol_usuarios(conn):
    """FASE 1: columna rol en users; promueve al usuario de id más bajo a dueño."""
    if not _columna_existe(conn, "users", "rol"):
        conn.execute(text("ALTER TABLE users ADD COLUMN rol VARCHAR(20) DEFAULT 'admin' NOT NULL"))
    hay_dueno = conn.execute(text("SELECT COUNT(*) FROM users WHERE rol = 'dueno'")).scalar()
    if not hay_dueno:
        primero = conn.execute(text("SELECT MIN(id) FROM users")).scalar()
        if primero is not None:
            conn.execute(text("UPDATE users SET rol = 'dueno' WHERE id = :id"), {"id": primero})


MIGRACIONES.append(("001_rol_usuarios", _m001_rol_usuarios))


def _add_col_si_falta(conn, tabla, columna, ddl):
    if not _columna_existe(conn, tabla, columna):
        conn.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {ddl}"))


def _m002_cotizaciones_comercial(conn):
    """FASE 4: cotizaciones con ítems, numeración y estados nuevos.
    - Añade columnas del modelo comercial.
    - Backfill: numero = COT-<id con ceros>.
    - Estados antiguos: aceptada -> aprobada."""
    add_cols = [
        ("numero", "numero VARCHAR(20)"),
        ("cliente_id", "cliente_id INTEGER"),
        ("subtotal", "subtotal FLOAT DEFAULT 0"),
        ("descuento_pct", "descuento_pct FLOAT DEFAULT 0"),
        ("descuento_valor", "descuento_valor FLOAT DEFAULT 0"),
        ("iva_pct", "iva_pct FLOAT DEFAULT 0"),
        ("iva_valor", "iva_valor FLOAT DEFAULT 0"),
        ("costo_estimado", "costo_estimado FLOAT DEFAULT 0"),
        ("utilidad", "utilidad FLOAT DEFAULT 0"),
        ("tiempo_ejecucion", "tiempo_ejecucion VARCHAR(120) DEFAULT ''"),
        ("forma_pago", "forma_pago VARCHAR(200) DEFAULT ''"),
        ("vigencia_cotizacion", "vigencia_cotizacion VARCHAR(120) DEFAULT ''"),
        ("observaciones", "observaciones TEXT DEFAULT ''"),
        ("plantilla_id", "plantilla_id INTEGER"),
        ("plantilla_version", "plantilla_version INTEGER"),
        ("documento_id", "documento_id INTEGER"),
    ]
    for columna, ddl in add_cols:
        _add_col_si_falta(conn, "cotizaciones", columna, ddl)
    numerar = conn.execute(text("SELECT id FROM cotizaciones WHERE numero IS NULL")).fetchall()
    for (cid,) in numerar:
        conn.execute(text("UPDATE cotizaciones SET numero = :num WHERE id = :id"),
                     {"num": f"COT-{cid:05d}", "id": cid})
    conn.execute(text("UPDATE cotizaciones SET estado = 'aprobada' WHERE estado = 'aceptada'"))


MIGRACIONES.append(("002_cotizaciones_comercial", _m002_cotizaciones_comercial))


def _m003_operaciones(conn):
    """FASE 6: proyectos completos y gastos clasificados. No destructiva."""
    add_proy = [
        ("codigo", "codigo VARCHAR(20)"),
        ("cliente_id", "cliente_id INTEGER"),
        ("cliente", "cliente VARCHAR(200) DEFAULT ''"),
        ("descripcion", "descripcion TEXT DEFAULT ''"),
        ("presupuesto", "presupuesto FLOAT DEFAULT 0"),
        ("fecha_inicio", "fecha_inicio DATETIME"),
        ("fecha_fin", "fecha_fin DATETIME"),
        ("avance_pct", "avance_pct FLOAT DEFAULT 0"),
    ]
    for columna, ddl in add_proy:
        if not _columna_existe(conn, "proyectos", columna):
            conn.execute(text(f"ALTER TABLE proyectos ADD COLUMN {ddl}"))
    numerar = conn.execute(text("SELECT id FROM proyectos WHERE codigo IS NULL")).fetchall()
    for (pid,) in numerar:
        conn.execute(text("UPDATE proyectos SET codigo = :c WHERE id = :id"),
                     {"c": f"PRY-{pid:05d}", "id": pid})
    # presupuesto/ cliente desde la cotización de origen
    conn.execute(text(
        "UPDATE proyectos SET presupuesto = (SELECT total FROM cotizaciones "
        "WHERE cotizaciones.id = proyectos.cotizacion_id) "
        "WHERE presupuesto = 0 AND EXISTS (SELECT 1 FROM cotizaciones WHERE cotizaciones.id = proyectos.cotizacion_id)"
    ))
    conn.execute(text(
        "UPDATE proyectos SET cliente = (SELECT cliente FROM cotizaciones "
        "WHERE cotizaciones.id = proyectos.cotizacion_id) "
        "WHERE cliente = '' AND EXISTS (SELECT 1 FROM cotizaciones WHERE cotizaciones.id = proyectos.cotizacion_id)"
    ))
    add_gasto = [
        ("tipo", "tipo VARCHAR(20) DEFAULT 'gasto'"),
        ("categoria", "categoria VARCHAR(30) DEFAULT 'otro'"),
        ("creado_por_id", "creado_por_id INTEGER"),
    ]
    for columna, ddl in add_gasto:
        if not _columna_existe(conn, "gastos", columna):
            conn.execute(text(f"ALTER TABLE gastos ADD COLUMN {ddl}"))


MIGRACIONES.append(("003_operaciones", _m003_operaciones))


def _m004_marcas_servicios(conn):
    """FASE 7.x por el propietario: vínculo servicio↔marca (desplegable)."""
    if not _columna_existe(conn, "servicios", "marca_id"):
        conn.execute(text("ALTER TABLE servicios ADD COLUMN marca_id INTEGER"))


MIGRACIONES.append(("004_marca_servicios", _m004_marcas_servicios))


def _registrar_migracion(conn, version):
    conn.execute(text(
        f"INSERT INTO {TABLA_MIGRACIONES} (version) SELECT '{version}' "
        f"WHERE NOT EXISTS (SELECT 1 FROM {TABLA_MIGRACIONES} WHERE version = '{version}')"
    ))


def _run_migraciones():
    with engine.begin() as conn:
        conn.execute(text(
            f"CREATE TABLE IF NOT EXISTS {TABLA_MIGRACIONES} "
            "(id INTEGER PRIMARY KEY, version VARCHAR(64) UNIQUE, "
            "aplicada_en DATETIME DEFAULT CURRENT_TIMESTAMP)"
        ))
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
