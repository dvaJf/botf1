import discord
from discord import app_commands
from discord.ext import tasks, commands
import aiohttp
import asyncio
from datetime import datetime, timedelta

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = "MTQ5NDAzNDgyMDI3ODM5MDg2NA.GvdmmH.q8E4MhzRwRb3IGAuKI_zZHJre6UXZ_icMsI6L0"
API_BASE_URL = "https://f1u.vercel.app/"
LEADERBOARD_CHANNEL_ID = 1493951203367850126
REMINDER_CHANNEL_ID = 1415736281949933609

# ========== БОТ ==========
class RaceBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )
        
        self.session = None
        self.reminded_1h = set()
        self.reminded_24h = set()

    async def setup_hook(self):
        await self.tree.sync()
        check_races.start(self)
        print("✅ Бот запущен и команды синхронизированы!")

    async def on_ready(self):
        self.session = aiohttp.ClientSession()
        print(f"🤖 Бот {self.user} подключен к Discord!")
        print(f"📊 Канал для таблиц: {LEADERBOARD_CHANNEL_ID}")
        print(f"⏰ Канал для напоминаний: {REMINDER_CHANNEL_ID}")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching, 
                name="за гонками"
            )
        )

    async def close(self):
        if self.session:
            await self.session.close()
        await super().close()

    async def fetch_api(self, endpoint):
        """Запрос к API"""
        if not self.session:
            return None
        try:
            async with self.session.get(f"{API_BASE_URL}{endpoint}") as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
        except Exception as e:
            print(f"❌ API Error: {e}")
            return None

# ========== ЗАДАЧИ ==========
@tasks.loop(minutes=1)
async def check_races(bot):
    """Проверка предстоящих гонок и отправка напоминаний"""
    try:
        races = await bot.fetch_api("/races")
        if not races:
            return

        now = datetime.now()
        
        for race in races:
            race_id = race.get("id")
            race_date_str = race.get("time")
            
            if not race_date_str:
                continue
                
            try:
                race_date = datetime.fromisoformat(race_date_str.replace('Z', '+00:00'))
                race_date = race_date.replace(tzinfo=None)
            except:
                continue
            
            time_until = race_date - now
            
            # Напоминание за 1 час
            if timedelta(minutes=55) < time_until <= timedelta(minutes=65):
                if race_id not in bot.reminded_1h:
                    await send_reminder(bot, race, "1 час", urgent=True)
                    bot.reminded_1h.add(race_id)
            
            # Напоминание за 24 часа
            elif timedelta(hours=23, minutes=55) < time_until <= timedelta(hours=24, minutes=5):
                if race_id not in bot.reminded_24h:
                    await send_reminder(bot, race, "24 часа", urgent=False)
                    bot.reminded_24h.add(race_id)
            
            # Очистка старых напоминаний
            elif time_until < timedelta(0):
                bot.reminded_1h.discard(race_id)
                bot.reminded_24h.discard(race_id)
                
    except Exception as e:
        print(f"❌ Ошибка в check_races: {e}")

async def send_reminder(bot, race, time_text, urgent=False):
    """Отправка напоминания о гонке"""
    channel = bot.get_channel(REMINDER_CHANNEL_ID)
    if not channel:
        return
    
    race_name = race.get("name", "Неизвестная гонка")
    race_time = race.get("time", "Неизвестно")
    
    # Форматируем дату
    try:
        dt = datetime.fromisoformat(race_time.replace('Z', '+00:00'))
        date_str = dt.strftime("%d.%m.%Y %H:%M")
    except:
        date_str = str(race_time)[:16]
    
    if urgent:
        embed = discord.Embed(
            title="🏁 Скоро гонка!",
            description=f"**{race_name}** начнется через **{time_text}**!",
            color=0xff0000
        )
        embed.add_field(name="📅 Дата", value=date_str, inline=True)
        embed.add_field(name="🔗 Регистрация", value=f"[Зарегистрироваться]({API_BASE_URL})", inline=True)
        embed.set_footer(text="Не пропустите! 🏎️")
        
        await channel.send("@everyon", embed=embed)
    else:
        embed = discord.Embed(
            title="📅 Напоминание о гонке",
            description=f"**{race_name}** завтра!",
            color=0x3498db
        )
        embed.add_field(name="📅 Дата", value=date_str, inline=True)
        embed.add_field(name="⏰ До старта", value=time_text, inline=True)
        embed.add_field(name="🔗 Регистрация", value=f"[Зарегистрироваться]({API_BASE_URL})", inline=False)
        embed.set_footer(text="Готовьтесь к гонке! 🏎️")
        
        await channel.send("@everyon", embed=embed)

# ========== SLASH КОМАНДЫ ==========
bot = RaceBot()

@bot.tree.command(name="leaderboard", description="🏆 Таблица лидеров")
@app_commands.describe(limit="Количество позиций (по умолчанию 10)")
async def leaderboard_slash(interaction: discord.Interaction, limit: int = 10):
    await interaction.response.defer()
    
    users_data = await bot.fetch_api("/auth/users/leaderboard")
    if not users_data:
        await interaction.followup.send("❌ Не удалось загрузить таблицу лидеров")
        return
    
    embed = create_leaderboard_embed(users_data, limit)
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="races", description="📋 Список всех гонок")
@app_commands.describe(status="Фильтр по статусу")
@app_commands.choices(status=[
    app_commands.Choice(name="Все", value="all"),
    app_commands.Choice(name="Открыта регистрация", value="Регистрация"),
    app_commands.Choice(name="Завершена", value="Завершена"),
])
async def races_slash(interaction: discord.Interaction, status: app_commands.Choice[str] = None):
    await interaction.response.defer()
    
    races = await bot.fetch_api("/races")
    if not races:
        await interaction.followup.send("❌ Не удалось загрузить список гонок")
        return
    
    if status and status.value != "all":
        races = [r for r in races if r.get("status") == status.value]
    
    embed = discord.Embed(
        title="📋 Список гонок",
        color=0x3498db,
        timestamp=datetime.now()
    )
    
    status_emoji = {"Регистрация": "🟢", "Завершена": "🏁"}
    
    for race in races[:10]:
        emoji = status_emoji.get(race.get("status", ""), "🏎️")
        name = race.get("name", "Без названия")
        time = race.get("time", "Неизвестно")
        race_type = race.get("race", "Неизвестно")
        users = race.get("users", 0)
        maxuser = race.get("maxuser", 0)
        
        try:
            dt = datetime.fromisoformat(time.replace('Z', '+00:00'))
            date_str = dt.strftime("%d.%m.%Y %H:%M")
        except:
            date_str = str(time)[:16] if time else "Неизвестно"
        
        embed.add_field(
            name=f"{emoji} {name}",
            value=f"📅 {date_str}\n🏁 {race_type}\n👥 {users}/{maxuser} участников",
            inline=False
        )
    
    if len(races) > 10:
        embed.set_footer(text=f"И еще {len(races) - 10} гонок...")
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="race", description="🔍 Информация о гонке")
@app_commands.describe(race_id="ID гонки")
async def race_slash(interaction: discord.Interaction, race_id: int):
    await interaction.response.defer()
    
    race = await bot.fetch_api(f"/races/{race_id}")
    if not race:
        await interaction.followup.send(f"❌ Гонка с ID `{race_id}` не найдена")
        return
    
    embed = discord.Embed(
        title=f"🏎️ {race.get('name', 'Без названия')}",
        description=race.get("about") or "Описание отсутствует",
        color=0xe74c3c,
        timestamp=datetime.now()
    )
    
    time = race.get("time", "Неизвестно")
    try:
        dt = datetime.fromisoformat(time.replace('Z', '+00:00'))
        date_str = dt.strftime("%d.%m.%Y %H:%M")
    except:
        date_str = str(time)[:16] if time else "Неизвестно"
    
    embed.add_field(name="📅 Дата", value=date_str, inline=True)
    embed.add_field(name="🏁 Тип трассы", value=race.get("race", "Неизвестно"), inline=True)
    embed.add_field(name="📊 Статус", value=race.get("status", "Неизвестно"), inline=True)
    embed.add_field(name="👥 Участники", value=f"{race.get('users', 0)}/{race.get('maxuser', 0)}", inline=True)
    
    creator = race.get("creator_email")
    if creator:
        embed.add_field(name="👤 Организатор", value=creator.split('@')[0], inline=True)
    
    likes = race.get("organizer_likes", 0)
    dislikes = race.get("organizer_dislikes", 0)
    if likes > 0 or dislikes > 0:
        embed.add_field(name="⭐ Рейтинг", value=f"👍 {likes} | 👎 {dislikes}", inline=True)
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="register", description="✅ Ссылка на регистрацию")
@app_commands.describe(race_id="ID гонки")
async def register_slash(interaction: discord.Interaction, race_id: int):
    url = f"{API_BASE_URL}races/{race_id}/register"
    
    embed = discord.Embed(
        title="🔗 Регистрация на гонку",
        description=f"[Нажмите здесь для регистрации]({url})",
        color=0x2ecc71
    )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)
@bot.command(name="notify")
@commands.has_permissions(administrator=True)
async def notify_cmd(ctx, race_id: int, urgent: str = "1h"):
    race = await bot.fetch_api(f"/races/{race_id}")
    if not race:
        await ctx.send(f"❌ Гонка с ID `{race_id}` не найдена")
        return
    
    is_urgent = urgent == "1h"
    time_text = "1 час" if is_urgent else "24 часа"
    
    await send_reminder(bot, race, time_text, urgent=is_urgent)
    await ctx.send(f"✅ Уведомление отправлено!")
# ========== НОВАЯ КОМАНДА /notify ==========
@bot.tree.command(name="notify", description="🔔 Отправить уведомление о гонке")
@app_commands.describe(race_id="ID гонки", urgent="Тип уведомления")
@app_commands.choices(urgent=[
    app_commands.Choice(name="За час", value="1h"),
    app_commands.Choice(name="За день", value="24h")
])
async def notify_slash(interaction: discord.Interaction, race_id: int, urgent: app_commands.Choice[str]):
    await interaction.response.defer(ephemeral=True)
    
    race = await bot.fetch_api(f"/races/{race_id}")
    if not race:
        await interaction.followup.send(f"❌ Гонка с ID `{race_id}` не найдена", ephemeral=True)
        return
    
    is_urgent = urgent.value == "1h"
    time_text = "1 час" if is_urgent else "24 часа"
    
    await send_reminder(bot, race, time_text, urgent=is_urgent)
    
    await interaction.followup.send(
        f"✅ Уведомление о гонке **{race.get('name')}** отправлено!",
        ephemeral=True
    )

# ========== ТЕКСТОВЫЕ КОМАНДЫ ==========
@bot.command(name="sync")
@commands.has_permissions(administrator=True)
async def sync_commands(ctx):
    """Синхронизация slash-команд (только для админов)"""
    await bot.tree.sync()
    await ctx.send("✅ Команды синхронизированы!")

@bot.command(name="post_leaderboard")
@commands.has_permissions(administrator=True)
async def post_leaderboard(ctx, limit: int = 10):
    """Публикация таблицы лидеров в канал"""
    users_data = await bot.fetch_api("/auth/users/leaderboard")
    if not users_data:
        await ctx.send("❌ Не удалось загрузить таблицу")
        return
    
    embed = create_leaderboard_embed(users_data, limit)
    await ctx.send("@everyone 🏆 Новая таблица лидеров!", embed=embed)

# ========== УТИЛИТЫ ==========
def create_leaderboard_embed(users_data, limit):
    """Создание embed для таблицы лидеров"""
    embed = discord.Embed(
        title="🏆 Таблица лидеров",
        description=f"Топ-{limit} пилотов",
        color=0xf1c40f,
        timestamp=datetime.now()
    )
    
    if not users_data or len(users_data) == 0:
        embed.description = "Таблица пуста"
        return embed
    
    medals = ["🥇", "🥈", "🥉"]
    
    for i, entry in enumerate(users_data[:limit], 1):
        medal = medals[i-1] if i <= 3 else f"#{i}"
        email = entry.get("email", "Неизвестно")
        score = entry.get("score", 0)
        races = entry.get("races_completed", 0)
        best_pos = entry.get("best_position")
        
        best_str = f"🏁 {best_pos}" if best_pos else "—"
        
        embed.add_field(
            name=f"{medal} {email.split('@')[0]}",
            value=f"⭐ {score} очков | 🏁 {races} гонок | Лучшая: {best_str}",
            inline=False
        )
    
    return embed

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    bot.run(BOT_TOKEN)