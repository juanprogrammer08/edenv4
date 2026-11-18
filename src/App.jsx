import React, { useState, useEffect, createContext, useContext } from 'react'
import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom'

// ============================================================
// API helper
// ============================================================
const API = '/api'

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
  const text = await res.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  if (!res.ok) {
    const detail = data?.detail || data?.error || `Error ${res.status}`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return data
}

// ============================================================
// Contexto de autenticación
// ============================================================
const AuthContext = createContext(null)

export function useAuth() {
  return useContext(AuthContext)
}

function PrivateRoute({ children }) {
  const auth = useAuth()
  const location = useLocation()
  if (!auth.user) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }
  return children
}

// ============================================================
// Login
// ============================================================
function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [enviando, setEnviando] = useState(false)
  const auth = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = location.state?.from?.pathname || '/'

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    setEnviando(true)
    try {
      await auth.login(username, password)
      navigate(from, { replace: true })
    } catch (err) {
      setError(err.message || 'Credenciales incorrectas')
    } finally {
      setEnviando(false)
    }
  }

  return (
    <div className="auth-wrap">
      <div className="auth-card">
        <div className="auth-logo">
          <span className="auth-logo-mark">E</span>
          <div>
            <h2>EDÉN</h2>
            <p className="auth-sub">Asistente Empresarial Inteligente</p>
          </div>
        </div>
        <form onSubmit={handleSubmit} className="auth-form">
          <div className="form-group">
            <label>Usuario</label>
            <input
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              autoFocus
              required
              autoComplete="username"
            />
          </div>
          <div className="form-group">
            <label>Contraseña</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              autoComplete="current-password"
            />
          </div>
          {error && <div className="alert alert-error">{error}</div>}
          <button type="submit" disabled={enviando} className="btn btn-primary btn-block">
            {enviando ? 'Verificando…' : 'Entrar'}
          </button>
        </form>
        <p className="auth-alt">
          ¿Primera vez? <a href="/register">Configura a la dueña o el dueño</a>
        </p>
      </div>
    </div>
  )
}

// ============================================================
// Registro (solo bootstrap del DUEÑO; el backend lo cierra después)
// ============================================================
function RegisterPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmar, setConfirmar] = useState('')
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)
  const navigate = useNavigate()

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    if (password !== confirmar) {
      setError('Las contraseñas no coinciden')
      return
    }
    try {
      await apiFetch('/auth/register', { method: 'POST', form: { username, password } })
      setSuccess('Dueño registrado. Ahora inicia sesión.')
      setTimeout(() => navigate('/login'), 1500)
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="auth-wrap">
      <div className="auth-card">
        <div className="auth-logo">
          <span className="auth-logo-mark">E</span>
          <div>
            <h2>Configurar dueño</h2>
            <p className="auth-sub">Este paso solo está disponible mientras la empresa no tenga dueño</p>
          </div>
        </div>
        <form onSubmit={handleSubmit} className="auth-form">
          <div className="form-group">
            <label>Usuario</label>
            <input type="text" value={username} onChange={e => setUsername(e.target.value)} required minLength={3} autoComplete="username" />
          </div>
          <div className="form-group">
            <label>Contraseña (mínimo 8 caracteres)</label>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} required minLength={8} autoComplete="new-password" />
          </div>
          <div className="form-group">
            <label>Confirmar contraseña</label>
            <input type="password" value={confirmar} onChange={e => setConfirmar(e.target.value)} required minLength={8} autoComplete="new-password" />
          </div>
          {error && <div className="alert alert-error">{error}</div>}
          {success && <div className="alert alert-success">{success}</div>}
          <button type="submit" className="btn btn-primary btn-block">Registrar dueño</button>
        </form>
        <p className="auth-alt">
          ¿Ya tienes cuenta? <a href="/login">Inicia sesión</a>
        </p>
      </div>
    </div>
  )
}

// ============================================================
// Vistas del panel
// ============================================================
function VistaResumen({ auth }) {
  const [empresa, setEmpresa] = useState(null)
  const [cotizaciones, setCotizaciones] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let vivo = true
    Promise.all([
      apiFetch('/empresa', { token: auth.token }),
      apiFetch('/cotizaciones', { token: auth.token }),
    ])
      .then(([emp, cots]) => {
        if (!vivo) return
        setEmpresa(emp)
        setCotizaciones(Array.isArray(cots) ? cots : [])
      })
      .catch(err => vivo && setError(err.message))
    return () => { vivo = false }
  }, [auth.token])

  if (error) return <div className="alert alert-error">{error}</div>

  const aprobadas = (cotizaciones || []).filter(c => c.estado === 'aceptada')
  const totalCotizado = (cotizaciones || []).reduce((s, c) => s + (c.total || 0), 0)
  const fmt = n => new Intl.NumberFormat('es-CO', { style: 'currency', currency: 'COP', maximumFractionDigits: 0 }).format(n || 0)

  return (
    <div>
      <h3 className="vista-titulo">Resumen</h3>
      {!empresa && !cotizaciones ? <div className="spinner" /> : (
        <>
          <div className="grid-cards">
            <div className="stat-card">
              <span className="stat-valor">{cotizaciones ? cotizaciones.length : '—'}</span>
              <span className="stat-etiqueta">Cotizaciones registradas</span>
            </div>
            <div className="stat-card">
              <span className="stat-valor">{aprobadas.length}</span>
              <span className="stat-etiqueta">Aprobadas</span>
            </div>
            <div className="stat-card">
              <span className="stat-valor">{fmt(totalCotizado)}</span>
              <span className="stat-etiqueta">Valor cotizado</span>
            </div>
          </div>
          {empresa && (
            <div className="card">
              <h4>Empresa</h4>
              <div className="tabla-datos">
                <div><span>Nombre</span><strong>{empresa.nombre || 'Pendiente de configurar'}</strong></div>
                <div><span>NIT</span><strong>{empresa.nit || '—'}</strong></div>
                <div><span>Ciudad</span><strong>{empresa.ciudad || '—'}</strong></div>
                <div><span>Teléfono</span><strong>{empresa.telefono || '—'}</strong></div>
              </div>
              {auth.user.rol === 'dueno' && !empresa.nombre && (
                <p className="nota">Configura los datos de tu empresa en la sección <strong>Empresa</strong>.</p>
              )}
            </div>
          )}
          <div className="card card-quieto">
            <h4>Construcción por fases</h4>
            <p className="muted">
              Fase 1 (fundamentos, roles y seguridad) está en producción.
              Telegram, plantillas DOCX, catálogo de servicios, cotizaciones completas,
              proyectos, gastos, agenda, documentos, credenciales y EDÉN AI Core se
              activarán por fases — cada módulo aparece aquí cuando funcione de verdad.
            </p>
          </div>
        </>
      )}
    </div>
  )
}

function VistaEmpresa({ auth, empresa, alGuardar }) {
  const esDueno = auth.user.rol === 'dueno'
  const [form, setForm] = useState(empresa)
  const [msg, setMsg] = useState(null)
  const [guardando, setGuardando] = useState(false)

  useEffect(() => { setForm(empresa) }, [empresa])

  if (!form) return <div className="spinner" />

  const campo = clave => ({
    value: form[clave] || '',
    onChange: e => setForm({ ...form, [clave]: e.target.value }),
    disabled: !esDueno,
  })

  async function guardar(e) {
    e.preventDefault()
    setMsg(null)
    setGuardando(true)
    try {
      const datos = { ...form }
      delete datos.id
      delete datos.actualizado_en
      Object.keys(datos).forEach(k => { if (datos[k] === undefined) delete datos[k] })
      await apiFetch('/empresa', { method: 'PUT', body: datos, token: auth.token })
      setMsg({ tipo: 'ok', texto: 'Datos de la empresa guardados.' })
      alGuardar()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    } finally {
      setGuardando(false)
    }
  }

  return (
    <div>
      <h3 className="vista-titulo">Empresa</h3>
      <form onSubmit={guardar} className="card">
        <div className="form-grid">
          <div className="form-group"><label>Nombre o razón social</label><input {...campo('nombre')} maxLength={200} /></div>
          <div className="form-group"><label>NIT</label><input {...campo('nit')} maxLength={50} /></div>
          <div className="form-group"><label>Teléfono</label><input {...campo('telefono')} maxLength={50} /></div>
          <div className="form-group"><label>Correo</label><input {...campo('correo')} type="email" maxLength={120} /></div>
          <div className="form-group"><label>Ciudad</label><input {...campo('ciudad')} maxLength={100} /></div>
        </div>
        <div className="form-group"><label>Dirección</label><input {...campo('direccion')} maxLength={200} /></div>
        {msg && <div className={`alert ${msg.tipo === 'ok' ? 'alert-success' : 'alert-error'}`}>{msg.texto}</div>}
        {esDueno
          ? <button type="submit" className="btn btn-primary" disabled={guardando}>{guardando ? 'Guardando…' : 'Guardar cambios'}</button>
          : <p className="muted">Solo el dueño puede modificar la configuración de la empresa.</p>}
      </form>
    </div>
  )
}

function VistaUsuarios({ auth }) {
  const [usuarios, setUsuarios] = useState(null)
  const [msg, setMsg] = useState(null)
  const [nuevo, setNuevo] = useState({ username: '', password: '' })
  const [trabajando, setTrabajando] = useState(false)

  async function cargar() {
    try {
      setUsuarios(await apiFetch('/usuarios', { token: auth.token }))
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }
  useEffect(() => { cargar() }, [])

  async function crearAdmin(e) {
    e.preventDefault()
    setMsg(null)
    setTrabajando(true)
    try {
      await apiFetch('/usuarios', { method: 'POST', body: nuevo, token: auth.token })
      setNuevo({ username: '', password: '' })
      setMsg({ tipo: 'ok', texto: 'Administrador creado.' })
      await cargar()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    } finally {
      setTrabajando(false)
    }
  }

  async function cambiarEstado(u) {
    setMsg(null)
    try {
      await apiFetch(`/usuarios/${u.id}/estado?activo=${!u.is_active}`, { method: 'PUT', token: auth.token })
      await cargar()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }

  async function resetPassword(u) {
    const nueva = prompt(`Contraseña nueva para ${u.username} (mínimo 8 caracteres):`)
    if (nueva === null) return
    if (nueva.length < 8) {
      setMsg({ tipo: 'error', texto: 'La contraseña debe tener al menos 8 caracteres.' })
      return
    }
    setMsg(null)
    try {
      await apiFetch(`/usuarios/${u.id}/password`, { method: 'PUT', body: { password: nueva }, token: auth.token })
      setMsg({ tipo: 'ok', texto: `Contraseña restablecida para ${u.username}.` })
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }

  async function eliminar(u) {
    if (!window.confirm(`¿Eliminar definitivamente a ${u.username}?`)) return
    setMsg(null)
    try {
      await apiFetch(`/usuarios/${u.id}`, { method: 'DELETE', token: auth.token })
      await cargar()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }

  if (!usuarios) return msg ? <div className="alert alert-error">{msg.texto}</div> : <div className="spinner" />

  return (
    <div>
      <h3 className="vista-titulo">Usuarios</h3>
      {msg && <div className={`alert ${msg.tipo === 'ok' ? 'alert-success' : 'alert-error'}`}>{msg.texto}</div>}
      <form onSubmit={crearAdmin} className="card fila-form">
        <div className="form-group"><label>Usuario nuevo (administrador)</label>
          <input value={nuevo.username} onChange={e => setNuevo({ ...nuevo, username: e.target.value })} required minLength={3} placeholder="nombre.usuario" /></div>
        <div className="form-group"><label>Contraseña (mín. 8)</label>
          <input type="password" value={nuevo.password} onChange={e => setNuevo({ ...nuevo, password: e.target.value })} required minLength={8} /></div>
        <button type="submit" className="btn btn-primary" disabled={trabajando}>{trabajando ? 'Creando…' : 'Crear administrador'}</button>
      </form>
      <div className="card">
        <table className="table">
          <thead>
            <tr><th>Usuario</th><th>Rol</th><th>Estado</th><th>Creado</th><th>Acciones</th></tr>
          </thead>
          <tbody>
            {usuarios.map(u => (
              <tr key={u.id} className={u.is_active ? '' : 'fila-inactiva'}>
                <td>{u.username}{u.id === auth.user.id && <em> (tú)</em>}</td>
                <td><span className={`badge ${u.rol === 'dueno' ? 'badge-azul' : 'badge-violeta'}`}>{u.rol === 'dueno' ? 'Dueño' : 'Administrador'}</span></td>
                <td>{u.is_active ? 'Activo' : 'Inactivo'}</td>
                <td>{u.created_at ? u.created_at.slice(0, 10) : '—'}</td>
                <td className="acciones">
                  {u.rol !== 'dueno' && (
                    <>
                      <button type="button" className="btn btn-mini" onClick={() => cambiarEstado(u)}>{u.is_active ? 'Desactivar' : 'Activar'}</button>
                      <button type="button" className="btn btn-mini" onClick={() => resetPassword(u)}>Restablecer contraseña</button>
                      <button type="button" className="btn btn-mini btn-peligro" onClick={() => eliminar(u)}>Eliminar</button>
                    </>
                  )}
                  {u.rol === 'dueno' && <span className="muted">—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

const ROL_ETIQUETA = { dueno: 'Dueño', admin: 'Administrador' }

function VistaCuenta({ auth, alActualizar }) {
  const [p1, setP1] = useState('')
  const [p2, setP2] = useState('')
  const [msg, setMsg] = useState(null)
  const [guardando, setGuardando] = useState(false)

  async function guardar(e) {
    e.preventDefault()
    setMsg(null)
    if (p1 !== p2) { setMsg({ tipo: 'error', texto: 'Las contraseñas no coinciden.' }); return }
    setGuardando(true)
    try {
      await apiFetch('/mi/password', { method: 'PUT', body: { password: p1 }, token: auth.token })
      setMsg({ tipo: 'ok', texto: 'Contraseña actualizada.' })
      setP1(''); setP2('')
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    } finally {
      setGuardando(false)
    }
  }

  return (
    <div>
      <h3 className="vista-titulo">Mi cuenta</h3>
      <div className="card">
        <div className="tabla-datos">
          <div><span>Usuario</span><strong>{auth.user.username}</strong></div>
          <div><span>Rol</span><span className={`badge ${auth.user.rol === 'dueno' ? 'badge-azul' : 'badge-violeta'}`}>{ROL_ETIQUETA[auth.user.rol] || auth.user.rol}</span></div>
        </div>
        <form onSubmit={guardar}>
          <div className="form-grid">
            <div className="form-group"><label>Contraseña nueva (mín. 8)</label>
              <input type="password" value={p1} onChange={e => setP1(e.target.value)} required minLength={8} autoComplete="new-password" /></div>
            <div className="form-group"><label>Confirmar</label>
              <input type="password" value={p2} onChange={e => setP2(e.target.value)} required minLength={8} autoComplete="new-password" /></div>
          </div>
          {msg && <div className={`alert ${msg.tipo === 'ok' ? 'alert-success' : 'alert-error'}`}>{msg.texto}</div>}
          <button type="submit" className="btn btn-primary" disabled={guardando}>{guardando ? 'Guardando…' : 'Cambiar contraseña'}</button>
        </form>
      </div>
    </div>
  )
}

// ============================================================
// Vista Telegram
// ============================================================
function VistaTelegram({ auth }) {
  const esDueno = auth.user.rol === 'dueno'
  const [estado, setEstado] = useState(null)
  const [cuentas, setCuentas] = useState([])
  const [mensajes, setMensajes] = useState([])
  const [msg, setMsg] = useState(null)
  const [tokenInput, setTokenInput] = useState('')
  const [modoInput, setModoInput] = useState('polling')
  const [webhookUrl, setWebhookUrl] = useState('')
  const [codigo, setCodigo] = useState(null)
  const [notifi, setNotifi] = useState({ cuenta_id: '', texto: '' })
  const [trabajo, setTrabajo] = useState(false)

  async function cargarTodo() {
    try {
      const est = await apiFetch('/telegram/estado', { token: auth.token })
      setEstado(est)
      setModoInput(est.bot.modo || 'polling')
      setWebhookUrl(est.bot.webhook_url || '')
      if (esDueno) {
        setCuentas(await apiFetch('/telegram/cuentas', { token: auth.token }))
      }
      setMensajes(await apiFetch('/telegram/mensajes?limit=15', { token: auth.token }))
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }
  useEffect(() => { cargarTodo() }, [])

  async function guardarToken(e) {
    e.preventDefault()
    setMsg(null)
    setTrabajo(true)
    try {
      const nueva = await apiFetch('/telegram/config', {
        method: 'PUT', body: { bot_token: tokenInput, modo: modoInput }, token: auth.token,
      })
      setTokenInput('')
      setMsg({ tipo: 'ok', texto: `Token validado y cifrado. Bot: ${nueva.bot_username}` })
      await cargarTodo()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    } finally {
      setTrabajo(false)
    }
  }

  async function accion(nombre, cuerpo = null) {
    setMsg(null)
    setTrabajo(true)
    try {
      const r = await apiFetch(`/telegram/${nombre}`, { method: 'POST', body: cuerpo || {}, token: auth.token })
      setMsg({ tipo: 'ok', texto: r.estado_texto ? `Bot: ${r.estado_texto}` : 'Hecho.' })
      await cargarTodo()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    } finally {
      setTrabajo(false)
    }
  }

  async function generarCodigo() {
    setMsg(null)
    try {
      setCodigo(await apiFetch('/telegram/codigo', { token: auth.token }))
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }

  async function desvincular(id) {
    if (!window.confirm('¿Desvincular esta cuenta de Telegram?')) return
    try {
      await apiFetch(`/telegram/cuentas/${id}`, { method: 'DELETE', token: auth.token })
      await cargarTodo()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }

  async function enviarNotificacion(e) {
    e.preventDefault()
    setMsg(null)
    try {
      const r = await apiFetch('/telegram/notificar', {
        method: 'POST', body: { cuenta_id: Number(notifi.cuenta_id), texto: notifi.texto }, token: auth.token,
      })
      setMsg({ tipo: r.ok ? 'ok' : 'error', texto: r.ok ? 'Notificación enviada.' : 'Telegram no entregó el mensaje.' })
      await cargarTodo()
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.message })
    }
  }

  if (!estado) return msg ? <div className="alert alert-error">{msg.texto}</div> : <div className="spinner" />
  const bot = estado.bot

  return (
    <div>
      <h3 className="vista-titulo">Telegram</h3>
      {msg && <div className={`alert ${msg.tipo === 'ok' ? 'alert-success' : 'alert-error'}`}>{msg.texto}</div>}

      <div className="grid-cards">
        <div className="stat-card">
          <span className="stat-valor">{bot.activo ? 'En línea' : 'Apagado'}</span>
          <span className="stat-etiqueta">Estado del bot</span>
        </div>
        <div className="stat-card">
          <span className="stat-valor">{bot.bot_username || '—'}</span>
          <span className="stat-etiqueta">Bot configurado</span>
        </div>
        <div className="stat-card">
          <span className="stat-valor">{estado.mi_cuenta.vinculada ? 'Vinculado' : 'Sin vincular'}</span>
          <span className="stat-etiqueta">Tu Telegram {estado.mi_cuenta.chat_id ? `(${estado.mi_cuenta.chat_id})` : ''}</span>
        </div>
      </div>

      <div className="card">
        <h4>Vincular tu cuenta</h4>
        {!estado.mi_cuenta.vinculada ? (
          <>
            <p className="muted">Genera un código temporal de un solo uso (10 minutos) y envíalo al bot por Telegram: <code>/vincular CODIGO</code></p>
            {codigo ? (
              <p className="codigo-grande">{codigo.codigo} <em>expira en {codigo.expira_en_minutos} minutos</em></p>
            ) : (
              <button type="button" className="btn btn-primary" onClick={generarCodigo}>Generar código</button>
            )}
          </>
        ) : (
          <button type="button" className="btn btn-mini" onClick={() => desvincularConfirmado()}>Desvincular mi chat</button>
        )}
      </div>

      {esDueno && (
        <div className="card">
          <h4>Configuración del bot (solo dueño)</h4>
          <form onSubmit={guardarToken} className="fila-form">
            <div className="form-group">
              <label>Token de @BotFather (se guarda cifrado; nunca se vuelve a mostrar)</label>
              <input type="password" value={tokenInput} onChange={e => setTokenInput(e.target.value)} placeholder="123456:ABC-DEF..." required />
            </div>
            <div className="form-group">
              <label>Modo</label>
              <select value={modoInput} onChange={e => setModoInput(e.target.value)}>
                <option value="polling">Long-polling (desarrollo)</option>
                <option value="webhook">Webhook (producción HTTPS)</option>
              </select>
            </div>
            <button type="submit" className="btn btn-primary" disabled={trabajo}>Guardar y validar</button>
          </form>
          {modoInput === 'webhook' && (
            <div className="form-group">
              <label>URL pública del webhook</label>
              <input value={webhookUrl} onChange={e => setWebhookUrl(e.target.value)} placeholder="https://tu-dominio/api/telegram/webhook" />
            </div>
          )}
          <div className="fila-acciones">
            <button type="button" className="btn" onClick={() => accion('probar')} disabled={trabajo}>Probar conexión</button>
            {bot.activo
              ? <button type="button" className="btn btn-peligro" onClick={() => accion('desactivar')} disabled={trabajo}>Desactivar bot</button>
              : <button type="button" className="btn btn-primary" onClick={() => accion('activar', modoInput === 'webhook' ? { webhook_url: webhookUrl || null } : {})} disabled={trabajo}>Activar bot</button>}
          </div>
          <p className="muted">Última verificación: {bot.ultima_verificacion ? bot.ultima_verificacion.replace('T', ' ').slice(0, 19) : '—'}</p>
        </div>
      )}

      {esDueno && (
        <div className="card">
          <h4>Cuentas vinculadas</h4>
          {cuentas.length === 0 ? <p className="muted">Aún no hay cuentas vinculadas.</p> : (
            <table className="table">
              <thead><tr><th>Telegram</th><th>Usuario del panel</th><th>Desde</th><th></th></tr></thead>
              <tbody>
                {cuentas.map(c => (
                  <tr key={c.id}>
                    <td>{c.telegram_username ? '@' + c.telegram_username : c.telegram_id}</td>
                    <td>{c.usuario}</td>
                    <td>{c.vinculado_en ? c.vinculado_en.slice(0, 10) : '—'}</td>
                    <td className="acciones">
                      {c.activo
                        ? <button type="button" className="btn btn-mini btn-peligro" onClick={() => desvincular(c.id)}>Desvincular</button>
                        : <em className="muted">inactiva</em>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <form onSubmit={enviarNotificacion} className="fila-form" style={{ marginTop: '1rem' }}>
            <div className="form-group">
              <label>Enviar mensaje a una cuenta</label>
              <select value={notifi.cuenta_id} onChange={e => setNotifi({ ...notifi, cuenta_id: e.target.value })} required>
                <option value="">Elegir cuenta…</option>
                {cuentas.filter(c => c.activo).map(c => (
                  <option key={c.id} value={c.id}>{c.usuario} ({c.telegram_id})</option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label>Texto</label>
              <input value={notifi.texto} onChange={e => setNotifi({ ...notifi, texto: e.target.value })} required maxLength={3800} />
            </div>
            <button type="submit" className="btn btn-primary" disabled={trabajo}>Enviar</button>
          </form>
        </div>
      )}

      <div className="card">
        <h4>Últimos mensajes</h4>
        {mensajes.length === 0 ? <p className="muted">Sin mensajes todavía.</p> : (
          <table className="table">
            <thead><tr><th>Dirección</th><th>Tipo</th><th>Contenido</th><th>Fecha</th><th></th></tr></thead>
            <tbody>
              {mensajes.map(m => (
                <tr key={m.id}>
                  <td>{m.direccion === 'entrada' ? '→ EDÉN' : 'EDÉN →'}</td>
                  <td>{m.tipo}</td>
                  <td className="celda-texto">{m.archivo_nombre ? `📎 ${m.archivo_nombre}` : (m.texto || '—')}</td>
                  <td>{m.creado_en ? m.creado_en.replace('T', ' ').slice(0, 19) : '—'}</td>
                  <td>{m.entregado ? '' : <span className="badge badge-error">falló</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )

  function desvincularConfirmado() {
    /* la desvinculación propia se hace sobre la cuenta del usuario; el backend
       requiere el id: lo obtenemos del listado si es dueño, si no usamos su estado */
    apiFetch('/telegram/cuentas', { token: auth.token })
      .then(async lista => {
        const mia = lista.find(c => c.activo) || (lista.length === 1 ? lista[0] : null)
        if (!mia) throw new Error('No hay vinculación activa que desvincular')
        await apiFetch(`/telegram/cuentas/${mia.id}`, { method: 'DELETE', token: auth.token })
        await cargarTodo()
      })
      .catch(err => setMsg({ tipo: 'error', texto: err.message }))
  }
}

// ============================================================
// Panel (dashboard con navegación de módulos)
// ============================================================
function Dashboard({ auth }) {
  const [vista, setVista] = useState('resumen')
  const [empresa, setEmpresa] = useState(null)

  async function cargarEmpresa() {
    try {
      setEmpresa(await apiFetch('/empresa', { token: auth.token }))
    } catch { /* la vista de resumen muestra su propio error */ }
  }
  useEffect(() => { cargarEmpresa() }, [])

  const esDueno = auth.user.rol === 'dueno'
   const items = [
    { id: 'resumen', nombre: 'Resumen' },
    { id: 'empresa', nombre: 'Empresa' },
    { id: 'telegram', nombre: 'Telegram' },
    { id: 'cuenta', nombre: 'Mi cuenta' },
    ...(esDueno ? [{ id: 'usuarios', nombre: 'Usuarios' }] : []),
  ]

  return (
    <div className="panel">
      <aside className="sidebar">
        <div className="sidebar-marca">
          <span className="auth-logo-mark">E</span>
          <strong>EDÉN</strong>
        </div>
        <nav>
          {items.map(t => (
            <button key={t.id} type="button" onClick={() => setVista(t.id)}
              className={`nav-item ${vista === t.id ? 'activo' : ''}`}>
              {t.nombre}
            </button>
          ))}
        </nav>
        <div className="sidebar-pie">
          <span className="badge badge-azul">{ROL_ETIQUETA[auth.user.rol]}</span>
          <span className="muted">{auth.user.username}</span>
          <button type="button" className="btn btn-mini" onClick={auth.logout}>Cerrar sesión</button>
        </div>
      </aside>
      <main className="panel-main">
        {vista === 'resumen' && <VistaResumen auth={auth} />}
        {vista === 'empresa' && <VistaEmpresa alGuardar={cargarEmpresa} auth={auth} empresa={empresa} />}
        {vista === 'telegram' && <VistaTelegram auth={auth} />}
        {vista === 'cuenta' && <VistaCuenta auth={auth} />}
        {vista === 'usuarios' && <VistaUsuarios auth={auth} />}
      </main>
    </div>
  )
}

// ============================================================
// Página principal
// ============================================================
export default function App() {
  const [user, setUser] = useState(null)
  const [token, setToken] = useState(null)
  const [loading, setLoading] = useState(true)

  function getToken() {
    return localStorage.getItem('token')
  }

  async function login(username, password) {
    const data = await apiFetch('/auth/login', { method: 'POST', form: { username, password } })
    localStorage.setItem('token', data.access_token)
    setToken(data.access_token)
    await fetchUser(data.access_token)
  }

  function logout() {
    localStorage.removeItem('token')
    setToken(null)
    setUser(null)
  }

  async function fetchUser(tk) {
    const tokenUsado = tk || getToken()
    if (!tokenUsado) { setLoading(false); return }
    try {
      const me = await apiFetch('/auth/me', { token: tokenUsado })
      setUser(me)
      setToken(tokenUsado)
    } catch {
      localStorage.removeItem('token')
      setUser(null)
      setToken(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchUser() }, [])

  const authContextValue = { user, token, login, logout }

  if (loading) {
    return <div className="cargando"><div className="spinner" /></div>
  }

  return (
    <AuthContext.Provider value={authContextValue}>
      <Routes>
        <Route path="/" element={<PrivateRoute><Dashboard auth={{ ...authContextValue }} /></PrivateRoute>} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthContext.Provider>
  )
}
