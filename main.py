"""
Discord Bot — Stats + Voice Tracker
Commands:
.топдня
.топвся
.топвойс
.стата

Styled like JuniperBot
"""

import os
import json
import threading

from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands, tasks
from discord.ui import View, Button
from flask import Flask

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

PREFIX = "."
DATA_FILE = "data.json"

MOSCOW_TZ = timezone(timedelta(hours=3))

ACCENT_COLOR = 0x8B5CF6

# ─────────────────────────────────────────────
# FLASK
# ─────────────────────────────────────────────

app_flask = Flask(__name__)


@app_flask.route("/")
def home():
    return "Bot is alive"


def run_flask():
    port = int(os.environ.get("FLASK_PORT", 8000))
    app_flask.run(host="0.0.0.0", port=port)


def keep_alive():
    threading.Thread(
        target=run_flask,
        daemon=True
    ).start()


# ─────────────────────────────────────────────
# TIME
# ─────────────────────────────────────────────

def moscow_now():
    return datetime.now(MOSCOW_TZ)


def today_date():
    return moscow_now().strftime("%Y-%m-%d")


# ─────────────────────────────────────────────
# DATA
# ─────────────────────────────────────────────

def empty_data():
    return {
        "messages": {
            "daily": {},
            "all_time": {}
        },

        "voice": {
            "all_time": {}
        },

        "usernames": {},

        "last_reset": today_date()
    }


def load_data():

    if os.path.exists(DATA_FILE):

        try:

            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            data.setdefault("messages", {})
            data["messages"].setdefault("daily", {})
            data["messages"].setdefault("all_time", {})

            data.setdefault("voice", {})
            data["voice"].setdefault("all_time", {})

            data.setdefault("usernames", {})

            return data

        except Exception:
            pass

    return empty_data()


def save_data(data):

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def format_voice(seconds):

    seconds = int(seconds)

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60

    if hours > 0:
        return f"{hours} ч. {minutes} мин."

    return f"{minutes} мин."


def get_name(uid):

    uid = str(uid)

    return data["usernames"].get(
        uid,
        f"User#{uid[-4:]}"
    )


# ─────────────────────────────────────────────
# BOT
# ─────────────────────────────────────────────

intents = discord.Intents.default()

intents.message_content = True
intents.voice_states = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None
)

data = {}

voice_join_times = {}

# ─────────────────────────────────────────────
# DAILY RESET
# ─────────────────────────────────────────────

@tasks.loop(minutes=1)
async def daily_reset():

    now = moscow_now()

    current_date = today_date()

    if (
        data.get("last_reset") != current_date
        and now.hour == 0
    ):

        data["messages"]["daily"] = {}

        data["last_reset"] = current_date

        save_data(data)

        print(f"[{current_date}] Daily reset complete")


# ─────────────────────────────────────────────
# EVENTS
# ─────────────────────────────────────────────

@bot.event
async def on_ready():

    global data

    data = load_data()

    if not daily_reset.is_running():
        daily_reset.start()

    print(f"✅ Logged in as {bot.user}")


@bot.event
async def on_message(message):

    if message.author.bot:
        return

    uid = str(message.author.id)

    data["usernames"][uid] = message.author.display_name

    # daily
    data["messages"]["daily"][uid] = (
        data["messages"]["daily"].get(uid, 0) + 1
    )

    # all time
    data["messages"]["all_time"][uid] = (
        data["messages"]["all_time"].get(uid, 0) + 1
    )

    save_data(data)

    await bot.process_commands(message)


@bot.event
async def on_voice_state_update(member, before, after):

    uid = member.id
    uid_str = str(uid)

    data["usernames"][uid_str] = member.display_name

    # JOIN
    if before.channel is None and after.channel is not None:

        voice_join_times[uid] = datetime.now(timezone.utc)

    # LEAVE / SWITCH
    elif before.channel is not None:

        if uid in voice_join_times:

            elapsed = (
                datetime.now(timezone.utc)
                - voice_join_times.pop(uid)
            ).total_seconds()

            data["voice"]["all_time"][uid_str] = (
                data["voice"]["all_time"].get(uid_str, 0)
                + elapsed
            )

            save_data(data)

        # SWITCH CHANNEL
        if after.channel is not None:

            voice_join_times[uid] = datetime.now(timezone.utc)


# ─────────────────────────────────────────────
# LEADERBOARD VIEW
# ─────────────────────────────────────────────

class LeaderboardView(View):

    def __init__(self, ctx, ranking, title, mode="messages"):
        super().__init__(timeout=180)

        self.ctx = ctx
        self.ranking = ranking
        self.title = title
        self.mode = mode

        self.page = 0
        self.per_page = 5
        self.max_pages = max(1, (len(ranking) - 1) // self.per_page + 1)

        self.update_buttons()

    def update_buttons(self):
        self.clear_items()

        buttons = [
            Button(emoji="⏪", style=discord.ButtonStyle.secondary),
            Button(emoji="◀", style=discord.ButtonStyle.secondary),
            Button(emoji="▶", style=discord.ButtonStyle.secondary),
            Button(emoji="⏩", style=discord.ButtonStyle.secondary),
            Button(emoji="❌", style=discord.ButtonStyle.danger)
        ]

        async def first_callback(interaction):
            if interaction.user != self.ctx.author:
                return await interaction.response.send_message(
                    "Это меню не твое",
                    ephemeral=True
                )

            self.page = 0
            await interaction.response.edit_message(
                embed=await self.make_embed(),
                view=self
            )

        async def prev_callback(interaction):
            if interaction.user != self.ctx.author:
                return await interaction.response.send_message(
                    "Это меню не твое",
                    ephemeral=True
                )

            if self.page > 0:
                self.page -= 1

            await interaction.response.edit_message(
                embed=await self.make_embed(),
                view=self
            )

        async def next_callback(interaction):
            if interaction.user != self.ctx.author:
                return await interaction.response.send_message(
                    "Это меню не твое",
                    ephemeral=True
                )

            if self.page < self.max_pages - 1:
                self.page += 1

            await interaction.response.edit_message(
                embed=await self.make_embed(),
                view=self
            )

        async def last_callback(interaction):
            if interaction.user != self.ctx.author:
                return await interaction.response.send_message(
                    "Это меню не твое",
                    ephemeral=True
                )

            self.page = self.max_pages - 1

            await interaction.response.edit_message(
                embed=await self.make_embed(),
                view=self
            )

        async def close_callback(interaction):
            await interaction.message.delete()

        callbacks = [
            first_callback,
            prev_callback,
            next_callback,
            last_callback,
            close_callback
        ]

        for btn, cb in zip(buttons, callbacks):
            btn.callback = cb
            self.add_item(btn)

    async def make_embed(self):
        embed = discord.Embed(
            title=f"🏆 {self.title}",
            color=ACCENT_COLOR
        )

        start = self.page * self.per_page
        end = start + self.per_page
        sliced = self.ranking[start:end]

        medals = {
            0: "🥇",
            1: "🥈",
            2: "🥉"
        }

        # АВАТАР ТОП-1 ЧЕРЕЗ API
        if self.ranking:
            top_uid = int(self.ranking[0][0])

            try:
                user = await self.ctx.bot.fetch_user(top_uid)

                embed.set_thumbnail(
                    url=user.display_avatar.url
                )
            except:
                pass

        separator = "────────────────────────────"

        for i, (uid, value) in enumerate(sliced, start=start):

            medal = medals.get(i, f"`#{i+1}`")

            stat = (
                format_voice(value)
                if self.mode == "voice"
                else str(value)
            )

            label = (
                "Время в войсе"
                if self.mode == "voice"
                else "Сообщений"
            )

            embed.add_field(
                name=f"{medal} {get_name(uid)}",
                value=f"{label}: **{stat}**\n{separator}",
                inline=False
            )

        embed.set_footer(
            text=f"Страница {self.page+1}/{self.max_pages}"
        )

        return embed
    # ─────────────────────────────────

   def make_embed(self):
    embed = discord.Embed(
        title=f"🏆 {self.title}",
        color=ACCENT_COLOR
    )

    start = self.page * self.per_page
    end = start + self.per_page
    sliced = self.ranking[start:end]

    medals = {
        0: "🥇",
        1: "🥈",
        2: "🥉"
    }

    # АВАТАР ТОП-1
    if self.ranking:
        top_uid = int(self.ranking[0][0])

        user = self.ctx.bot.get_user(top_uid)

        if user and user.display_avatar:
            embed.set_thumbnail(
                url=user.display_avatar.url
            )

    separator = "────────────────────────────"

    for i, (uid, value) in enumerate(sliced, start=start):
        medal = medals.get(i, f"`#{i+1}`")

        stat = (
            format_voice(value)
            if self.mode == "voice"
            else str(value)
        )

        label = "Время в войсе" if self.mode == "voice" else "Сообщений"

        embed.add_field(
            name=f"{medal} {get_name(uid)}",
            value=f"{label}: **{stat}**\n{separator}",
            inline=False
        )

    embed.set_footer(
        text=f"Страница {self.page+1}/{self.max_pages}"
    )

    return embed

# ─────────────────────────────────────────────
# COMMANDS
# ─────────────────────────────────────────────

@bot.command(name="топдня")
async def top_day(ctx):

    ranking = sorted(
        data["messages"]["daily"].items(),
        key=lambda x: x[1],
        reverse=True
    )

    if not ranking:
        return await ctx.send(
            "Сегодня никто не писал 😴"
        )

    view = LeaderboardView(
        ctx,
        ranking,
        "Топ дня",
        mode="messages"
    )

    await ctx.send(
        embed=view.make_embed(),
        view=view
    )


@bot.command(name="топвся")
async def top_all(ctx):

    ranking = sorted(
        data["messages"]["all_time"].items(),
        key=lambda x: x[1],
        reverse=True
    )

    if not ranking:
        return await ctx.send(
            "Нет данных."
        )

    view = LeaderboardView(
        ctx,
        ranking,
        "Топ всего времени",
        mode="messages"
    )

    await ctx.send(
        embed=view.make_embed(),
        view=view
    )


@bot.command(name="топвойс")
async def top_voice(ctx):

    ranking = sorted(
        data["voice"]["all_time"].items(),
        key=lambda x: x[1],
        reverse=True
    )

    if not ranking:
        return await ctx.send(
            "Никто не сидел в войсе."
        )

    view = LeaderboardView(
        ctx,
        ranking,
        "Топ голосового",
        mode="voice"
    )

    await ctx.send(
        embed=view.make_embed(),
        view=view
    )


# ─────────────────────────────────────────────
# .СТАТА
# ─────────────────────────────────────────────

@bot.command(name="стата")
async def stats(ctx):

    uid = str(ctx.author.id)

    daily = data["messages"]["daily"].get(uid, 0)

    all_time = data["messages"]["all_time"].get(uid, 0)

    voice = data["voice"]["all_time"].get(uid, 0)

    embed = discord.Embed(
        title="📊 Ваша статистика",
        color=ACCENT_COLOR
    )

    embed.description = (
        f"👤 **Пользователь:** {ctx.author.mention}\n\n"

        f"💬 **Сообщений за сутки:** "
        f"`{daily}`\n\n"

        f"📨 **Сообщений за всё время:** "
        f"`{all_time}`\n\n"

        f"🎤 **Время в войсе:** "
        f"`{format_voice(voice)}`\n\n"

        "\u200b\n\u200b"
    )

    embed.set_footer(
        text="Личная статистика пользователя"
    )

    if ctx.author.avatar:
        embed.set_thumbnail(
            url=ctx.author.avatar.url
        )

    await ctx.send(embed=embed)


# ─────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────

if __name__ == "__main__":

    token = os.environ.get("DISCORD_TOKEN")

    if not token:
        raise RuntimeError(
            "Set DISCORD_TOKEN environment variable"
        )

    keep_alive()

    bot.run(token)
