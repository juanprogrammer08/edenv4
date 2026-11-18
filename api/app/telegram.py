# -*- coding: utf-8 -*-
"""EDÉN — Integración Telegram (FASE 2).

- Configuración del bot con token CIFRADO en base de datos (Fernet desde AUTH_SECRET).
- Vinculación segura de usuarios del panel mediante código temporal de un solo uso.
- Recepción de mensajes por long-polling (desarrollo) o webhook (producción).
- Recepción de fotos y documentos guardados en MEDIA_DIR/telegram.
- Envío de mensajes/notificaciones a cuentas vinculadas.
- Historial completo de mensajes en telegram_mensajes.

El bot solo hace cosas reales en FASE 2: comandos, vinculación, adjuntos y
notificaciones. La interpretación inteligente llega con EDÉN AI Core (FASE 5)
y responde con honestidad hasta entonces.
"""
import asyncio
import hashlib
import os
import secrets
import shutil
import string
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import (
    TG_API, TG_CODE_TTL_MINUTOS, TG_MAX_ADJUNTO_MB, TG_POLL_SECONDS, MEDIA_DIR,
    PUBLIC_BASE_URL,
)
from app.db import SessionLocal, fernet_desde_secret, registrar_auditoria, get_db
from app.modelos import TelegramCuenta, TelegramCodigo, TelegramConfig, TelegramMensaje, User
from app.seguridad import cliente_ip, get_current_user, require_dueno

router = APIRouter()

# Tarea de long-polling en curso (una por proceso)
_tarea_polling: asyncio.Task | None = None


# ============================================================
# Utilidades internas
# ============================================================

def _fila_config(db: Session) -> TelegramConfig:
    cfg = db.execute(select(TelegramConfig).where(TelegramConfig.id == 1)).scalar_one_or_none()
    if not cfg:
        cfg = TelegramConfig(id=1)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def _obtener_token(db: Session) -> str | None:
    cfg = _fila_config(db)
    if not cfg.bot_token_cifrado:
        return None
    try:
        return fernet_desde_secret().decrypt(cfg.bot_token_cifrado.encode()).decode()
    except Exception:
        return None


def _config_publica(cfg: TelegramConfig) -> dict:
    """Estado del bot SIN exponer el token, jamás."""
    return {
        "configurado": bool(cfg.bot_token_cifrado),
        "bot_username": cfg.bot_username,
        "bot_id": cfg.bot_id,
        "modo": cfg.modo,
        "activo": bool(cfg.activo),
        "webhook_url": cfg.webhook_url,
        "estado_texto": cfg.estado_texto,
        "ultima_verificacion": cfg.ultima_verificacion.isoformat() if cfg.ultima_verificacion else None,
    }


def _sha256(texto: str) -> str:
    return hashlib.sha256(texto.encode()).hexdigest()


async def _llamar_api(token: str, metodo: str, payload: dict | None = None) -> dict:
    """Llama a la API de Telegram y devuelve el result, o lanza error honesto."""
    try:
        async with httpx.AsyncClient(timeout=40) as cliente:
            resp = await cliente.post(f"{TG_API}/bot{token}/{metodo}", json=payload or {})
    except httpx.RequestError as e:
        raise TelegramError(f"Sin conexión con Telegram ({metodo}): {type(e).__name__}")
    try:
        datos = resp.json()
    except Exception:
        raise TelegramError(f"Respuesta no válida de Telegram (HTTP {resp.status_code})")
    if not datos.get("ok"):
        descripcion = datos.get("description", f"HTTP {resp.status_code}")
        raise TelegramError(f"Telegram rechazó {metodo}: {descripcion}")
    return datos["result"]


class TelegramError(Exception):
    pass


async def _enviar_mensaje(token: str, chat_id: str, texto: str, db: Session) -> bool:
    """Envía texto a un chat (troceado a 3800 caracteres) y deja historial."""
    pedazos = [texto[i:i + 3800] for i in range(0, len(texto), 3800)] or [""]
    for pedazo in pedazos:
        try:
            await _llamar_api(token, "sendMessage", {"chat_id": chat_id, "text": pedazo})
            db.add(TelegramMensaje(chat_id=str(chat_id), direccion="salida", tipo="texto",
                                   texto=pedazo, entregado=True))
        except TelegramError as e:
            db.add(TelegramMensaje(chat_id=str(chat_id), direccion="salida", tipo="texto",
                                   texto=pedazo, entregado=False, error=str(e)[:500]))
            db.commit()
            return False
        db.commit()
    return True


def _cuenta_de_chat(db: Session, chat_id: str) -> TelegramCuenta | None:
    return db.execute(
        select(TelegramCuenta).where(TelegramCuenta.telegram_id == str(chat_id),
                                     TelegramCuenta.activo == True)  # noqa: E712
    ).scalar_one_or_none()


# ============================================================
# Procesamiento de updates (común a polling y webhook)
# ============================================================

async def _procesar_update(u: dict):
    """Procesa un update de Telegram: comandos, adjuntos y texto libre."""
    mensaje = u.get("message") or u.get("edited_message")
    if not mensaje:
        return
    chat_id = str((mensaje.get("chat") or {}).get("id", ""))
    if not chat_id:
        return
    db = SessionLocal()
    token = _obtener_token(db)
    try:
        de = mensaje.get("from") or {}
        t_id = str(de.get("id", chat_id))
        t_username = (de.get("username") or "")[:80]
        texto = mensaje.get("text") or mensaje.get("caption") or ""
        cuenta = _cuenta_de_chat(db, chat_id)

        # ---- adjuntos (foto / documento) ----
        if mensaje.get("document") or mensaje.get("photo"):
            tipo = "documento" if mensaje.get("document") else "foto"
            _registrar_entrada(db, chat_id, cuenta, tipo=tipo, texto=texto or None)
            if not token:
                return
            if not cuenta:
                await _enviar_mensaje(token, chat_id,
                                      "Recibí tu adjunto, pero tu Telegram no está vinculado a EDÉN. "
                                      "Genera un código en el panel y envía /vincular CODIGO.", db)
                return
            resultado = await _guardar_adjunto(token, mensaje, tipo, chat_id, cuenta, db)
            await _enviar_mensaje(token, chat_id, resultado, db)
            return

        if not texto:
            return

        # ---- comandos y texto ----
        if texto.startswith("/"):
            _registrar_entrada(db, chat_id, cuenta, tipo="comando", texto=texto)
            respuesta = await _comando(db, texto, cuenta, chat_id, t_username, token)
        else:
            _registrar_entrada(db, chat_id, cuenta, tipo="texto", texto=texto)
            if cuenta:
                # FASE 5: el texto libre va al núcleo Yeruzzza con el usuario vinculado
                usuario_panel = db.execute(select(User).where(User.id == cuenta.usuario_id,
                                                             User.is_active == True)).scalar_one_or_none()  # noqa: E712
                if not usuario_panel:
                    respuesta = "Tu cuenta está inactiva en el panel; pide al dueño que la reactivé."
                else:
                    try:
                        from app.ia_core import _nucleo
                        giro = await _nucleo(db, usuario_panel, texto, "telegram", chat_id)
                        respuesta = giro["texto"]
                    except Exception as e:
                        respuesta = f"No pude procesar tu solicitud: {str(e)[:200]}"
            else:
                respuesta = (
                    f"No estás vinculado a Yeruzzza. Tu Telegram ID es {t_id}. "
                    "Inicia sesión en el panel, sección Telegram, genera un código temporal y "
                    "envíame: /vincular CODIGO"
                )
        if token and respuesta:
            await _enviar_mensaje(token, chat_id, respuesta, db)
    finally:
        db.close()


async def _enviar_documento(token: str, chat_id: str, ruta: str, nombre: str, db: Session) -> bool:
    try:
        async with httpx.AsyncClient(timeout=120) as cliente:
            with open(ruta, "rb") as f:
                resp = await cliente.post(
                    f"{TG_API}/bot{token}/sendDocument",
                    data={"chat_id": chat_id, "caption": nombre[:200]},
                    files={"document": (nombre, f)},
                )
        try:
            datos = resp.json()
        except Exception:
            datos = {"ok": False}
        ok_envio = bool(datos.get("ok"))
        db.add(TelegramMensaje(chat_id=chat_id, direccion="salida", tipo="documento",
                               texto=nombre[:2000], archivo_ruta=ruta, entregado=ok_envio,
                               error="" if ok_envio else f"HTTP {resp.status_code}"))
        db.commit()
        return ok_envio
    except httpx.RequestError as e:
        db.add(TelegramMensaje(chat_id=chat_id, direccion="salida", tipo="documento",
                               texto=nombre[:2000], archivo_ruta=ruta, entregado=False,
                               error=f"sin conexión con Telegram: {type(e).__name__}"))
        db.commit()
        return False


def _registrar_entrada(db: Session, chat_id: str, cuenta, tipo: str, texto: str | None = None):
    db.add(TelegramMensaje(chat_id=chat_id, direccion="entrada", tipo=tipo, texto=texto,
                           cuenta_id=cuenta.id if cuenta else None))
    db.commit()


async def _comando(db: Session, texto: str, cuenta, chat_id: str, t_username: str, token: str | None) -> str:
    partes = texto.strip().split(maxsplit=1)
    comando = partes[0].lower()
    argumento = partes[1].strip() if len(partes) > 1 else ""

    if comando == "/start":
        if cuenta:
            return f"Yeruzzza en línea. Estás vinculado como {cuenta.telegram_username or 'cuenta de Telegram'}. Usa /estado o escríbeme lo que necesites."
        return ("Bienvenido a Yeruzzza Empresarial Asist. Para vincular tu Telegram: inicia sesión en el "
                "panel web, sección Telegram, genera un código temporal y envíame /vincular CODIGO.")

    if comando == "/vincular":
        if cuenta:
            return "Esta cuenta de Telegram ya está vinculada. Usa /estado para ver detalles."
        if not argumento:
            return "Envíame: /vincular CODIGO — el código se genera en el panel, sección Telegram."
        # El código va hasheado; solo coincide por hash, nunca está en claro en la BD
        fila = db.execute(
            select(TelegramCodigo).where(TelegramCodigo.codigo_hash == _sha256(argumento),
                                         TelegramCodigo.usado == False)  # noqa: E712
        ).scalar_one_or_none()
        if not fila or fila.expira_en < datetime.utcnow():
            return "El código no es válido o expiró. Genera uno nuevo en el panel (válido 10 minutos)."
        ya = db.execute(select(TelegramCuenta).where(TelegramCuenta.telegram_id == chat_id)).scalar_one_or_none()
        if ya:
            ya.activo = True
            ya.telegram_username = t_username or ya.telegram_username
            fila.usado = True
            db.commit()
            registrar_auditoria(db, "telegram_revinculacion", username_libre=f"chat {chat_id}",
                                detalle=f"chat {chat_id} re-vinculado a usuario {ya.usuario_id}")
            return "Tu Telegram ya tenía una vinculación; la reactivé."
        nueva = TelegramCuenta(telegram_id=chat_id, telegram_username=t_username,
                               usuario_id=fila.usuario_id)
        db.add(nueva)
        fila.usado = True
        db.commit()
        db.refresh(nueva)
        usuario = db.execute(select(User).where(User.id == fila.usuario_id)).scalar_one_or_none()
        registrar_auditoria(db, "telegram_vinculacion", usuario=usuario,
                            detalle=f"chat {chat_id} vinculado a {usuario.username if usuario else fila.usuario_id}")
        return (f"Vinculación lista, {usuario.username if usuario else ''}. Yeruzzza te enviará "
                "notificaciones, respuestas y documentos a este chat.")

    if comando in ("/confirmar", "/cancelar"):
        if not cuenta or not cuenta.usuario_id:
            return "Solo las cuentas vinculadas pueden autorizar acciones."
        if not argumento.isdigit():
            return f"Uso: {comando} NUMERO — el número aparece con cada propuesta (p. ej. /confirmar 3)."
        from app.modelos import IAAccion, Documento
        from app.db import registrar_auditoria
        accion = db.execute(select(IAAccion).where(IAAccion.id == int(argumento))).scalar_one_or_none()
        if not accion or accion.conversacion_id != f"tg-{chat_id}":
            return "Esa acción no existe o no pertenece a esta conversación."
        if accion.estado != "pendiente":
            return f"La acción ya está {accion.estado}."
        usuario_panel = db.execute(select(User).where(User.id == cuenta.usuario_id,
                                                      User.is_active == True)).scalar_one_or_none()  # noqa: E712
        if not usuario_panel:
            return "Tu cuenta del panel está inactiva."
        if comando == "/cancelar":
            accion.estado = "cancelada"
            accion.resuelta_en = datetime.now()
            db.commit()
            registrar_auditoria(db, "ia_accion_cancelada", usuario=usuario_panel)
            return "Propuesta cancelada. No se tocó nada."
        # confirmar: ejecutar con AUTORIZACIÓN HUMANA explícita
        from app.ia_core import _ejecutar_accion
        ok, resultado, completo = _ejecutar_accion(db, accion, usuario_panel)[:3]
        registrar_auditoria(db, "ia_accion_confirmada", usuario=usuario_panel,
                            detalle=f"{accion.herramienta} via Telegram: {'OK' if ok else 'FALLO'}")
        if not ok:
            return f"Fallo al ejecutar: {str(completo.get('error') if isinstance(completo, dict) else resultado)[:300]}"
        # si la acción produjo un documento, lo envía al chat
        if token and isinstance(completo, dict) and completo.get("documento_id"):
            ruta_doc = completo.get("archivo_pdf") if completo.get("pdf_ok") else completo.get("archivo_docx")
            if ruta_doc and os.path.exists(ruta_doc):
                await _enviar_documento(token, chat_id, ruta_doc, os.path.basename(ruta_doc), db)
        return f"Autorizado y ejecutado: {accion.resumen}"

    if comando == "/estado":
        if not cuenta:
            return "No estás vinculado. Genera un código en el panel y envía /vincular CODIGO."
        cfg = _fila_config(db)
        return (f"Yeruzzza Telegram — bot: {cfg.bot_username or 'sin configurar'} · estado: "
                f"{cfg.estado_texto} · activo: {'sí' if cfg.activo else 'no'} · tu vinculación: "
                f"{cuenta.telegram_username or cuenta.telegram_id} desde "
                f"{cuenta.vinculado_en.date().isoformat() if cuenta.vinculado_en else '—'}")

    if comando == "/desvincular":
        if not cuenta:
            return "No estás vinculado."
        cuenta.activo = False
        db.commit()
        usuario = db.execute(select(User).where(User.id == cuenta.usuario_id)).scalar_one_or_none()
        registrar_auditoria(db, "telegram_desvinculacion", usuario=usuario,
                            detalle=f"chat {chat_id} desvinculado desde el bot")
        return "Vinculación desactivada. Puedes reactivarla con un código nuevo desde el panel."

    return ("Comandos: /start, /vincular CODIGO, /estado, /desvincular, /confirmar N, /cancelar N. "
            "También puedes pedirme cotizaciones y datos en lenguaje natural, o enviarme fotos y documentos.")


async def _guardar_adjunto(token: str, mensaje: dict, tipo: str, chat_id: str, cuenta, db: Session) -> str:
    """Descarga foto/documento desde Telegram y lo guarda en MEDIA_DIR/telegram."""
    try:
        limite = TG_MAX_ADJUNTO_MB * 1024 * 1024
        if mensaje.get("document"):
            doc = mensaje["document"]
            file_id = doc["file_id"]
            nombre = (doc.get("file_name") or "documento")[:200]
            tamano = doc.get("file_size") or 0
        else:
            foto = mensaje["photo"][-1]  # la mayor resolución
            file_id = foto["file_id"]
            nombre = f"foto_{file_id[-10:]}.jpg"
            tamano = foto.get("file_size") or 0
        if tamano > limite:
            return f"Adjunto rechazado: supera {TG_MAX_ADJUNTO_MB} MB."
        info = await _llamar_api(token, "getFile", {"file_id": file_id})
        ruta_telegram = info.get("file_path")
        if not ruta_telegram:
            return "No pude descargar el adjunto (Telegram no entregó la ruta del archivo)."
        async with httpx.AsyncClient(timeout=120) as cliente:
            resp = await cliente.get(f"{TG_API}/file/bot{token}/{ruta_telegram}")
        if resp.status_code != 200:
            return f"No pude descargar el adjunto (HTTP {resp.status_code})."
        destino_dir = os.path.join(MEDIA_DIR, "telegram", f"chat_{chat_id}")
        os.makedirs(destino_dir, exist_ok=True)
        seguro = "".join(c for c in os.path.basename(nombre) if c.isalnum() or c in "._- ") or "archivo"
        destino = os.path.join(destino_dir, f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{seguro}")
        with open(destino, "wb") as f:
            f.write(resp.content)
        db.add(TelegramMensaje(chat_id=chat_id, direccion="entrada", tipo=tipo, texto=None,
                               archivo_nombre=seguro, archivo_ruta=destino,
                               archivo_tamano=len(resp.content), cuenta_id=cuenta.id))
        db.commit()
        return f"Adjunto recibido y guardado: {seguro} ({len(resp.content)} bytes). " \
               "Quedará disponible para los documentos y el AI Core."
    except TelegramError as e:
        return f"No puede descargar el adjunto: {e}"


# ============================================================
# Long-polling
# ============================================================

async def _bucle_polling():
    offset = 0
    fallos = 0
    while True:
        db = SessionLocal()
        try:
            cfg = _fila_config(db)
            token = _obtener_token(db)
            if not cfg.activo or cfg.modo != "polling" or not token:
                return
            async with httpx.AsyncClient(timeout=TG_POLL_SECONDS + 15) as cliente:
                resp = await cliente.get(
                    f"{TG_API}/bot{token}/getUpdates",
                    params={"offset": offset, "timeout": TG_POLL_SECONDS},
                )
            datos = resp.json()
            if not datos.get("ok"):
                cfg.estado_texto = f"getUpdates fallo: {str(datos.get('description'))[:150]}"
                db.commit()
                fallos += 1
                if fallos >= 3:
                    cfg.activo = False
                    db.commit()
                    return
                await asyncio.sleep(5)
                continue
            fallos = 0
            for u in datos.get("result", []):
                offset = u["update_id"] + 1
                try:
                    await _procesar_update(u)
                except Exception as e:
                    registrar_auditoria(db, "telegram_update_error", detalle=str(e)[:500])
        finally:
            db.close()


def _parar_polling():
    global _tarea_polling
    if _tarea_polling and not _tarea_polling.done():
        _tarea_polling.cancel()
    _tarea_polling = None


def _arrancar_polling():
    global _tarea_polling
    if _tarea_polling and not _tarea_polling.done():
        return
    _tarea_polling = asyncio.create_task(_bucle_polling())


# ============================================================
# Endpoints del panel
# ============================================================

class ConfigIn(BaseModel):
    bot_token: str = Field(..., min_length=10, max_length=200)
    modo: str = Field("polling", pattern="^(polling|webhook)$")


class ActivarIn(BaseModel):
    webhook_url: str | None = Field(None, max_length=300)


class NotificarIn(BaseModel):
    cuenta_id: int
    texto: str = Field(..., min_length=1, max_length=3800)


@router.get("/telegram/estado")
async def telegram_estado(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Estado del bot visible para todos los usuarios del panel."""
    cfg = _fila_config(db)
    mia = db.execute(select(TelegramCuenta).where(TelegramCuenta.usuario_id == current_user.id,
                                                  TelegramCuenta.activo == True)).scalar_one_or_none()  # noqa: E712
    return {"bot": _config_publica(cfg), "mi_cuenta": {
        "vinculada": bool(mia),
        "chat_id": mia.telegram_id if mia else None,
        "vinculado_en": mia.vinculado_en.isoformat() if mia and mia.vinculado_en else None,
    }}


@router.get("/telegram/config")
async def telegram_config(current_user: User = Depends(require_dueno), db: Session = Depends(get_db)):
    return _config_publica(_fila_config(db))


@router.put("/telegram/config")
async def guardar_telegram_config(datos: ConfigIn, current_user: User = Depends(require_dueno),
                                  db: Session = Depends(get_db)):
    """Guarda el token CIFRADO y lo valida de una vez contra getMe."""
    async with httpx.AsyncClient(timeout=20) as cliente:
        resp = await cliente.post(f"{TG_API}/bot{datos.bot_token}/getMe")
    try:
        me = resp.json()
    except Exception:
        raise HTTPException(400, detail=f"Telegram no respondió (HTTP {resp.status_code})")
    if not me.get("ok"):
        raise HTTPException(400, detail=f"Token inválido: {str(me.get('description'))[:150]}")
    resultado = me["result"]
    cfg = _fila_config(db)
    cifrado = fernet_desde_secret().encrypt(datos.bot_token.encode()).decode()
    cfg.bot_token_cifrado = cifrado
    cfg.bot_username = f"@{resultado.get('username')}" if resultado.get("username") else None
    cfg.bot_id = str(resultado.get("id") or "")
    cfg.modo = datos.modo
    cfg.estado_texto = "Token válido, bot identificado"
    cfg.ultima_verificacion = datetime.utcnow()
    db.commit()
    registrar_auditoria(db, "telegram_config_guardada", usuario=current_user,
                        detalle=f"bot {cfg.bot_username}, modo {cfg.modo}")
    return _config_publica(cfg)


@router.post("/telegram/probar")
async def probar_telegram(current_user: User = Depends(require_dueno), db: Session = Depends(get_db)):
    token = _obtener_token(db)
    if not token:
        raise HTTPException(400, detail="No hay token guardado. Configúralo primero.")
    try:
        async with httpx.AsyncClient(timeout=20) as cliente:
            resp = await cliente.post(f"{TG_API}/bot{token}/getMe")
        me = resp.json()
        if not me.get("ok"):
            raise TelegramError(str(me.get("description", ""))[:150])
    except Exception as e:
        cfg = _fila_config(db)
        cfg.estado_texto = f"Prueba falló: {str(e)[:150]}"
        cfg.ultima_verificacion = datetime.utcnow()
        db.commit()
        registrar_auditoria(db, "telegram_prueba", usuario=current_user, detalle="FALLÓ")
        return {"ok": False, "estado_texto": cfg.estado_texto}
    cfg = _fila_config(db)
    cfg.estado_texto = f"Conectado como @{me['result'].get('username')}"
    cfg.ultima_verificacion = datetime.utcnow()
    db.commit()
    registrar_auditoria(db, "telegram_prueba", usuario=current_user, detalle="OK")
    return {"ok": True, "bot_username": f"@{me['result'].get('username')}",
            "estado_texto": cfg.estado_texto}


@router.post("/telegram/activar")
async def activar_telegram(datos: ActivarIn | None = None, current_user: User = Depends(require_dueno),
                           db: Session = Depends(get_db)):
    """Pone el bot en marcha: polling local o webhook con secreto validado."""
    token = _obtener_token(db)
    if not token:
        raise HTTPException(400, detail="Configura el token del bot primero.")
    cfg = _fila_config(db)
    datos = datos or ActivarIn()
    if cfg.modo == "webhook":
        url = datos.webhook_url or (f"{PUBLIC_BASE_URL}/api/telegram/webhook" if PUBLIC_BASE_URL else None)
        if not url:
            raise HTTPException(400, detail="Para webhook necesitas la URL pública del API (o PUBLIC_BASE_URL configurada).")
        if not url.startswith("https://"):
            raise HTTPException(400, detail="Telegram exige HTTPS para webhooks.")
        secreto = cfg.webhook_secret or (secrets.token_hex(24))
        try:
            await _llamar_api(token, "setWebhook", {"url": url, "secret_token": secreto,
                                                    "allowed_updates": ["message", "edited_message"]})
        except TelegramError as e:
            cfg.estado_texto = str(e)[:200]
            db.commit()
            raise HTTPException(502, detail=f"No se pudo registrar el webhook: {e}")
        cfg.webhook_secret = secreto
        cfg.webhook_url = url
        cfg.activo = True
        cfg.estado_texto = f"Webhook activo en {url}"
    else:
        _arrancar_polling()
        cfg.activo = True
        cfg.estado_texto = "Long-polling activo"
    cfg.ultima_verificacion = datetime.utcnow()
    db.commit()
    registrar_auditoria(db, "telegram_activado", usuario=current_user,
                        detalle=f"modo {cfg.modo}, estado: {cfg.estado_texto}")
    return _config_publica(cfg)


@router.post("/telegram/desactivar")
async def desactivar_telegram(current_user: User = Depends(require_dueno), db: Session = Depends(get_db)):
    token = _obtener_token(db)
    cfg = _fila_config(db)
    if cfg.modo == "webhook" and token:
        try:
            await _llamar_api(token, "deleteWebhook", {})
        except TelegramError:
            pass  # lo registramos igualmente y seguimos: desactivar no puede quedar bloqueado
    _parar_polling()
    cfg.activo = False
    cfg.estado_texto = "Desactivado"
    db.commit()
    registrar_auditoria(db, "telegram_desactivado", usuario=current_user)
    return _config_publica(cfg)


# ---------------- Webhook público (protegido por secreto) ----------------

@router.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    db = SessionLocal()
    try:
        cfg = _fila_config(db)
        secreto = request.headers.get("x-telegram-bot-api-secret-token", "")
        if not cfg.activo or not cfg.webhook_secret or secreto != cfg.webhook_secret:
            registrar_auditoria(db, "telegram_webhook_rechazado", username_libre="telegram",
                                ip=cliente_ip(request),
                                detalle="secreto inválido o bot inactivo")
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Webhook no autorizado")
        try:
            u = await request.json()
        except Exception:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Update no válido")
        try:
            await _procesar_update(u)
        except Exception as e:
            registrar_auditoria(db, "telegram_update_error", username_libre="telegram",
                                detalle=str(e)[:500])
        return {"ok": True}
    finally:
        db.close()


# ---------------- Vinculación ----------------

@router.get("/telegram/codigo")
async def generar_codigo(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Código temporal de un solo uso (10 min) para vincular el chat del usuario."""
    codigo = "".join(secrets.choice(string.digits) for _ in range(6))
    db.execute(update(TelegramCodigo).where(TelegramCodigo.usuario_id == current_user.id,
                                            TelegramCodigo.usado == False)  # noqa: E712
               .values(usado=True))
    db.add(TelegramCodigo(codigo_hash=_sha256(codigo), usuario_id=current_user.id,
                          expira_en=datetime.utcnow() + timedelta(minutes=TG_CODE_TTL_MINUTOS)))
    db.commit()
    registrar_auditoria(db, "telegram_codigo_generado", usuario=current_user)
    return {"codigo": codigo, "expira_en_minutos": TG_CODE_TTL_MINUTOS,
            "instruccion": f"Ábrele el chat al bot y envía: /vincular {codigo}"}


@router.get("/telegram/cuentas")
async def listar_cuentas(current_user: User = Depends(require_dueno), db: Session = Depends(get_db)):
    filas = db.execute(select(TelegramCuenta).order_by(TelegramCuenta.id.desc())).scalars().all()
    usuarios = {u.id: u for u in db.execute(select(User)).scalars().all()}
    return [{
        "id": c.id,
        "telegram_id": c.telegram_id,
        "telegram_username": c.telegram_username,
        "usuario": usuarios[c.usuario_id].username if c.usuario_id in usuarios else "?",
        "usuario_id": c.usuario_id,
        "activo": c.activo,
        "vinculado_en": c.vinculado_en.isoformat() if c.vinculado_en else None,
    } for c in filas]


@router.delete("/telegram/cuentas/{cuenta_id}")
async def desvincular(cuenta_id: int, current_user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    cuenta = db.execute(select(TelegramCuenta).where(TelegramCuenta.id == cuenta_id)).scalar_one_or_none()
    if not cuenta:
        raise HTTPException(404, detail="Vinculación no encontrada")
    if current_user.rol != "dueno" and cuenta.usuario_id != current_user.id:
        raise HTTPException(403, detail="Solo el dueño o la propia cuenta pueden desvincular")
    db.delete(cuenta)
    db.commit()
    registrar_auditoria(db, "telegram_desvinculacion", usuario=current_user,
                        detalle=f"cuenta {cuenta.telegram_id}")
    return {"ok": True}


# ---------------- Historial ----------------

@router.get("/telegram/mensajes")
async def listar_mensajes(limit: int = 50, todas: bool = False,
                          current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    limite = max(1, min(limit, 200))
    query = select(TelegramMensaje).order_by(TelegramMensaje.id.desc()).limit(limite)
    if current_user.rol != "dueno" or not todas:
        query = query.where(TelegramMensaje.chat_id.in_(
            select(TelegramCuenta.telegram_id).where(TelegramCuenta.usuario_id == current_user.id)
        ))
    filas = db.execute(query).scalars().all()
    return [{
        "id": m.id, "chat_id": m.chat_id, "direccion": m.direccion, "tipo": m.tipo,
        "texto": m.texto, "archivo_nombre": m.archivo_nombre,
        "archivo_tamano": m.archivo_tamano, "entregado": m.entregado,
        "creado_en": m.creado_en.isoformat() if m.creado_en else None,
    } for m in filas]


# ---------------- Notificaciones ----------------

@router.post("/telegram/notificar")
async def notificar(datos: NotificarIn, current_user: User = Depends(require_dueno),
                    db: Session = Depends(get_db)):
    """El dueño envía un mensaje manual a una cuenta vinculada."""
    cuenta = db.execute(select(TelegramCuenta).where(TelegramCuenta.id == datos.cuenta_id,
                                                     TelegramCuenta.activo == True)).scalar_one_or_none()  # noqa: E712
    if not cuenta:
        raise HTTPException(404, detail="La cuenta no existe o está inactiva")
    token = _obtener_token(db)
    if not token:
        raise HTTPException(400, detail="No hay token de bot configurado")
    ok = await _enviar_mensaje(token, cuenta.telegram_id, datos.texto, db)
    registrar_auditoria(db, "telegram_notificacion", usuario=current_user,
                        detalle=f"a chat {cuenta.telegram_id}: {'OK' if ok else 'FALLÓ'}")
    return {"ok": ok, "chat_id": cuenta.telegram_id}


# ---------------- Arranque con la app ----------------

async def arrancar_telegram():
    """Si el bot quedó activo en modo polling, reanuda el bucle al reiniciar."""
    db = SessionLocal()
    try:
        cfg = _fila_config(db)
        if cfg.activo and cfg.modo == "polling" and _obtener_token(db):
            _arrancar_polling()
    finally:
        db.close()
