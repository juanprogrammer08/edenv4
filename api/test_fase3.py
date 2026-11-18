# -*- coding: utf-8 -*-
"""Pruebas E2E de la FASE 3 (Plantillas de cotización) contra BD temporal."""
import io
import json
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:///./test_fase3.db"
os.environ["MEDIA_DIR"] = "./media_test_fase3"
sys.stdout.reconfigure(encoding="utf-8")

import httpx
import urllib.parse
import urllib.request
import urllib.error
from docx import Document

BASE = "http://127.0.0.1:8423/api"
PASADOS, FALLAS = [], []


def llamada(metodo, ruta, token=None, **kw):
    r = httpx.request(metodo, BASE + ruta, timeout=120, **kw)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, r.text


def descarga_binaria(ruta, token):
    r = httpx.get(BASE + ruta, headers={"Authorization": "Bearer " + token}, timeout=300)
    return r.status_code, r.content


def prueba(nombre, condicion, detalle=""):
    if condicion:
        PASADOS.append(nombre)
        print(f"  OK   {nombre}")
    else:
        FALLAS.append(f"{nombre} | {detalle}")
        print(f"  FALLA {nombre} {detalle}")


def docx_prueba(tabla_en_marca=True):
    doc = Document()
    doc.add_paragraph("Cotización {{numero_cotizacion}} — Cliente: {{nombre_cliente}}")
    doc.add_paragraph("Total: {{total}} — Subtotal: {{subtotal}}")
    doc.add_paragraph("Observaciones: {{observaciones}}")
    if tabla_en_marca:
        t = doc.add_table(rows=2, cols=6)
        for j, h in enumerate(["Ítem", "Descripción", "Cantidad", "Unidad", "Precio unitario", "Total"]):
            t.rows[0].cells[j].text = h
        t.rows[1].cells[0].text = "{{tabla_servicios}}"
        for j in range(1, 6):
            t.rows[1].cells[j].text = "X"
    else:
        doc.add_paragraph("Detalle: {{tabla_servicios}}")
    doc.sections[0].header.paragraphs[0].text = "Empresa: {{nombre_empresa}} / NIT {{nit_empresa}}"
    bufer = io.BytesIO()
    doc.save(bufer)
    return bufer.getvalue()


# ---- 1. usuario dueño propio de la BD temporal ----
s, h = llamada("GET", "/health")
prueba("health 1.3.0", s == 200 and h.get("version", "").startswith("1.3.0"), (s, h))
s, r = llamada("POST", "/auth/register", data={"username": "yovani_test", "password": "claveSegura123"},
               headers={"Content-Type": "application/x-www-form-urlencoded"})
prueba("registro creacional de dueño", s == 201 and isinstance(r, dict) and r.get("rol") == "dueno", (s, r))
s, r = llamada("POST", "/auth/login", data={"username": "yovani_test", "password": "claveSegura123"},
               headers={"Content-Type": "application/x-www-form-urlencoded"})
tk_dueno = r.get("access_token") if isinstance(r, dict) else None
prueba("login dueño", s == 200 and tk_dueno, (s, r))
enc = {"Authorization": "Bearer " + tk_dueno}

s, ta = llamada("POST", "/usuarios", json={"username": "admin_pl", "password": "operativo99"}, headers=enc)
s, tl = llamada("POST", "/auth/login", data={"username": "admin_pl", "password": "operativo99"},
                headers={"Content-Type": "application/x-www-form-urlencoded"})
tk_admin = tl.get("access_token")
enc_adm = {"Authorization": "Bearer " + tk_admin}

# ---- 2. subir plantilla DOCX (tabla como marca) ----
arch1 = docx_prueba(tabla_en_marca=True)
s, p1 = llamada("POST", "/plantillas", headers=enc,
                data={"nombre": "Cotización YERUZZA", "descripcion": "Formato principal"},
                files={"archivo": ("cotizacion_yeruzza.docx", arch1)})
prueba("subida DOCX crea plantilla v1", s == 201 and p1.get("version") == 1, (s, p1))
esperadas = {"numero_cotizacion", "nombre_cliente", "total", "subtotal", "observaciones",
             "tabla_servicios", "nombre_empresa", "nit_empresa"}
detectadas = set(p1.get("variables", []))
prueba("variables detectadas correctamente", esperadas.issubset(detectadas),
       (esperadas - detectadas))
id_p1 = p1.get("id")

# ---- 3. validaciones ----
s, dup = llamada("POST", "/plantillas", headers=enc,
                 data={"nombre": "Cotización YERUZZA"}, files={"archivo": ("x.docx", arch1)})
prueba("nombre duplicado → 400", s == 400, (s, dup))
s, mal = llamada("POST", "/plantillas", headers=enc,
                 data={"nombre": "otra"}, files={"archivo": ("x.pdf", b"no es docx")})
prueba("extensión no-docx → 400", s == 400, (s, mal))
s, adm403 = llamada("POST", "/plantillas", headers=enc_adm,
                    data={"nombre": "de_admin"}, files={"archivo": ("x.docx", arch1)})
prueba("admin NO puede subir plantillas (403)", s == 403, (s, adm403))

# ---- 4. plantilla HTML ----
html_plantilla = """<html><head><title>Cotización</title></head><body>
<h1>{{nombre_empresa}}</h1><h2>{{nombre_cliente}}</h2>
<p>{{descripcion_proyecto}}</p>
{{tabla_servicios}}
<p>Total: <b>{{total}}</b></p></body></html>"""
s, p2 = llamada("POST", "/plantillas", headers=enc,
                data={"nombre": "Cotización HTML", "contenido_html": html_plantilla})
prueba("plantilla HTML registrada", s == 201 and p2.get("tipo") == "html", (s, p2))
id_p2 = p2.get("id")

# ---- 5. versión nueva + historial ----
arch2 = docx_prueba(tabla_en_marca=True)
s, v2 = llamada(f"POST", f"/plantillas/{id_p1}/version", headers=enc,
                files={"archivo": ("cotizacion_yeruzza_v2.docx", arch2)})
prueba("nueva versión DOCX → v2", s == 200 and v2.get("version") == 2, (s, v2))
s, hist = llamada("GET", f"/plantillas/{id_p1}/historial", headers=enc)
prueba("historial conserva ambas versiones", s == 200 and len(hist) == 2
       and hist[0]["es_actual"] is True, (s, hist))

# ---- 6. predeterminada ----
s, def1 = llamada(f"POST", f"/plantillas/{id_p1}/predeterminada", headers=enc)
prueba("plantilla predeterminada definida", s == 200 and def1.get("es_predeterminada") is True, (s, def1))
s, def2 = llamada(f"POST", f"/plantillas/{id_p2}/predeterminada", headers=enc)
s, chk = llamada("GET", "/plantillas", headers=enc)
p1_estado = next(p for p in chk if p["id"] == id_p1)
prueba("solo una predeterminada a la vez", p1_estado["es_predeterminada"] is False, (s, p1_estado))

# ---- 7. descarga del original ----
s2, bytes_orig = descarga_binaria(f"/plantillas/{id_p1}/archivo", tk_dueno)
prueba("descarga del original DOCX", s2 == 200 and len(bytes_orig) > 1000)

# ---- 8. generar documento con la plantilla tabla ----
datos = {
    "numero_cotizacion": "COT-2026-0007",
    "nombre_cliente": "Edificio Centenario",
    "documento_cliente": "900555123-4", "telefono_cliente": "+57 300 111 2233",
    "correo_cliente": "admin@centenario.co", "direccion_cliente": "Av 5 #45-67",
    "descripcion_proyecto": "25 puntos de datos y 8 eléctricos regulados",
    "items": [
        {"descripcion": "Punto de datos (red)", "cantidad": 15, "unidad": "punto", "precio_unitario": 65000},
        {"descripcion": "Punto de energía regulada", "cantidad": 4, "unidad": "punto", "precio_unitario": 78000},
    ],
    "descuento_pct": 5, "iva_pct": 19, "tiempo_ejecucion": "5 días",
    "forma_pago": "50/50", "vigencia_cotizacion": "15 días",
    "observaciones": "Incluye materiales.",
}
s, gen = llamada("POST", f"/plantillas/{id_p1}/generar", headers=enc, json=datos)
prueba("documento generado", s == 200 and gen.get("documento_id") > 0, (s, gen))
id_doc = gen.get("documento_id", 0)
prueba("referencia de versión en salida", gen.get("nombre_archivo_docx", "").find("_2_") > 0, gen)

# reemplazo REAL dentro del docx generado
s2, bytes_doc = descarga_binaria(f"/documentos/{id_doc}/descarga?formato=docx", tk_dueno)
doc_gen = Document(io.BytesIO(bytes_doc))
textos = "\n".join(p.text for p in doc_gen.paragraphs)
prueba("variables simples reemplazadas", "COT-2026-0007" in textos and "Edificio Centenario" in textos
       and "{{" not in textos, textos[:120])
prueba("encabezado de página reemplazado",
       "Empresa:" in doc_gen.sections[0].header.paragraphs[0].text and
       "{{nombre_empresa}}" not in doc_gen.sections[0].header.paragraphs[0].text)
prueba("totales con formato colombiano", "$1.287.000" in textos and "$1.454.954" in textos, textos[:200])
t0 = doc_gen.tables[0]
nombres_celdas = [t0.rows[i].cells[1].text for i in range(len(t0.rows))]
prueba("tabla de servicios rellenada con N filas",
       t0.rows[0].cells[0].text == "Ítem" and "Punto de datos (red)" in nombres_celdas
       and "Punto de energía regulada" in nombres_celdas
       and "{{" not in "\n".join(c.text for r in t0.rows for c in r.cells),
       nombres_celdas)
prueba("filas de totales añadidas", "TOTAL" in nombres_celdas and "Subtotal" in nombres_celdas,
       nombres_celdas)

# ---- 9. plantilla con marcador en PÁRRAFO (tabla nueva insertada) ----
s, p3 = llamada("POST", "/plantillas", headers=enc,
                data={"nombre": "Formato sencillo"},
                files={"archivo": ("sencillo.docx", docx_prueba(tabla_en_marca=False))})
s, gen2 = llamada("POST", f"/plantillas/{p3['id']}/generar", headers=enc, json=datos)
s2, bytes_d2 = descarga_binaria(f"/documentos/{gen2['documento_id']}/descarga?formato=docx", tk_dueno)
d2 = Document(io.BytesIO(bytes_d2))
tablas2 = d2.tables
prueba("marcador en párrafo inserta tabla nueva", len(tablas2) >= 1
       and tablas2[0].rows[0].cells[0].text == "Ítem", [len(tablas2)])

# ---- 10. generación HTML ----
s, genh = llamada("POST", f"/plantillas/{id_p2}/generar", headers=enc, json=datos)
prueba("documento HTML generado", s == 200, (s, genh))
s, html_lleno = llamada("GET", f"/documentos/{genh['documento_id']}/descarga?formato=html", headers=enc)
texto = html_lleno if isinstance(html_lleno, str) else str(html_lleno)
prueba("HTML llena variables y tabla", "Edificio Centenario" in texto and "tabla_servicios" in texto
       and "Punto de datos (red)" in texto and "{{" not in texto, texto[:150])

# ---- 11. documentos listados con su plantilla y versión ----
s, docs = llamada("GET", "/documentos", headers=enc)
doc_v2 = next((d for d in docs if d["plantilla"] == "Cotización YERUZZA"
               and d["plantilla_version"] == 2), None)
prueba("historial de documentos registra plantilla/versión",
       s == 200 and doc_v2 is not None and doc_v2["numero_cotizacion"] == "COT-2026-0007",
       docs[:1])

# ---- 12. eliminar plantilla con documentos → desactiva ----
s, delv = llamada("DELETE", f"/plantillas/{id_p1}", headers=enc)
prueba("eliminar con documentos da 409 y desactiva", s == 409, (s, delv))
s, chk2 = llamada("GET", "/plantillas", headers=enc)
p1b = next(p for p in chk2 if p["id"] == id_p1)
prueba("plantilla quedo desactivada", p1b["activa"] is False and p1b["es_predeterminada"] is False, p1b)

print()
print(f"RESULTADO: {len(PASADOS)} OK / {len(FALLAS)} FALLAS")
for f in FALLAS:
    print("  FALLA:", f)
