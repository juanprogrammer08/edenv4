import React, { useState, useEffect } from 'react'

import { fmtCOP, ESTADO_ETIQUETA } from './Comercial.jsx'
import { CATEGORIA_GASTO } from './Operaciones.jsx'

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

export function VistaReportes({ auth }) {
  const [rep, setRep] = useState(null)
  const [clientes, setClientes] = useState([])
  const [msg, setMsg] = useState(null)
  const [filtros, setFiltros] = useState({ desde: '', hasta: '', cliente_id: '' })

  async function cargar(f = filtros) {
    try {
      const params = new URLSearchParams()
      if (f.desde) params.set('desde', f.desde)
      if (f.hasta) params.set('hasta', f.hasta + 'T23:59:59')
      if (f.cliente_id) params.set('cliente_id', f.cliente_id)
      setRep(await apiFetch('/reportes?' + params.toString(), { token: auth.token }))
      setClientes(await apiFetch('/clientes', { token: auth.token }))
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }
  useEffect(() => { cargar(filtros) }, [])

  const ETIQUETA_CATEG = {
    materiales: 'Materiales', mano_obra: 'Mano de obra', herramientas: 'Herramientas',
    transporte: 'Transporte', servicios: 'Servicios', otro: 'Otro',
  }

  return (
    <div>
      <h3 className="vista-titulo">Reportes</h3>
      {msg && <div className={`alert alert-error`}>{msg.texto}</div>}
      <form className="card fila-form" onSubmit={e => { e.preventDefault(); cargar(filtros) }}>
        <div className="form-group"><label>Desde</label>
          <input type="date" value={filtros.desde}
                 onChange={e => setFiltros({ ...filtros, desde: e.target.value })} /></div>
        <div className="form-group"><label>Hasta</label>
          <input type="date" value={filtros.hasta}
                 onChange={e => setFiltros({ ...filtros, hasta: e.target.value })} /></div>
        <div className="form-group"><label>Cliente</label>
          <select value={filtros.cliente_id}
                  onChange={e => setFiltros({ ...filtros, cliente_id: e.target.value })}>
            <option value="">Todos</option>
            {clientes.map(c => <option key={c.id} value={c.id}>{c.nombre}</option>)}
          </select></div>
        <button type="submit" className="btn btn-primary">Aplicar</button>
      </form>

      {!rep ? <div className="spinner" /> : (
        <>
          <div className="grid-cards">
            <div className="stat-card"><span className="stat-valor">{rep.cotizaciones.conteo_total}</span><span className="stat-etiqueta">Cotizaciones en el rango</span></div>
            <div className="stat-card"><span className="stat-valor">{fmtCOP(rep.cotizaciones.valor_total)}</span><span className="stat-etiqueta">Valor cotizado</span></div>
            <div className="stat-card"><span className="stat-valor">{fmtCOP(rep.rentabilidad.utilidad_cotizada)}</span><span className="stat-etiqueta">Utilidad cotizada</span></div>
            <div className="stat-card"><span className="stat-valor">{rep.proyectos.activos}</span><span className="stat-etiqueta">Proyectos activos</span></div>
            <div className="stat-card"><span className="stat-valor">{fmtCOP(rep.gastos.total)}</span><span className="stat-etiqueta">Ejecutado</span></div>
            <div className="stat-card"><span className="stat-valor">{fmtCOP(rep.gastos.cobertura)}</span><span className="stat-etiqueta">Cobertura (presupuesto − ejecutado)</span></div>
            <div className="stat-card"><span className="stat-valor">{rep.clientes_nuevos}</span><span className="stat-etiqueta">Clientes nuevos</span></div>
          </div>

          <div className="grid-cards">
            <div className="card">
              <h4>Cotizaciones por estado</h4>
              {Object.entries(rep.cotizaciones.por_estado).length === 0
                ? <p className="muted">Sin cotizaciones en el rango.</p>
                : Object.entries(rep.cotizaciones.por_estado).map(([est, v]) => (
                  <div className="tabla-datos" key={est}>
                    <div><span>{ESTADO_ETIQUETA[est] || est}</span>
                      <strong>{v.conteo} · {fmtCOP(v.valor)}</strong></div>
                  </div>
                ))}
            </div>
            <div className="card">
              <h4>Gastos por categoría</h4>
              {Object.entries(rep.gastos.por_categoria).length === 0
                ? <p className="muted">Sin gastos en el rango.</p>
                : Object.entries(rep.gastos.por_categoria).map(([cat, m]) => (
                  <div className="tabla-datos" key={cat}>
                    <div><span>{ETIQUETA_CATEG[cat] || cat}</span><strong>{fmtCOP(m)}</strong></div>
                  </div>
                ))}
            </div>
            <div className="card">
              <h4>Top clientes</h4>
              {rep.top_clientes.length === 0 ? <p className="muted">—</p> : rep.top_clientes.map((c, i) => (
                <div className="tabla-datos" key={i}>
                  <div><span>{c.cliente}</span><strong>{fmtCOP(c.valor)}</strong></div>
                </div>
              ))}
            </div>
          </div>

          {rep.servicios_mas_solicitados.length > 0 && (
            <div className="card">
              <h4>Servicios más solicitados</h4>
              <table className="table">
                <thead><tr><th>Código</th><th>Servicio</th><th>Veces cotizado</th><th>Cantidad total</th></tr></thead>
                <tbody>
                  {rep.servicios_mas_solicitados.map((s, i) => (
                    <tr key={i}>
                      <td>{s.codigo}</td><td>{s.nombre}</td><td>{s.veces}</td><td>{s.cantidad_total}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}

export function VistaAuditoria({ auth }) {
  const [filas, setFilas] = useState(null)
  const [msg] = useState(null)
  const [accion, setAccion] = useState('')
  const [usuario, setUsuario] = useState('')

  async function cargar(a = accion, u = usuario) {
    try {
      const params = new URLSearchParams()
      params.set('limit', '300')
      if (a) params.set('action', a)
      if (u) params.set('username', u)
      setFilas(await apiFetch('/auditoria?' + params.toString(), { token: auth.token }))
    } catch (err) {
      setFilas([])
    }
  }
  useEffect(() => { cargar() }, [])

  return (
    <div>
      <h3 className="vista-titulo">Auditoría (solo dueño)</h3>
      {msg && <div className="alert alert-error">{msg}</div>}
      <form className="card fila-form" onSubmit={e => { e.preventDefault(); cargar() }}>
        <div className="form-group"><label>Filtrar por acción contiene</label>
          <input value={accion} placeholder="p. ej. cotizacion, credencial, login"
                 onChange={e => setAccion(e.target.value)} /></div>
        <div className="form-group"><label>Usuario</label>
          <input value={usuario} placeholder="yovani / amanda"
                 onChange={e => setUsuario(e.target.value)} /></div>
        <button type="submit" className="btn btn-primary">Filtrar</button>
      </form>
      <div className="card">
        {!filas ? <div className="spinner" /> : filas.length === 0 ? (
          <p className="muted">Sin registros con ese filtro.</p>
        ) : (
          <table className="table">
            <thead><tr><th>Fecha</th><th>Usuario</th><th>Acción</th><th>Detalle</th><th>IP</th></tr></thead>
            <tbody>
              {filas.map(a => (
                <tr key={a.id}>
                  <td>{a.creado_en ? a.creado_en.replace('T', ' ').slice(0, 19) : '—'}</td>
                  <td>{a.username || '—'}</td>
                  <td><span className="badge badge-violeta">{a.accion}</span></td>
                  <td className="celda-texto">{a.detalle || '—'}</td>
                  <td>{a.ip || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
