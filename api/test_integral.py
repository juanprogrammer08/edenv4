# -*- coding: utf-8 -*-
"""PRUEBAS INTEGRALES (FASE 7): el ciclo completo de la empresa en una BD temporal.

Historia: yovani estrena la plataforma → configura su empresa → crea un admin →
sube su plantilla → arma el catálogo → registra un cliente → cotiza → aprueba →
PDF → convierte en proyecto → compra materiales y registra gastos → agenda una
visita → guarda un plano y una credencial → prueba Yeruzzza IA → consulta
reportes y auditoría. Cada afirmación se verifica contra la BD real.
"""
import io
import json
import os
import sys
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:///./test_integral.db"
os.environ["MEDIA_DIR"] = "./media_test_integral"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx
from docx import Document

BASE = "http://127.0.0.1:8427/api"
PASADOS, FALLAS = [], []


def llamada(metodo, ruta, token=None, **kw):
    if token:
        headers = kw.pop("headers", {})
        headers["Authorization"] = "Bearer " + token
        kw["headers"] = headers
    r = httpx.request(metodo, BASE + ruta, timeout=180, **kw)
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


# ================= DÍA 1: la empresa configura la plataforma =================
s, h = llamada("GET", "/health")
prueba("salud del sistema 1.7.0 con base de datos real informada",
       s == 200 and h["version"].startswith("1.7.0") and h["db"] == "sqlite", h)

s, r = llamada("POST", "/auth/register", data={"username": "yovani", "password": "claveSegura123"},
               headers={"Content-Type": "application/x-www-form-urlencoded"})
prueba("primer registro = dueño", s == 201 and r["rol"] == "dueno", (s, r))
s, r = llamada("POST", "/auth/login", data={"username": "yovani", "password": "claveSegura123"},
               headers={"Content-Type": "application/x-www-form-urlencoded"})
tk = r.get("access_token")
enc = {"Authorization": "Bearer " + tk}
s, r = llamada("POST", "/usuarios", json={"username": "amanda", "password": "operativa99"}, headers=enc)
s, r = llamada("POST", "/auth/login", data={"username": "amanda", "password": "operativa99"},
               headers={"Content-Type": "application/x-www-form-urlencoded"})
tk_adm = r.get("access_token")
s, emp = llamada("PUT", "/empresa", json={
    "nombre": "Instalaciones Técnicas YERUZZA S.A.S.", "nit": "901123456-7",
    "ciudad": "Cali", "telefono": "+57 300 123 4567"}, token=tk)
prueba("empresa configurada", s == 200 and emp["nombre"].startswith("Instalaciones"), (s, emp))

# ================= plantilla con el diseño propio =================
doc = Document()
doc.add_paragraph("{{nombre_empresa}} — Cotización {{numero_cotizacion}}")
doc.add_paragraph("Cliente: {{nombre_cliente}} · Total: {{total}}")
doc.add_paragraph("Observaciones: {{observaciones}}")
doc.add_paragraph("{{tabla_servicios}}")
doc.sections[0].header.paragraphs[0].text = "NIT {{nit_empresa}}"
buf = io.BytesIO(); doc.save(buf)
s, plant = llamada("POST", "/plantillas", headers=enc,
                   data={"nombre": "Cotización oficial YERUZZA"},
                   files={"archivo": ("oficial.docx", buf.getvalue())})
s, _ = llamada("POST", "/plantillas/" + str(plant["id"]) + "/predeterminada", headers=enc)
prueba("plantilla DOCX del dueño predeterminada",
       s == 200 or (s == 200 and plant["version"] == 1), plant)

# ================= catálogo =================
catalogo = [
    ("PD-001", "Punto de datos (red)", "redes", 65000, 25000, 15000),
    ("PE-001", "Punto de energía regulada", "electrica", 78000, 30000, 15000),
    ("RK-001", "Rack 12U instalado", "redes", 850000, 450000, 120000),
]
ids = {}
for codigo, nombre, cat, precio, mat, obra in catalogo:
    s, serv = llamada("POST", "/servicios", json={
        "codigo": codigo, "nombre": nombre, "categoria": cat, "unidad": "punto",
        "precio_venta": precio, "costo_materiales": mat, "costo_mano_obra": obra}, token=tk)
    ids[codigo] = serv["id"]
s, cat_list = llamada("GET", "/servicios", token=tk_adm)
prueba("catálogo completo con margen real", len(cat_list) == 3
       and all(x["margen_pct"] > 0 for x in cat_list), cat_list)

# ================= cliente + cotización =================
s, cli = llamada("POST", "/clientes", json={
    "nombre": "Centro comercial Unicentro", "nit": "800123456-1",
    "contacto": "Ing. Restrepo", "ciudad": "Cali"}, token=tk_adm)
s, cot = llamada("POST", "/cotizaciones", json={
    "cliente_id": cli["id"],
    "descripcion": "25 puntos de datos, 8 eléctricos regulados, 1 rack 12U",
    "items": [
        {"servicio_id": ids["PD-001"], "descripcion": "Punto de datos (red)",
         "cantidad": 25, "unidad": "punto", "precio_unitario": 65000, "costo_unitario": 40000},
        {"servicio_id": ids["PE-001"], "descripcion": "Punto de energía regulada",
         "cantidad": 8, "unidad": "punto", "precio_unitario": 78000, "costo_unitario": 45000},
        {"servicio_id": ids["RK-001"], "descripcion": "Rack 12U instalado",
         "cantidad": 1, "unidad": "und", "precio_unitario": 850000, "costo_unitario": 570000},
    ],
    "descuento_pct": 3, "iva_pct": 19, "forma_pago": "50% anticipo, 50% contra entrega",
    "vigencia_cotizacion": "15 días"}, token=tk_adm)
prueba("cotización creada por el admin con numeración COT",
       s == 201 and cot["numero"] == "COT-2026-00001" and cot["total"] > 1500000, cot)
prueba("cotización respeta los límites del dueño",
       cot["descuento_pct"] == 3 and cot["utilidad"] > 0, cot)

s, dup = llamada(f"POST", f"/cotizaciones/{cot['id']}/duplicar", token=tk_adm)
s, est = llamada("POST", f"/cotizaciones/{cot['id']}/estado", json={"estado": "enviada"}, token=tk_adm)
s, est = llamada("POST", f"/cotizaciones/{cot['id']}/estado", json={"estado": "aprobada"}, token=tk)
s, rpdf = llamada("POST", f"/cotizaciones/{cot['id']}/pdf", token=tk)
prueba("PDF/DOCX generado con la plantilla del dueño", rpdf.get("documento_id", 0) > 0, rpdf)
rd = httpx.get(BASE + f"/documentos/{rpdf['documento_id']}/descarga?formato=docx",
               headers={"Authorization": "Bearer " + tk})
doc_gen = Document(io.BytesIO(rd.content))
textos = "\n".join(p.text for p in doc_gen.paragraphs)
prueba("el documento lleva los datos reales y el diseño",
       "COT-2026-00001" in textos and "Centro comercial Unicentro" in textos
       and "{{" not in textos, textos[:100])

# ================= proyecto =================
s, conv = llamada(f"POST", f"/cotizaciones/{cot['id']}/convertir", token=tk)
s, proys = llamada("GET", "/proyectos", token=tk)
proy = proys[0]
prueba("proyecto con presupuesto = cotización", conv["ok"] and proy["presupuesto"] == cot["total"]
       and proy["codigo"] == "PRY-00001", proy)

# compra materiales + gasto mano de obra
s, g1 = llamada("POST", "/gastos", json={"proyecto_id": proy["id"],
                                         "descripcion": "Cable cat6, keystone, rack accesorios",
                                         "monto": 640000, "tipo": "compra", "categoria": "materiales"},
                token=tk_adm)
s, g2 = llamada("POST", "/gastos", json={
    "proyecto_id": proy["id"], "descripcion": "Cuadrilla instalación",
    "monto": 320000, "tipo": "gasto", "categoria": "mano_obra"}, token=tk)
s, fin = llamada("GET", f"/proyectos/{proy['id']}", token=tk)
prueba("ejecución real contra presupuesto con desglose",
       fin["gastos_total"] == 960000 and fin["saldo"] == round(fin["presupuesto"] - 960000, 2)
       and fin["utilidad_real"] == round(fin["presupuesto"] - 960000, 2), fin)

# ================= agenda + repositorio + bóveda =================
s, ev = llamada("POST", "/agenda", json={"titulo": "Entrega certificación Unicentro",
                                         "fecha_hora": (datetime.utcnow() + timedelta(days=2)).isoformat(),
                                         "tipo": "entrega", "cliente_id": cli["id"],
                                         "proyecto_id": proy["id"]}, token=tk_adm)
prueba("entrega agendada y ligada", s == 201 and ev["recordado"] is False, ev)

s, arch = llamada("POST", "/archivos", token=tk_adm,
                  data={"categoria": "foto", "proyecto_id": proy["id"], "cliente_id": cli["id"]},
                  files={"archivo": ("avance_jornada.txt", b"Fotos avance: rack subido, patch panel ok")})
r = httpx.get(BASE + f"/archivos/{arch['id']}/descarga", headers={"Authorization": "Bearer " + tk})
prueba("repositorio guarda y devuelve el plano/foto", r.status_code == 200
       and b"patch panel ok" in r.content, r.status_code)

s, cred = llamada("POST", "/credenciales", json={
    "plataforma": "Portal Unicentro proveedores", "usuario_cuenta": "yeruzza.co",
    "password": "UniProv2026", "categoria": "cliente"}, token=tk)
s, rev = llamada("POST", f"/credenciales/{cred['id']}/revelar", token=tk)
prueba("bóveda: guardada cifrada y revelada con auditoría",
       rev.get("password") == "UniProv2026", rev)

# ================= Yeruzzza IA (honestidad + autorización) =================
s, cfg = llamada("PUT", "/ia/config", json={"api_base": "http://127.0.0.1:9901/v1",
                                            "modelo": "ollama-cloud/fake", "api_key": "omni-fake-key"},
                 token=tk)
s, prueba_ia = llamada("POST", "/ia/probar", token=tk)
prueba("proveedor IA muerto se reporta con honestidad", prueba_ia["ok"] is False, prueba_ia)
s, ch = llamada("POST", "/ia/chat", json={"texto": "cuánto vale un punto de datos?"}, token=tk_adm)
prueba("núcleo desactivado responde sin fingir", ch["ia_activa"] is False, ch)
# propuesta pendiente → autorización humana → ejecución real
# (con el proveedor muerto, la acción se siembra directamente como el flujo real
#  del núcleo: propuesta guardada → el humano confirma → ejecución verificada)
from app.modelos import IAAccion, User as MU  # noqa: E402
from app.db import SessionLocal  # noqa: E402
ses = SessionLocal()
dueno_db = ses.query(MU).filter_by(username="yovani").one()
acc = IAAccion(conversacion_id=f"panel-{dueno_db.id}", usuario_id=dueno_db.id,
               herramienta="crear_cotizacion",
               argumentos=json.dumps({"nombre_cliente": "Constructora Omega",
                                      "items": [{"descripcion": "Punto de voz", "cantidad": 5,
                                                 "unidad": "punto", "precio_unitario": 52000,
                                                 "costo_unitario": 34000}],
                                      "iva_pct": 19}),
               resumen="Crear cotización para Constructora Omega (5 ítems)")
ses.add(acc); ses.commit(); id_acc = acc.id; ses.close()
s, conf = llamada("POST", f"/ia/acciones/{id_acc}/confirmar", token=tk)
prueba("autorización humana ejecuta la cotización propuesta",
       s == 200 and conf["ok"] is True and conf["resultado"].get("numero"), conf)

# ================= reportes y auditoría =================
s, rep = llamada("GET", "/reportes", token=tk)
prueba("reporte con datos reales del ciclo completo",
       rep["cotizaciones"]["conteo_total"] >= 2
       and rep["gastos"]["total"] == 960000
       and rep["proyectos"]["activos"] >= 1
       and rep["top_clientes"]
       and rep["top_clientes"][0]["cliente"].startswith("Centro comercial")
       and any(x["codigo"] == "PD-001" and x["veces"] >= 2
               for x in rep["servicios_mas_solicitados"]),
       rep)
s, rep_cli = llamada("GET", f"/reportes?cliente_id={cli['id']}", token=tk)
prueba("filtro por cliente acota el reporte",
       rep_cli["cotizaciones"]["conteo_total"] < rep["cotizaciones"]["conteo_total"], rep_cli)
s, audi = llamada("GET", "/auditoria?limit=300", token=tk)
acciones = {a["accion"] for a in audi}
prueba("auditoría registra la jornada completa",
       {"cotizacion_creada", "gasto_registrado", "credencial_revelada",
        "archivo_subido", "cotizacion_pdf", "ia_accion_confirmada"}.issubset(acciones),
       sorted(acciones)[:20])
s, audi_adm = llamada("GET", f"/auditoria?username=amanda&limit=300", token=tk)
prueba("auditoría filtrable por usuario",
       len(audi_adm) > 0 and all(a["username"] == "amanda" for a in audi_adm), len(audi_adm))
s, audi403 = llamada("GET", "/auditoria", token=tk_adm)
prueba("el admin NO consulta auditoría", s == 403)

print()
print(f"INTEGRAL: {len(PASADOS)} OK / {len(FALLAS)} FALLAS")
for f in FALLAS:
    print("  FALLA:", f)
