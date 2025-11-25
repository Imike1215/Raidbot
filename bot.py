import discord
from discord.ext import commands
from discord.ui import View, Button, Select, Modal, TextInput
from functools import partial
from datetime import datetime, timedelta
import asyncio
from aiohttp import web, ClientSession

# ------------------- Intents -------------------
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ------------------- Konfiguráció -------------------
roles = ["Tank", "DPS", "Healer"]
status_options = ["Biztos", "Csere"]
role_emojis = {"Tank": "🛡️", "DPS": "⚔️", "Healer": "❤️"}
active_teams = {}
user_role_choice = {}  # user_id -> (role, status)

DASHBOARD_URL = "https://a-te-dashboard-cimed.onrender.com/"  # Render dashboard URL

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
    view = create_view_with_modals(max_roles, members_dict, team_message.id)
    await team_message.edit(view=view)
    active_teams[team_message.id] = {
        "size": size,
        "max": max_roles,
        "members": members_dict,
        "message": team_message,
        "start_time": None,
        "start_day": None,
        "end_time": None,
        "end_day": None
    }

# ------------------- Embed létrehozása -------------------
def create_embed(size, max_roles, members_dict, start_time=None, start_day=None, end_time=None, end_day=None):
    embed = discord.Embed(
        title=f"🎯 {size}-fős Csapatkereső – Válaszd a szereped!",
        description="Kattints a gombokra a jelentkezéshez vagy visszavonáshoz.",
        color=0x3498db
    )
    if start_time is not None and start_day is not None:
        embed.description += f"\n🕒 Event kezdete: {start_day} {start_time}:00"
    if end_time is not None and end_day is not None:
        embed.description += f"\n⏹ Keresés vége: {end_day} {end_time}:00"

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
    if not team_data: return

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

    embed = create_embed(team_data["size"], team_data["max"], team_data["members"],
                         start_time=team_data.get("start_time"), start_day=team_data.get("start_day"),
                         end_time=team_data.get("end_time"), end_day=team_data.get("end_day"))
    view = create_view_with_modals(team_data["max"], team_data["members"], team_data["message"].id)
    await team_data["message"].edit(embed=embed, view=view)
    await interaction.response.defer()

# ------------------- Modal a nap kiválasztásához -------------------
class DaySelectModal(Modal):
    def __init__(self, team_id, purpose="start"):
        super().__init__(title="Válassz napot")
        self.team_id = team_id
        self.purpose = purpose
        self.day_input = TextInput(label="Dátum (YYYY-MM-DD)", placeholder="Pl.: 2025-11-26")
        self.add_item(self.day_input)

    async def on_submit(self, interaction: discord.Interaction):
        team_data = active_teams.get(self.team_id)
        if not team_data:
            await interaction.response.send_message("Csapat nem található.", ephemeral=True)
            return
        selected_day = self.day_input.value
        if self.purpose == "start":
            team_data["start_day"] = selected_day
        else:
            team_data["end_day"] = selected_day

        embed = create_embed(team_data["size"], team_data["max"], team_data["members"],
                             start_time=team_data.get("start_time"), start_day=team_data.get("start_day"),
                             end_time=team_data.get("end_time"), end_day=team_data.get("end_day"))
        view = create_view_with_modals(team_data["max"], team_data["members"], self.team_id)
        await team_data["message"].edit(embed=embed, view=view)
        await interaction.response.send_message(f"{'Kezdés' if self.purpose=='start' else 'Keresés vége'} napja beállítva: {selected_day}", ephemeral=True)

# ------------------- View létrehozása modalokkal -------------------
def create_view_with_modals(max_roles, members_dict, team_id):
    view = View(timeout=None)
    # Szerep gombok
    for role in roles:
        for status in status_options:
            button_label = get_button_label(role, status, max_roles, members_dict)
            button_style = get_button_style(role, status, max_roles, members_dict)
            button = Button(label=button_label, style=button_style)
            button.callback = partial(button_callback, role=role, status=status)
            view.add_item(button)

    # Modal gombok
    start_day_btn = Button(label="📅 Válassz kezdő napot", style=discord.ButtonStyle.primary)
    end_day_btn = Button(label="⏹ Válassz keresés vége napot", style=discord.ButtonStyle.danger)

    async def start_day_btn_callback(interaction):
        await interaction.response.send_modal(DaySelectModal(team_id, "start"))
    async def end_day_btn_callback(interaction):
        await interaction.response.send_modal(DaySelectModal(team_id, "end"))

    start_day_btn.callback = start_day_btn_callback
    end_day_btn.callback = end_day_btn_callback
    view.add_item(start_day_btn)
    view.add_item(end_day_btn)

    # Óra dropdownok
    hour_options = [discord.SelectOption(label=f"{h}:00", value=str(h)) for h in range(24)]
    start_hour_select = Select(placeholder="Kezdő óra 🕒", options=hour_options)
    end_hour_select = Select(placeholder="Keresés vége óra 🕒", options=hour_options)

    async def start_hour_callback(interaction):
        team_data = active_teams.get(team_id)
        if team_data:
            team_data["start_time"] = start_hour_select.values[0]
            embed = create_embed(team_data["size"], team_data["max"], team_data["members"],
                                 start_time=team_data.get("start_time"), start_day=team_data.get("start_day"),
                                 end_time=team_data.get("end_time"), end_day=team_data.get("end_day"))
            new_view = create_view_with_modals(team_data["max"], team_data["members"], team_id)
            await team_data["message"].edit(embed=embed, view=new_view)
            await interaction.response.send_message(f"Kezdő óra beállítva: {team_data['start_time']}:00", ephemeral=True)

    async def end_hour_callback(interaction):
        team_data = active_teams.get(team_id)
        if team_data:
            team_data["end_time"] = end_hour_select.values[0]
            embed = create_embed(team_data["size"], team_data["max"], team_data["members"],
                                 start_time=team_data.get("start_time"), start_day=team_data.get("start_day"),
                                 end_time=team_data.get("end_time"), end_day=team_data.get("end_day"))
            new_view = create_view_with_modals(team_data["max"], team_data["members"], team_id)
            await team_data["message"].edit(embed=embed, view=new_view)
            await interaction.response.send_message(f"Keresés vége óra beállítva: {team_data['end_time']}:00", ephemeral=True)

    start_hour_select.callback = start_hour_callback
    end_hour_select.callback = end_hour_callback
    view.add_item(start_hour_select)
    view.add_item(end_hour_select)

    return view

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
    if team_data.get("start_time") and team_data.get("start_day"):
        content += f"🕒 Event kezdete: {team_data['start_day']} {team_data['start_time']}:00\n"
    if team_data.get("end_time") and team_data.get("end_day"):
        content += f"⏹ Keresés vége: {team_data['end_day']} {team_data['end_time']}:00"
    await ctx.send(content)

# ------------------- Open port dashboard -------------------
async def handle_dashboard(request):
    return web.Response(text="Csapat bot dashboard élő!")

app = web.Application()
app.router.add_get("/", handle_dashboard)

async def run_dashboard():
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()

bot.loop.create_task(run_dashboard())

# ------------------- Keep-alive ping -------------------
async def keep_alive():
    async with ClientSession() as session:
        while True:
            try:
                async with session.get(DASHBOARD_URL) as resp:
                    print(f"Dashboard ping: {resp.status}")
            except Exception as e:
                print(f"Dashboard ping exception: {e}")
            await asyncio.sleep(10*60)  # 10 percenként pingel

bot.loop.create_task(keep_alive())

# ------------------- Indítás (Render + Bot) -------------------
if __name__ == "__main__":
    threading.Thread(target=start_web).start()
    bot.run(os.environ["DISCORD_TOKEN"])