import React, { useState, useEffect } from 'react'

import { ESTADO_ETIQUETA, fmtCOP } from './Comercial.jsx'

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

export const ESTADO_PROY = {
  activo: 'Activo', pausado: 'Pausado', finalizado: 'Finalizado', cancelado: 'Cancelado',
}

export const CATEGORIA_GASTO = {
  materiales: 'Materiales', mano_obra: 'Mano de obra', herramientas: 'Herramientas',
  transporte: 'Transporte', servicios: 'Servicios', otro: 'Otro',
}

export function VistaProyectos({ auth }) {
  const [proyectos, setProyectos] = useState(null)
  const [clientes, setClientes] = useState([])
  const [msg, setMsg] = useState(null)
  const [det, setDet] = useState(null)
  const [trabajo, setTrabajo] = useState(false)
  const [nuevo, setNuevo] = useState({
    nombre: '', cliente_id: '', descripcion: '', presupuesto: 0, fecha_inicio: '',
  })

  async function cargar() {
    try {
      setProyectos(await apiFetch('/proyectos', { token: auth.token }))
      setClientes(await apiFetch('/clientes', { token: auth.token }))
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }
  useEffect(() => { cargar() }, [])

  async function crear(e) {
    e.preventDefault()
    setMsg(null)
    setTrabajo(true)
    try {
      await apiFetch('/proyectos', { method: 'POST', body: {
        ...nuevo,
        cliente_id: nuevo.cliente_id ? Number(nuevo.cliente_id) : null,
        presupuesto: Number(nuevo.presupuesto) || 0,
      }, token: auth.token })
      setNuevo({ nombre: '', cliente_id: '', descripcion: '', presupuesto: 0, fecha_inicio: '' })
      setMsg({ tipo: 'ok', texto: 'Proyecto creado.' })
      await cargar()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    } finally {
      setTrabajo(false)
    }
  }

  async function detalle(p) {
    try {
      setDet(await apiFetch(`/proyectos/${p.id}`, { token: auth.token }))
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }

  async function registrarGasto(p) {
    const descripcion = prompt('Descripción del gasto/compra:', '')
    if (!descripcion) return
    const monto = prompt('Monto:', '')
    if (!monto || isNaN(Number(monto))) { alert('Monto inválido'); return }
    const tipo = prompt('Tipo — gasto o compra:', 'gasto')
    if (!tipo) return
    const categoria = prompt('Categoría — materiales, mano_obra, herramientas, transporte, servicios, otro:', 'otro')
    if (!categoria) return
    try {
      await apiFetch('/gastos', { method: 'POST', body: {
        proyecto_id: p.id, descripcion, monto: Number(monto),
        tipo: ['gasto', 'compra'].includes(tipo) ? tipo : 'gasto',
        categoria: Object.keys(CATEGORIA_GASTO).includes(categoria) ? categoria : 'otro',
      }, token: auth.token })
      setMsg({ tipo: 'ok', texto: 'Registrado.' })
      await cargar()
      if (det && det.id === p.id) setDet(await apiFetch(`/proyectos/${p.id}`, { token: auth.token }))
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }

  async function cambiarEstado(p, estado) {
    try {
      await apiFetch(`/proyectos/${p.id}`, { method: 'PUT',
        body: { estado, avance_pct: estado === 'finalizado' ? 100 : p.avance_pct },
        token: auth.token })
      await cargar()
      if (det && det.id === p.id) setDet(await apiFetch(`/proyectos/${p.id}`, { token: auth.token }))
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }

  return (
    <div>
      <h3 className="vista-titulo">Proyectos</h3>
      {msg && <div className={`alert ${msg.tipo === 'ok' ? 'alert-success' : 'alert-error'}`}>{msg.texto}</div>}

      <form onSubmit={crear} className="card">
        <h4>Nuevo proyecto</h4>
        <div className="form-grid">
          <div className="form-group"><label>Nombre</label>
            <input value={nuevo.nombre} onChange={e => setNuevo({ ...nuevo, nombre: e.target.value })} required /></div>
          <div className="form-group"><label>Cliente</label>
            <select value={nuevo.cliente_id} onChange={e => setNuevo({ ...nuevo, cliente_id: e.target.value })}>
              <option value="">Sin cliente</option>
              {clientes.map(c => <option key={c.id} value={c.id}>{c.nombre}</option>)}
            </select></div>
          <div className="form-group"><label>Presupuesto</label>
            <input type="number" step="any" min="0" value={nuevo.presupuesto}
                   onChange={e => setNuevo({ ...nuevo, presupuesto: e.target.value })} /></div>
        </div>
        <div className="form-group"><label>Descripción</label>
          <textarea value={nuevo.descripcion} rows={2}
                    onChange={e => setNuevo({ ...nuevo, descripcion: e.target.value })} /></div>
        <button type="submit" className="btn btn-primary" disabled={trabajo}>Crear proyecto</button>
      </form>

      <div className="card">
        {!proyectos ? <div className="spinner" /> : proyectos.length === 0 ? (
          <p className="muted">Sin proyectos. Nacen de cotizaciones aprobadas o se crean aquí.</p>
        ) : (
          <table className="table">
            <thead>
              <tr><th>Código</th><th>Nombre</th><th>Cliente</th><th>Presupuesto</th><th>Ejecutado</th><th>Saldo</th><th>Estado</th><th></th></tr>
            </thead>
            <tbody>
              {proyectos.map(p => (
                <tr key={p.id}>
                  <td>{p.codigo || p.id}</td>
                  <td><strong>{p.nombre}</strong></td>
                  <td>{p.cliente || '—'}</td>
                  <td>{fmtCOP(p.presupuesto)}</td>
                  <td>{fmtCOP(p.gastos_total)}</td>
                  <td style={{ color: p.saldo < 0 ? 'var(--c-rojo)' : undefined }}>{fmtCOP(p.saldo)}</td>
                  <td><span className={`badge ${p.estado === 'activo' ? 'badge-azul' : p.estado === 'finalizado' ? 'badge-verde' : 'badge-violeta'}`}>{ESTADO_PROY[p.estado] || p.estado}</span></td>
                  <td className="acciones">
                    <button type="button" className="btn btn-mini" onClick={() => detalle(p)}>Detalle</button>
                    <button type="button" className="btn btn-mini" onClick={() => registrarGasto(p)}>+ Gasto/Compra</button>
                    {p.estado === 'activo' && (
                      <button type="button" className="btn btn-mini" onClick={() => cambiarEstado(p, 'finalizado')}>Finalizar</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {det && (
        <div className="card">
          <h4>{det.codigo} — {det.nombre} <span className="badge badge-azul">{ESTADO_PROY[det.estado]}</span></h4>
          <div className="tabla-datos">
            <div><span>Cliente</span><strong>{det.cliente || '—'}</strong></div>
            <div><span>Descripción</span><strong>{det.descripcion || '—'}</strong></div>
            <div><span>Presupuesto</span><strong>{fmtCOP(det.presupuesto)}</strong></div>
            <div><span>Ejecutado (gastos + compras)</span><strong>{fmtCOP(det.gastos_total)}</strong></div>
            <div><span>Saldo disponible</span><strong>{fmtCOP(det.saldo)}</strong></div>
            {det.cotizacion && (
              <div><span>Cotización origen</span><strong>{det.cotizacion.numero} ({ESTADO_ETIQUETA[det.cotizacion.estado]}, {fmtCOP(det.cotizacion.total)})</strong></div>
            )}
            <div><span>Avance</span><strong>{det.avance_pct}%</strong></div>
          </div>
          {det.desglose_gastos.length > 0 && (
            <>
              <h4>Desglose por categoría</h4>
              <div className="tabla-datos">
                {det.desglose_gastos.map(d => (
                  <div key={d.categoria}><span>{CATEGORIA_GASTO[d.categoria] || d.categoria}</span><strong>{fmtCOP(d.monto)}</strong></div>
                ))}
              </div>
            </>
          )}
          <button type="button" className="btn btn-mini" onClick={() => setDet(null)}>Cerrar detalle</button>&nbsp;
          <button type="button" className="btn btn-mini" onClick={() => registrarGasto({ id: det.id })}>+ Registrar gasto/compra</button>
        </div>
      )}
    </div>
  )
}

export function VistaAgenda({ auth }) {
  const [eventos, setEventos] = useState(null)
  const [clientes, setClientes] = useState([])
  const [msg, setMsg] = useState(null)
  const [nuevo, setNuevo] = useState({
    titulo: '', fecha_hora: '', tipo: 'visita_tecnica', cliente_id: '', notas: '',
  })
  const [trabajo, setTrabajo] = useState(false)

  async function cargar() {
    try {
      setEventos(await apiFetch('/agenda?dias=30', { token: auth.token }))
      setClientes(await apiFetch('/clientes', { token: auth.token }))
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }
  useEffect(() => { cargar() }, [])

  async function crear(e) {
    e.preventDefault()
    setMsg(null)
    setTrabajo(true)
    try {
      await apiFetch('/agenda', { method: 'POST', body: {
        titulo: nuevo.titulo,
        fecha_hora: new Date(nuevo.fecha_hora).toISOString().slice(0, 19),
        tipo: nuevo.tipo,
        cliente_id: nuevo.cliente_id ? Number(nuevo.cliente_id) : null,
        notas: nuevo.notas,
      }, token: auth.token })
      setNuevo({ titulo: '', fecha_hora: '', tipo: 'visita_tecnica', cliente_id: '', notas: '' })
      setMsg({ tipo: 'ok', texto: 'Evento en la agenda. El vigilante lo recordará por Telegram 24 h antes.' })
      await cargar()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    } finally {
      setTrabajo(false)
    }
  }

  async function eliminar(ev) {
    if (!window.confirm(`¿Eliminar "${ev.titulo}"?`)) return
    try {
      await apiFetch(`/agenda/${ev.id}`, { method: 'DELETE', token: auth.token })
      await cargar()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }

  const TIPOS = {
    visita_tecnica: 'Visita técnica', reunion: 'Reunión', entrega: 'Entrega',
    vencimiento: 'Vencimiento', seguimiento: 'Seguimiento', otro: 'Otro',
  }

  return (
    <div>
      <h3 className="vista-titulo">Agenda</h3>
      {msg && <div className={`alert ${msg.tipo === 'ok' ? 'alert-success' : 'alert-error'}`}>{msg.texto}</div>}
      <form onSubmit={crear} className="card">
        <h4>Nuevo evento</h4>
        <div className="form-grid">
          <div className="form-group"><label>Tipo</label>
            <select value={nuevo.tipo} onChange={e => setNuevo({ ...nuevo, tipo: e.target.value })}>
              {Object.entries(TIPOS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select></div>
          <div className="form-group"><label>Fecha y hora</label>
            <input type="datetime-local" value={nuevo.fecha_hora}
                   onChange={e => setNuevo({ ...nuevo, fecha_hora: e.target.value })} required /></div>
          <div className="form-group"><label>Cliente (opcional)</label>
            <select value={nuevo.cliente_id} onChange={e => setNuevo({ ...nuevo, cliente_id: e.target.value })}>
              <option value="">—</option>
              {clientes.map(c => <option key={c.id} value={c.id}>{c.nombre}</option>)}
            </select></div>
        </div>
        <div className="form-group"><label>Título</label>
          <input value={nuevo.titulo} onChange={e => setNuevo({ ...nuevo, titulo: e.target.value })} required /></div>
        <div className="form-group"><label>Notas</label>
          <textarea value={nuevo.notas} rows={2}
                    onChange={e => setNuevo({ ...nuevo, notas: e.target.value })} /></div>
        <button type="submit" className="btn btn-primary" disabled={trabajo}>Agendar</button>
      </form>

      <div className="card">
        <h4>Próximos 30 días</h4>
        {!eventos ? <div className="spinner" /> : eventos.length === 0 ? (
          <p className="muted">Nada agendado. Los eventos de hoy y mañana se recuerdan por Telegram (si el bot está activo).</p>
        ) : (
          <table className="table">
            <thead><tr><th>Cuándo</th><th>Tipo</th><th>Título</th><th>Cliente</th><th>Notas</th><th></th></tr></thead>
            <tbody>
              {eventos.map(ev => (
                <tr key={ev.id} className={ev.recordado ? '' : ''}>
                  <td>{ev.fecha_hora ? ev.fecha_hora.replace('T', ' ').slice(0, 16) : '—'}</td>
                  <td>{TIPOS[ev.tipo] || ev.tipo}</td>
                  <td><strong>{ev.titulo}</strong></td>
                  <td>{ev.cliente || '—'}</td>
                  <td>{ev.notas || '—'}</td>
                  <td className="acciones">
                    <button type="button" className="btn btn-mini btn-peligro" onClick={() => eliminar(ev)}>Eliminar</button>
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

export function VistaDocumentos({ auth }) {
  const esDueno = auth.user.rol === 'dueno'
  const [archivos, setArchivos] = useState(null)
  const [clientes, setClientes] = useState([])
  const [proyectos, setProyectos] = useState([])
  const [msg, setMsg] = useState(null)
  const [cat, setCat] = useState('otro')
  const [clienteId, setClienteId] = useState('')
  const [proyectoId, setProyectoId] = useState('')

  async function cargar() {
    try {
      setArchivos(await apiFetch('/archivos', { token: auth.token }))
      setClientes(await apiFetch('/clientes', { token: auth.token }))
      setProyectos(await apiFetch('/proyectos', { token: auth.token }))
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }
  useEffect(() => { cargar() }, [])

  async function subir(e) {
    e.preventDefault()
    const f = e.target.archivo.files[0]
    if (!f) { setMsg({ tipo: 'error', texto: 'Elige un archivo.' }); return }
    const fd = new FormData()
    fd.append('archivo', f)
    fd.append('categoria', cat)
    if (clienteId) fd.append('cliente_id', clienteId)
    if (proyectoId) fd.append('proyecto_id', proyectoId)
    setMsg(null)
    try {
      const r = await fetch('/api/archivos', {
        method: 'POST', headers: { Authorization: `Bearer ${auth.token}` }, body: fd,
      })
      if (!r.ok) {
        const data = await r.json().catch(() => ({}))
        throw new Error(data?.detail || 'No se pudo subir.')
      }
      e.target.reset()
      setMsg({ tipo: 'ok', texto: 'Archivo guardado en el repositorio.' })
      await cargar()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }

  async function eliminar(a) {
    if (!window.confirm(`¿Eliminar "${a.nombre}" del repositorio?`)) return
    try {
      await apiFetch(`/archivos/${a.id}`, { method: 'DELETE', token: auth.token })
      await cargar()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }

  const CATEG = ['cotizacion', 'contrato', 'foto', 'factura', 'comprobante', 'plano', 'informe', 'tecnico', 'cliente', 'otro']

  return (
    <div>
      <h3 className="vista-titulo">Documentos</h3>
      {msg && <div className={`alert ${msg.tipo === 'ok' ? 'alert-success' : 'alert-error'}`}>{msg.texto}</div>}
      <form onSubmit={subir} className="card">
        <h4>Subir al repositorio</h4>
        <div className="form-grid">
          <div className="form-group"><label>Archivo (máx 25 MB)</label>
            <input type="file" name="archivo" required /></div>
          <div className="form-group"><label>Categoría</label>
            <select value={cat} onChange={e => setCat(e.target.value)}>
              {CATEG.map(cg => <option key={cg} value={cg}>{cg}</option>)}
            </select></div>
          <div className="form-group"><label>Cliente (opcional)</label>
            <select value={clienteId} onChange={e => setClienteId(e.target.value)}>
              <option value="">—</option>
              {clientes.map(c => <option key={c.id} value={c.id}>{c.nombre}</option>)}
            </select></div>
          <div className="form-group"><label>Proyecto (opcional)</label>
            <select value={proyectoId} onChange={e => setProyectoId(e.target.value)}>
              <option value="">—</option>
              {proyectos.map(p => <option key={p.id} value={p.id}>{p.codigo} · {p.nombre}</option>)}
            </select></div>
        </div>
        <button type="submit" className="btn btn-primary">Subir</button>
      </form>

      <div className="card">
        {!archivos ? <div className="spinner" /> : archivos.length === 0 ? (
          <p className="muted">Repositorio vacío. Los PDF/DOCX generados en Plantillas aparecen en su propia sección.</p>
        ) : (
          <table className="table">
            <thead><tr><th>Nombre</th><th>Categoría</th><th>Cliente</th><th>Proyecto</th><th>Tamaño</th><th>Fecha</th><th></th></tr></thead>
            <tbody>
              {archivos.map(a => {
                const cl = clientes.find(c => c.id === a.cliente_id)
                const pr = proyectos.find(p => p.id === a.proyecto_id)
                return (
                  <tr key={a.id}>
                    <td><strong>{a.nombre}</strong></td>
                    <td>{a.categoria}</td>
                    <td>{cl ? cl.nombre : '—'}</td>
                    <td>{pr ? `${pr.codigo}` : '—'}</td>
                    <td>{(a.tamano / 1024).toFixed(1)} KB</td>
                    <td>{a.creado_en ? a.creado_en.slice(0, 10) : '—'}</td>
                    <td className="acciones">
                      <button type="button" className="btn btn-mini"
                              onClick={() => descargarAutenticado(`/api/archivos/${a.id}/descarga`, auth.token, a.nombre)}>Descargar</button>
                      {esDueno && (
                        <button type="button" className="btn btn-mini btn-peligro" onClick={() => eliminar(a)}>Eliminar</button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

export function VistaCredenciales({ auth }) {
  const [credenciales, setCredenciales] = useState(null)
  const [msg, setMsg] = useState(null)
  const [nuevo, setNuevo] = useState({ plataforma: '', url: '', usuario_cuenta: '', password: '', categoria: 'general', notas: '' })
  const [trabajo, setTrabajo] = useState(false)

  async function cargar() {
    try {
      setCredenciales(await apiFetch('/credenciales', { token: auth.token }))
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }
  useEffect(() => { cargar() }, [])

  async function crear(e) {
    e.preventDefault()
    setMsg(null)
    setTrabajo(true)
    try {
      await apiFetch('/credenciales', { method: 'POST', body: nuevo, token: auth.token })
      setNuevo({ plataforma: '', url: '', usuario_cuenta: '', password: '', categoria: 'general', notas: '' })
      setMsg({ tipo: 'ok', texto: 'Credencial guardada cifrada.' })
      await cargar()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    } finally {
      setTrabajo(false)
    }
  }

  async function revelar(c) {
    setMsg(null)
    try {
      const r = await apiFetch(`/credenciales/${c.id}/revelar`, { method: 'POST', token: auth.token })
      window.prompt(`Contraseña de "${c.plataforma}" (queda en auditoría): Ctrl+C para copiar`, r.password)
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }

  async function eliminar(c) {
    if (!window.confirm(`¿Eliminar la credencial de "${c.plataforma}"?`)) return
    try {
      await apiFetch(`/credenciales/${c.id}`, { method: 'DELETE', token: auth.token })
      await cargar()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }

  return (
    <div>
      <h3 className="vista-titulo">Bóveda de Credenciales (solo dueño)</h3>
      {msg && <div className={`alert ${msg.tipo === 'ok' ? 'alert-success' : 'alert-error'}`}>{msg.texto}</div>}
      <form onSubmit={crear} className="card">
        <h4>Nueva credencial</h4>
        <div className="form-grid">
          <div className="form-group"><label>Plataforma</label>
            <input value={nuevo.plataforma} onChange={e => setNuevo({ ...nuevo, plataforma: e.target.value })} required /></div>
          <div className="form-group"><label>URL</label>
            <input value={nuevo.url} onChange={e => setNuevo({ ...nuevo, url: e.target.value })} /></div>
          <div className="form-group"><label>Usuario de la cuenta</label>
            <input value={nuevo.usuario_cuenta} onChange={e => setNuevo({ ...nuevo, usuario_cuenta: e.target.value })} /></div>
          <div className="form-group"><label>Contraseña (se cifra)</label>
            <input type="password" value={nuevo.password} onChange={e => setNuevo({ ...nuevo, password: e.target.value })} required /></div>
          <div className="form-group"><label>Categoría</label>
            <input value={nuevo.categoria} onChange={e => setNuevo({ ...nuevo, categoria: e.target.value })} /></div>
        </div>
        <div className="form-group"><label>Notas</label>
          <textarea value={nuevo.notas} rows={2}
                    onChange={e => setNuevo({ ...nuevo, notas: e.target.value })} /></div>
        <button type="submit" className="btn btn-primary" disabled={trabajo}>Guardar cifrada</button>
      </form>

      <div className="card">
        {!credenciales ? <div className="spinner" /> : credenciales.length === 0 ? (
          <p className="muted">Bóveda vacía. Las contraseñas se guardan cifradas y revelarlas queda auditado.</p>
        ) : (
          <table className="table">
            <thead><tr><th>Plataforma</th><th>URL</th><th>Usuario</th><th>Categoría</th><th></th></tr></thead>
            <tbody>
              {credenciales.map(c => (
                <tr key={c.id}>
                  <td><strong>{c.plataforma}</strong></td>
                  <td>{c.url || '—'}</td>
                  <td>{c.usuario_cuenta || '—'}</td>
                  <td>{c.categoria}</td>
                  <td className="acciones">
                    <button type="button" className="btn btn-mini" onClick={() => revelar(c)}>Revelar</button>
                    <button type="button" className="btn btn-mini btn-peligro" onClick={() => eliminar(c)}>Eliminar</button>
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
