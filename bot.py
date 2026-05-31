import os
import logging
import asyncio
from aiohttp import web
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN  = os.environ["BOT_TOKEN"]
OWNER_ID   = int(os.environ["OWNER_ID"])
# Render автоматически задаёт PORT; WEBHOOK_URL — твой https-адрес сервиса на Render
PORT       = int(os.environ.get("PORT", 8443))
WEBHOOK_URL = os.environ["WEBHOOK_URL"].rstrip("/")   # например https://my-bot.onrender.com

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def sender_tag(user) -> str:
    name = (user.full_name or "").strip() or "Без имени"
    if user.username:
        return f"👤 @{user.username} ({name}, id: {user.id})"
    return f"👤 {name} (id: {user.id})"


def is_owner(update: Update) -> bool:
    return update.effective_user.id == OWNER_ID


# ──────────────────────────────────────────────
# Handlers
# ──────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_owner(update):
        await update.message.reply_text(
            "✅ Бот работает в webhook-режиме. Все входящие сообщения пересылаются тебе."
        )
        return

    await update.message.reply_text(
        "👋 Привет! Напиши сообщение — я передам его владельцу бота.\n"
        "Можно присылать текст, фото, видео, файлы, голосовые, стикеры и т.д."
    )
    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=f"🔔 Новый пользователь открыл бота:\n{sender_tag(user)}",
    )


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    await update.message.reply_text(f"Твой Telegram ID: `{uid}`", parse_mode="Markdown")


async def forward_to_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg  = update.message
    user = update.effective_user

    if is_owner(update):
        return

    tag            = sender_tag(user)
    caption_prefix = f"📨 Сообщение от {tag}\n"

    if msg.text:
        await context.bot.send_message(chat_id=OWNER_ID, text=f"{caption_prefix}\n{msg.text}")

    elif msg.photo:
        cap = msg.caption or ""
        await context.bot.send_photo(chat_id=OWNER_ID, photo=msg.photo[-1].file_id,
                                     caption=f"{caption_prefix}{cap}")

    elif msg.video:
        cap = msg.caption or ""
        await context.bot.send_video(chat_id=OWNER_ID, video=msg.video.file_id,
                                     caption=f"{caption_prefix}{cap}")

    elif msg.video_note:
        await context.bot.send_message(chat_id=OWNER_ID, text=caption_prefix)
        await context.bot.send_video_note(chat_id=OWNER_ID, video_note=msg.video_note.file_id)

    elif msg.document:
        cap = msg.caption or ""
        await context.bot.send_document(chat_id=OWNER_ID, document=msg.document.file_id,
                                        caption=f"{caption_prefix}{cap}")

    elif msg.voice:
        await context.bot.send_message(chat_id=OWNER_ID, text=caption_prefix)
        await context.bot.send_voice(chat_id=OWNER_ID, voice=msg.voice.file_id)

    elif msg.audio:
        cap = msg.caption or ""
        await context.bot.send_audio(chat_id=OWNER_ID, audio=msg.audio.file_id,
                                     caption=f"{caption_prefix}{cap}")

    elif msg.sticker:
        await context.bot.send_message(chat_id=OWNER_ID, text=caption_prefix)
        await context.bot.send_sticker(chat_id=OWNER_ID, sticker=msg.sticker.file_id)

    elif msg.location:
        await context.bot.send_message(chat_id=OWNER_ID, text=caption_prefix)
        await context.bot.send_location(chat_id=OWNER_ID,
                                        latitude=msg.location.latitude,
                                        longitude=msg.location.longitude)

    elif msg.contact:
        c = msg.contact
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=(f"{caption_prefix}\n📇 Контакт:\n"
                  f"Имя: {c.first_name} {c.last_name or ''}\n"
                  f"Телефон: {c.phone_number}\n"
                  f"User ID: {c.user_id or '—'}"),
        )

    elif msg.animation:
        cap = msg.caption or ""
        await context.bot.send_animation(chat_id=OWNER_ID, animation=msg.animation.file_id,
                                         caption=f"{caption_prefix}{cap}")

    else:
        await context.bot.send_message(chat_id=OWNER_ID,
                                       text=f"{caption_prefix}\n[Неподдерживаемый тип сообщения]")

    await msg.reply_text("✅ Сообщение доставлено!")


# ──────────────────────────────────────────────
# Webhook + aiohttp web server
# ──────────────────────────────────────────────

async def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, forward_to_owner))

    # Устанавливаем webhook
    webhook_path = f"/webhook/{BOT_TOKEN}"
    full_url     = f"{WEBHOOK_URL}{webhook_path}"

    await app.initialize()
    await app.bot.set_webhook(url=full_url, allowed_updates=Update.ALL_TYPES)
    logger.info(f"Webhook установлен: {full_url}")

    # aiohttp-роутер
    async def handle_webhook(request: web.Request) -> web.Response:
        data   = await request.json()
        update = Update.de_json(data, app.bot)
        await app.process_update(update)
        return web.Response(text="ok")

    async def handle_health(request: web.Request) -> web.Response:
        """Health-check endpoint — Render пингует его, чтобы сервис не засыпал."""
        return web.Response(text="ok")

    aio_app = web.Application()
    aio_app.router.add_post(webhook_path, handle_webhook)
    aio_app.router.add_get("/health", handle_health)
    aio_app.router.add_get("/", handle_health)   # Render иногда стучится в корень

    runner = web.AppRunner(aio_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await app.start()
    await site.start()
    logger.info(f"Сервер слушает порт {PORT}")

    # Держим процесс живым
    try:
        await asyncio.Event().wait()
    finally:
        await app.stop()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
