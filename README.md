# EDÉN — Asistente Empresarial Inteligente para Gestión Integral

Este proyecto es una aplicación full-stack para la gestión integral de empresas de instalación y servicios técnicos. Combina un frontend SPA en React 18 con un backend API en FastAPI, autenticación JWT, persistencia en PostgreSQL (con fallback a SQLite) y despliegue en contenedores Docker coordinados con docker-compose para Dokploy.

---

## Contenido del repositorio

- **api/**: Código backend FastAPI con autenticación, CRUD y persistencia.
- **src/**: Código frontend React 18 con rutas, login/registro y guardia de rutas.
- **docker-compose.yml**: Orquestación de servicios db, api y web.
- **web.Dockerfile**: Dockerfile multi-stage para frontend React + nginx.
- **api/Dockerfile**: Dockerfile para backend FastAPI.
- **nginx.conf**: Configuración nginx para servir SPA y proxy a API.
- **package.json** y **vite.config.js**: Configuración frontend.
- **README.md**: Esta documentación.

---

## Requisitos previos

- Docker y docker-compose instalados en su sistema.
- Acceso a terminal / consola.
- Para desarrollo local: Node.js 18+ y npm 9+.

---

## Uso local (desarrollo y pruebas)

### 1. Clonar el repositorio

```bash
git clone <url-del-repositorio>
cd <nombre-del-repositorio>
```

### 2. Backend: instalar dependencias y ejecutar localmente (opcional)

```bash
cd api
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

La API estará disponible en: http://localhost:8000/api

### 3. Frontend: instalar dependencias y ejecutar localmente (opcional)

```bash
cd ../
npm install
npm run dev
```

La SPA React estará disponible en: http://localhost:5173

### 4. Ejecutar con Docker Compose (recomendado)

Desde la raíz del proyecto:

```bash
docker-compose up --build
```

Esto levantará tres servicios:

- **db**: PostgreSQL en el puerto 5432 interno.
- **api**: Backend FastAPI en http://localhost:8000/api
- **web**: Frontend React servido por nginx en http://localhost:8080

La aplicación completa estará accesible en http://localhost:8080

---

## Usuarios de prueba

Para facilitar pruebas, puede usar estas credenciales de usuario precreadas:

| Usuario  | Contraseña | Rol          |
|----------|------------|--------------|
| admin    | admin123   | Administrador|
| operador | oper123    | Operador     |
| tecnico  | tecn123    | Técnico      |

---

## Autenticación

- El frontend presenta pantallas de login y registro.
- El backend usa JWT para autenticación.
- El token JWT se guarda en `localStorage` y se envía en cada petición API en el header:

```
Authorization: Bearer <token>
```

- Las rutas protegidas requieren token válido; las rutas `/api/auth/*` y `/api/health` son públicas.

---

## Rutas API principales

| Ruta                | Método | Descripción                          | Autenticación |
|---------------------|--------|------------------------------------|---------------|
| `/api/auth/register` | POST   | Registrar nuevo usuario             | No            |
| `/api/auth/login`    | POST   | Login y obtención de token JWT      | No            |
| `/api/auth/me`       | GET    | Obtener datos del usuario logueado | Sí            |
| `/api/health`        | GET    | Estado de salud del backend         | No            |
| `/api/...`           | CRUD   | Rutas protegidas para gestión       | Sí            |

---

## Construcción y despliegue para Dokploy

### 1. Construir imágenes Docker

```bash
docker-compose build
```

### 2. Levantar servicios en Dokploy

- Suba las imágenes construidas a su registro Docker (Docker Hub, GitHub Container Registry, etc.).
- Configure Dokploy para desplegar con el archivo `docker-compose.yml`.
- Asigne el dominio o subdominio deseado al puerto **8080** del servicio `web` para que la SPA sea accesible públicamente.

### 3. Configuración de variables de entorno

En Dokploy, configure las siguientes variables para el servicio `api`:

- `AUTH_SECRET`: Clave secreta para firmar JWT (cadena segura y privada).
- `DATABASE_URL`: URL de conexión a base de datos PostgreSQL, ejemplo:

```
postgresql+psycopg://studio:studio@db:5432/producto
```

Si PostgreSQL no está disponible, el backend usará SQLite local `./app.db` como fallback.

---

## Notas importantes

- El frontend siempre consume la API bajo el prefijo `/api`.
- El servidor nginx sirve la SPA y redirige `/api` al backend.
- El backend FastAPI monta todas sus rutas bajo `/api`.
- El login y registro envían datos en formato `application/x-www-form-urlencoded`.
- El proyecto está preparado para producción con Docker y Dokploy.
- Para desarrollo, puede usar SQLite local sin necesidad de PostgreSQL.

---

## Contacto y soporte

Para dudas, reportes de errores o sugerencias, contacte con el equipo de YERUZZA Studio.

---

¡Gracias por usar EDÉN, su asistente empresarial inteligente!