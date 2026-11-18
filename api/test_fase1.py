# -*- coding: utf-8 -*-
"""Pruebas E2E de la FASE 1 contra una BD temporal (no toca app.db)."""
import json
import urllib.request
import urllib.error
import urllib.parse

BASE = "http://127.0.0.1:8421/api"
PASADOS = []
FALLAS = []

def llamada(metodo, ruta, datos=None, token=None):
    url = BASE + ruta
    cuerpo = None
    encabezados = {}
    if token:
        encabezados["Authorization"] = "Bearer " + token
    if datos is not None and isinstance(datos, dict) and "form" not in datos:
        cuerpo = json.dumps(datos["json"]).encode()
        encabezados["Content-Type"] = "application/json"
    elif datos is not None and isinstance(datos, dict) and "form" in datos:
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
        FALLAS.append(nombre + (" | " + str(detalle) if detalle else ""))
        print(f"  FALLA {nombre} {detalle}")

# 1. Health
s, h = llamada("GET", "/health")
prueba("health responde con version", s == 200 and h.get("status") == "ok" and "version" in h, h)

# 2. Primer registro = DUENO
s, r = llamada("POST", "/auth/register", {"form": {"username": "juan_dueno", "password": "claveSegura123"}})
prueba("primer registro crea DUENO (rol)", s == 201 and r and r.get("rol") == "dueno", (s, r))

# 3. Segundo registro bloqueado
s2, r2 = llamada("POST", "/auth/register", {"form": {"username": "intruso", "password": "claveSegura123"}})
prueba("registro cerrado tras existir dueno (403)", s2 == 403, (s2, r2))

# 4. Login dueno
s3, t = llamada("POST", "/auth/login", {"form": {"username": "juan_dueno", "password": "claveSegura123"}})
tk_dueno = t.get("access_token") if isinstance(t, dict) else None
prueba("login dueno entrega token", s3 == 200 and tk_dueno, (s3, t))

# 5. /auth/me con rol
s4, me = llamada("GET", "/auth/me", token=tk_dueno)
prueba("auth/me expone rol", s4 == 200 and me.get("rol") == "dueno", (s4, me))

# 6. Dueno crea administrador
s5, adm = llamada("POST", "/usuarios", {"json": {"username": "admin1", "password": "operativo99"}}, tk_dueno)
id_admin = adm.get("id") if isinstance(adm, dict) else None
prueba("dueno crea administrador (rol admin)", s5 == 201 and adm.get("rol") == "admin", (s5, adm))

# 7. Admin inicia sesion
s6, ta = llamada("POST", "/auth/login", {"form": {"username": "admin1", "password": "operativo99"}})
tk_admin = ta.get("access_token") if isinstance(ta, dict) else None
prueba("admin inicia sesion", s6 == 200 and tk_admin, (s6, ta))

# 8. Restricciones del ADMIN
sa, ra = llamada("GET", "/usuarios", token=tk_admin)
prueba("admin NO lista usuarios (403)", sa == 403, (sa, ra))
sb, rb = llamada("GET", "/auditoria", token=tk_admin)
prueba("admin NO consulta auditoria (403)", sb == 403, (sb, rb))
sc, rc = llamada("PUT", "/empresa", {"json": {"nombre": "Hackeo"}}, tk_admin)
prueba("admin NO edita empresa (403)", sc == 403, (sc, rc))
sd, rd = llamada("POST", "/usuarios", {"json": {"username": "escalon", "password": "operativo99"}}, tk_admin)
prueba("admin NO crea usuarios (403)", sd == 403, (sd, rd))

# 9. Gestion de empresa por dueno
se, re_ = llamada("GET", "/empresa", token=tk_dueno)
prueba("dueno consulta empresa", se == 200 and "nombre" in re_, (se, re_))
sf, rf = llamada("PUT", "/empresa", {"json": {"nombre": "Instalaciones Técnicas EDÉN S.A.S.", "nit": "900123456-1", "ciudad": "Cali"}}, tk_dueno)
prueba("dueno actualiza empresa", sf == 200 and rf.get("nombre") == "Instalaciones Técnicas EDÉN S.A.S." and rf.get("nit") == "900123456-1", (sf, rf))

# 10. Estado de usuarios: desactivar admin
sg, rg = llamada("PUT", f"/usuarios/{id_admin}/estado?activo=false", None, tk_dueno)
prueba("dueno desactiva admin", sg == 200 and rg.get("is_active") is False, (sg, rg))
sh, rh = llamada("POST", "/auth/login", {"form": {"username": "admin1", "password": "operativo99"}})
prueba("admin desactivado NO puede iniciar sesion", sh == 401, (sh, rh))
si, ri = llamada("PUT", f"/usuarios/{id_admin}/estado?activo=true", None, tk_dueno)
prueba("dueno reactiva admin", si == 200 and ri.get("is_active") is True, (si, ri))

# 11. El dueno no puede desactivarse ni eliminarse
sj, rj = llamada("GET", "/usuarios", token=tk_dueno)
id_dueno = next(u["id"] for u in rj if u["rol"] == "dueno")
sk, rk = llamada("PUT", f"/usuarios/{id_dueno}/estado?activo=false", None, tk_dueno)
prueba("dueno NO puede desactivarse a si mismo", sk == 403, (sk, rk))
sl, rl = llamada("DELETE", f"/usuarios/{id_dueno}", None, tk_dueno)
prueba("dueno NO puede eliminarse", sl == 403, (sl, rl))

# 12. Reseteo de contraseña por dueno
sm, rm = llamada("PUT", f"/usuarios/{id_admin}/password", {"json": {"password": "nuevaClave77"}}, tk_dueno)
prueba("dueno resetea password de admin", sm == 200, (sm, rm))
sn, rn = llamada("POST", "/auth/login", {"form": {"username": "admin1", "password": "nuevaClave77"}})
prueba("admin entra con password nueva", sn == 200, (sn, rn))

# 13. Cambio de password propia
so, ro = llamada("PUT", "/mi/password", {"json": {"password": "adminOtro55"}}, token=tk_admin)
prueba("usuario cambia su propia password", so == 200, (so, ro))
sp, rp = llamada("POST", "/auth/login", {"form": {"username": "admin1", "password": "adminOtro55"}})
prueba("login con password propia nueva", sp == 200, (sp, rp))

# 14. CRUD cotizaciones sigue vivo
sq, rq = llamada("POST", "/cotizaciones", {"json": {"cliente": "Edificio Centenario", "descripcion": "25 puntos de datos", "total": 12345.5}}, tk_admin)
prueba("admin crea cotizacion (CRUD conservado)", sq == 200 and rq.get("cliente") == "Edificio Centenario", (sq, rq))
sr, rr = llamada("GET", "/cotizaciones", token=tk_dueno)
prueba("dueno lista cotizaciones", sr == 200 and len(rr) >= 1, (sr, rr))

# 15. Auditoria registra operaciones
st, rt = llamada("GET", "/auditoria", token=tk_dueno)
acciones = [a["accion"] for a in rt] if isinstance(rt, list) else []
esperadas = {"admin_creado", "login_ok", "login_fallido", "empresa_actualizada", "usuario_estado", "password_reseteada", "password_propia_cambiada"}
prueba("auditoria registra operaciones sensibles", st == 200 and esperadas.issubset(set(acciones)), (st, set(acciones)))

# 16. Rate limit de login
bloqueado = False
for _ in range(8):
    sb2, _rb = llamada("POST", "/auth/login", {"form": {"username": "admin1", "password": "malamalamala"}})
    if sb2 == 429:
        bloqueado = True
        break
prueba("rate limit bloquea fuerza bruta (429)", bloqueado)

print()
print(f"RESULTADO: {len(PASADOS)} OK / {len(FALLAS)} FALLAS")
if FALLAS:
    for f in FALLAS:
        print("  FALLA:", f)
