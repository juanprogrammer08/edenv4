import React, { useState, useEffect } from 'react'

async function apiFetch(path, { method = 'GET', body = null, token = null } = {}) {
  const headers = {}
  if (token) headers.Authorization = `Bearer ${token}`
  let payload = null
  if (body !== null) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  const res = await fetch(`/api${path}`, { method, headers, body: payload })
  const text = await res.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  if (!res.ok) {
    const detail = data?.detail || `Error ${res.status}`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return data
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

export const fmtCOP = n => new Intl.NumberFormat('es-CO', { style: 'currency', currency: 'COP', maximumFractionDigits: 0 }).format(Number(n) || 0)

export const ESTADO_ETIQUETA = {
  borrador: 'Borrador', pendiente: 'Pendiente', enviada: 'Enviada',
  aprobada: 'Aprobada', rechazada: 'Rechazada', vencida: 'Vencida',
  convertida: 'Convertida en proyecto',
}

export function VistaServicios({ auth }) {
  const esDueno = auth.user.rol === 'dueno'
  const [servicios, setServicios] = useState(null)
  const [msg, setMsg] = useState(null)
  const [nuevo, setNuevo] = useState({
    codigo: '', nombre: '', descripcion: '', categoria: 'general', unidad: 'und',
    precio_venta: 0, costo_materiales: 0, costo_mano_obra: 0, tiempo_estimado_horas: 0,
  })
  const [trabajo, setTrabajo] = useState(false)

  async function cargar() {
    try { setServicios(await apiFetch('/servicios', { token: auth.token })) }
    catch (err) { setMsg({ tipo: 'error', texto: err.message }) }
  }
  useEffect(() => { cargar() }, [])

  async function guardar(e) {
    e.preventDefault()
    setMsg(null)
    setTrabajo(true)
    try {
      await apiFetch('/servicios', { method: 'POST', body: nuevo, token: auth.token })
      setNuevo({ codigo: '', nombre: '', descripcion: '', categoria: 'general', unidad: 'und',
                 precio_venta: 0, costo_materiales: 0, costo_mano_obra: 0, tiempo_estimado_horas: 0 })
      setMsg({ tipo: 'ok', texto: 'Servicio agregado al catálogo.' })
      await cargar()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    } finally {
      setTrabajo(false)
    }
  }

  async function editar(s) {
    const nombre = prompt('Nombre del servicio:', s.nombre)
    if (nombre === null) return
    const precio = prompt('Precio de venta:', s.precio_venta)
    if (precio === null) return
    try {
      await apiFetch(`/servicios/${s.id}`, { method: 'PUT', body: {
        ...s, nombre: nombre || s.nombre, precio_venta: Number(precio),
      }, token: auth.token })
      await cargar()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }

  async function toggle(s) {
    try {
      await apiFetch(`/servicios/${s.id}`, { method: 'PUT', body: { ...s, activo: !s.activo }, token: auth.token })
      await cargar()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }

  async function eliminar(s) {
    if (!window.confirm(`¿Eliminar "${s.nombre}"? Si se usó en cotizaciones, se desactivará en su lugar.`)) return
    try {
      await apiFetch(`/servicios/${s.id}`, { method: 'DELETE', token: auth.token })
      await cargar()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }

  return (
    <div>
      <h3 className="vista-titulo">Catálogo de Servicios</h3>
      {msg && <div className={`alert ${msg.tipo === 'ok' ? 'alert-success' : 'alert-error'}`}>{msg.texto}</div>}
      {esDueno && (
        <form onSubmit={guardar} className="card">
          <h4>Nuevo servicio</h4>
          <div className="form-grid">
            <div className="form-group"><label>Código</label>
              <input value={nuevo.codigo} onChange={e => setNuevo({ ...nuevo, codigo: e.target.value })} required maxLength={20} /></div>
            <div className="form-group"><label>Nombre</label>
              <input value={nuevo.nombre} onChange={e => setNuevo({ ...nuevo, nombre: e.target.value })} required maxLength={150} /></div>
            <div className="form-group"><label>Categoría</label>
              <input value={nuevo.categoria} onChange={e => setNuevo({ ...nuevo, categoria: e.target.value })} maxLength={60} /></div>
            <div className="form-group"><label>Unidad</label>
              <input value={nuevo.unidad} onChange={e => setNuevo({ ...nuevo, unidad: e.target.value })} maxLength={30} /></div>
            <div className="form-group"><label>Precio de venta</label>
              <input type="number" step="any" min="0" value={nuevo.precio_venta}
                     onChange={e => setNuevo({ ...nuevo, precio_venta: e.target.value })} required /></div>
            <div className="form-group"><label>Costo materiales</label>
              <input type="number" step="any" min="0" value={nuevo.costo_materiales}
                     onChange={e => setNuevo({ ...nuevo, costo_materiales: e.target.value })} /></div>
            <div className="form-group"><label>Costo mano de obra</label>
              <input type="number" step="any" min="0" value={nuevo.costo_mano_obra}
                     onChange={e => setNuevo({ ...nuevo, costo_mano_obra: e.target.value })} /></div>
            <div className="form-group"><label>Tiempo estimado (h)</label>
              <input type="number" step="any" min="0" value={nuevo.tiempo_estimado_horas}
                     onChange={e => setNuevo({ ...nuevo, tiempo_estimado_horas: e.target.value })} /></div>
          </div>
          <div className="form-group"><label>Descripción</label>
            <textarea value={nuevo.descripcion} rows={2}
                      onChange={e => setNuevo({ ...nuevo, descripcion: e.target.value })} /></div>
          <button type="submit" className="btn btn-primary" disabled={trabajo}>Agregar al catálogo</button>
        </form>
      )}
      <div className="card">
        {!servicios ? <div className="spinner" /> : servicios.length === 0 ? (
          <p className="muted">Catálogo vacío.</p>
        ) : (
          <table className="table">
            <thead><tr><th>Código</th><th>Nombre</th><th>Categoría</th><th>Unidad</th><th>Precio</th><th>Costo</th><th>Margen</th><th>Estado</th><th></th></tr></thead>
            <tbody>
              {servicios.map(s => (
                <tr key={s.id} className={s.activo ? '' : 'fila-inactiva'}>
                  <td>{s.codigo}</td>
                  <td>{s.nombre}</td>
                  <td>{s.categoria}</td>
                  <td>{s.unidad}</td>
                  <td>{fmtCOP(s.precio_venta)}</td>
                  <td>{fmtCOP(s.costo_total)}</td>
                  <td>{s.margen_pct}%</td>
                  <td>{s.activo ? 'Activo' : 'Inactivo'}</td>
                  <td className="acciones">
                    {esDueno && (
                      <>
                        <button type="button" className="btn btn-mini" onClick={() => editar(s)}>Editar</button>
                        <button type="button" className="btn btn-mini" onClick={() => toggle(s)}>{s.activo ? 'Desactivar' : 'Activar'}</button>
                        <button type="button" className="btn btn-mini btn-peligro" onClick={() => eliminar(s)}>Eliminar</button>
                      </>
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

export function VistaClientes({ auth }) {
  const [clientes, setClientes] = useState(null)
  const [msg, setMsg] = useState(null)
  const [abierto, setAbierto] = useState(null)
  const [historial, setHistorial] = useState(null)
  const [nuevo, setNuevo] = useState({
    nombre: '', nit: '', contacto: '', telefono: '', correo: '', direccion: '', ciudad: '', descripcion: '',
  })
  const [trabajo, setTrabajo] = useState(false)

  async function cargar() {
    try { setClientes(await apiFetch('/clientes', { token: auth.token })) }
    catch (err) { setMsg({ tipo: 'error', texto: err.message }) }
  }
  useEffect(() => { cargar() }, [])

  async function guardar(e) {
    e.preventDefault()
    setMsg(null)
    setTrabajo(true)
    try {
      await apiFetch('/clientes', { method: 'POST', body: nuevo, token: auth.token })
      setNuevo({ nombre: '', nit: '', contacto: '', telefono: '', correo: '', direccion: '', ciudad: '', descripcion: '' })
      setMsg({ tipo: 'ok', texto: 'Cliente registrado.' })
      await cargar()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    } finally {
      setTrabajo(false)
    }
  }

  async function editar(c) {
    const nombre = prompt('Nombre del cliente:', c.nombre)
    if (nombre === null) return
    const telefono = prompt('Teléfono:', c.telefono)
    if (telefono === null) return
    try {
      await apiFetch(`/clientes/${c.id}`, { method: 'PUT', body: { ...c, nombre, telefono }, token: auth.token })
      await cargar()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }

  async function eliminar(c) {
    if (!window.confirm(`¿Eliminar "${c.nombre}"? Si tiene cotizaciones, se desactivará en su lugar.`)) return
    try {
      await apiFetch(`/clientes/${c.id}`, { method: 'DELETE', token: auth.token })
      await cargar()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }

  async function verHistorial(c) {
    if (abierto === c.id) { setAbierto(null); return }
    setAbierto(c.id)
    setHistorial(null)
    try {
      setHistorial(await apiFetch(`/clientes/${c.id}/cotizaciones`, { token: auth.token }))
    } catch (err) {
      setHistorial([])
      setMsg({ tipo: 'error', texto: err.message })
    }
  }

  return (
    <div>
      <h3 className="vista-titulo">Clientes</h3>
      {msg && <div className={`alert ${msg.tipo === 'ok' ? 'alert-success' : 'alert-error'}`}>{msg.texto}</div>}

      <form onSubmit={guardar} className="card">
        <h4>Nuevo cliente</h4>
        <div className="form-grid">
          <div className="form-group"><label>Nombre o razón social</label>
            <input value={nuevo.nombre} onChange={e => setNuevo({ ...nuevo, nombre: e.target.value })} required /></div>
          <div className="form-group"><label>NIT / documento</label>
            <input value={nuevo.nit} onChange={e => setNuevo({ ...nuevo, nit: e.target.value })} /></div>
          <div className="form-group"><label>Contacto</label>
            <input value={nuevo.contacto} onChange={e => setNuevo({ ...nuevo, contacto: e.target.value })} /></div>
          <div className="form-group"><label>Teléfono</label>
            <input value={nuevo.telefono} onChange={e => setNuevo({ ...nuevo, telefono: e.target.value })} /></div>
          <div className="form-group"><label>Correo</label>
            <input type="email" value={nuevo.correo} onChange={e => setNuevo({ ...nuevo, correo: e.target.value })} /></div>
          <div className="form-group"><label>Ciudad</label>
            <input value={nuevo.ciudad} onChange={e => setNuevo({ ...nuevo, ciudad: e.target.value })} /></div>
        </div>
        <div className="form-group"><label>Dirección</label>
          <input value={nuevo.direccion} onChange={e => setNuevo({ ...nuevo, direccion: e.target.value })} /></div>
        <div className="form-group"><label>Descripción</label>
          <textarea value={nuevo.descripcion} rows={2}
                    onChange={e => setNuevo({ ...nuevo, descripcion: e.target.value })} /></div>
        <button type="submit" className="btn btn-primary" disabled={trabajo}>Registrar cliente</button>
      </form>

      <div className="card">
        {!clientes ? <div className="spinner" /> : clientes.length === 0 ? (
          <p className="muted">Sin clientes. Los clientes son registros comerciales, no usuarios.</p>
        ) : (
          <table className="table">
            <thead><tr><th>Nombre</th><th>NIT</th><th>Contacto</th><th>Teléfono</th><th>Ciudad</th><th>Estado</th><th></th></tr></thead>
            <tbody>
              {clientes.map(c => (
                <React.Fragment key={c.id}>
                  <tr className={c.activo ? '' : 'fila-inactiva'}>
                    <td>
                      <strong>{c.nombre}</strong>
                      <button type="button" className="btn btn-mini" style={{ marginLeft: '0.5rem' }}
                              onClick={() => verHistorial(c)}>{abierto === c.id ? 'Ocultar' : 'Historial'}</button>
                    </td>
                    <td>{c.nit || '—'}</td>
                    <td>{c.contacto || '—'}</td>
                    <td>{c.telefono || '—'}</td>
                    <td>{c.ciudad || '—'}</td>
                    <td>{c.activo ? 'Activo' : 'Inactivo'}</td>
                    <td className="acciones">
                      <button type="button" className="btn btn-mini" onClick={() => editar(c)}>Editar</button>
                      <button type="button" className="btn btn-mini btn-peligro" onClick={() => eliminar(c)}>Eliminar</button>
                    </td>
                  </tr>
                  {abierto === c.id && (
                    <tr>
                      <td colSpan={7}>
                        {historial === null ? <div className="spinner" /> : (
                          <div className="history-box">
                            {historial.length === 0 ? <em className="muted">Sin cotizaciones todavía.</em> : (
                              <table className="table">
                                <thead><tr><th>Número</th><th>Estado</th><th>Total</th><th>Fecha</th></tr></thead>
                                <tbody>
                                  {historial.map(h => (
                                    <tr key={h.id}>
                                      <td>{h.numero}</td>
                                      <td>{ESTADO_ETIQUETA[h.estado] || h.estado}</td>
                                      <td>{fmtCOP(h.total)}</td>
                                      <td>{h.creado_en ? h.creado_en.slice(0, 10) : '—'}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            )}
                          </div>
                        )}
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

export function VistaCotizaciones({ auth }) {
  const esDueno = auth.user.rol === 'dueno'
  const [cotizaciones, setCotizaciones] = useState(null)
  const [clientes, setClientes] = useState([])
  const [servicios, setServicios] = useState([])
  const [config, setConfig] = useState({ descuento_max_pct: 20, margen_minimo_pct: 15 })
  const [msg, setMsg] = useState(null)
  const [filtro, setFiltro] = useState('')
  const [trabajo, setTrabajo] = useState(false)
  const [nueva, setNueva] = useState(false)
  const [form, setForm] = useState({
    cliente_id: '', cliente: '', descripcion: '', descuento_pct: 0, iva_pct: 19,
    tiempo_ejecucion: '', forma_pago: '50% anticipo, 50% contra entrega',
    vigencia_cotizacion: '15 días', observaciones: '',
  })
  const [items, setItems] = useState([{ descripcion: '', cantidad: 1, unidad: 'und', precio_unitario: 0, costo_unitario: 0, servicio_id: null }])
  const [detalle, setDetalle] = useState(null)

  async function cargar() {
    try {
      setCotizaciones(await apiFetch('/cotizaciones' + (filtro ? `?estado=${filtro}` : ''), { token: auth.token }))
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }
  useEffect(() => { cargar() }, [filtro])
  useEffect(() => {
    Promise.all([
      apiFetch('/clientes', { token: auth.token }),
      apiFetch('/servicios?only_active=true', { token: auth.token }),
      apiFetch('/config-comercial', { token: auth.token }),
    ]).then(([cl, se, cfg]) => { setClientes(cl); setServicios(se); setConfig(cfg) })
      .catch(() => {})
  }, [])

  const subtotal = items.reduce((s, i) => s + (Number(i.cantidad) || 0) * (Number(i.precio_unitario) || 0), 0)
  const descuentoValor = subtotal * (Number(form.descuento_pct) || 0) / 100
  const base = subtotal - descuentoValor
  const ivaValor = base * (Number(form.iva_pct) || 0) / 100
  const total = base + ivaValor
  const costo = items.reduce((s, i) => s + (Number(i.cantidad) || 0) * (Number(i.costo_unitario) || 0), 0)
  const utilidad = base - costo
  const margen = base > 0 ? utilidad / base * 100 : 0

  async function crear(e) {
    e.preventDefault()
    setMsg(null)
    setTrabajo(true)
    try {
      await apiFetch('/cotizaciones', { method: 'POST', body: {
        ...form, cliente_id: form.cliente_id ? Number(form.cliente_id) : null,
        items: items.filter(i => i.descripcion.trim()).map(i => ({
          ...i, cantidad: Number(i.cantidad), precio_unitario: Number(i.precio_unitario),
          costo_unitario: Number(i.costo_unitario || 0),
        })),
        estado: 'pendiente',
      }, token: auth.token })
      setNueva(false)
      setItems([{ descripcion: '', cantidad: 1, unidad: 'und', precio_unitario: 0, costo_unitario: 0, servicio_id: null }])
      setMsg({ tipo: 'ok', texto: 'Cotización creada.' })
      await cargar()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    } finally {
      setTrabajo(false)
    }
  }

  async function cambiarEstado(c, nuevoEstado) {
    try {
      await apiFetch(`/cotizaciones/${c.id}/estado`, { method: 'POST', body: { estado: nuevoEstado }, token: auth.token })
      await cargar()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }

  async function duplicar(c) {
    try {
      await apiFetch(`/cotizaciones/${c.id}/duplicar`, { method: 'POST', token: auth.token })
      setMsg({ tipo: 'ok', texto: 'Cotización duplicada como borrador.' })
      await cargar()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }

  async function convertir(c) {
    setMsg(null)
    try {
      const r = await apiFetch(`/cotizaciones/${c.id}/convertir`, { method: 'POST', token: auth.token })
      setMsg({ tipo: 'ok', texto: `Proyecto #${r.proyecto_id} creado.` })
      await cargar()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }

  async function pdf(c) {
    setMsg(null)
    try {
      const r = await apiFetch(`/cotizaciones/${c.id}/pdf`, { method: 'POST', body: {}, token: auth.token })
      setMsg({ tipo: 'ok', texto: r.pdf_ok ? 'PDF generado.' : r.mensaje })
      descargarAutenticado(`/api/documentos/${r.documento_id}/descarga?formato=${r.pdf_ok ? 'pdf' : 'docx'}`,
                           auth.token, `${c.numero}.${r.pdf_ok ? 'pdf' : 'docx'}`)
      await cargar()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }

  async function verDetalle(c) {
    setDetalle(null)
    try {
      setDetalle(await apiFetch(`/cotizaciones/${c.id}`, { token: auth.token }))
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }

  return (
    <div>
      <h3 className="vista-titulo">Cotizaciones</h3>
      {msg && <div className={`alert ${msg.tipo === 'ok' ? 'alert-success' : 'alert-error'}`}>{msg.texto}</div>}
      <div className="fila-form" style={{ marginBottom: '1rem' }}>
        <div className="form-group" style={{ flex: '0 0 220px' }}>
          <label>Filtrar por estado</label>
          <select value={filtro} onChange={e => setFiltro(e.target.value)}>
            <option value="">Todas</option>
            {Object.entries(ESTADO_ETIQUETA).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
        <span style={{ flex: 1 }} />
        <button type="button" className="btn btn-primary" onClick={() => setNueva(true)}>+ Nueva cotización</button>
      </div>

      {nueva && (
        <form onSubmit={crear} className="card">
          <h4>Nueva cotización</h4>
          <div className="form-grid">
            <div className="form-group">
              <label>Cliente registrado</label>
              <select value={form.cliente_id} onChange={e => setForm({ ...form, cliente_id: e.target.value })}>
                <option value="">— escribir nombre —</option>
                {clientes.map(c => <option key={c.id} value={c.id}>{c.nombre}</option>)}
              </select>
            </div>
            <div className="form-group">
              <label>o nombre libre del cliente</label>
              <input value={form.cliente} onChange={e => setForm({ ...form, cliente: e.target.value })}
                     disabled={!!form.cliente_id} />
            </div>
            <div className="form-group">
              <label>IVA (%)</label>
              <input type="number" step="any" min="0" max="100" value={form.iva_pct}
                     onChange={e => setForm({ ...form, iva_pct: e.target.value })} />
            </div>
            <div className="form-group">
              <label>Descuento (%)</label>
              <input type="number" step="any" min="0" max="100" value={form.descuento_pct}
                     onChange={e => setForm({ ...form, descuento_pct: e.target.value })} />
            </div>
          </div>
          <div className="form-group">
            <label>Descripción del proyecto</label>
            <textarea value={form.descripcion} rows={2}
                      onChange={e => setForm({ ...form, descripcion: e.target.value })} />
          </div>
          <h4>Servicios (ítems)</h4>
          <p className="nota">Elige un servicio del catálogo para traer su precio y costo; o escribe una fila libre.</p>
          {items.map((it, idx) => (
            <div className="fila-form items-fila" key={idx}>
              <div className="form-group crece-3">
                <label>Servicio / descripción</label>
                <select value={it.servicio_id || ''}
                        onChange={e => {
                          const s = servicios.find(x => String(x.id) === e.target.value)
                          if (!s) { setItems(items.map((x, i) => i === idx ? { ...x, servicio_id: null } : x)); return }
                          setItems(items.map((x, i) => i === idx ? {
                            ...x, servicio_id: s.id, descripcion: s.nombre, unidad: s.unidad,
                            precio_unitario: s.precio_venta, costo_unitario: s.costo_total,
                          } : x))
                        }}>
                  <option value="">— texto libre —</option>
                  {servicios.map(s => <option key={s.id} value={s.id}>{s.codigo} · {s.nombre}</option>)}
                </select>
                <input value={it.descripcion}
                       onChange={e => setItems(items.map((x, i) => i === idx ? { ...x, descripcion: e.target.value } : x))}
                       required placeholder="Descripción de la fila" />
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
                <label>Precio</label>
                <input type="number" step="any" min="0" value={it.precio_unitario}
                       onChange={e => setItems(items.map((x, i) => i === idx ? { ...x, precio_unitario: e.target.value } : x))} />
              </div>
              <div className="form-group crece-2">
                <label>Costo</label>
                <input type="number" step="any" min="0" value={it.costo_unitario}
                       onChange={e => setItems(items.map((x, i) => i === idx ? { ...x, costo_unitario: e.target.value } : x))} />
              </div>
              <div className="form-group crece-2">
                <label>Total</label>
                <em className="total-item">{fmtCOP(Number(it.cantidad) * Number(it.precio_unitario))}</em>
              </div>
              <button type="button" className="btn btn-mini btn-peligro"
                      onClick={() => setItems(items.filter((_, i) => i !== idx))}
                      disabled={items.length === 1}>Quitar</button>
            </div>
          ))}
          <button type="button" className="btn btn-mini"
                  onClick={() => setItems([...items, { descripcion: '', cantidad: 1, unidad: 'und', precio_unitario: 0, costo_unitario: 0, servicio_id: null }])}>
            + Añadir fila
          </button>
          <div className="grid-cards" style={{ margin: '0.9rem 0' }}>
            <div className="stat-card"><span className="stat-valor">{fmtCOP(subtotal)}</span><span className="stat-etiqueta">Subtotal</span></div>
            <div className="stat-card"><span className="stat-valor">{fmtCOP(descuentoValor)}</span><span className="stat-etiqueta">Descuento</span></div>
            <div className="stat-card"><span className="stat-valor">{fmtCOP(utilidad)}</span><span className="stat-etiqueta">Utilidad (margen {margen.toFixed(1)}%)</span></div>
            <div className="stat-card"><span className="stat-valor">{fmtCOP(total)}</span><span className="stat-etiqueta">Total con IVA</span></div>
          </div>
          {margen < config.margen_minimo_pct ? (
            <div className="alert alert-error">
              El margen ({margen.toFixed(1)}%) queda bajo el mínimo del dueño ({config.margen_minimo_pct}%): los administradores no podrán guardarla{esDueno ? '; tú puedes, pero revisa el precio.' : '.'}
            </div>
          ) : null}
          {Number(form.descuento_pct) > config.descuento_max_pct ? (
            <div className="alert alert-error">
              El descuento supera el máximo del dueño ({config.descuento_max_pct}%): lo rechazará el backend.
            </div>
          ) : null}
          <div className="form-grid">
            <div className="form-group">
              <label>Tiempo de ejecución</label>
              <input value={form.tiempo_ejecucion} onChange={e => setForm({ ...form, tiempo_ejecucion: e.target.value })} />
            </div>
            <div className="form-group">
              <label>Forma de pago</label>
              <input value={form.forma_pago} onChange={e => setForm({ ...form, forma_pago: e.target.value })} />
            </div>
            <div className="form-group">
              <label>Vigencia</label>
              <input value={form.vigencia_cotizacion} onChange={e => setForm({ ...form, vigencia_cotizacion: e.target.value })} />
            </div>
          </div>
          <div className="form-group">
            <label>Observaciones</label>
            <textarea value={form.observaciones} rows={2}
                      onChange={e => setForm({ ...form, observaciones: e.target.value })} />
          </div>
          <button type="submit" className="btn btn-primary" disabled={trabajo}>Crear cotización</button>
        </form>
      )}

      <div className="card">
        {!cotizaciones ? <div className="spinner" />
          : cotizaciones.length === 0 ? <p className="muted">Sin cotizaciones todavía.</p>
          : (
          <table className="table">
            <thead>
              <tr><th>Número</th><th>Cliente</th><th>Estado</th><th>Total</th><th>Utilidad</th><th>Creada</th><th>Acciones</th></tr>
            </thead>
            <tbody>
              {cotizaciones.map(c => (
                <tr key={c.id}>
                  <td><strong>{c.numero}</strong></td>
                  <td>{c.cliente}</td>
                  <td><span className={`badge ${c.estado === 'aprobada' ? 'badge-azul' : c.estado === 'convertida' ? 'badge-verde' : 'badge-violeta'}`}>
                    {ESTADO_ETIQUETA[c.estado] || c.estado}</span></td>
                  <td>{fmtCOP(c.total)}</td>
                  <td>{fmtCOP(c.utilidad)}</td>
                  <td>{c.creado_en ? c.creado_en.slice(0, 10) : '—'}</td>
                  <td className="acciones">
                    <button type="button" className="btn btn-mini" onClick={() => verDetalle(c)}>Ver</button>
                    <select className="mini-select" value={c.estado} onChange={e => cambiarEstado(c, e.target.value)}>
                      {Object.entries(ESTADO_ETIQUETA).map(([k, v]) => (
                        <option key={k} value={k} disabled={k === 'convertida' || c.estado === 'convertida'}>{v}</option>
                      ))}
                    </select>
                    <button type="button" className="btn btn-mini" onClick={() => duplicar(c)}>Duplicar</button>
                    <button type="button" className="btn btn-mini" onClick={() => pdf(c)}>PDF</button>
                    {c.estado === 'aprobada' && (
                      <button type="button" className="btn btn-mini" onClick={() => convertir(c)}>Convertir en proyecto</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {detalle && (
        <div className="card">
          <h4>{detalle.numero} — {detalle.cliente} <span className="badge badge-violeta">{ESTADO_ETIQUETA[detalle.estado]}</span></h4>
          <div className=" tabla-datos" >
            <div><span>Descripción</span><strong>{detalle.descripcion || '—'}</strong></div>
            <div><span>Subtotal</span><strong>{fmtCOP(detalle.subtotal)}</strong></div>
            <div><span>Descuento</span><strong>{fmtCOP(detalle.descuento_valor)} ({detalle.descuento_pct}%)</strong></div>
            <div><span>IVA</span><strong>{fmtCOP(detalle.iva_valor)} ({detalle.iva_pct}%)</strong></div>
            <div><span>Total</span><strong>{fmtCOP(detalle.total)}</strong></div>
            <div><span>Costo estimado / utilidad</span><strong>{fmtCOP(detalle.costo_estimado)} / {fmtCOP(detalle.utilidad)}</strong></div>
            <div><span>Condiciones</span><strong>{[detalle.tiempo_ejecucion, detalle.forma_pago, detalle.vigencia_cotizacion].filter(Boolean).join(' · ') || '—'}</strong></div>
            {detalle.plantilla_version && (
              <div><span>Documento</span><strong>generado con plantilla v{detalle.plantilla_version}</strong></div>
            )}
          </div>
          <table className="table">
            <thead><tr><th>Ítem</th><th>Descripción</th><th>Cant.</th><th>Unidad</th><th>Precio</th><th>Total</th></tr></thead>
            <tbody>
              {detalle.items.map(i => (
                <tr key={i.id}>
                  <td>{i.orden}</td>
                  <td>{i.descripcion}</td>
                  <td>{i.cantidad}</td>
                  <td>{i.unidad}</td>
                  <td>{fmtCOP(i.precio_unitario)}</td>
                  <td>{fmtCOP(i.cantidad * i.precio_unitario)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <button type="button" className="btn btn-mini" onClick={() => setDetalle(null)}>Cerrar detalle</button>
        </div>
      )}
    </div>
  )
}
