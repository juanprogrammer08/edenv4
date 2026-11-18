# -*- coding: utf-8 -*-
"""Pruebas E2E de la FASE 6 (Operaciones) contra BD temporal."""
import io
import json
import os
import sys
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:///./test_fase6.db"
os.environ["MEDIA_DIR"] = "./media_test_fase6"
sys.stdout.reconfigure(encoding="utf-8")

import httpx

BASE = "http://127.0.0.1:8426/api"
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


# ---- setup: dueño, admin, cliente, servicio, cotización aprobada y convertida ----
s, h = llamada("GET", "/health")
prueba("health 1.6.0", s == 200 and h.get("version", "").startswith("1.6.0"), (s, h))
s, r = llamada("POST", "/auth/register", data={"username": "dueno6", "password": "claveSegura123"},
               headers={"Content-Type": "application/x-www-form-urlencoded"})
s, r = llamada("POST", "/auth/login", data={"username": "dueno6", "password": "claveSegura123"},
               headers={"Content-Type": "application/x-www-form-urlencoded"})
tk = r.get("access_token")
enc = {"Authorization": "Bearer " + tk}
s, _ = llamada("POST", "/usuarios", json={"username": "admin6", "password": "operativo99"}, headers=enc)
s, r = llamada("POST", "/auth/login", data={"username": "admin6", "password": "operativo99"},
               headers={"Content-Type": "application/x-www-form-urlencoded"})
tk_adm = r.get("access_token")

s, cli = llamada("POST", "/clientes", json={"nombre": "Constructora Omega"}, token=tk)
s, serv = llamada("POST", "/servicios", json={"codigo": "PD-001", "nombre": "Punto de datos (red)",
                                              "precio_venta": 65000, "costo_materiales": 25000,
                                              "costo_mano_obra": 15000}, token=tk)
s, cot = llamada("POST", "/cotizaciones", json={
    "cliente_id": cli["id"], "descripcion": "Piso 2",
    "items": [{"servicio_id": serv["id"], "descripcion": "Punto de datos (red)",
               "cantidad": 2, "unidad": "punto", "precio_unitario": 65000,
               "costo_unitario": 40000}],
    "iva_pct": 19}, token=tk)
s, _ = llamada(f"POST", f"/cotizaciones/{cot['id']}/estado", json={"estado": "aprobada"}, token=tk)
s, conv = llamada(f"POST", f"/cotizaciones/{cot['id']}/convertir", token=tk)
prueba("proyecto nacido de la cotización aprobada", s == 200 and conv.get("proyecto_id"), (s, conv))

# ---- 1. Proyectos ----
s, proys = llamada("GET", "/proyectos", token=tk)
p1 = proys[0]
prueba("proyecto con código PRY, presupuesto y cliente del snapshot",
       p1["codigo"] == "PRY-00001" and p1["presupuesto"] == cot["total"]
       and p1["cliente"] == "Constructora Omega", p1)

s, p2 = llamada("POST", "/proyectos", json={"nombre": "Reparación tablero principal",
                                            "cliente_id": cli["id"], "presupuesto": 500000,
                                            "descripcion": "Sin cotización previa", "fecha_inicio": None},
                token=tk_adm)
prueba("admin crea proyecto directo con código siguiente", s == 201 and p2["codigo"] == "PRY-00002", (s, p2))
id_p2 = p2["id"]
s, det = llamada("GET", f"/proyectos/{id_p2}", token=tk)
prueba("detalle financiero: saldo = presupuesto", det["presupuesto"] == 500000
       and det["gastos_total"] == 0 and det["saldo"] == 500000, det)

# ---- 2. Gastos y compras ----
s, g1 = llamada("POST", "/gastos", json={"proyecto_id": id_p2, "descripcion": "Cable UTP cat6",
                                         "monto": 100000, "tipo": "compra",
                                         "categoria": "materiales"}, token=tk_adm)
prueba("admin registra compra de materiales", s == 201 and g1["tipo"] == "compra", (s, g1))
s, g2 = llamada("POST", "/gastos", json={"proyecto_id": id_p2, "descripcion": "Traslado equipos",
                                         "monto": 20000, "tipo": "gasto",
                                         "categoria": "transporte"}, token=tk)
prueba("dueño registra gasto", s == 201, (s, g2))
s, g400 = llamada("POST", "/gastos", json={"proyecto_id": 999, "descripcion": "x",
                                           "monto": 1}, token=tk)
prueba("gasto sobre proyecto inexistente → 400", s == 400, (s, g400))
s, det2 = llamada("GET", f"/proyectos/{id_p2}", token=tk)
cats = {d["categoria"]: d["monto"] for d in det2["desglose_gastos"]}
prueba("comparación presupuesto vs real con desglose",
       det2["gastos_total"] == 120000 and det2["saldo"] == 380000
       and cats.get("materiales") == 100000 and cats.get("transporte") == 20000, det2)
s, gl = llamada("GET", f"/gastos?proyecto_id={id_p2}&tipo=compra", token=tk)
prueba("filtro de gastos por tipo", len(gl) == 1, gl)

# ---- 3. Agenda ----
manana = (datetime.utcnow().replace(microsecond=0) + timedelta(days=1)).isoformat()
s, ev = llamada("POST", "/agenda", json={"titulo": "Visita técnica Centro comercial",
                                         "fecha_hora": manana, "tipo": "visita_tecnica",
                                         "cliente_id": cli["id"], "proyecto_id": id_p2,
                                         "notas": "Llevar escalera"}, token=tk_adm)
prueba("admin agenda visita técnica", s == 201 and ev["recordado"] is False, (s, ev))
s, agenda = llamada("GET", "/agenda?dias=3", token=tk)
prueba("agenda lista el evento con cliente y proyecto",
       any(e["titulo"].startswith("Visita técnica") and e["cliente"] == "Constructora Omega"
           for e in agenda), agenda)
s, ev2 = llamada("DELETE", f"/agenda/{ev['id']}", token=tk)
prueba("evento eliminado", s == 200, (s, ev2))

# ---- 4. Gestor documental ----
s, arch = llamada("POST", "/archivos", token=tk_adm,
                  data={"categoria": "plano", "proyecto_id": id_p2, "cliente_id": cli["id"]},
                  files={"archivo": ("plano_piso2.txt", b"PLANO FASE 1 - layout racks")})
prueba("upload de archivo con categoría y vínculos", s == 201 and arch["proyecto_id"] == id_p2, (s, arch))
s, lista = llamada("GET", f"/archivos?proyecto_id={id_p2}", token=tk)
prueba("listado de archivos del proyecto", len(lista) == 1, lista)
r = httpx.get(BASE + f"/archivos/{arch['id']}/descarga", headers={"Authorization": "Bearer " + tk})
prueba("descarga del archivo original", r.status_code == 200 and b"layout racks" in r.content,
       r.status_code)
s, arch403 = llamada("DELETE", f"/archivos/{arch['id']}", token=tk_adm)
prueba("admin NO elimina archivos (solo dueño)", s == 403, (s, arch403))
s, delv = llamada("DELETE", f"/archivos/{arch['id']}", token=tk)
prueba("dueño elimina archivo", s == 200, (s, delv))

# ---- 5. Bóveda de credenciales ----
s, cr403 = llamada("GET", "/credenciales", token=tk_adm)
prueba("admin NO ve la bóveda (403)", s == 403, (s, cr403))
s, cred = llamada("POST", "/credenciales", json={
    "plataforma": "Proveedor de Internet", "url": "https://portal.isp.co",
    "usuario_cuenta": "usuario@empresa.co", "password": "SecretoPortal123",
    "categoria": "servicios", "notas": "Portal administrativo"}, token=tk)
prueba("dueño guarda credencial (sin password en la respuesta)", s == 201
       and "SecretoPortal" not in str(cred), (s, cred))
id_cred = cred["id"]
s, listaC = llamada("GET", "/credenciales", token=tk)
prueba("listado de credenciales JAMÁS devuelve la contraseña",
       any(c["id"] == id_cred for c in listaC)
       and "SecretoPortal123" not in str(listaC), listaC)
s, rev = llamada("POST", f"/credenciales/{id_cred}/revelar", token=tk)
prueba("revelar entrega la contraseña clara al dueño", s == 200
       and rev.get("password") == "SecretoPortal123", (s, rev))
s, audi = llamada("GET", "/auditoria?action=credencial_revelada", token=tk)
prueba("el acceso revelado queda auditado", s == 200 and len(audi) >= 1
       and audi[0]["accion"] == "credencial_revelada", (s, audi))
s, edit = llamada("PUT", f"/credenciales/{id_cred}", json={
    "plataforma": "Proveedor de Internet", "url": "https://portal.isp.co",
    "usuario_cuenta": "usuario@empresa.co", "password": "NuevaClave456",
    "categoria": "servicios", "notas": ""}, token=tk)
s, rev2 = llamada("POST", f"/credenciales/{id_cred}/revelar", token=tk)
prueba("credencial editada revela el nuevo secreto", rev2.get("password") == "NuevaClave456", rev2)
s, d404 = llamada("DELETE", f"/credenciales/{id_cred}/revelar".replace("/revelar", ""), token=tk)
prueba("dueño elimina credencial", s == 200, (s, d404))
s, rev3 = llamada("POST", f"/credenciales/{id_cred}/revelar", token=tk)
prueba("revelar credencial eliminada → 404", s == 404, (s, rev3))

# ---- 6. Estados de proyecto ----
s, fin = llamada("PUT", f"/proyectos/{id_p2}", json={"estado": "finalizado", "avance_pct": 100},
                 token=tk)
prueba("proyecto finalizado con avance y fecha fin", fin["estado"] == "finalizado"
       and fin["avance_pct"] == 100 and fin["fecha_fin"], fin)

print()
print(f"RESULTADO: {len(PASADOS)} OK / {len(FALLAS)} FALLAS")
for f in FALLAS:
    print("  FALLA:", f)
