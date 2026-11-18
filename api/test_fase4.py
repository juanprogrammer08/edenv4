# -*- coding: utf-8 -*-
"""Pruebas E2E de la FASE 4 (Comercial) contra BD temporal."""
import io
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:///./test_fase4.db"
os.environ["MEDIA_DIR"] = "./media_test_fase4"
sys.stdout.reconfigure(encoding="utf-8")

import httpx
from docx import Document

BASE = "http://127.0.0.1:8424/api"
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


def descarga_binaria(ruta, token):
    r = httpx.get(BASE + ruta, headers={"Authorization": "Bearer " + token}, timeout=120)
    return r.status_code, r.content


def prueba(nombre, condicion, detalle=""):
    if condicion:
        PASADOS.append(nombre)
        print(f"  OK   {nombre}")
    else:
        FALLAS.append(f"{nombre} | {detalle}")
        print(f"  FALLA {nombre} {detalle}")


# ---- dueño y admin ----
s, h = llamada("GET", "/health")
prueba("health 1.4.0", s == 200 and h.get("version", "").startswith("1.4.0"), (s, h))
s, r = llamada("POST", "/auth/register", data={"username": "dueno4", "password": "claveSegura123"},
               headers={"Content-Type": "application/x-www-form-urlencoded"})
s, r = llamada("POST", "/auth/login", data={"username": "dueno4", "password": "claveSegura123"},
               headers={"Content-Type": "application/x-www-form-urlencoded"})
tk = r.get("access_token")
enc = {"Authorization": "Bearer " + tk}
s, _ = llamada("POST", "/usuarios", json={"username": "admin4", "password": "operativo99"}, headers=enc)
s, r = llamada("POST", "/auth/login", data={"username": "admin4", "password": "operativo99"},
               headers={"Content-Type": "application/x-www-form-urlencoded"})
tk_adm = r.get("access_token")
enc_adm = {"Authorization": "Bearer " + tk_adm}

# ---- 1. Catálogo ----
s, c1 = llamada("POST", "/servicios", json={
    "codigo": "PD-001", "nombre": "Punto de datos (red)", "categoria": "redes",
    "unidad": "punto", "precio_venta": 65000, "costo_materiales": 25000,
    "costo_mano_obra": 15000, "tiempo_estimado_horas": 0.5}, token=tk)
prueba("dueño crea servicio con margen calculado", s == 201 and c1["margen_pct"] == 38.5, (s, c1))
s, adm403 = llamada("POST", "/servicios", json={"codigo": "X", "nombre": "X", "precio_venta": 1}, token=tk_adm)
prueba("admin NO crea servicios (403)", s == 403, (s, adm403))
s, dup = llamada("POST", "/servicios", json={"codigo": "PD-001", "nombre": "dup", "precio_venta": 1}, token=tk)
prueba("código de servicio duplicado → 400", s == 400, (s, dup))
s, c2 = llamada("POST", "/servicios", json={
    "codigo": "PE-001", "nombre": "Punto de energía regulada", "categoria": "electrica",
    "unidad": "punto", "precio_venta": 78000, "costo_materiales": 30000, "costo_mano_obra": 15000}, token=tk)
s, cr = llamada("GET", "/servicios", token=tk)
por_codigo = {x["codigo"]: x for x in cr}
prueba("catálogo listado con costo_total y margen",
       por_codigo["PD-001"]["costo_total"] == 40000 and por_codigo["PD-001"]["margen_pct"] == 38.5,
       por_codigo.get("PD-001"))

# ---- 2. Clientes ----
s, cl1 = llamada("POST", "/clientes", json={"nombre": "Edificio Centenario", "nit": "900555123-4",
                                            "contacto": "Sra. Gómez", "telefono": "+57 300 111 2233",
                                            "correo": "admin@centenario.co", "ciudad": "Cali"}, token=tk_adm)
prueba("admin crea cliente (clientes son operativos)", s == 201, (s, cl1))
s, dupc = llamada("POST", "/clientes", json={"nombre": "Edificio Centenario"}, token=tk)
prueba("cliente duplicado → 400", s == 400, (s, dupc))
s, cl2 = llamada("POST", "/clientes", json={"nombre": "Inversiones Delta"}, token=tk)
id_cl1, id_cl2 = cl1["id"], cl2["id"]

# ---- 3. Config comercial ----
s, cfg = llamada("GET", "/config-comercial", token=tk)
prueba("config por defecto 20/15", cfg == {"descuento_max_pct": 20.0, "margen_minimo_pct": 15.0}, (s, cfg))
s, cfg403 = llamada("PUT", "/config-comercial", json={"descuento_max_pct": 30, "margen_minimo_pct": 10}, token=tk_adm)
prueba("admin NO cambia límites (403)", s == 403, (s, cfg403))

# ---- 4. Cotización con ítems del catálogo (snapshot) ----
cotizacion_body = {
    "cliente_id": id_cl1,
    "descripcion": "Red y energía para piso 3",
    "items": [
        {"servicio_id": c1["id"], "descripcion": c1["nombre"], "cantidad": 15, "unidad": "punto",
         "precio_unitario": 65000, "costo_unitario": 40000},
        {"servicio_id": c2["id"], "descripcion": c2["nombre"], "cantidad": 4, "unidad": "punto",
         "precio_unitario": 78000, "costo_unitario": 45000},
    ],
    "descuento_pct": 5, "iva_pct": 19, "forma_pago": "50/50", "vigencia_cotizacion": "15 días",
}
s, cot = llamada("POST", "/cotizaciones", json=cotizacion_body, token=tk)
prueba("cotización creada con numeración automática", s == 201 and cot["numero"] == "COT-2026-00001",
       (s, cot.get("numero") if isinstance(cot, dict) else cot))
prueba("cálculo: subtotal 1.287.000, total 1.454.953,5",
       cot["subtotal"] == 1287000 and abs(cot["total"] - 1454953.5) < 0.01, (s, cot))
prueba("costo y utilidad estimados", cot["costo_estimado"] == 780000 and cot["utilidad"] == 442650, cot)
prueba("snapshot de cliente", cot["cliente"] == "Edificio Centenario" and cot["cliente_id"] == id_cl1, cot)
id_cot = cot["id"]

# límites: admin con descuento 35% > 20 → 400
body_desc = dict(cotizacion_body, descuento_pct=35)
s, lim = llamada("POST", "/cotizaciones", json=body_desc, token=tk_adm)
prueba("descuento sobre el límite del dueño → 400", s == 400, (s, lim))
# margen bajo para admin (costo casi = precio)
body_margen = {"cliente": "Al por menor", "iva_pct": 0,
               "items": [{"descripcion": "venta floja", "cantidad": 10, "precio_unitario": 1000,
                          "costo_unitario": 960}]}
s, mg = llamada("POST", "/cotizaciones", json=body_margen, token=tk_adm)
prueba("margen bajo el mínimo para admin → 400", s == 400, (s, mg))
s, mg2 = llamada("POST", "/cotizaciones", json=body_margen, token=tk)
prueba("el dueño sí puede salvar ese margen (es su decisión)", s == 201, (s, mg2))
id_cot_dueno = mg2["id"] if s == 201 else None

# ---- 5. Edición y estados ----
s, edit = llamada("PUT", f"/cotizaciones/{id_cot}", json={
    "descripcion": "Red y energía piso 3 (ajustada)",
    "items": cotizacion_body["items"] + [
        {"descripcion": "Cascada entre racks", "cantidad": 1, "unidad": "und",
         "precio_unitario": 120000, "costo_unitario": 60000}],
    "descuento_pct": 5, "iva_pct": 19}, token=tk_adm)
prueba("admin edita cotización y recalcula", s == 200 and edit["subtotal"] == 1407000
       and edit["costo_estimado"] == 840000, (s, edit))
s, est = llamada("POST", f"/cotizaciones/{id_cot}/estado", json={"estado": "pendiente"}, token=tk_adm)
prueba("borrador → pendiente", s == 200 and est["estado"] == "pendiente", (s, est))
s, est2 = llamada("POST", f"/cotizaciones/{id_cot}/estado", json={"estado": "aprobada"}, token=tk_adm)
prueba("pendiente → aprobada", s == 200 and est2["estado"] == "aprobada", (s, est2))
s, edit409 = llamada("PUT", f"/cotizaciones/{id_cot}", json={
    "items": [{"descripcion": "x", "cantidad": 1, "precio_unitario": 1}], "iva_pct": 0}, token=tk)
prueba("editar una aprobada → 409", s == 409, (s, edit409))
s, conv409 = llamada("POST", f"/cotizaciones/{id_cot_dueno}/convertir", token=tk)
prueba("convertir no-aprobada → 409", s == 409, (s, conv409))
s, conv = llamada("POST", f"/cotizaciones/{id_cot}/convertir", token=tk)
prueba("aprobada → proyecto creado", s == 200 and conv.get("proyecto_id", 0) > 0, (s, conv))
s, proys = llamada("GET", "/proyectos", token=tk)
prueba("proyecto activo con nombre desde la cotización", proys and proys[0]["estado"] == "activo", (s, proys))
s, conv2 = llamada("POST", f"/cotizaciones/{id_cot}/convertir", token=tk)
prueba("reconvertir → 409", s == 409, (s, conv2))

# ---- 6. Duplicar ----
s, dupcot = llamada("POST", f"/cotizaciones/{id_cot}/duplicar", token=tk_adm)
prueba("duplicar crea borrador con nuevo número e ítems",
       s == 200 and dupcot["estado"] == "borrador" and dupcot["numero"] != "COT-2026-00001"
       and len(dupcot["items"]) == 3, (s, dupcot))

# ---- 7. Historial del cliente ----
s, hist = llamada("GET", f"/clientes/{id_cl1}/cotizaciones", token=tk_adm)
prueba("historial comercial del cliente", s == 200 and len(hist) >= 1
       and hist[0]["cliente_id"] == id_cl1, (s, hist))

# ---- 8. PDF de la cotización (plantilla de la FASE 3) ----
doc = Document()
doc.add_paragraph("Cotización {{numero_cotizacion}} — {{nombre_cliente}}")
doc.add_paragraph("Total: {{total}}")
doc.add_paragraph("{{tabla_servicios}}")
buf = io.BytesIO(); doc.save(buf)
s, plant = llamada("POST", "/plantillas", headers=enc,
                   data={"nombre": "Plantilla Comercial"},
                   files={"archivo": ("comercial.docx", buf.getvalue())})
s, pdf = llamada("POST", "/plantillas/" + str(plant["id"]) + "/predeterminada", headers=enc)
s, rpdf = llamada("POST", f"/cotizaciones/{id_cot}/pdf", token=tk)
prueba("PDF de cotización generado con plantilla predeterminada",
       s == 200 and rpdf.get("documento_id", 0) > 0, (s, rpdf))
s, detalle = llamada("GET", f"/cotizaciones/{id_cot}", token=tk)
prueba("cotización amarrada a plantilla y documento",
       detalle["plantilla_id"] == plant["id"] and detalle["documento_id"] == rpdf["documento_id"], detalle)
s2, bytes_doc = descarga_binaria(f"/documentos/{rpdf['documento_id']}/descarga?formato=docx", tk)
doc_gen = Document(io.BytesIO(bytes_doc))
textos = "\n".join(p.text for p in doc_gen.paragraphs)
prueba("el PDF/DOCX contiene los datos reales de la cotización",
       "COT-2026-00001" in textos and "Edificio Centenario" in textos and "{{" not in textos,
       textos[:120])

# ---- 9. Indicadores reales ----
s, ind = llamada("GET", "/indicadores", token=tk_adm)
prueba("indicadores con conteos y valores reales",
       ind["cotizaciones"]["total"] >= 3
       and ind["cotizaciones"]["valor_cotizado"] > 3000000
       and ind["clientes_total"] == 2 and ind["proyectos"]["activos"] == 1
       and ind["servicios_mas_solicitados"]
       and ind["servicios_mas_solicitados"][0]["nombre"] not in ("?", None), ind)

# ---- 10. Eliminación protegida ----
s, delServ = llamada("DELETE", f"/servicios/{c1['id']}", token=tk)
prueba("servicio usado en cotizaciones → 409 + desactivado", s == 409, (s, delServ))
s, chkServ = llamada("GET", "/servicios", token=tk)
prueba("servicio quedó inactivo (no borrado)", any(x["id"] == c1["id"] and not x["activo"] for x in chkServ))

print()
print(f"RESULTADO: {len(PASADOS)} OK / {len(FALLAS)} FALLAS")
for f in FALLAS:
    print("  FALLA:", f)
