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

## Hoja de ruta (spec maestra)

1. **FASE 1 — Fundamentos (esta):** roles, empresa, seguridad, auditoría. ✅
2. **FASE 2 — Telegram:** bot, vinculación de usuarios por código temporal, webhooks, envío de PDF.
3. **FASE 3 — Plantillas:** DOCX + HTML + variables `{{...}}`, versiones, PDF.
4. **FASE 4 — Comercial:** catálogo, clientes, cotizaciones con ítems, PDF.
5. **FASE 5 — IA:** EDÉN AI Core, agentes, herramientas reales sobre la BD.
7. **FASE 7 —** reportes, auditoría completa, pruebas integrales.

Cada fase se entrega completa y verificada; nada se marca como terminado sin pruebas.
