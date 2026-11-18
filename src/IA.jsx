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

export function VistaAI({ auth }) {
  const esDueno = auth.user.rol === 'dueno'
  const [msg, setMsg] = useState(null)
  const [mensajes, setMensajes] = useState(null)
  const [acciones, setAcciones] = useState([])
  const [config, setConfig] = useState(null)
  const [input, setInput] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [cfgForm, setCfgForm] = useState({ api_base: '', modelo: '', api_key: '' })
  const [iaActiva, setIaActiva] = useState(false)
  const [trabajo, setTrabajo] = useState(false)

  async function cargarTodo() {
    try {
      setMensajes(await apiFetch('/ia/mensajes', { token: auth.token }))
      setAcciones(await apiFetch('/ia/acciones', { token: auth.token }))
      if (esDueno) {
        const c = await apiFetch('/ia/config', { token: auth.token })
        setConfig(c)
        setIaActiva(c.activo)
        setCfgForm(f => ({
          api_base: f.api_base || c.api_base || '',
          modelo: f.modelo || c.modelo || '',
          api_key: '',
        }))
      }
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }
  useEffect(() => { cargarTodo() }, [])

  async function enviar(e) {
    e.preventDefault()
    const texto = input.trim()
    if (!texto || enviando) return
    setInput('')
    setMsg(null)
    setEnviando(true)
    const temporal = { rol: 'usuario', texto, creado_en: new Date().toISOString() }
    setMensajes(mensajes ? [...mensajes, temporal] : [temporal])
    try {
      const r = await apiFetch('/ia/chat', { method: 'POST', body: { texto }, token: auth.token })
      setMensajes(m => [
        ...m.filter(x => x !== temporal),
        temporal,
        { rol: 'asistente', texto: r.texto, agente: r.agente, herramientas: r.herramientas || [] },
      ])
      if (r.acciones?.length) setAcciones(await apiFetch('/ia/acciones', { token: auth.token }))
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    } finally {
      setEnviando(false)
    }
  }

  async function confirmar(a, confirmarAhora) {
    setMsg(null)
    setTrabajo(true)
    try {
      const r = await apiFetch(`/ia/acciones/${a.id}/${confirmarAhora ? 'confirmar' : 'cancelar'}`, {
        method: 'POST', token: auth.token,
      })
      setMsg({ tipo: r.ok ? 'ok' : 'error',
               texto: r.ok ? 'Autorizado y ejecutado.' : 'Propuesta cancelada.' })
      setAcciones(await apiFetch('/ia/acciones', { token: auth.token }))
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    } finally {
      setTrabajo(false)
    }
  }

  async function guardarConfig(e) {
    e.preventDefault()
    setMsg(null)
    setTrabajo(true)
    try {
      await apiFetch('/ia/config', { method: 'PUT', body: cfgForm, token: auth.token })
      setCfgForm(f => ({ ...f, api_key: '' }))
      setMsg({ tipo: 'ok', texto: 'Configuración guardada (clave cifrada).' })
      await cargarTodo()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    } finally {
      setTrabajo(false)
    }
  }

  async function probar() {
    setMsg(null)
    setTrabajo(true)
    try {
      const r = await apiFetch('/ia/probar', { method: 'POST', token: auth.token })
      setMsg({ tipo: r.ok ? 'ok' : 'error', texto: r.estado_texto })
      await cargarTodo()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    } finally {
      setTrabajo(false)
    }
  }

  async function alternar() {
    setMsg(null)
    setTrabajo(true)
    try {
      await apiFetch('/ia/activar', { method: 'POST', body: { activo: !iaActiva }, token: auth.token })
      setIaActiva(!iaActiva)
      setMsg({ tipo: 'ok', texto: iaActiva ? 'Núcleo apagado.' : 'Núcleo activado.' })
      await cargarTodo()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    } finally {
      setTrabajo(false)
    }
  }

  return (
    <div>
      <h3 className="vista-titulo">Yeruzzza AI — Centro de inteligencia</h3>
      {msg && <div className={`alert ${msg.tipo === 'ok' ? 'alert-success' : 'alert-error'}`}>{msg.texto}</div>}

      {esDueno && config && (
        <div className="card">
          <h4>Configuración del proveedor (solo dueño)</h4>
          <p className="muted">
            Estado: {config.estado_texto} · <strong>{iaActiva ? 'EN LÍNEA' : 'APAGADO'}</strong> ·
            modelo {config.modelo || '—'} · última prueba{' '}
            {config.ultima_prueba ? config.ultima_prueba.replace('T', ' ').slice(0, 19) : '—'}
          </p>
          <form onSubmit={guardarConfig}>
            <div className="form-grid">
              <div className="form-group">
                <label>Base del API (compatible OpenAI: OpenAI u OmniRoute)</label>
                <input value={cfgForm.api_base} placeholder="https://api.openai.com/v1"
                       onChange={e => setCfgForm({ ...cfgForm, api_base: e.target.value })} required />
              </div>
              <div className="form-group">
                <label>Modelo</label>
                <input value={cfgForm.modelo} placeholder="gpt-4.1-mini"
                       onChange={e => setCfgForm({ ...cfgForm, modelo: e.target.value })} required />
              </div>
              <div className="form-group">
                <label>Clave (se guarda cifrada; nunca vuelve a mostrarse)</label>
                <input type="password" value={cfgForm.api_key}
                       onChange={e => setCfgForm({ ...cfgForm, api_key: e.target.value })}
                       placeholder="sk-..." required />
              </div>
            </div>
            <div className="fila-acciones">
              <button type="submit" className="btn btn-primary" disabled={trabajo}>Guardar y cifrar</button>
              <button type="button" className="btn" onClick={probar} disabled={trabajo}>Probar conexión</button>
              <button type="button" className="btn" onClick={alternar} disabled={trabajo}>
                {iaActiva ? 'Apagar núcleo' : 'Encender núcleo'}
              </button>
            </div>
          </form>
        </div>
      )}

      {acciones.filter(a => a.estado === 'pendiente').length > 0 && (
        <div className="card">
          <h4>Autorización humana requerida</h4>
          {acciones.filter(a => a.estado === 'pendiente').map(a => (
            <div className="fila-form" key={a.id}>
              <div style={{ flex: 1 }}>
                <strong>A#{a.id}</strong> · {a.resumen}
              </div>
              <button type="button" className="btn btn-mini btn-primary" onClick={() => confirmar(a, true)}
                      disabled={trabajo}>Confirmar</button>
              <button type="button" className="btn btn-mini btn-peligro" onClick={() => confirmar(a, false)}
                      disabled={trabajo}>Cancelar</button>
            </div>
          ))}
        </div>
      )}

      <div className="card">
        {!mensajes ? <div className="spinner" />
          : mensajes.length === 0 ? <p className="muted">Escríbele a Yeruzzza: pídele precios del catálogo, crea clientes o cotizaciones, genera documentos.</p>
          : null}
        {mensajes && mensajes.map(m => (
          <div key={m.id} className={`ia-msg ${m.rol === 'usuario' ? 'ia-msg-usuario' : 'ia-msg-asistente'}`}>
            {m.rol === 'asistente' && m.agente && <span className="badge badge-azul">{m.agente}</span>}
            <div className="ia-texto">{m.texto}</div>
            {m.herramientas && m.herramientas.length > 0 && (
              <div className="muted" style={{ fontSize: '0.75rem' }}>
                herramientas: {m.herramientas.join(', ')}
              </div>
            )}
          </div>
        ))}
      </div>

      <form onSubmit={enviar} className="composer ia-composer">
        <textarea value={input} rows={2} className="ia-input"
                  placeholder={'P. ej.: ¿qué precios hay? · crea un cliente llamado… · cotiza 15 puntos de datos y 4 de energía regulada con la marca Centenario'}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); enviar(e) }
                  }} />
        <button type="submit" className="btn btn-primary" disabled={enviando || !input.trim()}>
          {enviando ? 'Yeruzzza pensando…' : 'Enviar'}
        </button>
      </form>
    </div>
  )
}
