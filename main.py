"""
Discord Bot — voice time + message tracking
Prefix: "."
Commands (Russian): .стата | .топ дня | .топвся | .топвойс
Keep-alive: Flask on FLASK_PORT env var (default 8000)
Token: set DISCORD_TOKEN in environment / Replit Secrets
"""
import os
import json
import threading
from datetime import datetime, timezone, timedelta
import discord
from discord.ext import commands, tasks
from flask import Flask
PREFIX = "."
DATA_FILE = "data.json"
MOSCOW_TZ = timezone(timedelta(hours=3))
# ── Flask keep-alive ──────────────────────────────────────────
app_flask = Flask(__name__)
@app_flask.route("/")
def home():
    return "Bot is alive"
def run_flask():
    port = int(os.environ.get("FLASK_PORT", 8000))
    app_flask.run(host="0.0.0.0", port=port)
def keep_alive():
    threading.Thread(target=run_flask, daemon=True).start()
# ── Persistent data (JSON) ────────────────────────────────────
def _moscow_now():
    return datetime.now(MOSCOW_TZ)
def _today():
    return _moscow_now().strftime("%Y-%m-%d")
def _empty_data():
    return {
        "messages":  {"all_time": {}, "daily": {}},
        "voice":     {"all_time": {}},
        "usernames": {},
        "last_reset": _today(),
    }
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                d.setdefault("usernames", {})
                return d
        except Exception:
            pass
    return _empty_data()
def save_data(d):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
# ── Time helpers ──────────────────────────────────────────────
def _format_voice(seconds):
    minutes = seconds / 60
    if minutes >= 60:
        return f"{minutes / 60:.1f} ч."
    return f"{int(minutes)} мин."
# ── Bot setup ─────────────────────────────────────────────────
intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True   # enable in Developer Portal → Bot → Privileged Gateway Intents
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)
voice_join_times = {}
data = {}
# ── Daily reset ───────────────────────────────────────────────
@tasks.loop(minutes=1)
async def daily_reset_task():
    today = _today()
    if data.get("last_reset") != today:
        data["messages"]["daily"] = {}
        data["last_reset"] = today
        save_data(data)
        print(f"[{today}] Daily stats reset.")
# ── Events ────────────────────────────────────────────────────
@bot.event
async def on_ready():
    global data
    data = load_data()
    today = _today()
    if data.get("last_reset") != today:
        data["messages"]["daily"] = {}
        data["last_reset"] = today
        save_data(data)
    daily_reset_task.start()
    print(f"✅ Logged in as {bot.user} — Moscow: {_moscow_now().strftime('%Y-%m-%d %H:%M')}")
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    uid = str(message.author.id)
    data["usernames"][uid] = message.author.display_name
    data["messages"]["all_time"][uid] = data["messages"]["all_time"].get(uid, 0) + 1
    data["messages"]["daily"][uid]    = data["messages"]["daily"].get(uid, 0) + 1
    save_data(data)
    await bot.process_commands(message)
@bot.event
async def on_voice_state_update(member, before, after):
    uid = member.id
    uid_str = str(uid)
    data["usernames"][uid_str] = member.display_name
    if before.channel is None and after.channel is not None:
        voice_join_times[uid] = datetime.now(timezone.utc)
    elif before.channel is not None:
        if uid in voice_join_times:
            elapsed = (datetime.now(timezone.utc) - voice_join_times.pop(uid)).total_seconds()
            data["voice"]["all_time"][uid_str] = data["voice"]["all_time"].get(uid_str, 0) + elapsed
            save_data(data)
        if after.channel is not None:
            voice_join_times[uid] = datetime.now(timezone.utc)
# ── Helpers ───────────────────────────────────────────────────
def _name(uid_str):
    return data["usernames"].get(uid_str, f"User#{uid_str[-4:]}")
def _box(title, lines):
    sep = "═" * 32
    body = "\n".join(lines) if lines else "  Нет данных"
    return f"```\n╔{sep}╗\n║  {title}\n╠{sep}╣\n{body}\n╚{sep}╝\n```"
# ── Commands ──────────────────────────────────────────────────
@bot.command(name="стата")
async def personal_stats(ctx):
    uid = str(ctx.author.id)
    data["usernames"][uid] = ctx.author.display_name
    msg_all   = data["messages"]["all_time"].get(uid, 0)
    msg_day   = data["messages"]["daily"].get(uid, 0)
    voice_sec = data["voice"]["all_time"].get(uid, 0)
    lines = [
        f"  👤 {ctx.author.display_name}",
        f"  ✉️  Сообщений сегодня : {msg_day}",
        f"  📨 Сообщений всего   : {msg_all}",
        f"  🎙️  Голос (всего)     : {_format_voice(voice_sec) if voice_sec else '0 мин.'}",
    ]
    await ctx.send(_box("📊 Твоя статистика", lines))
@bot.command(name="топ")
async def top_day(ctx, *, arg=""):
    if arg.strip() != "дня":
        await ctx.send("Используй: `.топ дня`")
        return
    ranking = sorted(data["messages"]["daily"].items(), key=lambda x: x[1], reverse=True)[:10]
    if not ranking:
        await ctx.send("Сегодня ещё никто не писал 😴")
        return
    lines = [f"  {i:>2}. {_name(uid):<22} {n} сообщ." for i, (uid, n) in enumerate(ranking, 1)]
    await ctx.send(_box("🏆 Топ дня — сообщения", lines))
@bot.command(name="топвся")
async def top_all(ctx):
    ranking = sorted(data["messages"]["all_time"].items(), key=lambda x: x[1], reverse=True)[:10]
    if not ranking:
        await ctx.send("Данных пока нет.")
        return
    lines = [f"  {i:>2}. {_name(uid):<22} {n} сообщ." for i, (uid, n) in enumerate(ranking, 1)]
    await ctx.send(_box("🏆 Топ всего времени — сообщения", lines))
@bot.command(name="топвойс")
async def top_voice(ctx):
    ranking = sorted(data["voice"]["all_time"].items(), key=lambda x: x[1], reverse=True)[:10]
    if not ranking:
        await ctx.send("Пока никто не был в голосовых каналах.")
        return
    lines = [f"  {i:>2}. {_name(uid):<22} {_format_voice(s)}" for i, (uid, s) in enumerate(ranking, 1)]
    await ctx.send(_box("🎙️ Топ голоса — всего времени", lines))
# ── Run ───────────────────────────────────────────────────────
if __name__ == "__main__":
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("Set DISCORD_TOKEN environment variable to your bot token.")
    keep_alive()
    bot.run(token)