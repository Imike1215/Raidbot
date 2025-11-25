import discord
from discord.ext import commands
from discord.ui import View, Select
import asyncio
import os

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

roles = ["Tank", "DPS", "Healer"]
role_emojis = {"Tank": "🛡️", "DPS": "⚔️", "Healer": "❤️"}
status_options = ["Biztos", "Csere"]

active_teams = {}  # team_id -> csapat adatok

# ---------------- EMBED ----------------
def create_embed(size, max_roles, members_dict):
    embed = discord.Embed(
        title=f"🎯 {size}-fős Csapatkereső",
        description="Jelentkezz a szerepekre:",
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

# ---------------- MULTI-SELECT VIEW ----------------
def create_role_select_view(max_roles, members_dict, team_id):
    view = View(timeout=None)

    # ---------------- Biztos szerep select ----------------
    biztos_options = [discord.SelectOption(label=role, value=role) for role in roles]
    biztos_select = Select(
        placeholder="✅ Válassz Biztos szerepeket",
        options=biztos_options,
        min_values=0,
        max_values=len(roles)
    )

    async def biztos_callback(interaction):
        user = interaction.user
        team_data = active_teams[team_id]

        # Töröljük a felhasználót minden szerepből a Biztos listában
        for r in roles:
            if user in team_data["members"][r]["Biztos"]:
                team_data["members"][r]["Biztos"].remove(user)

        # Új választások hozzáadása
        for selected_role in biztos_select.values:
            if len(team_data["members"][selected_role]["Biztos"]) < team_data["max"][selected_role]:
                team_data["members"][selected_role]["Biztos"].append(user)

        # Embed frissítése
        embed = create_embed(team_data["size"], team_data["max"], team_data["members"])
        await team_data["message"].edit(embed=embed, view=create_role_select_view(team_data["max"], team_data["members"], team_id))
        await interaction.response.defer()

    biztos_select.callback = biztos_callback
    view.add_item(biztos_select)

    # ---------------- Csere szerep select ----------------
    csere_options = [discord.SelectOption(label=role, value=role) for role in roles]
    csere_select = Select(
        placeholder="🔄 Válassz Csere szerepeket",
        options=csere_options,
        min_values=0,
        max_values=len(roles)
    )

    async def csere_callback(interaction):
        user = interaction.user
        team_data = active_teams[team_id]

        # Töröljük a felhasználót minden szerepből a Csere listában
        for r in roles:
            if user in team_data["members"][r]["Csere"]:
                team_data["members"][r]["Csere"].remove(user)

        # Új választások hozzáadása
        for selected_role in csere_select.values:
            team_data["members"][selected_role]["Csere"].append(user)

        # Embed frissítése
        embed = create_embed(team_data["size"], team_data["max"], team_data["members"])
        await team_data["message"].edit(embed=embed, view=create_role_select_view(team_data["max"], team_data["members"], team_id))
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
    view = create_role_select_view(max_roles, members_dict, msg.id)
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

# ---------------- BOT INDÍTÁS ----------------
async def main():
    token = os.environ["DISCORD_TOKEN"]
    await bot.start(token)

asyncio.run(main())