import os
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
