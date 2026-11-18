import React, { useState, useEffect } from 'react'

async function apiFetch(path, { method = 'GET', body = null, token = null, form = null } = {}) {
  const headers = {}
  if (token) headers.Authorization = `Bearer ${token}`
  let payload = body
  if (form) {
    headers['Content-Type'] = 'application/x-www-form-urlencoded'
    payload = new URLSearchParams(form).toString()
  } else if (body !== null) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  const res = await fetch(`/api${path}`, { method, headers, body: payload })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    const detail = data?.detail || `Error ${res.status}`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return res.json().catch(() => ({}))
}

export function descargarAutenticado(url, token, nombre) {
  fetch(url, { headers: { Authorization: `Bearer ${token}` } })
    .then(r => {
      if (!r.ok) throw new Error(`Error ${r.status}`)
      return r.blob()
    })
    .then(blob => {
      const u = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = u
      a.download = nombre || 'descarga'
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(u)
    })
    .catch(err => window.alert(err.message))
}

export function VistaPlantillas({ auth }) {
  const esDueno = auth.user.rol === 'dueno'
  const [plantillas, setPlantillas] = useState(null)
  const [documentos, setDocumentos] = useState([])
  const [msg, setMsg] = useState(null)
  const [trabajo, setTrabajo] = useState(false)
  const [upload, setUpload] = useState({ nombre: '', descripcion: '', html: '' })
  const [archivo, setArchivo] = useState(null)
  const [versiones, setVersiones] = useState({})
  const [gen, setGen] = useState({
    plantilla_id: '', numero_cotizacion: '', nombre_cliente: '', documento_cliente: '',
    telefono_cliente: '', correo_cliente: '', direccion_cliente: '', descripcion_proyecto: '',
    descuento_pct: 0, iva_pct: 0, tiempo_ejecucion: '', forma_pago: '',
    vigencia_cotizacion: '', observaciones: '',
  })
  const [items, setItems] = useState([
    { descripcion: '', cantidad: 1, unidad: 'und', precio_unitario: 0 },
  ])
  const [resultado, setResultado] = useState(null)

  async function cargarTodo() {
    try {
      setPlantillas(await apiFetch('/plantillas', { token: auth.token }))
      setDocumentos(await apiFetch('/documentos?limit=10', { token: auth.token }))
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }
  useEffect(() => { cargarTodo() }, [])

  async function cambiarActiva(p) {
    setMsg(null)
    setTrabajo(true)
    try {
      await apiFetch(`/plantillas/${p.id}`, { method: 'PUT', body: { activa: !p.activa }, token: auth.token })
      await cargarTodo()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    } finally {
      setTrabajo(false)
    }
  }

  async function subir(e) {
    e.preventDefault()
    setMsg(null)
    setTrabajo(true)
    try {
      const fd = new FormData()
      fd.append('nombre', upload.nombre)
      fd.append('descripcion', upload.descripcion)
      if (archivo) {
        fd.append('archivo', archivo)
      } else if (upload.html.trim()) {
        fd.append('contenido_html', upload.html)
      } else {
        throw new Error('Elige un archivo DOCX o pega el HTML.')
      }
      const r = await fetch('/api/plantillas', {
        method: 'POST',
        headers: { Authorization: `Bearer ${auth.token}` },
        body: fd,
      })
      if (!r.ok) {
        const data = await r.json().catch(() => ({}))
        throw new Error(data?.detail || 'No se pudo subir la plantilla.')
      }
      setUpload({ nombre: '', descripcion: '', html: '' })
      setArchivo(null)
      setMsg({ tipo: 'ok', texto: 'Plantilla registrada y variables detectadas.' })
      await cargarTodo()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    } finally {
      setTrabajo(false)
    }
  }

  async function accion(path, cuerpo = null) {
    setMsg(null)
    setTrabajo(true)
    try {
      await apiFetch(path, { method: 'POST', body: cuerpo, token: auth.token })
      await cargarTodo()
      setMsg({ tipo: 'ok', texto: 'Listo.' })
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    } finally {
      setTrabajo(false)
    }
  }

  async function eliminar(p) {
    if (!window.confirm(`¿Eliminar la plantilla "${p.nombre}"?`)) return
    setMsg(null)
    try {
      await apiFetch(`/plantillas/${p.id}`, { method: 'DELETE', token: auth.token })
      await cargarTodo()
      setMsg({ tipo: 'ok', texto: 'Plantilla eliminada.' })
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }

  async function nuevaVersion(p) {
    const entrada = document.createElement('input')
    entrada.type = 'file'
    entrada.accept = p.tipo === 'docx' ? '.docx' : '.html,.htm,.txt'
    entrada.onchange = async () => {
      const f = entrada.files[0]
      if (!f) return
      setMsg(null)
      setTrabajo(true)
      try {
        const fd = new FormData()
        if (p.tipo === 'docx') {
          fd.append('archivo', f)
        } else {
          fd.append('contenido_html', await f.text())
        }
        const r = await fetch(`/api/plantillas/${p.id}/version`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${auth.token}` },
          body: fd,
        })
        if (!r.ok) {
          const data = await r.json().catch(() => ({}))
          throw new Error(data?.detail || 'No se pudo subir la nueva versión.')
        }
        await cargarTodo()
        setMsg({ tipo: 'ok', texto: `Versión ${p.version + 1} registrada; los históricos no cambian.` })
      } catch (err) {
        setMsg({ tipo: 'error', texto: err.message })
      } finally {
        setTrabajo(false)
      }
    }
    entrada.click()
  }

  async function generar(e) {
    e.preventDefault()
    setMsg(null)
    setTrabajo(true)
    setResultado(null)
    try {
      const cuerpo = { ...gen, items: items.filter(i => i.descripcion.trim()) }
      const r = await apiFetch(`/plantillas/${gen.plantilla_id}/generar`, {
        method: 'POST', body: cuerpo, token: auth.token,
      })
      setResultado(r)
      setMsg({ tipo: 'ok', texto: 'Documento generado.' })
      await cargarTodo()
    } catch (err) {
      setMsg({tipo: 'error', texto: err.message})
    } finally {
      setTrabajo(false)
    }
  }

  async function previsualizar(p) {
    setMsg(null)
    setTrabajo(true)
    try {
      const r = await apiFetch(`/plantillas/${p.id}/previsualizar`, {
        method: 'POST', body: null, token: auth.token,
      })
      setResultado(r)
      setMsg({ tipo: 'ok', texto: 'Documento de prueba generado (no queda registrado).' })
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    } finally {
      setTrabajo(false)
    }
  }

  return (
    <div>
      <h3 className="vista-titulo">Plantillas de Cotización</h3>
      {msg && <div className={`alert ${msg.tipo === 'ok' ? 'alert-success' : 'alert-error'}`}>{msg.texto}</div>}

      <div className="card">
        <h4>Generar documento</h4>
        {plantillas && plantillas.length === 0 && <p className="muted">Primero sube una plantilla con el dueño.</p>}
        <form onSubmit={generar}>
          <div className="form-grid">
            <div className="form-group">
              <label>Plantilla</label>
              <select value={gen.plantilla_id}
                      onChange={e => setGen({ ...gen, plantilla_id: e.target.value })} required>
                <option value="">Elegir…</option>
                {(plantillas || []).filter(p => p.activa).map(p => (
                  <option key={p.id} value={p.id}>
                    {p.nombre} (v{p.version}){p.es_predeterminada ? ' ★' : ''}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label>Número de cotización</label>
              <input value={gen.numero_cotizacion}
                     onChange={e => setGen({ ...gen, numero_cotizacion: e.target.value })} required />
            </div>
            <div className="form-group">
              <label>Cliente</label>
              <input value={gen.nombre_cliente}
                     onChange={e => setGen({ ...gen, nombre_cliente: e.target.value })} required />
            </div>
            <div className="form-group">
              <label>Documento/NIT del cliente</label>
              <input value={gen.documento_cliente}
                     onChange={e => setGen({ ...gen, documento_cliente: e.target.value })} />
            </div>
          </div>
          <div className="form-grid">
            <div className="form-group">
              <label>Correo del cliente</label>
              <input value={gen.correo_cliente}
                     onChange={e => setGen({ ...gen, correo_cliente: e.target.value })} />
            </div>
            <div className="form-group">
              <label>Teléfono del cliente</label>
              <input value={gen.telefono_cliente}
                     onChange={e => setGen({ ...gen, telefono_cliente: e.target.value })} />
            </div>
            <div className="form-group">
              <label>Dirección del cliente</label>
              <input value={gen.direccion_cliente}
                     onChange={e => setGen({ ...gen, direccion_cliente: e.target.value })} />
            </div>
          </div>
          <div className="form-group">
            <label>Descripción del proyecto</label>
            <textarea value={gen.descripcion_proyecto} rows={2}
                      onChange={e => setGen({ ...gen, descripcion_proyecto: e.target.value })} />
          </div>
          <h4>Servicios (ítems)</h4>
          {items.map((it, idx) => (
            <div className="fila-form items-fila" key={idx}>
              <div className="form-group crece-3">
                <label>Descripción</label>
                <input value={it.descripcion}
                       onChange={e => setItems(items.map((x, i) => i === idx ? { ...x, descripcion: e.target.value } : x))} />
              </div>
              <div className="form-group crece-1">
                <label>Cant.</label>
                <input type="number" step="0.5" min="0" value={it.cantidad}
                       onChange={e => setItems(items.map((x, i) => i === idx ? { ...x, cantidad: e.target.value } : x))} />
              </div>
              <div className="form-group crece-1">
                <label>Unidad</label>
                <input value={it.unidad}
                       onChange={e => setItems(items.map((x, i) => i === idx ? { ...x, unidad: e.target.value } : x))} />
              </div>
              <div className="form-group crece-2">
                <label>Precio unitario</label>
                <input type="number" step="any" min="0" value={it.precio_unitario}
                       onChange={e => setItems(items.map((x, i) => i === idx ? { ...x, precio_unitario: e.target.value } : x))} />
              </div>
              <div className="form-group crece-2">
                <label>Total</label>
                <em className="total-item">{(Number(it.cantidad || 0) * Number(it.precio_unitario || 0)).toLocaleString('es-CO', { style: 'currency', currency: 'COP', maximumFractionDigits: 0 })}</em>
              </div>
              <button type="button" className="btn btn-mini btn-peligro" onClick={() => setItems(items.filter((_, i) => i !== idx))} disabled={items.length === 1}>Quitar</button>
            </div>
          ))}
          <button type="button" className="btn btn-mini" onClick={() => setItems([...items, { descripcion: '', cantidad: 1, unidad: 'und', precio_unitario: 0 }])}>
            + Añadir servicio
          </button>
          <div className="form-grid" style={{ marginTop: '0.9rem' }}>
            <div className="form-group">
              <label>Descuento (%)</label>
              <input type="number" step="any" min="0" max="100" value={gen.descuento_pct}
                     onChange={e => setGen({ ...gen, descuento_pct: e.target.value })} />
            </div>
            <div className="form-group">
              <label>IVA (%)</label>
              <input type="number" step="any" min="0" max="100" value={gen.iva_pct}
                     onChange={e => setGen({ ...gen, iva_pct: e.target.value })} />
            </div>
            <div className="form-group">
              <label>Tiempo de ejecución</label>
              <input value={gen.tiempo_ejecucion}
                     onChange={e => setGen({ ...gen, tiempo_ejecucion: e.target.value })} />
            </div>
            <div className="form-group">
              <label>Forma de pago</label>
              <input value={gen.forma_pago}
                     onChange={e => setGen({ ...gen, forma_pago: e.target.value })} />
            </div>
            <div className="form-group">
              <label>Vigencia de la cotización</label>
              <input value={gen.vigencia_cotizacion}
                     onChange={e => setGen({ ...gen, vigencia_cotizacion: e.target.value })} />
            </div>
          </div>
          <div className="form-group">
            <label>Observaciones</label>
            <textarea value={gen.observaciones} rows={2}
                      onChange={e => setGen({ ...gen, observaciones: e.target.value })} />
          </div>
          <button type="submit" className="btn btn-primary" disabled={trabajo}>Generar</button>
        </form>
        {resultado && <DescargasDocumento r={resultado} token={auth.token} />}
      </div>

      <div className="card">
        <h4>Plantillas registradas</h4>
        {!plantillas ? <div className="spinner" /> : plantillas.length === 0 ? (
          <p className="muted">Sin plantillas aún.</p>
        ) : (
          <table className="table">
            <thead>
              <tr><th>Nombre</th><th>Tipo</th><th>Versión</th><th>Estado</th><th>Variables</th><th>Acciones</th></tr>
            </thead>
            <tbody>
              {plantillas.map(p => (
                <tr key={p.id} className={p.activa ? '' : 'fila-inactiva'}>
                  <td>
                    <strong>{p.nombre}</strong>
                    {p.es_predeterminada && <span className="badge badge-azul">predeterminada</span>}
                    {p.descripcion ? <div className="muted" style={{ fontSize: '0.8rem' }}>{p.descripcion}</div> : null}
                  </td>
                  <td>{p.tipo.toUpperCase()}</td>
                  <td>v{p.version}</td>
                  <td>{p.activa ? 'Activa' : 'Desactivada'}</td>
                  <td>{p.variables.length}</td>
                  <td className="acciones">
                    <button type="button" className="btn btn-mini" onClick={() => previsualizar(p)}>Previsualizar</button>
                    <button type="button" className="btn btn-mini"
                            onClick={() => descargarAutenticado(`/api/plantillas/${p.id}/archivo`, auth.token, p.archivo_nombre)}>Descargar</button>
                    {esDueno && (
                      <>
                        <button type="button" className="btn btn-mini" onClick={() => nuevaVersion(p)}>Nueva versión</button>
                        {!p.es_predeterminada && (
                          <button type="button" className="btn btn-mini" onClick={() => accion(`/plantillas/${p.id}/predeterminada`)}>Predeterminar</button>
                        )}
                        <button type="button" className="btn btn-mini" onClick={() => cambiarActiva(p)}>{p.activa ? 'Desactivar' : 'Activar'}</button>
                        <button type="button" className="btn btn-mini btn-peligro" onClick={() => eliminar(p)}>Eliminar</button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {esDueno && (
        <div className="card">
          <h4>Subir nueva plantilla (solo dueño)</h4>
          <form onSubmit={subir}>
            <div className="form-grid">
              <div className="form-group">
                <label>Nombre</label>
                <input value={upload.nombre} onChange={e => setUpload({ ...upload, nombre: e.target.value })} required maxLength={120} />
              </div>
              <div className="form-group">
                <label>Descripción</label>
                <input value={upload.descripcion} onChange={e => setUpload({ ...upload, descripcion: e.target.value })} maxLength={500} />
              </div>
            </div>
            <div className="form-group">
              <label>Archivo DOCX (formato principal)</label>
              <input type="file" accept=".docx" onChange={e => setArchivo(e.target.files[0] || null)} />
            </div>
            <div className="form-group">
              <label>O bien pega la plantilla HTML</label>
              <textarea value={upload.html} rows={5} placeholder="&lt;html&gt;…{{total}}…&lt;/html&gt;"
                        onChange={e => setUpload({ ...upload, html: e.target.value })} />
            </div>
            <button type="submit" className="btn btn-primary" disabled={trabajo}>
              {trabajo ? 'Subiendo…' : 'Subir plantilla'}
            </button>
          </form>
        </div>
      )}

      <div className="card">
        <h4>Documentos generados</h4>
        {documentos.length === 0 ? <p className="muted">Sin documentos todavía.</p> : (
          <table className="table">
            <thead><tr><th>Número</th><th>Plantilla</th><th>Tipo</th><th>Fecha</th><th>Descargas</th></tr></thead>
            <tbody>
              {documentos.map(d => (
                <tr key={d.id}>
                  <td>{d.numero_cotizacion}</td>
                  <td>{d.plantilla} (v{d.plantilla_version})</td>
                  <td>{d.tipo}</td>
                  <td>{d.creado_en ? d.creado_en.replace('T', ' ').slice(0, 19) : '—'}</td>
                  <td className="acciones">
                    <button type="button" className="btn btn-mini"
                            onClick={() => descargarAutenticado(`/api/documentos/${d.id}/descarga?formato=docx`, auth.token, `${d.numero_cotizacion}.docx`)}>DOCX</button>
                    {d.pdf_ok && (
                      <button type="button" className="btn btn-mini"
                              onClick={() => descargarAutenticado(`/api/documentos/${d.id}/descarga?formato=pdf`, auth.token, `${d.numero_cotizacion}.pdf`)}>PDF</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}