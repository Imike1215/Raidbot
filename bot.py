import discord
from discord.ext import commands
from discord.ui import View, Select
from aiohttp import web, ClientSession
import asyncio
import os

# ---------------- BOT BEÁLLÍTÁS ----------------
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

roles = ["Tank", "DPS", "Healer"]
role_emojis = {"Tank": "🛡️", "DPS": "⚔️", "Healer": "❤️"}

active_teams = {}  # team_id -> csapat adatok

# ---------------- EMBED ----------------
def create_embed(size, max_roles, members_dict):
    embed = discord.Embed(
        title=f"🎯 {size}-fős Csapatkereső",
        description="Válaszd ki a szerepedet:",
        color=0x3498db
    )

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

# ---------------- VIEW KÉSZÍTÉSE ----------------
def create_dual_select_view(max_roles, members_dict, team_id):
    view = View(timeout=None)

    # ---------------- Biztos Select ----------------
    biztos_options = [discord.SelectOption(label=f"{role_emojis[r]} {r}", value=r) for r in roles]
    biztos_select = Select(
        placeholder="✅ Biztos szerep választás",
        options=biztos_options,
        min_values=0,
        max_values=1
    )

    async def biztos_callback(interaction):
        user = interaction.user
        team_data = active_teams[team_id]

        selected_role = biztos_select.values[0] if biztos_select.values else None

        # Ha újra rákattint az aktuális választására -> törlés
        previous_role = None
        for r in roles:
            if user in team_data["members"][r]["Biztos"]:
                previous_role = r
                break
        if selected_role == previous_role:
            team_data["members"][selected_role]["Biztos"].remove(user)
        else:
            if previous_role:
                team_data["members"][previous_role]["Biztos"].remove(user)
            if selected_role:
                if len(team_data["members"][selected_role]["Biztos"]) < team_data["max"][selected_role]:
                    team_data["members"][selected_role]["Biztos"].append(user)

        embed = create_embed(team_data["size"], team_data["max"], team_data["members"])
        await team_data["message"].edit(embed=embed, view=create_dual_select_view(team_data["max"], team_data["members"], team_id))
        await interaction.response.defer()

    biztos_select.callback = biztos_callback
    view.add_item(biztos_select)

    # ---------------- Csere Select ----------------
    csere_options = [discord.SelectOption(label=f"{role_emojis[r]} {r}", value=r) for r in roles]
    csere_select = Select(
        placeholder="🔄 Csere szerep választás",
        options=csere_options,
        min_values=0,
        max_values=1
    )

    async def csere_callback(interaction):
        user = interaction.user
        team_data = active_teams[team_id]

        selected_role = csere_select.values[0] if csere_select.values else None

        # Ha újra rákattint az aktuális választására -> törlés
        previous_role = None
        for r in roles:
            if user in team_data["members"][r]["Csere"]:
                previous_role = r
                break
        if selected_role == previous_role:
            team_data["members"][selected_role]["Csere"].remove(user)
        else:
            if previous_role:
                team_data["members"][previous_role]["Csere"].remove(user)
            if selected_role:
                team_data["members"][selected_role]["Csere"].append(user)

        embed = create_embed(team_data["size"], team_data["max"], team_data["members"])
        await team_data["message"].edit(embed=embed, view=create_dual_select_view(team_data["max"], team_data["members"], team_id))
        await interaction.response.defer()

    csere_select.callback = csere_callback
    view.add_item(csere_select)

    return view

# ---------------- TEAM PARANCS ----------------
@bot.command()
async def team(ctx, size: int, tank: int, dps: int, healer: int):
    if size not in [5, 10]:
        return await ctx.send("Csak 5 vagy 10 fős csapat lehet!")
    if tank + dps + healer > size:
        return await ctx.send("A szerepek összege nem lehet nagyobb mint a csapat létszáma!")

    max_roles = {"Tank": tank, "DPS": dps, "Healer": healer}
    members_dict = {r: {"Biztos": [], "Csere": []} for r in roles}

    embed = create_embed(size, max_roles, members_dict)
    msg = await ctx.send(embed=embed)
    view = create_dual_select_view(max_roles, members_dict, msg.id)
    await msg.edit(view=view)

    active_teams[msg.id] = {
        "size": size,
        "max": max_roles,
        "members": members_dict,
        "message": msg
    }

# ---------------- CLOSE PARANCS ----------------
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
    await ctx.send(text)

# ---------------- DASHBOARD ----------------
async def dashboard():
    app = web.Application()
    app.router.add_get("/", lambda request: web.Response(text="Bot dashboard fut!"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Dashboard fut a {port} porton.")

# ---------------- KEEP-ALIVE ----------------
async def keep_alive():
    url = os.environ.get("RENDER_EXTERNAL_URL")
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

# ---------------- BOT INDÍTÁS ----------------
async def main():
    asyncio.create_task(dashboard())
    asyncio.create_task(keep_alive())
    token = os.environ["DISCORD_TOKEN"]
    await bot.start(token)

asyncio.run(main())