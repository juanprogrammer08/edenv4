# -*- coding: utf-8 -*-
"""EDÉN — Administrador de Plantillas de Cotización (FASE 3).

- Plantillas DOCX (principales, se conserva el diseño original) y HTML.
- Motor de variables {{...}} con detección automática.
- {{tabla_servicios}} genera/reemplaza una tabla de ítems de varias filas.
- Versiones: cada actualización guarda un snapshot; los documentos guardan
  la referencia de la versión usada para no alterar históricos.
- Generación de documentos con cálculo subtotal/descuento/IVA/total.
- PDF: DOCX→PDF con LibreOffice si está disponible (SOFFICE_PATH o PATH);
  si no, se entrega el .docx con mensaje honesto.
"""
import html as html_mod
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from typing import List, Optional

from docx import Document
from docx.oxml.ns import qn
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import MEDIA_DIR, ROL_DUENO, ROL_ADMIN
from app.db import get_db, registrar_auditoria
from app.modelos import Documento, Empresa, Plantilla, PlantillaVersion, User
from app.seguridad import get_current_user, require_dueno

router = APIRouter()

DIR_PLANTILLAS = os.path.join(MEDIA_DIR, "plantillas")
DIR_DOCUMENTOS = os.path.join(MEDIA_DIR, "documentos")

RE_VARIABLE = re.compile(r"\{\{\s*([a-z_0-9]+)\s*\}\}", re.IGNORECASE)
VARIABLES_INICIOS = [
    "numero_cotizacion", "fecha", "nombre_empresa", "nit_empresa", "direccion_empresa",
    "telefono_empresa", "correo_empresa", "nombre_cliente", "documento_cliente",
    "telefono_cliente", "correo_cliente", "direccion_cliente", "descripcion_proyecto",
    "subtotal", "descuento", "iva", "total", "tiempo_ejecucion", "forma_pago",
    "vigencia_cotizacion", "observaciones", "tabla_servicios",
]

ENCABEZADOS_TABLA = ["Ítem", "Descripción", "Cantidad", "Unidad", "Precio unitario", "Total"]

# ------------------------------------------------------------------
# Utilidades de archivos y PDF
# ------------------------------------------------------------------

def _nombre_seguro(nombre: str) -> str:
    base = os.path.basename(nombre or "archivo")
    return "".join(c for c in base if c.isalnum() or c in "._- ") or "archivo"


def _dir_plantilla(pid: int) -> str:
    d = os.path.join(DIR_PLANTILLAS, str(pid))
    os.makedirs(d, exist_ok=True)
    return d


def _ruta_version(pid: int, version: int, nombre_archivo: str) -> str:
    return os.path.join(_dir_plantilla(pid), f"v{version}_{_nombre_seguro(nombre_archivo)}")


def _buscar_soffice() -> Optional[str]:
    candidato_env = os.getenv("SOFFICE_PATH")
    candidatos = [candidato_env] if candidato_env else []
    encontrado = shutil.which("soffice")
    if encontrado:
        candidatos.append(encontrado)
    for ruta in candidatos:
        if ruta and os.path.exists(ruta):
            return ruta
    if os.name == "nt":
        for base in (r"C:\Program Files\LibreOffice", r"C:\Program Files (x86)\LibreOffice"):
            candidatos.append(os.path.join(base, "program", "soffice.exe"))
    for ruta in candidatos:
        if ruta and os.path.exists(ruta):
            return ruta
    return None


def _docx_a_pdf(ruta_docx: str) -> tuple[Optional[str], str]:
    """Convierte DOCX a PDF con LibreOffice headless. (ruta_pdf|None, mensaje)"""
    soffice = _buscar_soffice()
    if not soffice:
        return None, ("PDF requiere LibreOffice en el servidor; se entrega el .docx con el "
                      "contenido ya reemplazado.")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run(
                [soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp, ruta_docx],
                capture_output=True, timeout=120,
            )
            pdf_tmp = os.path.join(tmp, os.path.splitext(os.path.basename(ruta_docx))[0] + ".pdf")
            if r.returncode == 0 and os.path.exists(pdf_tmp):
                pdf_destino = os.path.splitext(ruta_docx)[0] + ".pdf"
                shutil.move(pdf_tmp, pdf_destino)
                return pdf_destino, "PDF generado con LibreOffice"
            return None, f"LibreOffice no pudo convertir el documento (código {r.returncode})."
    except Exception as e:
        return None, f"Fallo la conversión a PDF: {e}"


def _html_a_pdf(ruta_html: str) -> tuple[Optional[str], str]:
    try:
        from weasyprint import HTML  # opcional; documentado en README
    except Exception:
        return None, "PDF de HTML requiere WeasyPrint en el servidor; se entrega el HTML lleno."
    try:
        pdf_destino = os.path.splitext(ruta_html)[0] + ".pdf"
        HTML(filename=ruta_html).write_pdf(pdf_destino)
        return pdf_destino, "PDF generado con WeasyPrint"
    except Exception as e:
        return None, f"Fallo la conversión a PDF: {e}"


# ------------------------------------------------------------------
# Cálculo y valores de variables
# ------------------------------------------------------------------

class ItemEntrada(BaseModel):
    descripcion: str = Field(..., max_length=500)
    cantidad: float = Field(..., gt=0)
    unidad: str = Field("und", max_length=30)
    precio_unitario: float = Field(..., ge=0)


class DatosDocumento(BaseModel):
    numero_cotizacion: str = Field(..., max_length=60)
    nombre_cliente: str = Field(..., max_length=200)
    documento_cliente: str = Field("", max_length=60)
    telefono_cliente: str = Field("", max_length=50)
    correo_cliente: str = Field("", max_length=120)
    direccion_cliente: str = Field("", max_length=200)
    descripcion_proyecto: str = Field("", max_length=2000)
    items: List[ItemEntrada] = Field(..., min_length=1)
    descuento_pct: float = Field(0, ge=0, le=100)
    iva_pct: float = Field(0, ge=0, le=100)
    tiempo_ejecucion: str = Field("", max_length=120)
    forma_pago: str = Field("", max_length=200)
    vigencia_cotizacion: str = Field("", max_length=120)
    observaciones: str = Field("", max_length=2000)


def _fmt_moneda(v: float) -> str:
    return f"${v:,.0f}".replace(",", ".")


def _valores(datos: DatosDocumento, empresa) -> dict:
    subtotal = sum(i.cantidad * i.precio_unitario for i in datos.items)
    descuento = subtotal * datos.descuento_pct / 100
    base_iva = subtotal - descuento
    iva = base_iva * datos.iva_pct / 100
    total = base_iva + iva
    return {
        "numero_cotizacion": datos.numero_cotizacion,
        "fecha": datetime.now().strftime("%d/%m/%Y"),
        "nombre_empresa": empresa.nombre or "",
        "nit_empresa": empresa.nit or "",
        "direccion_empresa": empresa.direccion or "",
        "telefono_empresa": empresa.telefono or "",
        "correo_empresa": empresa.correo or "",
        "nombre_cliente": datos.nombre_cliente,
        "documento_cliente": datos.documento_cliente,
        "telefono_cliente": datos.telefono_cliente,
        "correo_cliente": datos.correo_cliente,
        "direccion_cliente": datos.direccion_cliente,
        "descripcion_proyecto": datos.descripcion_proyecto,
        "subtotal": _fmt_moneda(subtotal),
        "descuento": _fmt_moneda(descuento),
        "iva": _fmt_moneda(iva),
        "total": _fmt_moneda(total),
        "tiempo_ejecucion": datos.tiempo_ejecucion,
        "forma_pago": datos.forma_pago,
        "vigencia_cotizacion": datos.vigencia_cotizacion,
        "observaciones": datos.observaciones,
    }


def _items_ordenados(datos: DatosDocumento) -> list:
    subtotal = sum(i.cantidad * i.precio_unitario for i in datos.items)
    descuento = subtotal * datos.descuento_pct / 100
    base_iva = subtotal - descuento
    iva = base_iva * datos.iva_pct / 100
    total = base_iva + iva
    filas = []
    for n, i in enumerate(datos.items, start=1):
        filas.append({
            "item": str(n), "descripcion": i.descripcion,
            "cantidad": _fmt_cantidad(i.cantidad), "unidad": i.unidad,
            "precio_unitario": _fmt_moneda(i.precio_unitario),
            "total": _fmt_moneda(i.cantidad * i.precio_unitario),
        })
    filas.append({"item": "", "descripcion": "Subtotal", "cantidad": "", "unidad": "",
                  "precio_unitario": "", "total": _fmt_moneda(subtotal)})
    if descuento:
        filas.append({"item": "", "descripcion": "Descuento", "cantidad": "", "unidad": "",
                      "precio_unitario": "", "total": "-" + _fmt_moneda(descuento)})
    if datos.iva_pct:
        filas.append({"item": "", "descripcion": f"IVA ({datos.iva_pct}%)", "cantidad": "", "unidad": "",
                      "precio_unitario": "", "total": _fmt_moneda(iva)})
    filas.append({"item": "", "descripcion": "TOTAL", "cantidad": "", "unidad": "",
                  "precio_unitario": "", "total": _fmt_moneda(total)})
    return filas


def _fmt_cantidad(c: float) -> str:
    return f"{c:g}"


# ------------------------------------------------------------------
# Motor de variables: DOCX (conserva el diseño original de la plantilla)
# ------------------------------------------------------------------

def _detectar_variables_docx(ruta: str) -> List[str]:
    doc = Document(ruta)
    textos = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for fila in t.rows:
            for celda in fila.cells:
                textos.append(celda.text)
    for seccion in doc.sections:
        for contenedor in (seccion.header, seccion.footer):
            textos += [p.text for p in contenedor.paragraphs]
    encontradas = set()
    for texto in textos:
        encontradas.update(m.group(1).lower() for m in RE_VARIABLE.finditer(texto))
    return [v for v in VARIABLES_INICIOS if v in encontradas] + \
           [v for v in sorted(encontradas) if v not in VARIABLES_INICIOS]


def _reemplazar_docx(doc, valores: dict, filas_items: list):
    """Reemplaza variables en párrafos, tablas, encabezados y pies.

    - Variables simples: se funden los runs del párrafo conservando el formato
      del primer run que contenga la variable.
    - {{tabla_servicios}}: si está en una celda de una tabla existente, esa
      tabla se rellena clonando su fila plantilla; si está en un párrafo, se
      inserta una tabla nueva en ese lugar.
    """
    placeholder_tabla = None

    def reemplaza_parrafo(parrafo):
        nonlocal placeholder_tabla
        marc = re.search(r"\{\{\s*tabla_servicios\s*\}\}", parrafo.text, re.IGNORECASE)
        if marc and placeholder_tabla is None:
            placeholder_tabla = parrafo
            parrafo.text = ""
            return
        if "{{" not in parrafo.text and parrafo.text:
            return
        texto_antes = parrafo.text
        if "{{" in texto_antes:
            nuevo = RE_VARIABLE.sub(lambda m: str(valores.get(m.group(1).lower(),
                                                            "")), texto_antes)
            _reescribe_runs_simple(parrafo, nuevo)

    # párrafos del cuerpo
    for p in doc.paragraphs:
        reemplaza_parrafo(p)
    # celdas de tablas (incluye tablas de encabezado/pie dentro de secciones)
    for seccion in doc.sections:
        for contenedor in (seccion.header, seccion.footer):
            for p in contenedor.paragraphs:
                reemplaza_parrafo(p)
            for t in contenedor.tables:
                _recorre_tablas(t, reemplaza_parrafo, valores, filas_items)
    for t in doc.tables:
        _recorre_tablas(t, reemplaza_parrafo, valores, filas_items)

    # Insertar tabla nueva donde estaba el placeholder suelto
    if placeholder_tabla is not None and placeholder_tabla._parent is not None:
        _insertar_tabla_docx(doc, placeholder_tabla, filas_items)


def _recorre_tablas(tabla, reemplaza_parrafo, valores, filas_items):
    """Recorre celdas; si encuentra {{tabla_servicios} en una celda, usa esa tabla."""
    for fila in tabla.rows:
        parrafos = []
        for celda in fila.cells:
            for p in celda.paragraphs:
                parrafos.append(p)
        for p in parrafos:
            if re.search(r"\{\{\s*tabla_servicios\s*\}\}", p.text or "", re.IGNORECASE):
                _rellena_tabla_existente(tabla, filas_items)
                return
            reemplaza_parrafo(p)
    for fila in tabla.rows:
        for celda in fila.cells:
            if celda.tables:
                for t2 in celda.tables:
                    _recorre_tablas(t2, reemplaza_parrafo, valores, filas_items)


def _rellena_tabla_existente(tabla, filas_items):
    """Rellena la tabla donde estaba {{tabla_servicios}}: la fila de la celda
    que contenía el marcador se usa como FORMATO de fila de datos y se clona."""
    # localizar fila plantilla (la que contiene el marcador)
    fila_plantilla_idx = None
    for idx, fila in enumerate(tabla.rows):
        for celda in fila.cells:
            if re.search(r"\{\{\s*tabla_servicios\s*\}\}", celda.text or "", re.IGNORECASE):
                fila_plantilla_idx = idx
                break
        if fila_plantilla_idx is not None:
            break
    if fila_plantilla_idx is None:
        return False
    tabla_xml = tabla._tbl
    filas_xml = tabla_xml.findall(qn("w:tr"))
    fila_xml = filas_xml[fila_plantilla_idx]
    import copy
    claves = _columnas_fila(None)
    for valores_fila in filas_items:
        nueva = copy.deepcopy(fila_xml)
        tabla_xml.append(nueva)
        nueva_fila = tabla.rows[-1]
        for j, texto in enumerate([valores_fila[c] for c in claves]):
            celda = nueva_fila.cells[j] if j < len(nueva_fila.cells) else None
            if celda is None:
                continue
            _reescribe_celda(celda, texto)
    # borrar la fila plantilla original
    tabla._tbl.remove(tabla.rows[fila_plantilla_idx]._tr)
    return True


def _columnas_fila(v):
    return ["item", "descripcion", "cantidad", "unidad", "precio_unitario", "total"]


def _reescribe_celda(celda, texto: str):
    parrrafos = celda.paragraphs
    if not parrrafos:
        celda.text = texto
        return
    _reescribe_runs_simple(parrrafos[0], texto)
    for p in parrrafos[1:]:
        _reescribe_runs_simple(p, "")


def _reescribe_runs_simple(parrafo, nuevo_texto: str):
    """Deja el texto en el primer run conservando su formato; vacía los demás."""
    runs = parrafo.runs
    if not runs:
        # párrafo sin runs: crear uno heredando el estilo del párrafo
        run = parrafo.add_run(nuevo_texto)
        return
    runs[0].text = nuevo_texto
    for r in runs[1:]:
        r.text = ""


def _insertar_tabla_docx(doc, parrafo_marca, filas_items):
    """Inserta una tabla nueva justo donde estaba el párrafo del marcador."""
    from docx.oxml import OxmlElement
    # crear tabla con python-docx y moverla a la posición del párrafo
    n = len(filas_items)
    tabla = doc.add_table(rows=n, cols=6)
    try:
        tabla.style = "Table Grid"
    except KeyError:
        pass  # plantilla sin estilo Table Grid: se deja el estilo base
    for i, valores_fila in enumerate(filas_items):
        for j, clave in enumerate(_columnas_fila(valores_fila)):
            celda = tabla.rows[i].cells[j]
            _reescribe_celda(celda, valores_fila[clave])
    # encabezados en la primera fila
    for j, enc in enumerate(ENCABEZADOS_TABLA):
        _reescribe_celda(tabla.rows[0].cells[j], enc)
    # mover: insertar antes del párrafo del marcador, luego borrarlo
    parrafo_marca._p.addnext(tabla._tbl)
    parrafo_marca._p.getparent().remove(parrafo_marca._p)


def _render_docx(ruta_plantilla: str, valores: dict, filas_items: list, destino: str):
    doc = Document(ruta_plantilla)
    _reemplazar_docx(doc, valores, filas_items)
    doc.save(destino)


# ------------------------------------------------------------------
# Motor de variables: HTML
# ------------------------------------------------------------------

def _detectar_variables_html(contenido: str) -> List[str]:
    encontradas = set(m.group(1).lower() for m in RE_VARIABLE.finditer(contenido))
    return [v for v in VARIABLES_INICIOS if v in encontradas] + \
           [v for v in sorted(encontradas) if v not in VARIABLES_INICIOS]


def _escapa(v: str) -> str:
    return html_mod.escape(str(v))


def _tabla_html(filas_items: list) -> str:
    enc = "".join(f"<th>{_escapa(h)}</th>" for h in ENCABEZADOS_TABLA)
    claves = _columnas_fila(None)
    filas_html = []
    for v in filas_items:
        tds = "".join(f"<td>{_escapa(v[k])}</td>" for k in claves)
        filas_html.append(f"<tr>{tds}</tr>")
    return (f'<table class="tabla_servicios">'
            f"<thead><tr>{enc}</tr></thead><tbody>{''.join(filas_html)}</tbody></table>")


def _render_html(contenido: str, valores: dict, filas_items: list) -> str:
    salida = RE_VARIABLE.sub(
        lambda m: (_tabla_html(filas_items)
                   if m.group(1).lower() == "tabla_servicios"
                   else _escapa(valores.get(m.group(1).lower(), ""))),
        contenido,
    )
    # estilo base de la tabla solo si no trae ninguno para .tabla_servicios
    if "tabla_servicios" in salida and ".tabla_servicios th" not in salida:
        estilo = (
            "<style>.tabla_servicios{width:100%;border-collapse:collapse;font-size:10pt;}"
            ".tabla_servicios th,.tabla_servicios td{border:1px solid #444;padding:5px 7px;text-align:left;}"
            ".tabla_servicios th{background:#eef2f7;}</style>"
        )
        if "</head>" in salida.lower():
            salida = re.sub(r"</head>", estilo + "</head>", salida, flags=re.IGNORECASE, count=1)
        else:
            salida = estilo + salida
    return salida


# ------------------------------------------------------------------
# Endpoints del panel
# ------------------------------------------------------------------

def _fila_plantilla(db: Session, pid: int) -> Plantilla:
    p = db.execute(select(Plantilla).where(Plantilla.id == pid)).scalar_one_or_none()
    if not p:
        raise HTTPException(404, detail="Plantilla no encontrada")
    return p


def _plantilla_predeterminada(db: Session) -> Optional[Plantilla]:
    return db.execute(select(Plantilla).where(Plantilla.es_predeterminada == True,  # noqa: E712
                                              Plantilla.activa == True)).scalar_one_or_none()  # noqa: E712


def _plantilla_publica(p: Plantilla) -> dict:
    return {
        "id": p.id, "nombre": p.nombre, "tipo": p.tipo, "descripcion": p.descripcion,
        "version": p.version, "variables": json.loads(p.variables or "[]"),
        "es_predeterminada": p.es_predeterminada, "activa": p.activa,
        "archivo_nombre": p.archivo_nombre, "tamano": p.tamano,
        "creada_en": p.creado_en.isoformat() if p.creado_en else None,
        "actualizado_en": p.actualizado_en.isoformat() if p.actualizado_en else None,
    }


@router.get("/plantillas")
def listar_plantillas(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    filas = db.execute(select(Plantilla).order_by(Plantilla.id.desc())).scalars().all()
    return [_plantilla_publica(p) for p in filas]


@router.post("/plantillas", status_code=status.HTTP_201_CREATED)
async def subir_plantilla(
    nombre: str = Form(...),
    descripcion: str = Form(""),
    archivo: Optional[UploadFile] = File(None),
    contenido_html: Optional[str] = Form(None),
    current_user: User = Depends(require_dueno),
    db: Session = Depends(get_db),
):
    """Sube una plantilla DOCX (archivo) o registra una HTML (contenido_html)."""
    if archivo is None and not contenido_html:
        raise HTTPException(400, detail="Envía un archivo DOCX o el contenido HTML.")
    tipo = "docx" if archivo is not None else "html"
    if tipo == "docx" and not (archivo.filename or "").lower().endswith(".docx"):
        raise HTTPException(400, detail="La plantilla DOCX debe ser un archivo .docx")
    existe = db.execute(select(Plantilla).where(Plantilla.nombre == nombre)).scalar_one_or_none()
    if existe:
        raise HTTPException(400, detail="Ya existe una plantilla con ese nombre")

    p = Plantilla(nombre=nombre[:120], descripcion=(descripcion or "")[:500], tipo=tipo,
                  version=1, activa=True, creado_por_id=current_user.id)
    # validar primero: variables
    if tipo == "docx":
        contenido_bytes = await archivo.read()
        if not contenido_bytes or len(contenido_bytes) > 10 * 1024 * 1024:
            raise HTTPException(400, detail="Archivo vacío o mayor a 10 MB")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = os.path.join(tmp, _nombre_seguro(archivo.filename))
            with open(tmp_path, "wb") as f:
                f.write(contenido_bytes)
            try:
                vars_detect = _detectar_variables_docx(tmp_path)
            except Exception:
                raise HTTPException(400, detail="El archivo no es un DOCX válido.")
        p.archivo_nombre = _nombre_seguro(archivo.filename)
        p.tamano = len(contenido_bytes)
        p.variables = json.dumps(vars_detect)
    else:
        if len(contenido_html) > 400_000:
            raise HTTPException(400, detail="La plantilla HTML supera 400.000 caracteres")
        p.archivo_nombre = f"{_nombre_seguro(nombre)}.html"
        p.tamano = len(contenido_html.encode())
        p.variables = json.dumps(_detectar_variables_html(contenido_html))
    db.add(p)
    db.commit()
    db.refresh(p)

    # guardar archivo según la versión 1
    destino = _ruta_version(p.id, 1, p.archivo_nombre)
    if tipo == "docx":
        with open(destino, "wb") as f:
            f.write(contenido_bytes)
    else:
        with open(destino, "w", encoding="utf-8") as f:
            f.write(contenido_html)
    db.add(PlantillaVersion(plantilla_id=p.id, version=1, archivo_ruta=destino,
                            nombre=p.nombre, descripcion=p.descripcion,
                            creado_por_id=current_user.id))
    db.commit()
    registrar_auditoria(db, "plantilla_creada", usuario=current_user,
                        detalle=f"{p.nombre} ({tipo}, v1, variables: {len(json.loads(p.variables or '[]'))})")
    return _plantilla_publica(p)


@router.post("/plantillas/{pid}/version")
async def nueva_version(
    pid: int,
    archivo: Optional[UploadFile] = File(None),
    contenido_html: Optional[str] = Form(None),
    current_user: User = Depends(require_dueno),
    db: Session = Depends(get_db),
):
    p = _fila_plantilla(db, pid)
    nueva_version_num = p.version + 1
    if p.tipo == "docx":
        if archivo is None:
            raise HTTPException(400, detail="Esta plantilla es DOCX: envía el archivo .docx nuevo.")
        if not (archivo.filename or "").lower().endswith(".docx"):
            raise HTTPException(400, detail="El archivo debe ser .docx")
        contenido_bytes = await archivo.read()
        if not contenido_bytes or len(contenido_bytes) > 10 * 1024 * 1024:
            raise HTTPException(400, detail="Archivo vacío o mayor a 10 MB")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = os.path.join(tmp, _nombre_seguro(archivo.filename))
            with open(tmp_path, "wb") as f:
                f.write(contenido_bytes)
            try:
                variables = _detectar_variables_docx(tmp_path)
            except Exception:
                raise HTTPException(400, detail="El archivo no es un DOCX válido.")
        p.archivo_nombre = _nombre_seguro(archivo.filename)
        p.tamano = len(contenido_bytes)
        destino = _ruta_version(p.id, nueva_version_num, p.archivo_nombre)
        with open(destino, "wb") as f:
            f.write(contenido_bytes)
    else:
        if archivo is not None:
            raise HTTPException(400, detail="Esta plantilla es HTML: envía contenido_html (o crea una DOCX nueva).")
        if not contenido_html:
            raise HTTPException(400, detail="Envía el contenido HTML de la nueva versión.")
        variables = _detectar_variables_html(contenido_html)
        p.tamano = len(contenido_html.encode())
        destino = _ruta_version(p.id, nueva_version_num, p.archivo_nombre)
        with open(destino, "w", encoding="utf-8") as f:
            f.write(contenido_html)
    p.version = nueva_version_num
    p.variables = json.dumps(variables)
    db.add(PlantillaVersion(plantilla_id=p.id, version=nueva_version_num, archivo_ruta=destino,
                            nombre=p.nombre, descripcion=p.descripcion,
                            creado_por_id=current_user.id))
    db.commit()
    registrar_auditoria(db, "plantilla_version_nueva", usuario=current_user,
                        detalle=f"{p.nombre} -> v{nueva_version_num}")
    return _plantilla_publica(p)


class PlantillaEdit(BaseModel):
    nombre: Optional[str] = Field(None, max_length=120)
    descripcion: Optional[str] = Field(None, max_length=500)
    activa: Optional[bool] = None


@router.put("/plantillas/{pid}")
def editar_plantilla(pid: int, datos: PlantillaEdit,
                     current_user: User = Depends(require_dueno), db: Session = Depends(get_db)):
    p = _fila_plantilla(db, pid)
    cambios = []
    if datos.nombre is not None and datos.nombre != p.nombre:
        otro = db.execute(select(Plantilla).where(Plantilla.nombre == datos.nombre)).scalar_one_or_none()
        if otro:
            raise HTTPException(400, detail="Ya existe una plantilla con ese nombre")
        cambios.append(f"nombre={datos.nombre}")
        p.nombre = datos.nombre
    if datos.descripcion is not None:
        cambios.append("descripcion")
        p.descripcion = datos.descripcion[:500]
    if datos.activa is not None:
        if p.es_predeterminada and datos.activa is False:
            raise HTTPException(400, detail="No puedes desactivar la plantilla predeterminada; define otra predeterminada primero.")
        cambios.append(f"activa={datos.activa}")
        p.activa = datos.activa
    db.commit()
    registrar_auditoria(db, "plantilla_editada", usuario=current_user,
                        detalle=f"{p.nombre}: {', '.join(cambios) or 'sin cambios'}")
    return _plantilla_publica(p)


@router.post("/plantillas/{pid}/predeterminada")
def definir_predeterminada(pid: int, current_user: User = Depends(require_dueno),
                           db: Session = Depends(get_db)):
    p = _fila_plantilla(db, pid)
    if not p.activa:
        raise HTTPException(400, detail="La plantilla debe estar activa para ser predeterminada")
    for otra in db.execute(select(Plantilla).where(Plantilla.es_predeterminada == True)).scalars().all():  # noqa: E712
        otra.es_predeterminada = False
    p.es_predeterminada = True
    db.commit()
    registrar_auditoria(db, "plantilla_predeterminada", usuario=current_user, detalle=p.nombre)
    return _plantilla_publica(p)


@router.delete("/plantillas/{pid}")
def eliminar_plantilla(pid: int, current_user: User = Depends(require_dueno),
                       db: Session = Depends(get_db)):
    p = _fila_plantilla(db, pid)
    usada = db.execute(select(Documento).where(Documento.plantilla_id == pid)).scalar_one_or_none()
    if usada:
        p.activa = False
        db.commit()
        registrar_auditoria(db, "plantilla_desactivada_por_historial", usuario=current_user, detalle=p.nombre)
        raise HTTPException(409, detail="La plantilla tiene documentos generados: se desactivó para conservar el historial.")
    carpeta = _dir_plantilla(pid)
    db.delete(p)
    db.commit()
    shutil.rmtree(carpeta, ignore_errors=True)
    registrar_auditoria(db, "plantilla_eliminada", usuario=current_user)
    return {"ok": True}


@router.get("/plantillas/{pid}/archivo")
def descargar_original(pid: int, version: Optional[int] = None,
                       current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = _fila_plantilla(db, pid)
    v = version or p.version
    fija = db.execute(select(PlantillaVersion).where(PlantillaVersion.plantilla_id == pid,
                                                     PlantillaVersion.version == v)).scalar_one_or_none()
    ruta = fija.archivo_ruta if fija else _ruta_version(pid, v, p.archivo_nombre)
    if not os.path.exists(ruta):
        raise HTTPException(404, detail="El archivo de esa versión no existe")
    registrar_auditoria(db, "plantilla_descargada", usuario=current_user, detalle=f"{p.nombre} v{v}")
    tipo_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document" \
        if p.tipo == "docx" else "text/html; charset=utf-8"
    from fastapi.responses import FileResponse
    return FileResponse(ruta, filename=os.path.basename(ruta), media_type=tipo_mime)


@router.get("/plantillas/{pid}/historial")
def historial_plantilla(pid: int, current_user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    p = _fila_plantilla(db, pid)
    filas = db.execute(select(PlantillaVersion).where(PlantillaVersion.plantilla_id == pid)
                       .order_by(PlantillaVersion.version.desc())).scalars().all()
    return [{
        "version": v.version, "nombre": v.nombre, "descripcion": v.descripcion,
        "archivo": os.path.basename(v.archivo_ruta) if v.archivo_ruta else None,
        "creada_en": v.creado_en.isoformat() if v.creado_en else None,
        "es_actual": v.version == p.version,
    } for v in filas]


def _empresa_de_bd(db: Session):
    """Datos de empresa para las variables; si el dueño no los configuró aún,
    usa defaults vacíos sin romper la generación."""
    empresa = db.execute(select(Empresa).where(Empresa.id == 1)).scalar_one_or_none()
    if empresa is None:
        empresa = Empresa(id=1)
        db.add(empresa)
        db.commit()
    return empresa


@router.post("/plantillas/{pid}/previsualizar")
async def previsualizar(pid: int,
                        current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Genera un documento de PRUEBA con datos de ejemplo (no queda registrado)."""
    p = _fila_plantilla(db, pid)
    if not p.activa:
        raise HTTPException(400, detail="La plantilla está desactivada")
    empresa = _empresa_de_bd(db)
    datos = DatosDocumento(
        numero_cotizacion="PRUEBA-0001",
        nombre_cliente="Cliente de ejemplo S.A.S.",
        documento_cliente="N-900111222",
        telefono_cliente="+57 300 000 0000",
        correo_cliente="_cliente@ejemplo.com",
        direccion_cliente="Calle 1 #2-3",
        descripcion_proyecto="Red eléctrica y de datos para la planta principal.",
        items=[
            ItemEntrada(descripcion="Punto de datos (red)", cantidad=15, unidad="punto",
                        precio_unitario=65000),
            ItemEntrada(descripcion="Punto de energía regulada", cantidad=4, unidad="punto",
                        precio_unitario=78000),
        ],
        descuento_pct=5, iva_pct=19, tiempo_ejecucion="5 días hábiles",
        forma_pago="50% anticipo, 50% contra entrega",
        vigencia_cotizacion="15 días",
        observaciones="Los precios incluyen materiales y mano de obra.",
    )
    resultado = _generar_archivos(p, datos, empresa)
    doc = Documento(
        plantilla_id=p.id, plantilla_version=p.version, tipo="prueba",
        numero_cotizacion="PRUEBA-0001",
        datos_json=json.dumps(json.loads(datos.model_dump_json()), ensure_ascii=False),
        archivo_docx=resultado["ruta_docx"], archivo_html=resultado["ruta_html"],
        archivo_pdf=resultado["ruta_pdf"], pdf_ok=resultado["pdf_ok"],
        creado_por_id=current_user.id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    registrar_auditoria(db, "plantilla_previsualizada", usuario=current_user,
                        detalle=f"{p.nombre} v{p.version}")
    return {
        "documento_id": doc.id,
        "numero_cotizacion": "PRUEBA-0001",
        "nombre_archivo_docx": os.path.basename(resultado["ruta_docx"]) if resultado["ruta_docx"] else None,
        "nombre_archivo_pdf": os.path.basename(resultado["ruta_pdf"]) if resultado["ruta_pdf"] else None,
        "nombre_archivo_html": os.path.basename(resultado["ruta_html"]) if resultado["ruta_html"] else None,
        "pdf_ok": resultado["pdf_ok"], "mensaje": resultado["mensaje"],
        "prueba": True,
    }


# ---------------- Generación de documento real ----------------

class GenerarSalida(BaseModel):
    documento_id: int
    numero_cotizacion: str
    nombre_archivo_docx: Optional[str] = None
    nombre_archivo_pdf: Optional[str] = None
    nombre_archivo_html: Optional[str] = None
    pdf_ok: bool
    mensaje: str = ""


@router.post("/plantillas/{pid}/generar", response_model=GenerarSalida)
def generar_documento(pid: int, datos: DatosDocumento,
                      current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = _fila_plantilla(db, pid)
    if not p.activa:
        raise HTTPException(400, detail="La plantilla está desactivada")
    empresa = _empresa_de_bd(db)
    resultado = _generar_archivos(p, datos, empresa)
    doc = Documento(
        plantilla_id=p.id, plantilla_version=p.version, tipo="cotizacion",
        numero_cotizacion=datos.numero_cotizacion,
        datos_json=json.dumps(json.loads(datos.model_dump_json()), ensure_ascii=False),
        archivo_docx=resultado["ruta_docx"], archivo_html=resultado["ruta_html"],
        archivo_pdf=resultado["ruta_pdf"], pdf_ok=resultado["pdf_ok"],
        creado_por_id=current_user.id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    registrar_auditoria(db, "documento_generado", usuario=current_user,
                        detalle=f"{datos.numero_cotizacion} con {p.nombre} v{p.version}")
    return GenerarSalida(
        documento_id=doc.id, numero_cotizacion=datos.numero_cotizacion,
        nombre_archivo_docx=os.path.basename(resultado["ruta_docx"]) if resultado["ruta_docx"] else None,
        nombre_archivo_pdf=os.path.basename(resultado["ruta_pdf"]) if resultado["ruta_pdf"] else None,
        nombre_archivo_html=os.path.basename(resultado["ruta_html"]) if resultado["ruta_html"] else None,
        pdf_ok=resultado["pdf_ok"], mensaje=resultado["mensaje"],
    )


def _generar_archivos(p: Plantilla, datos: DatosDocumento, empresa) -> dict:
    valores = _valores(datos, empresa)
    filas = _items_ordenados(datos)
    marca = datetime.now().strftime("%Y%m%d%H%M%S")
    base = f"{_nombre_seguro(datos.numero_cotizacion)}_{p.version}_{marca}"
    os.makedirs(DIR_DOCUMENTOS, exist_ok=True)
    ruta_docx = ruta_html = ruta_pdf = None
    if p.tipo == "docx":
        ruta_org = None
        fija = db_select_version(p.id, p.version)
        ruta_org = fija.archivo_ruta if fija else None
        if not ruta_org or not os.path.exists(ruta_org):
            raise HTTPException(500, detail="Falta el archivo de la plantilla en el disco")
        ruta_docx = os.path.join(DIR_DOCUMENTOS, base + ".docx")
        _render_docx(ruta_org, valores, filas, ruta_docx)
        ruta_pdf, mensaje = _docx_a_pdf(ruta_docx)
    else:
        contenido = open(ruta_version_archivo(p.id, p.version), encoding="utf-8").read()
        lleno = _render_html(contenido, valores, filas)
        ruta_html = os.path.join(DIR_DOCUMENTOS, base + ".html")
        with open(ruta_html, "w", encoding="utf-8") as f:
            f.write(lleno)
        ruta_pdf, mensaje = _html_a_pdf(ruta_html)
    return {"ruta_docx": ruta_docx, "ruta_html": ruta_html, "ruta_pdf": ruta_pdf,
            "pdf_ok": ruta_pdf is not None, "mensaje": mensaje}


def db_select_version(pid, version):
    from app.modelos import PlantillaVersion
    from sqlalchemy import select as _sel
    ses = None
    try:
        from app.db import SessionLocal
        ses = SessionLocal()
        return ses.execute(_sel(PlantillaVersion).where(
            PlantillaVersion.plantilla_id == pid,
            PlantillaVersion.version == version)).scalar_one_or_none()
    finally:
        if ses:
            ses.close()


def ruta_version_archivo(pid, version) -> str:
    fija = db_select_version(pid, version)
    if not fija or not os.path.exists(fija.archivo_ruta):
        raise HTTPException(500, detail="Falta el archivo de la plantilla en el disco")
    return fija.archivo_ruta


@router.get("/documentos")
def listar_documentos(limit: int = 50, current_user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    filas = db.execute(select(Documento).order_by(Documento.id.desc())
                       .limit(max(1, min(limit, 200)))).scalars().all()
    plantillas = {p.id: p for p in db.execute(select(Plantilla)).scalars().all()}
    return [{
        "id": d.id, "tipo": d.tipo, "numero_cotizacion": d.numero_cotizacion,
        "plantilla": plantillas[d.plantilla_id].nombre if d.plantilla_id in plantillas else "?",
        "plantilla_version": d.plantilla_version, "pdf_ok": d.pdf_ok,
        "creado_en": d.creado_en.isoformat() if d.creado_en else None,
    } for d in filas]


@router.get("/documentos/{did}/descarga")
def descargar_documento(did: int, formato: str = "docx",
                        current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    d = db.execute(select(Documento).where(Documento.id == did)).scalar_one_or_none()
    if not d:
        raise HTTPException(404, detail="Documento no encontrado")
    rutas = {"pdf": d.archivo_pdf, "docx": d.archivo_docx, "html": d.archivo_html}
    ruta = rutas.get(formato)
    if not ruta or not os.path.exists(ruta):
        raise HTTPException(404, detail=f"No hay archivo {formato} para este documento")
    from fastapi.responses import FileResponse
    mimes = {"pdf": "application/pdf", "docx":
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             "html": "text/html; charset=utf-8"}
    registrar_auditoria(db, "documento_descargado", usuario=current_user,
                        detalle=f"{d.numero_cotizacion} ({formato})")
    return FileResponse(ruta, filename=os.path.basename(ruta), media_type=mimes[formato])
