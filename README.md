# YERUZZA Empresarial Asist — Plataforma Empresarial Inteligente

(Producto renombrado por decisión del propietario: antes "EDÉN".)

Plataforma para empresas de instalaciones técnicas, servicios eléctricos, redes
y mantenimiento: panel web + bot de Telegram + documentos con las plantillas
propias de la empresa. Se desarrolla por fases (ver "Hoja de ruta" al final).

## Arquitectura

- **api/**: backend FastAPI (SQLAlchemy 2.x sincrónico, JWT, bcrypt).
  PostgreSQL en producción; fallback honesto a SQLite para desarrollo local.
- **src/**: SPA React 18 + react-router-dom.
- **Docker Compose**: db (PostgreSQL 16) + api + web (nginx sirve la SPA y
  invierte /api al api).

## Ejecución local (desarrollo)

    cd api
    python -m venv venv          # una sola vez
    venv\Scripts\activate        # Windows
    pip install -r requirements.txt
    uvicorn app.main:app --port 8000

    # en otra terminal, en la raíz:
    npm install                 # una sola vez
    npm run dev                 # SPA en http://localhost:3000 (proxy /api → 8000)

## Pruebas

    cd api
    DATABASE_URL=sqlite:///./test_fase1.db python -m uvicorn app.main:app --port 8421
    python test_fase1.py        # 26 pruebas E2E de la fase 1
    DATABASE_URL=sqlite:///./test_fase2.db python -m uvicorn app.main:app --port 8422
    python test_fase2.py        # 26 pruebas E2E de la fase 2

## Seguridad (FASE 1)

- Roles: **dueño** (acceso total) y **administrador** (operativo restringido).
- Registro cerrado: el primer registro crea al dueño; después queda bloqueado y
  solo el dueño crea administradores desde el panel.
- El dueño crea/desactiva/elimina/establece contraseñas de administradores.
- Auditoría en la tabla `auditoria` (login ok/fallido, gestión de usuarios,
  cambios de empresa, rate limit). Consulta: `GET /api/auditoria` (solo dueño).
- Rate limit de login (6 intentos / 300 s por IP, configurable por env).
- JWT HS256 + bcrypt. El token incluye el rol.
- El admin no puede: listar usuarios, consultar auditoría, editar empresa,
  crear usuarios, ni tocar al dueño.
- Contraseñas de usuario mínimo 8 caracteres.

## FASE 2 — Telegram (hecha, pendiente del token real del dueño)

- Config del bot en el panel (solo dueño): token **cifrado con Fernet** y
  validado contra getMe al guardarlo — un token falso se rechaza de una vez.
  El token nunca sale del backend ni se vuelve a mostrar.
- Long-polling (desarrollo) o **webhook HTTPS con secreto**
  `X-Telegram-Bot-Api-Secret-Token` (producción); sin secreto → 403.
- Vinculación segura: código temporal de 6 dígitos de un solo uso (10 min,
  solo hasheado en BD), un chat de Telegram queda ligado a un usuario del
  panel. Los no vinculados solo reciben su Telegram ID e instrucciones.
- Comandos: /start, /vincular CODIGO, /estado, /desvincular.
- Recepción de fotos y documentos (máx 20 MB) guardados en `MEDIA_DIR/telegram`.
- Notificaciones manuales del dueño a cuentas vinculadas.
- Historial completo de mensajes (entradas, salidas, fallos de envío).
- Auditoría Telegram: códigos, vinculación, webhook rechazado, activar/desactivar,
  notificaciones. El admin no ve la config del bot.

## FASE 3 — Plantillas de Cotización (hecha)

- Panel "Plantillas": subida de **DOCX** (formato principal) o registro de
  **HTML** (pegado), nombre/descripción, detección automática de variables
  `{{...}}`, previsualización con datos de ejemplo, versiones con historial,
  predeterminada única, activar/desactivar, eliminar (si tiene documentos se
  desactiva para conservar el historial), descarga del original.
- Solo el dueño administra plantillas; todos los usuarios pueden generar.
- Motor de variables: 22 variables de empresa/cliente/totales + `{{tabla_servicios}}`
  (múltiples filas: ítem, descripción, cantidad, unidad, precio unitario, total,
  más filas de subtotal/descuento/IVA/TOTAL).
- **Conservación del diseño**: en DOCX se reemplaza el texto conservando el
  formato original (párrafos, tablas, encabezados y pies de página); si
  `{{tabla_servicios}}` está dentro de una tabla, su fila se clona con el
  formato de la plantilla; si está en un párrafo, se inserta una tabla nueva.
- Totales en formato colombiano ($1.287.000) calculados del formulario:
  subtotal = Σ items, descuento %, IVA % sobre la base, total.
- Documentos: cada generación/amarrado guarda plantilla + **versión** +
  datos completos (JSON); actualizar una plantilla nunca altera históricos.
- PDF: DOCX→PDF con **LibreOffice headless** si está disponible en el servidor
  (`SOFFICE_PATH` o en PATH; instalar `libreoffice` en producción); sin él se
  entrega el .docx lleno con mensaje honesto. HTML→PDF con WeasyPrint (opcional).
- Telegram envía documentos desde FASE 5 (AI Core); el envío está cableado
  en `_enviar`.

## FASE 4 — Comercial (hecha)

- **Catálogo de servicios** (`app/comercial.py`): código, nombre, categoría,
  unidad, **precio de venta, costo de materiales y mano de obra, tiempo
  estimado**, margen calculado en vivo. Solo el dueño lo administra; todos
  consultan. Un servicio usado en cotizaciones se desactiva en vez de
  borrarse (el historial queda intacto).
- **Clientes**: registros comerciales SIN usuarios; admin y dueño los manejan.
  Historial comercial por cliente (sus cotizaciones) inline en el panel.
- **Cotizaciones reales**: numeración automática `COT-2026-#####`, ítems con
  **precio/costo snapshot** del catálogo (mutar el catálogo no cambia
  cotizaciones viejas), cálculo central subtotal/descuento/IVA/costo/utilidad/
  margen, estados (borrador, pendiente, enviada, aprobada, rechazada, vencida,
  convertida), duplicar, editar (solo no-aprobadas), **PDF con la plantilla
  predeterminada** (FASE 3) y conversión aprobada→proyecto.
- **Límites del dueño** (`config_comercial`): descuento máximo (20% por
  defecto) y margen mínimo (15% por defecto); los administradores no pueden
  guardar cotizaciones que los violen; el dueño puede (son sus reglas).
- **Indicadores** (`/indicadores`): conteos y valores reales — cotizaciones,
  aprobadas, valor cotizado/aprobado, proyectos activos/finalizados, gastos,
  clientes, servicios más solicitados. El Resumen del panel los consume.
- Migración `002_cotizaciones_comercial`: columnas nuevas + numeración
  retroactiva + remapeo aceptada→aprobada (no destructiva).

## FASE 5 — Núcleo de IA "Yeruzzza" (hecha, pendiente de la clave de proveedor)

- **Configuración por panel (solo dueño)**: API base compatible OpenAI
  (OpenAI directo u OmniRoute), modelo y clave — guardada **cifrada con
  Fernet**, validable con "Probar conexión"; interruptor Encender/Apagar.
- **Asistente Principal + agentes**: el núcleo enruta cada solicitud a una
  especialidad (comercial, financiero, proyectos, administrativo, seguridad)
  con clasificación del proveedor y respaldo por palabras clave; cada
  respuesta queda amarrada al agente en el historial (ia_mensajes).
- **Herramientas reales sobre la BD**: catálogo de precios, clientes,
  cotizaciones, indicadores, proyectos — la IA NO inventa datos, los pide.
- **Autorización humana obligatoria**: toda escritura (crear cliente,
  crear cotización, generar PDF) se convierte en ACCIÓN PENDIENTE que el
  usuario confirma (`/confirmar N` en Telegram o botón en el panel) o
  cancela. Los límites del dueño (descuento/margen) aplican también a la IA.
- **Telegram**: el texto libre de las cuentas vinculadas va directo al
  núcleo; `/confirmar N` y `/cancelar N`; si la acción generó documento, el
  bot lo envía al chat.
- Degradación honesta: sin proveedor o sin clave, responde que falta
  configuración — nunca simula inteligencia.
- Fallback por variables: IA_BASE_URL / IA_MODEL / IA_API_KEY (el panel
  tiene prioridad).

## FASE 6 — Operaciones (hecha)

- **Proyectos completos** (`app/operaciones.py`): código `PRY-#####`, cliente,
  presupuesto, fechas, avance, estado (activo/pausado/finalizado/cancelado);
  nacen de la conversión de cotizaciones aprobadas o se crean directos;
  **comparación presupuesto vs ejecutado** con desglose por categoría y saldo
  (rojo al quedarse sin saldo).
- **Gastos y compras**: tipo (gasto|compra) y categoría (materiales, mano de
  obra, herramientas, transporte, servicios, otro); siempre ligados a un
  proyecto; editables; el admin y el dueño registran.
- **Agenda**: visitas técnicas, reuniones, entregas, vencimientos,
  seguimientos; ligados a cliente/proyecto; **vigilante de fondo cada 5 min
  notifica por Telegram a las cuentas vinculadas 24 h antes** (una vez),
  cuando el bot está activo.
- **Gestor documental**: repositorio `/media/archivos` con categorías
  (contrato, plano, factura, comprobante, foto, informe, técnico, cliente) y
  vínculos a cliente/proyecto/cotización; descarga autenticada; eliminar
  solo dueño (borra también el fichero).
- **Bóveda de credenciales (solo dueño)**: plataforma, URL, usuario y
  contraseña **cifrada con Fernet**; el listado JAMÁS la devuelve;
  "Revelar" la muestra al dueño una vez y **queda auditado**
  (`credencial_revelada`). Si se rota AUTH_SECRET hay que volver a guardarla.
- Migración `003_operaciones` (proyectos completos con backfill de código/
  presupuesto/cliente desde la cotización; gastos con tipo/categoría).
- CRUD viejo de proyectos/gastos retirado de `main.py` (vive completo en
  `operaciones.py`).

## Variables de entorno

| Variable | Default | Uso |
|---|---|---|
| AUTH_SECRET | — (requerida en producción) | clave firma JWT + cifrado del token del bot |
| DATABASE_URL | sqlite:///./app.db | cadena PostgreSQL |
| CORS_ORIGINS | * | lista separada por comas en producción |
| LOGIN_RATE_LIMIT / LOGIN_WINDOW_SECONDS | 6 / 300 | límite intentos login |
| MEDIA_DIR | ./media | guardado de adjuntos |
| PUBLIC_BASE_URL | — | base pública del API para registro del webhook |
| TG_CODE_TTL_MINUTOS / TG_MAX_ADJUNTO_MB / TG_POLL_SECONDS | 10 / 20 / 25 | Telegram |
| SOFFICE_PATH | — | ruta de soffice.exe para DOCX→PDF (o LibreOffice en PATH) |

## Rutas API

| Ruta | Métodos | Acceso |
|---|---|---|
| /auth/register | POST | público (solo para crear al dueño inicial) |
| /auth/login | POST | público (rate limit) |
| /auth/me | GET | autenticado |
| /mi/password | PUT | autenticado (contraseña propia) |
| /usuarios | GET/POST | solo dueño |
| /usuarios/{id}/estado | PUT | solo dueño (no aplica al dueño) |
| /usuarios/{id}/password | PUT | solo dueño (no aplica al dueño) |
| /usuarios/{id} | DELETE | solo dueño (nunca el dueño) |
| /empresa | GET | autenticado |
| /empresa | PUT | solo dueño |
| /auditoria | GET | solo dueño |
| /telegram/... | GET/POST/PUT/DELETE | estado y código (autenticado); config/cuentas/notificar (solo dueño) |
| /cotizaciones, /proyectos, /gastos, /bitacoras | CRUD | autenticado |

## Despliegue en Dokploy

1. Repo → **Dokploy** (proyecto Compose) apuntando a este repositorio.
2. Variables de entorno (servicio **api**):
   - `AUTH_SECRET` (obligatoria, larga y aleatoria — también cifra el token del
     bot, la clave IA y las contraseñas de la bóveda: **si se rota, hay que
     volver a guardar token/clave/contraseñas**)
   - `CORS_ORIGINS=https://tu-dominio.com`
   - `PUBLIC_BASE_URL=https://tu-dominio.com` (para el webhook de Telegram)
3. Dominio de Dokploy → puerto **8080 del servicio web** (nginx sirve la SPA y
   hace proxy `/api → api:8000`).
4. **PDF**: la imagen del API ya instala LibreOffice (`SOFFICE_PATH` por
   defecto `/usr/bin/soffice`): las plantillas DOCX se convierten a PDF
   conservando el diseño; el build es más pesado, es el costo honesto del PDF.
5. **Volúmenes**: `pgdata` (Postgres) y `media` (adjuntos, plantillas,
   documentos y archivos del repositorio) ya están en el compose.
6. Al arrancar: la BD se migra sola (001→003) y el **primer registro** crea al
   dueño. Después: token de @BotFather en **Telegram**; credenciales de
   **OmniRoute** en **Yeruzzza AI**; las plantillas DOCX propias en
   **Plantillas**; y cambiar la contraseña temporal del dueño.

### Verificación post-despliegue

    GET /api/health  →  {"status":"ok","version":"1.7.0","db":"postgresql",...}

La suite `api/test_integral.py` reproduce la historia completa (dueño →
plantilla → catálogo → cliente → cotización → PDF → proyecto → gastos →
agenda → documentos → bóveda → IA → reportes → auditoría) contra una BD
temporal:

    DATABASE_URL=sqlite:///./test_integral.db uvicorn app.main:app --port 8427
    python test_integral.py        # 22 comprobaciones OK

## Hoja de ruta (spec maestra)

1. **FASE 1 — Fundamentos:** roles, empresa, seguridad, auditoría. ✅ 1.1.0
2. **FASE 2 — Telegram:** bot, vinculación, webhooks, adjuntos, notificaciones. ✅ 1.2.0
3. **FASE 3 — Plantillas:** DOCX/HTML + variables + versiones + documentos. ✅ 1.3.0
4. **FASE 4 — Comercial:** catálogo, clientes, cotizaciones con ítems, límites. ✅ 1.4.0
5. **FASE 5 — IA:** núcleo Yeruzzza, agentes, herramientas reales, autorización humana. ✅ 1.5.0
6. **FASE 6 — Operaciones:** proyectos, gastos/compras, agenda, documentos, bóveda. ✅ 1.6.0
7. **FASE 7 — Cierre:** reportes con filtros, auditoría visualizada, pruebas
   integrales (22 OK), límite del chat IA, LibreOffice para PDF de producción y
   documentación de despliegue. ✅ 1.7.0

Pendiente del propietario (datos externos, con la UI lista): token de
@BotFather, credenciales de OmniRoute (sección Yeruzzza AI), plantillas DOCX
propias y cambiar la contraseña temporal.
Cada fase se entregó completa y verificada; nada se marcó como terminado sin pruebas.
