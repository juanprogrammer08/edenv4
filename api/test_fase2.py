# -*- coding: utf-8 -*-
"""Pruebas E2E de la FASE 2 (Telegram) contra BD temporal.

Lo único que NO puede probarse sin el token real de BotFather es la
conversación directa con Telegram (getMe/sendMessage/getUpdates): esas
quedan marcadas como activación externa del propietario.
"""
import json
import sqlite3
import urllib.parse
import urllib.request
import urllib.error
import asyncio
import os
import sys

# El proceso de pruebas inyecta updates del bot y DEBE apuntar a la BD temporal
os.environ["DATABASE_URL"] = "sqlite:///./test_fase2.db"
sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8422/api"
BD_PRUEBA = os.path.join(os.path.dirname(__file__), "test_fase2.db")
SECRET_PRUEBA = "SECRETOTELEGRAMTEST123456"

PASADOS, FALLAS = [], []


def llamada(metodo, ruta, datos=None, token=None, encabezados_extra=None):
    url = BASE + ruta
    cuerpo, encabezados = None, (encabezados_extra or {})
    if token:
        encabezados["Authorization"] = "Bearer " + token
    if isinstance(datos, dict):
        if "json" in datos:
            cuerpo = json.dumps(datos["json"]).encode()
            encabezados["Content-Type"] = "application/json"
        elif "form" in datos:
            cuerpo = urllib.parse.urlencode(datos["form"]).encode()
            encabezados["Content-Type"] = "application/x-www-form-urlencoded"
    solicitud = urllib.request.Request(url, data=cuerpo, headers=encabezados, method=metodo)
    try:
        with urllib.request.urlopen(solicitud) as r:
            texto = r.read().decode()
            return r.status, (json.loads(texto) if texto else None)
    except urllib.error.HTTPError as e:
        texto = e.read().decode()
        try:
            return e.code, json.loads(texto)
        except Exception:
            return e.code, texto


def prueba(nombre, condicion, detalle=""):
    if condicion:
        PASADOS.append(nombre)
        print(f"  OK   {nombre}")
    else:
        FALLAS.append(f"{nombre} | {detalle}")
        print(f"  FALLA {nombre} {detalle}")


# ---- 1. health y dueño en BD limpia ----
s, h = llamada("GET", "/health")
prueba("health con version 1.2.0", s == 200 and h.get("version", "").startswith("1.2.0"), (s, h))

s, r = llamada("POST", "/auth/register", {"form": {"username": "yovani", "password": "claveSegura123"}})
prueba(" registro creacional de dueno", s == 201 and r.get("rol") == "dueno", (s, r))

s, t = llamada("POST", "/auth/login", {"form": {"username": "yovani", "password": "claveSegura123"}})
tk_dueno = t.get("access_token")
prueba("login dueno", s == 200 and tk_dueno, (s, t))

s, adm = llamada("POST", "/usuarios", {"json": {"username": "admin_tg", "password": "operativo99"}}, tk_dueno)
prueba("dueno crea admin", s == 201, (s, adm))
s, ta = llamada("POST", "/auth/login", {"form": {"username": "admin_tg", "password": "operativo99"}})
tk_admin = ta.get("access_token")

# ---- 2. Config del bot (sin token real) ----
s, c = llamada("GET", "/telegram/config", None, tk_dueno)
prueba("GET config inicial sin token", s == 200 and c.get("configurado") is False, (s, c))

s, c2 = llamada("GET", "/telegram/config", None, tk_admin)
prueba("admin NO ve config del bot (403)", s == 403, (s, c2))

s, c3 = llamada("GET", "/telegram/estado", None, tk_admin)
prueba("todos ven estado basico del bot", s == 200 and "bot" in c3 and "mi_cuenta" in c3, (s, c3))

s, c4 = llamada("PUT", "/telegram/config", {"json": {"bot_token": "123:ABCdef"}}, tk_dueno)
prueba("guardar token falso es rechazado por Telegram con 400", s == 400, (s, c4))

s, c5 = llamada("POST", "/telegram/activar", {"json": {}}, tk_dueno)
prueba("activar sin token configurado da 400", s == 400, (s, c5))

# ---- 3. Vinculación por código (sin bot en línea: update inyectado) ----
s, cod = llamada("GET", "/telegram/codigo", None, tk_dueno)
codigo_valido = cod.get("codigo")
prueba("dueno genera codigo temporal", s == 200 and len(codigo_valido) == 6, (s, cod))

s, cod2 = llamada("GET", "/telegram/codigo", None, tk_dueno)
prueba("nuevo codigo generado (valida re-generacion)", s == 200, (s, cod2))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.telegram import _procesar_update  # noqa: E402

async def update_texto(texto, uid="70001", uname="yovani_tg"):
    await _procesar_update({
        "update_id": 1,
        "message": {"chat": {"id": uid}, "from": {"id": uid, "username": uname}, "text": texto},
    })

# código inválido
asyncio.run(update_texto("/vincular 999999"))
s, cuentas = llamada("GET", "/telegram/cuentas", None, tk_dueno)
prueba("codigo invalido NO vincula", s == 200 and cuentas == [], (s, cuentas))

# código re-generado anterior (primer código quedó invalidado por la segunda generación)
asyncio.run(update_texto(f"/vincular {codigo_valido}"))
s, cuentas = llamada("GET", "/telegram/cuentas", None, tk_dueno)
prueba("primer codigo invalidado por la regeneracion", s == 200 and cuentas == [], (s, cuentas))

# código vigente (el segundo)
asyncio.run(update_texto(f"/vincular {cod2['codigo']}"))
s, cuentas = llamada("GET", "/telegram/cuentas", None, tk_dueno)
prueba("vinculacion con codigo vigente", s == 200 and len(cuentas) == 1
       and cuentas[0]["usuario"] == "yovani" and cuentas[0]["telegram_id"] == "70001", (s, cuentas))

id_cuenta = cuentas[0]["id"] if cuentas else None

# re-vincular la misma cuenta (debe reactivarse, no duplicar)
asyncio.run(update_texto("/start"))
s, cuentas2 = llamada("GET", "/telegram/cuentas", None, tk_dueno)
prueba("no se duplica la vinculación", s == 200 and len(cuentas2) == 1, (s, cuentas2))

# ---- 4. Webhook protegido por secreto ----
s, w = llamada("POST", "/telegram/webhook", {"json": {"update_id": 2}})
prueba("webhook sin secreto da 403", s == 403, (s, w))

con = sqlite3.connect(BD_PRUEBA)
con.execute("UPDATE telegram_config SET webhook_secret=?, activo=1 WHERE id=1", (SECRET_PRUEBA,))
con.commit()
con.close()

update_prueba = {"update_id": 3,
                 "message": {"chat": {"id": "70001"}, "from": {"id": "70001", "username": "yovani_tg"},
                             "text": "/estado"}}
s, w2 = llamada("POST", "/telegram/webhook", {"json": update_prueba},
                encabezados_extra={"X-Telegram-Bot-Api-Secret-Token": SECRET_PRUEBA})
prueba("webhook con secreto válido procesa (200)", s == 200 and w2 is not None and w2.get("ok") is True, (s, w2))

s, w3 = llamada("POST", "/telegram/webhook", {"json": update_prueba},
                encabezados_extra={"X-Telegram-Bot-Api-Secret-Token": "otrosecreto"})
prueba("webhook con secreto errado da 403", s == 403, (s, w3))

# ---- 5. Historial de mensajes ----
# Inyectamos un token cifrado falso para ejercitar el camino de SALIDA:
# el envío real fallará contra Telegram (401 / sin red) y debe quedar
# registrado honestamente como salida no entregada.
import sqlite3 as _sq3
from app.db import fernet_desde_secret
con2 = _sq3.connect(BD_PRUEBA)
con2.execute("UPDATE telegram_config SET bot_token_cifrado=? WHERE id=1",
             (fernet_desde_secret().encrypt(b"123:TESTTOKENFALSO").decode(),))
con2.commit()
con2.close()
asyncio.run(update_texto("/estado"))

s, msj = llamada("GET", "/telegram/mensajes", None, tk_dueno)
direcciones = {m["direccion"] for m in msj} if isinstance(msj, list) else set()
prueba("historial registra entradas y salidas", s == 200 and "entrada" in direcciones and "salida" in direcciones,
       (s, direcciones))
salida_no_entregada = any(m["direccion"] == "salida" and m["entregado"] is False
                          for m in msj) if isinstance(msj, list) else False
prueba("la salida fallida queda registrada con su error", salida_no_entregada)
prueba("los comandos quedan tipados",
       any(m["tipo"] == "comando" for m in msj) if isinstance(msj, list) else False)

# ---- 6. Desvinculación ----
s, d = llamada("DELETE", f"/telegram/cuentas/{id_cuenta}", None, tk_dueno)
prueba("dueño desvincula cuenta", s == 200 and d.get("ok") is True, (s, d))
s, cuentas3 = llamada("GET", "/telegram/cuentas", None, tk_dueno)
prueba("cuenta desvinculada desaparece", cuentas3 == [], (s, cuentas3))

# ---- 7. Auditoría de Telegram ----
s, audi = llamada("GET", "/auditoria?limit=200", None, tk_dueno)
acciones = {a["accion"] for a in audi} if isinstance(audi, list) else set()
esperadas = {"telegram_codigo_generado", "telegram_vinculacion", "telegram_desvinculacion",
             "telegram_webhook_rechazado"}
prueba("auditoría registra operaciones Telegram", esperadas.issubset(acciones),
       (esperadas - acciones))

# ---- 8. Notificación sin bot en línea (token falso) ----
con = sqlite3.connect(BD_PRUEBA)
cur = con.execute("INSERT INTO telegram_cuentas (telegram_id, telegram_username, usuario_id, activo) "
                  "VALUES ('70002', 'admin_tg', 2, 1)")
id_cuenta_falsa = cur.lastrowid
con.commit()
con.close()
s, n = llamada("POST", "/telegram/notificar", {"json": {"cuenta_id": id_cuenta_falsa, "texto": "hola"}}, tk_dueno)
prueba("notificar con token falso reporta falla honesta", s == 200 and n.get("ok") is False, (s, n))
s, n2 = llamada("POST", "/telegram/notificar", {"json": {"cuenta_id": 999, "texto": "hola"}}, tk_dueno)
prueba("notificar a cuenta inexistente da 404", s == 404, (s, n2))

print()
print(f"RESULTADO: {len(PASADOS)} OK / {len(FALLAS)} FALLAS")
if FALLAS:
    for f in FALLAS:
        print("  FALLA:", f)
