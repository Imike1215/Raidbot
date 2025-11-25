import discord
from discord.ext import commands
from discord.ui import View, Button, Select
from functools import partial
from aiohttp import web, ClientSession
import asyncio
import os
from datetime import datetime, timedelta

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

roles = ["Tank", "DPS", "Healer"]
status_options = ["Biztos", "Csere"]
role_emojis = {"Tank": "🛡️", "DPS": "⚔️", "Healer": "❤️"}

active_teams = {}
user_role_choice = {}

# ---------------- EMBED KÉSZÍTÉS ----------------
def create_embed(size, max_roles, members_dict, start_time=None, start_day=None, end_time=None, end_day=None):
    embed = discord.Embed(
        title=f"🎯 {size}-fős Csapatkereső",
        description="Kattints a szerepre a jelentkezéshez:",
        color=0x3498db
    )
    if start_time and start_day:
        embed.description += f"\n🕒 Kezdés: **{start_day} {start_time}:00**"
    if end_time and end_day:
        embed.description += f"\n⏹ Keresés vége: **{end_day} {end_time}:00**"

    biztos_field = ""
    csere_field = ""
    for role in roles:
        emoji = role_emojis[role]
        biztos = ", ".join([m.display_name for m in members_dict[role]["Biztos"]]) or "..."
        csere = ", ".join([m.display_name for m in members_dict[role]["Csere"]]) or "..."
        current = len(members_dict[role]["Biztos"])
        max_val = max_roles[role]
        if current >= max_val:
            bar = "🟥" * current + "⚪" * (max_val - current)
        elif current / max_val >= 0.5:
            bar = "🟨" * current + "⚪" * (max_val - current)
        else:
            bar = "🟩" * current + "⚪" * (max_val - current)
        biztos_field += f"{emoji} **{role}**: {biztos}\n{bar}\n"
        csere_field += f"{emoji} **{role}**: {csere}\n"

    embed.add_field(name="✅ Biztos", value=biztos_field, inline=True)
    embed.add_field(name="🔄 Csere", value=csere_field, inline=True)
    return embed

# ---------------- SZEREP GOMBOK ----------------
def get_button_style(role, status, max_roles, members_dict):
    if status == "Biztos":
        current = len(members_dict[role]["Biztos"])
        max_val = max_roles[role]
        if current >= max_val:
            return discord.ButtonStyle.danger
        elif current / max_val >= 0.5:
            return discord.ButtonStyle.secondary
        else:
            return discord.ButtonStyle.success
    return discord.ButtonStyle.primary

def get_button_label(role, status, max_roles, members_dict):
    emoji = role_emojis[role]
    if status == "Biztos":
        c = len(members_dict[role]["Biztos"])
        m = max_roles[role]
        return f"{emoji} {role} - Biztos ({c}/{m})"
    else:
        c = len(members_dict[role]["Csere"])
        return f"{emoji} {role} - Csere ({c})"

async def button_callback(interaction, role, status):
    user = interaction.user
    team_data = active_teams.get(interaction.message.id)
    if not team_data:
        return

    # Ha ugyanaz a választás, törlés
    if user_role_choice.get(user.id) == (role, status):
        team_data["members"][role][status].remove(user)
        del user_role_choice[user.id]
    else:
        # Ha már választott korábban
        if user.id in user_role_choice:
            r, st = user_role_choice[user.id]
            if user in team_data["members"][r][st]:
                team_data["members"][r][st].remove(user)
        # Hozzáadás
        if status == "Biztos" and len(team_data["members"][role]["Biztos"]) >= team_data["max"][role]:
            team_data["members"][role]["Csere"].append(user)
            user_role_choice[user.id] = (role, "Csere")
        else:
            team_data["members"][role][status].append(user)
            user_role_choice[user.id] = (role, status)

    embed = create_embed(
        team_data["size"], team_data["max"], team_data["members"],
        start_time=team_data["start_time"], start_day=team_data["start_day"],
        end_time=team_data["end_time"], end_day=team_data["end_day"]
    )
    view = create_view(team_data["max"], team_data["members"], interaction.message.id)
    await interaction.message.edit(embed=embed, view=view)
    await interaction.response.defer()

# ---------------- NAP+ÓRA SELECT ----------------
def get_next_days(n=7):
    today = datetime.now()
    return [(today + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]

def create_view(max_roles, members_dict, team_id):
    view = View(timeout=None)

    # Szerepkattintások
    for role in roles:
        for status in status_options:
            btn = Button(
                label=get_button_label(role, status, max_roles, members_dict),
                style=get_button_style(role, status, max_roles, members_dict)
            )
            btn.callback = partial(button_callback, role=role, status=status)
            view.add_item(btn)

    # Kezdés nap+óra
    start_options = [
        discord.SelectOption(label=f"{day} {hour}:00", value=f"{day}|{hour}")
        for day in get_next_days() for hour in range(24)
    ]
    start_select = Select(placeholder="📅 Kezdés (nap + óra)", options=start_options)

    async def start_callback(interaction):
        day, hour = start_select.values[0].split("|")
        team_data = active_teams[team_id]
        team_data["start_day"] = day
        team_data["start_time"] = hour
        embed = create_embed(
            team_data["size"], team_data["max"], team_data["members"],
            team_data["start_time"], team_data["start_day"],
            team_data["end_time"], team_data["end_day"]
        )
        await team_data["message"].edit(embed=embed, view=create_view(max_roles, members_dict, team_id))
        await interaction.response.defer()
    start_select.callback = start_callback
    view.add_item(start_select)

    # Keresés vége nap+óra
    end_options = [
        discord.SelectOption(label=f"{day} {hour}:00", value=f"{day}|{hour}")
        for day in get_next_days() for hour in range(24)
    ]
    end_select = Select(placeholder="⏹ Keresés vége (nap + óra)", options=end_options)

    async def end_callback(interaction):
        day, hour = end_select.values[0].split("|")
        team_data = active_teams[team_id]
        team_data["end_day"] = day
        team_data["end_time"] = hour
        embed = create_embed(
            team_data["size"], team_data["max"], team_data["members"],
            team_data["start_time"], team_data["start_day"],
            team_data["end_time"], team_data["end_day"]
        )
        await team_data["message"].edit(embed=embed, view=create_view(max_roles, members_dict, team_id))
        await interaction.response.defer()
    end_select.callback = end_callback
    view.add_item(end_select)

    return view

# ---------------- CSAPAT PARANCS ----------------
@bot.command()
async def team(ctx, size: int, tank: int, dps: int, healer: int):
    if size not in [5, 10]:
        return await ctx.send("Csak 5 vagy 10 fős csapat lehet!")
    if tank + dps + healer > size:
        return await ctx.send("A szerepek összege nem lehet nagyobb mint a csapat létszáma!")

    user_role_choice.clear()
    max_roles = {"Tank": tank, "DPS": dps, "Healer": healer}
    members_dict = {r: {"Biztos": [], "Csere": []} for r in roles}

    embed = create_embed(size, max_roles, members_dict)
    msg = await ctx.send(embed=embed)
    view = create_view(max_roles, members_dict, msg.id)
    await msg.edit(view=view)

    active_teams[msg.id] = {
        "size": size,
        "max": max_roles,
        "members": members_dict,
        "message": msg,
        "start_time": None,
        "start_day": None,
        "end_time": None,
        "end_day": None
    }

# ---------------- CSAPAT LEZÁRÁS ----------------
@bot.command()
async def close(ctx):
    if not active_teams:
        return await ctx.send("Nincs aktív csapat.")
    team_id, team = active_teams.popitem()
    text = "🎉 **Csapat lezárva!** 🎉\n\n"
    for role in roles:
        biztos = ", ".join([m.display_name for m in team["members"][role]["Biztos"]]) or "..."
        csere = ", ".join([m.display_name for m in team["members"][role]["Csere"]]) or "..."
        text += f"**{role}**\n✔ Biztos: {biztos}\n🔄 Csere: {csere}\n\n"
    if team["start_day"] and team["start_time"]:
        text += f"🕒 Kezdés: {team['start_day']} {team['start_time']}:00\n"
    if team["end_day"] and team["end_time"]:
        text += f"⏹ Keresés vége: {team['end_day']} {team['end_time']}:00"
    await ctx.send(text)

# ---------------- DASHBOARD + KEEPALIVE ----------------
async def dashboard():
    app = web.Application()
    app.router.add_get("/", lambda request: web.Response(text="Bot dashboard fut!"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Dashboard fut a {port} porton.")

async def keep_alive():
    url = os.environ.get("RENDER_EXTERNAL_URL", None)
    if not url:
        print("Nincs RENDER_EXTERNAL_URL beállítva.")
        return
    async with ClientSession() as session:
        while True:
            try:
                async with session.get(url) as r:
                    print("KeepAlive:", r.status)
            except Exception as e:
                print("KeepAlive hiba:", e)
            await asyncio.sleep(600)

async def main():
    asyncio.create_task(dashboard())
    asyncio.create_task(keep_alive())
    token = os.environ["DISCORD_TOKEN"]
    await bot.start(token)

asyncio.run(main())