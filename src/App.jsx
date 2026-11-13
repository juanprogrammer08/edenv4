import React, { useState, useEffect, createContext, useContext } from 'react'
import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom'

// Contexto de autenticación para compartir estado y funciones
const AuthContext = createContext(null)

// Hook para usar el contexto de autenticación
export function useAuth() {
  return useContext(AuthContext)
}

// Componente que protege rutas privadas, redirigiendo a login si no hay token válido
function PrivateRoute({ children }) {
  const auth = useAuth()
  const location = useLocation()

  if (!auth.user) {
    // Redirige a login guardando la ruta original para volver luego
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  return children
}

// Página de Login
function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const auth = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = location.state?.from?.pathname || '/'

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    try {
      await auth.login(username, password)
      navigate(from, { replace: true })
    } catch (err) {
      setError('Credenciales incorrectas')
    }
  }

  return (
    <div className="auth-container">
      <h2>Iniciar sesión</h2>
      <form onSubmit={handleSubmit} className="auth-form">
        <label>
          Usuario
          <input
            type="text"
            value={username}
            onChange={e => setUsername(e.target.value)}
            required
            autoComplete="username"
          />
        </label>
        <label>
          Contraseña
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            required
            autoComplete="current-password"
          />
        </label>
        {error && <p className="error">{error}</p>}
        <button type="submit">Entrar</button>
      </form>
      <p>
        ¿No tienes cuenta? <a href="/register">Regístrate</a>
      </p>
    </div>
  )
}

// Página de Registro
function RegisterPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(false)
  const navigate = useNavigate()

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    setSuccess(false)
    try {
      const params = new URLSearchParams()
      params.append('username', username)
      params.append('password', password)

      const res = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: params.toString(),
      })

      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.detail || 'Error en registro')
      }

      setSuccess(true)
      setTimeout(() => navigate('/login'), 1500)
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="auth-container">
      <h2>Registro</h2>
      <form onSubmit={handleSubmit} className="auth-form">
        <label>
          Usuario
          <input
            type="text"
            value={username}
            onChange={e => setUsername(e.target.value)}
            required
            autoComplete="username"
          />
        </label>
        <label>
          Contraseña
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            required
            autoComplete="new-password"
          />
        </label>
        {error && <p className="error">{error}</p>}
        {success && <p className="success">Registro exitoso. Redirigiendo a login...</p>}
        <button type="submit">Registrar</button>
      </form>
      <p>
        ¿Ya tienes cuenta? <a href="/login">Inicia sesión</a>
      </p>
    </div>
  )
}

// Página principal protegida (ejemplo dashboard)
function Dashboard() {
  const auth = useAuth()

  async function handleLogout() {
    auth.logout()
  }

  return (
    <div className="dashboard-container">
      <header>
        <h1>Bienvenido, {auth.user?.username || 'Usuario'}</h1>
        <button onClick={handleLogout}>Cerrar sesión</button>
      </header>
      <main>
        <p>Esta es la aplicación EDÉN - Asistente Empresarial Inteligente.</p>
        {/* Aquí se pueden agregar más componentes y rutas internas */}
      </main>
    </div>
  )
}

// Componente principal App con rutas y contexto de autenticación
export default function App() {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  // Función para obtener el token JWT desde localStorage
  function getToken() {
    return localStorage.getItem('token')
  }

  // Función para guardar token y cargar usuario
  async function login(username, password) {
    const params = new URLSearchParams()
    params.append('username', username)
    params.append('password', password)

    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: params.toString(),
    })

    if (!res.ok) {
      throw new Error('Login fallido')
    }

    const data = await res.json()
    localStorage.setItem('token', data.access_token)
    await fetchUser()
  }

  // Función para eliminar token y usuario
  function logout() {
    localStorage.removeItem('token')
    setUser(null)
  }

  // Función para obtener datos del usuario actual con token
  async function fetchUser() {
    const token = getToken()
    if (!token) {
      setUser(null)
      setLoading(false)
      return
    }

    try {
      const res = await fetch('/api/auth/me', {
        headers: { Authorization: `Bearer ${token}` },
      })

      if (!res.ok) {
        throw new Error('Token inválido')
      }

      const data = await res.json()
      setUser(data)
    } catch {
      localStorage.removeItem('token')
      setUser(null)
    } finally {
      setLoading(false)
    }
  }

  // Al montar el componente, intenta cargar usuario si hay token
  useEffect(() => {
    fetchUser()
  }, [])

  // Contexto que se pasa a los hijos
  const authContextValue = {
    user,
    login,
    logout,
  }

  if (loading) {
    return <div className="loading">Cargando...</div>
  }

  return (
    <AuthContext.Provider value={authContextValue}>
      <Routes>
        <Route
          path="/"
          element={
            <PrivateRoute>
              <Dashboard />
            </PrivateRoute>
          }
        />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        {/* Ruta comodín para redirigir a raíz */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthContext.Provider>
  )
}