# -*- coding: utf-8 -*-
"""Pruebas E2E de la FASE 5 (Núcleo de IA Yeruzzza) contra BD temporal."""
import json
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:///./test_fase5.db"
os.environ["MEDIA_DIR"] = "./media_test_fase5"
sys.stdout.reconfigure(encoding="utf-8")

import httpx

BASE = "http://127.0.0.1:8425/api"
PASADOS, FALLAS = [], []


def llamada(metodo, ruta, token=None, **kw):
    if token:
        headers = kw.pop("headers", {})
        headers["Authorization"] = "Bearer " + token
        kw["headers"] = headers
    r = httpx.request(metodo, BASE + ruta, timeout=120, **kw)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, r.text


def prueba(nombre, condicion, detalle=""):
    if condicion:
        PASADOS.append(nombre)
        print(f"  OK   {nombre}")
    else:
        FALLAS.append(f"{nombre} | {detalle}")
        print(f"  FALLA {nombre} {detalle}")


# ---- usuarios ----
s, h = llamada("GET", "/health")
prueba("health 1.5.0", s == 200 and h.get("version", "").startswith("1.5.0"), (s, h))
s, r = llamada("POST", "/auth/register", data={"username": "dueno5", "password": "claveSegura123"},
               headers={"Content-Type": "application/x-www-form-urlencoded"})
s, r = llamada("POST", "/auth/login", data={"username": "dueno5", "password": "claveSegura123"},
               headers={"Content-Type": "application/x-www-form-urlencoded"})
tk = r.get("access_token")
enc = {"Authorization": "Bearer " + tk}
s, _ = llamada("POST", "/usuarios", json={"username": "admin5", "password": "operativo99"}, headers=enc)
s, r = llamada("POST", "/auth/login", data={"username": "admin5", "password": "operativo99"},
               headers={"Content-Type": "application/x-www-form-urlencoded"})
tk_adm = r.get("access_token")

# ---- 1. Config de IA (permisos + cifrado + honestidad) ----
s, c0 = llamada("GET", "/ia/config", token=tk)
prueba("config IA inicial sin configurar", s == 200 and c0["configurado"] is False, (s, c0))
s, a403 = llamada("GET", "/ia/config", token=tk_adm)
prueba("admin NO ve config IA (403)", s == 403, (s, a403))
s, act = llamada("POST", "/ia/activar", json={"activo": True}, token=tk)
prueba("activar sin credenciales → 400", s == 400, (s, act))

# clave con base inalcanzable (nada escucha en 9900): debe quedar guardada y cifrada
s, c1 = llamada("PUT", "/ia/config", json={"api_base": "http://127.0.0.1:9900/v1",
                                           "modelo": "modelo-fake", "api_key": "sk-prueba-123456"},
                token=tk)
prueba("clave IA guardada y nunca expuesta", s == 200 and c1["clave_guardada"] is True
       and "sk-prueba" not in str(c1), (s, c1))
s, probar = llamada("POST", "/ia/probar", token=tk)
prueba("probar IA con base muerta reporta falla honesta", s == 200 and probar["ok"] is False,
       (s, probar))

# ---- 2. Chat honesto sin IA activa ----
s, ch = llamada("POST", "/ia/chat", json={"texto": "cuántos clientes tengo?"}, token=tk)
prueba("chat con núcleo desactivado responde con honestidad", s == 200
       and ch["ia_activa"] is False and "desactivado" in ch["texto"], (s, ch))

# ---- 3. Herramientas reales (offline, directas) ----
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.db import SessionLocal  # noqa: E402
from app.modelos import User as MUser  # noqa: E402
from app.ia_core import _ejecutar_crear_cliente, _ejecutar_crear_cotizacion, _lista_servicios  # noqa: E402

db = SessionLocal()
dueno = db.query(MUser).filter_by(username="dueno5").one()
admin = db.query(MUser).filter_by(username="admin5").one()

r1 = _ejecutar_crear_cliente(db, {"nombre": "Constructora Omega", "nit": "900777-1", "ciudad": "Cali"}, dueno)
prueba("herramienta crear_cliente funciona", r1["ok"] is True and r1.get("cliente_id"), r1)
r1b = _ejecutar_crear_cliente(db, {"nombre": "Constructora Omega"}, dueno)
prueba("crear_cliente rechaza duplicado", r1b["ok"] is False, r1b)

r2 = _ejecutar_crear_cotizacion(db, {
    "nombre_cliente": "Constructora Omega",
    "items": [{"descripcion": "Punto de datos", "cantidad": 10, "precio_unitario": 65000,
               "costo_unitario": 40000}],
    "descuento_pct": 10, "iva_pct": 19}, dueno)
prueba("herramienta crear_cotizacion respeta límites del dueño", r2["ok"] is True, r2)
r3 = _ejecutar_crear_cotizacion(db, {
    "nombre_cliente": "Constructora Omega",
    "items": [{"descripcion": "x", "cantidad": 1, "precio_unitario": 1000, "costo_unitario": 1}],
    "descuento_pct": 50}, admin)
prueba("la IA de un admin NO puede violar el descuento máximo", r3["ok"] is False
       and "descuento" in str(r3.get("error")), r3)
servicios = json.loads(_lista_servicios(db, {}))
prueba("herramienta listar_servicios devuelve JSON real",
       isinstance(servicios.get("servicios"), list), servicios)
db.close()

# ---- 4. Autorización humana: propuestas pendientes ----
# (el chat con IA muerta no crea propuestas; simulamos una propuesta real)
from app.modelos import IAAccion  # noqa: E402
ses = SessionLocal()
dueno2 = ses.query(MUser).filter_by(username="dueno5").one()
propuesta = IAAccion(conversacion_id=f"panel-{dueno2.id}", usuario_id=dueno2.id,
                     herramienta="crear_cliente",
                     argumentos=json.dumps({"nombre": "Inversiones Delta S.A.S.", "ciudad": "Bogotá"}),
                     resumen="Crear cliente: Inversiones Delta S.A.S.")
ses.add(propuesta)
ses.commit()
id_accion = propuesta.id
ses.close()

s, conf = llamada("POST", f"/ia/acciones/{id_accion}/confirmar", token=tk)
prueba("confirmación humana ejecuta la acción", s == 200 and conf["ok"] is True
       and conf["resultado"].get("cliente_id"), (s, conf))
s, clientes = llamada("GET", "/clientes", token=tk)
prueba("el cliente aprobado quedó en la base", any(c["nombre"] == "Inversiones Delta S.A.S."
                                                   for c in clientes), (s, clientes))
s, conf2 = llamada("POST", f"/ia/acciones/{id_accion}/confirmar", token=tk)
prueba("reconfirmar acción ejecutada → 409", s == 409, (s, conf2))

ses = SessionLocal()
dueno3 = ses.query(MUser).filter_by(username="dueno5").one()
propuesta2 = IAAccion(conversacion_id=f"panel-{dueno3.id}", usuario_id=dueno3.id,
                      herramienta="crear_cliente",
                      argumentos=json.dumps({"nombre": "Cancelado S.A."}),
                      resumen="Crear cliente: Cancelado S.A.")
ses.add(propuesta2)
ses.commit()
id_cancelar = propuesta2.id
ses.close()
s, can = llamada("POST", f"/ia/acciones/{id_cancelar}/cancelar", token=tk)
prueba("cancelar propuesta descarta sin tocar datos", s == 200 and can["ok"] is True, (s, can))
s, clientes2 = llamada("GET", "/clientes", token=tk)
prueba("el cliente cancelado NO existe", not any(c["nombre"] == "Cancelado S.A." for c in clientes2))
s, a403b = llamada("POST", f"/ia/acciones/{id_cancelar}/confirmar", token=tk_adm)
prueba("admin NO confirma acciones ajenas (403)", s == 403, (s, a403b))

# ---- 5. Historial del núcleo ----
s, msj = llamada("GET", "/ia/mensajes", token=tk)
prueba("historial del núcleo guarda turnos usuario/asistente",
       s == 200 and any(m["rol"] == "usuario" for m in msj)
       and any(m["rol"] == "asistente" for m in msj), (s, msj))

print()
print(f"RESULTADO: {len(PASADOS)} OK / {len(FALLAS)} FALLAS")
for f in FALLAS:
    print("  FALLA:", f)
