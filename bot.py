import discord
from discord.ext import commands
from discord.ui import View, Button, Select
from functools import partial

# ------------------- Intents -------------------
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ------------------- Konfiguráció -------------------
roles = ["Tank", "DPS", "Healer"]
status_options = ["Biztos", "Csere"]
role_emojis = {"Tank": "🛡️", "DPS": "⚔️", "Healer": "❤️"}
role_colors = {"Tank": 0x8B4513, "DPS": 0xFF0000, "Healer": 0x00FF00}

active_teams = {}
user_role_choice = {}  # user_id -> (role, status)

# ------------------- Ready -------------------
@bot.event
async def on_ready():
    print(f"Bejelentkezve mint: {bot.user}")

# ------------------- Csapat létrehozása -------------------
@bot.command()
async def team(ctx, size: int, tank: int, dps: int, healer: int):
    user_role_choice.clear()
    max_roles = {"Tank": tank, "DPS": dps, "Healer": healer}

    if size not in [5, 10]:
        await ctx.send("Csak 5 vagy 10 fős csapat hozható létre.")
        return
    if sum(max_roles.values()) > size:
        await ctx.send("A szerepek összege nem lehet nagyobb, mint a csapatméret!")
        return

    members_dict = {role: {"Biztos": [], "Csere": []} for role in roles}
    embed = create_embed(size, max_roles, members_dict)
    team_message = await ctx.send(embed=embed)

    view = create_view(max_roles, members_dict, team_message.id)
    await team_message.edit(view=view)

    active_teams[team_message.id] = {
        "size": size,
        "max": max_roles,
        "members": members_dict,
        "message": team_message,
        "start_time": None
    }

# ------------------- Embed létrehozása -------------------
def create_embed(size, max_roles, members_dict, start_time=None):
    embed = discord.Embed(
        title=f"🎯 {size}-fős Csapatkereső – Válaszd a szereped!",
        description="Kattints a gombokra a jelentkezéshez vagy visszavonáshoz.",
        color=0x3498db
    )

    if start_time is not None:
        embed.description += f"\n🕒 Event kezdete: {start_time}:00"

    biztos_field = ""
    csere_field = ""
    for role in roles:
        emoji = role_emojis[role]
        biztos_list = ", ".join([m.display_name for m in members_dict[role]["Biztos"]]) or "..."
        csere_list = ", ".join([m.display_name for m in members_dict[role]["Csere"]]) or "..."

        max_val = max_roles[role]
        current = len(members_dict[role]["Biztos"])
        if current >= max_val:
            bar_color = "🟥"
        elif current / max_val >= 0.5:
            bar_color = "🟨"
        else:
            bar_color = "🟩"
        filled = bar_color * current
        empty = "⚪" * (max_val - current)
        progress_bar = filled + empty

        biztos_field += f"{emoji} {role}: {biztos_list}\n{progress_bar}\n"
        csere_field += f"{emoji} {role}: {csere_list}\n"

    embed.add_field(name="✅ Biztos", value=biztos_field, inline=True)
    embed.add_field(name="🔄 Csere", value=csere_field, inline=True)
    return embed

# ------------------- View létrehozása -------------------
def create_view(max_roles, members_dict, team_id):
    view = View(timeout=None)

    # Button-ok létrehozása
    for role in roles:
        for status in status_options:
            button_label = get_button_label(role, status, max_roles, members_dict)
            button_style = get_button_style(role, status, max_roles, members_dict)
            button = Button(label=button_label, style=button_style)
            button.callback = partial(button_callback, role=role, status=status)
            view.add_item(button)

    # Dropdown időpont választó
    options = [discord.SelectOption(label=f"{h}:00", value=str(h)) for h in range(0, 24)]
    select = Select(placeholder="Válaszd ki az event indulási idejét 🕒", options=options)

    async def select_callback(interaction):
        selected_hour = select.values[0]
        team_data = active_teams.get(team_id)
        if not team_data:
            await interaction.response.send_message("Csapat nem található.", ephemeral=True)
            return
        team_data["start_time"] = selected_hour
        embed = create_embed(team_data["size"], team_data["max"], team_data["members"], start_time=selected_hour)
        new_view = create_view(team_data["max"], team_data["members"], team_id)
        await team_data["message"].edit(embed=embed, view=new_view)
        await interaction.response.send_message(f"Event kezdési ideje beállítva: {selected_hour}:00", ephemeral=True)

    select.callback = select_callback
    view.add_item(select)

    return view

# ------------------- Button label és style -------------------
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
    else:
        return discord.ButtonStyle.primary

def get_button_label(role, status, max_roles, members_dict):
    emoji = role_emojis[role]
    if status == "Biztos":
        current = len(members_dict[role]["Biztos"])
        max_val = max_roles[role]
        if current >= max_val:
            status_emoji = "🔴"
        elif current / max_val >= 0.5:
            status_emoji = "🟡"
        else:
            status_emoji = "🟢"
        return f"{emoji} {role} - Biztos ({current}/{max_val}) {status_emoji}"
    else:
        current = len(members_dict[role]["Csere"])
        return f"{emoji} {role} - Csere ({current}) 🔵"

# ------------------- Button callback -------------------
async def button_callback(interaction, role, status):
    user = interaction.user
    team_data = next((t for t in active_teams.values() if t["message"].id == interaction.message.id), None)
    if not team_data:
        return

    # Toggle logika + túljelentkezés Csere-be
    if user_role_choice.get(user.id) == (role, status):
        team_data["members"][role][status].remove(user)
        del user_role_choice[user.id]
    else:
        if user.id in user_role_choice:
            old_role, old_status = user_role_choice[user.id]
            if user in team_data["members"][old_role][old_status]:
                team_data["members"][old_role][old_status].remove(user)
        if status == "Biztos" and len(team_data["members"][role]["Biztos"]) >= team_data["max"][role]:
            team_data["members"][role]["Csere"].append(user)
            user_role_choice[user.id] = (role, "Csere")
        else:
            team_data["members"][role][status].append(user)
            user_role_choice[user.id] = (role, status)

    embed = create_embed(team_data["size"], team_data["max"], team_data["members"], start_time=team_data.get("start_time"))
    view = create_view(team_data["max"], team_data["members"], team_data["message"].id)
    await team_data["message"].edit(embed=embed, view=view)
    await interaction.response.defer()

# ------------------- Csapat lezárása -------------------
@bot.command()
async def close(ctx):
    if not active_teams:
        await ctx.send("Nincs aktív csapat, amit le lehetne zárni.")
        return
    team_id, team_data = active_teams.popitem()
    user_role_choice.clear()
    content = f"🎉 Csapat lezárva! 🎉 ({team_data['size']} fős)\n\n"
    for role in roles:
        biztos = ", ".join([m.display_name for m in team_data["members"][role]["Biztos"]]) or "..."
        csere = ", ".join([m.display_name for m in team_data["members"][role]["Csere"]]) or "..."
        content += f"✅ {role} - Biztos: {biztos}\n🔵 {role} - Csere: {csere}\n\n"
    if team_data.get("start_time"):
        content += f"🕒 Event kezdete: {team_data['start_time']}:00"
    await ctx.send(content)

# ------------------- Bot indítása -------------------
import os
bot.run(os.getenv("DISCORD_TOKEN"))