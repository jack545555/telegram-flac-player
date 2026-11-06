import os
import time
import hmac
import hashlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    ContextTypes,
    filters
)

from bitchord_addon_auth import verify_headers

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL = os.getenv("CHANNEL", "flac01608")
MEDIA_SECRET = os.getenv("MEDIA_SECRET")

tracks = {}
telegram_app = None


async def channel_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.channel_post

    if not message:
        return

    media = message.audio or message.document

    if not media:
        return

    mime = getattr(media, "mime_type", "") or ""

    if message.audio is None and mime not in (
        "audio/flac",
        "audio/x-flac",
    ):
        return

    title = (
        getattr(media, "title", None)
        or getattr(media, "file_name", None)
        or f"Track {message.message_id}"
    )

    tracks[str(message.message_id)] = {
        "id": str(message.message_id),
        "title": title,
        "artist": getattr(media, "performer", "") or "Unknown",
        "format": "flac" if "flac" in mime else "audio",
        "file_id": media.file_id,
        "file_size": media.file_size or 0
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_app

    telegram_app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    telegram_app.add_handler(
        MessageHandler(
            filters.ChatType.CHANNEL
            & (filters.AUDIO | filters.Document.ALL),
            channel_audio
        )
    )

    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling(
        allowed_updates=["channel_post"]
    )

    yield

    await telegram_app.updater.stop()
    await telegram_app.stop()
    await telegram_app.shutdown()


app = FastAPI(lifespan=lifespan)


async def authenticate(request: Request):
    result = await run_in_threadpool(
        verify_headers,
        request.headers
    )

    if not result.ok:
        return JSONResponse(
            status_code=result.status,
            content=result.body,
            headers=result.headers
        )

    return None


@app.get("/manifest.json")
async def manifest():
    return {
        "id": "bd.telegram.flacplayer",
        "name": "Telegram FLAC Player",
        "version": "1.0.0",
        "resources": ["search", "stream"],
        "bitchordAuth": True,
        "allowDownloads": 0,
        "settings": [
            {
                "key": "quality",
                "type": "select",
                "default": "lossless",
                "options": [
                    {"value": "lossless", "label": "Lossless"},
                    {"value": "high", "label": "High"}
                ]
            }
        ]
    }


@app.get("/search")
async def search(request: Request, q: str = ""):
    denied = await authenticate(request)
    if denied:
        return denied

    results = []

    for track in tracks.values():
        if q.lower() in (
            track["title"] + " " + track["artist"]
        ).lower():

            results.append({
                "id": track["id"],
                "title": track["title"],
                "artist": track["artist"],
                "format": track["format"],
                "audioQuality": "UNKNOWN"
            })

    return {"tracks": results}


@app.get("/stream/{track_id}")
async def stream(track_id: str, request: Request):
    denied = await authenticate(request)
    if denied:
        return denied

    track = tracks.get(track_id)

    if not track:
        raise HTTPException(404, "Track not found")

    expiry = int(time.time()) + 900

    message = f"{track_id}:{expiry}"

    signature = hmac.new(
        MEDIA_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

    host = os.getenv("PUBLIC_URL", "").rstrip("/")

    return {
        "url": f"{host}/media/{track_id}?expires={expiry}&signature={signature}",
        "format": track["format"],
        "codec": track["format"],
        "quality": "Telegram Audio",
        "encrypted": False
    }


@app.get("/media/{track_id}")
async def media(track_id: str, expires: int, signature: str):
    if expires < int(time.time()):
        raise HTTPException(403, "Link expired")

    message = f"{track_id}:{expires}"

    expected = hmac.new(
        MEDIA_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature, expected):
        raise HTTPException(403, "Invalid signature")

    track = tracks.get(track_id)

    if not track:
        raise HTTPException(404, "Track not found")

    if track["file_size"] > 20 * 1024 * 1024:
        raise HTTPException(413, "Telegram Bot API file limit")

    file = await telegram_app.bot.get_file(
        track["file_id"]
    )

    return RedirectResponse(file.file_path)


@app.get("/")
async def home():
    return {"status": "running", "name": "Telegram FLAC Player"}import os
from fastapi import FastAPI
from telethon import TelegramClient, events
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

api_id = int(os.getenv("API_ID", "0"))
api_hash = os.getenv("API_HASH", "")
bot_token = os.getenv("BOT_TOKEN", "")
channel = os.getenv("CHANNEL", "flac01608")

client = TelegramClient(
    "flac_player",
    api_id,
    api_hash
)

tracks = []

@app.on_event("startup")
async def startup():
    await client.start(bot_token=bot_token)

    entity = await client.get_entity(channel)

    async for msg in client.iter_messages(entity, limit=1000):
        if msg.audio or msg.document:
            tracks.append({
                "id": str(msg.id),
                "title": msg.message or f"Telegram Track {msg.id}",
                "format": "unknown"
            })

@app.get("/search")
async def search(q: str = ""):
    results = [
        t for t in tracks
        if q.lower() in t["title"].lower()
    ]
    return {"tracks": results}

@app.get("/")
async def home():
    return {"name": "Telegram FLAC Player", "status": "running"}
