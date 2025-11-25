# bot.py
import os
import asyncio
import discord
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput, Select
from functools import partial
from aiohttp import web, ClientSession

# ------------------- Bot setup -------------------
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ------------------- Konfiguráció -------------------
ROLES = ["Tank", "DPS", "Healer"]
STATUS_OPTIONS = ["Biztos", "Csere"]
ROLE_EMOJI = {"Tank": "🛡️", "DPS": "⚔️", "Healer": "❤️"}

active_teams = {}      # message_id -> team data
user_role_choice = {}  # user_id -> (message_id, role, status)

# ------------------- Embed létrehozása -------------------
def create_embed(size, max_roles, members_dict, start_day=None, start_time=None, end_day=None, end_time=None, description=None):
    embed = discord.Embed(
        title=f"🎯 {size}-fős Csapatkereső",
        description=description or "Jelentkezz a szerepedre a gombokkal!",
        color=0x3498db
    )

    if start_day and start_time is not None:
        embed.description += f"\n🕒 **Kezdés:** {start_day} {start_time}:00"
    if end_day and end_time is not None:
        embed.description += f"\n⏹ **Keresés vége:** {end_day} {end_time}:00"

    biztos_field = ""
    csere_field = ""

    for r in ROLES:
        biztos_list = ", ".join([m.display_name for m in members_dict[r]["Biztos"]]) or "..."
        csere_list = ", ".join([m.display_name for m in members_dict[r]["Csere"]]) or "..."
        max_val = max_roles[r]
        current = len(members_dict[r]["Biztos"])

        if max_val > 0:
            if current >= max_val:
                bar = "🟥" * current + "⚪" * (max_val - current)
            elif current / max_val >= 0.5:
                bar = "🟨" * current + "⚪" * (max_val - current)
            else:
                bar = "🟩" * current + "⚪" * (max_val - current)
        else:
            bar = "⚪"

        biztos_field += f"{ROLE_EMOJI[r]} **{r}**\n{biztos_list}\n{bar}\n\n"
        csere_field += f"{ROLE_EMOJI[r]} **{r}**\n{csere_list}\n\n"

    embed.add_field(name="✅ Biztos", value=biztos_field, inline=True)
    embed.add_field(name="🔄 Csere", value=csere_field, inline=True)
    return embed

# ------------------- Helper label/style -------------------
def get_button_label(role, status, max_roles, members):
    if status == "Biztos":
        c = len(members[role]["Biztos"])
        m = max_roles[role]
        return f"{ROLE_EMOJI[role]} {role} - Biztos ({c}/{m})"
    else:
        c = len(members[role]["Csere"])
        return f"{ROLE_EMOJI[role]} {role} - Csere ({c})"

def get_button_style(role, status, max_roles, members):
    if status == "Biztos":
        current = len(members[role]["Biztos"])
        maxv = max_roles[role]
        if maxv == 0:
            return discord.ButtonStyle.secondary
        if current >= maxv:
            return discord.ButtonStyle.danger
        elif current / maxv >= 0.5:
            return discord.ButtonStyle.secondary
        else:
            return discord.ButtonStyle.success
    return discord.ButtonStyle.primary

# ------------------- Button callback -------------------
async def role_button_callback(interaction: discord.Interaction, message_id: int, role: str, status: str):
    user = interaction.user
    team = active_teams.get(message_id)
    if not team:
        await interaction.response.send_message("Csapat nem található (lehet, hogy lejárt).", ephemeral=True)
        return

    members = team["members"]
    # toggle
    prev = user_role_choice.get(user.id)
    if prev and prev[0] == message_id and (prev[1], prev[2]) == (role, status):
        # eltávolítjuk
        if user in members[role][status]:
            members[role][status].remove(user)
        user_role_choice.pop(user.id, None)
    else:
        # ha más szerepben volt, eltávolítjuk onnan
        if prev and prev[0] == message_id:
            pr, ps = prev[1], prev[2]
            if user in members[pr][ps]:
                members[pr][ps].remove(user)
        # ha biztos tele van és újra biztosba akar menni -> cserebe tesszük
        if status == "Biztos" and len(members[role]["Biztos"]) >= team["max"][role]:
            members[role]["Csere"].append(user)
            user_role_choice[user.id] = (message_id, role, "Csere")
        else:
            members[role][status].append(user)
            user_role_choice[user.id] = (message_id, role, status)

    # frissítjük az embedet és view-t
    embed = create_embed(team["size"], team["max"], team["members"],
                         start_day=team.get("start_day"), start_time=team.get("start_time"),
                         end_day=team.get("end_day"), end_time=team.get("end_time"))
    view = create_team_view(team["max"], team["members"], message_id)
    await team["message"].edit(embed=embed, view=view)
    await interaction.response.defer()

# ------------------- Modal (dátum + óra) -------------------
class DateTimeModal(Modal):
    def __init__(self, message_id: int, purpose: str):
        title = "Kezdés dátum+óra" if purpose == "start" else "Vége dátum+óra"
        super().__init__(title=title)
        self.message_id = message_id
        self.purpose = purpose
        # Dátum input
        self.date = TextInput(label="Dátum (YYYY-MM-DD)", placeholder="2025-11-26", required=True, max_length=10)
        # Óra input (0-23)
        self.hour = TextInput(label="Óra (0-23)", placeholder="Pl.: 20", required=True, max_length=2)
        self.add_item(self.date)
        self.add_item(self.hour)

    async def on_submit(self, interaction: discord.Interaction):
        team = active_teams.get(self.message_id)
        if not team:
            await interaction.response.send_message("Csapat nem található.", ephemeral=True)
            return

        # Validálás
        date_val = self.date.value.strip()
        hour_val = self.hour.value.strip()
        try:
            # egyszerű formátum ellenőrzés
            parts = date_val.split("-")
            if len(parts) != 3 or not all(p.isdigit() for p in parts):
                raise ValueError("Hibás dátum formátum.")
            y, m, d = map(int, parts)
            if not (1 <= m <= 12 and 1 <= d <= 31):
                raise ValueError("Hibás dátum.")
            hour_int = int(hour_val)
            if not (0 <= hour_int <= 23):
                raise ValueError("Óra 0-23 között kell legyen.")
        except Exception as e:
            await interaction.response.send_message(f"Hibás input: {e}", ephemeral=True)
            return

        if self.purpose == "start":
            team["start_day"] = date_val
            team["start_time"] = hour_int
        else:
            team["end_day"] = date_val
            team["end_time"] = hour_int

        embed = create_embed(team["size"], team["max"], team["members"],
                             start_day=team.get("start_day"), start_time=team.get("start_time"),
                             end_day=team.get("end_day"), end_time=team.get("end_time"))
        view = create_team_view(team["max"], team["members"], self.message_id)
        await team["message"].edit(embed=embed, view=view)
        await interaction.response.send_message("Időpont beállítva!", ephemeral=True)

# ------------------- View létrehozása -------------------
def create_team_view(max_roles, members_dict, message_id):
    view = View(timeout=None)

    # szerep gombok
    for r in ROLES:
        for s in STATUS_OPTIONS:
            btn = Button(label=get_button_label(r, s, max_roles, members_dict),
                         style=get_button_style(r, s, max_roles, members_dict))
            # Closure-callback: pass message_id, role, status
            btn.callback = partial(lambda inter, mid, role, status: asyncio.create_task(role_button_callback(inter, mid, role, status)),
                                   message_id, r, s)
            view.add_item(btn)

    # kezdő dátum+óra modal gomb
    start_btn = Button(label="📅 Kezdés dátum+óra", style=discord.ButtonStyle.primary)
    async def start_btn_cb(inter: discord.Interaction):
        await inter.response.send_modal(DateTimeModal(message_id, "start"))
    start_btn.callback = start_btn_cb
    view.add_item(start_btn)

    # vége dátum+óra modal gomb
    end_btn = Button(label="⏹ Keresés vége dátum+óra", style=discord.ButtonStyle.danger)
    async def end_btn_cb(inter: discord.Interaction):
        await inter.response.send_modal(DateTimeModal(message_id, "end"))
    end_btn.callback = end_btn_cb
    view.add_item(end_btn)

    return view

# ------------------- Parancs: team -------------------
@bot.command()
async def team(ctx, size: int, tank: int, dps: int, healer: int, *, description: str = None):
    """
    !team <size> <tank> <dps> <healer> [leírás]
    """
    if size not in (5, 10):
        await ctx.send("Csak 5 vagy 10 fős csapat hozható létre.")
        return
    if tank + dps + healer > size:
        await ctx.send("A szerepek összege nem lehet nagyobb, mint a csapatméret.")
        return

    max_roles = {"Tank": tank, "DPS": dps, "Healer": healer}
    members = {r: {"Biztos": [], "Csere": []} for r in ROLES}

    embed = create_embed(size, max_roles, members, description=description)
    msg = await ctx.send(embed=embed)

    view = create_team_view(max_roles, members, msg.id)
    await msg.edit(view=view)

    active_teams[msg.id] = {
        "size": size,
        "max": max_roles,
        "members": members,
        "message": msg,
        "start_day": None,
        "start_time": None,
        "end_day": None,
        "end_time": None
    }

    await ctx.send("Csapat létrehozva! Kattints a gombokra a jelentkezéshez.")

# ------------------- Parancs: close -------------------
@bot.command()
async def close(ctx):
    if not active_teams:
        await ctx.send("Nincs aktív csapat.")
        return
    msg_id, team = active_teams.popitem()
    user_role_choice_copy = {k:v for k,v in user_role_choice.items() if v[0] != msg_id}
    # csak a másik csapatokra hagyjuk meg a választásokat
    keys_to_remove = [k for k,v in user_role_choice.items() if v[0] == msg_id]
    for k in keys_to_remove:
        user_role_choice.pop(k, None)

    text = f"🎉 **Csapat ({team['size']}) lezárva!** 🎉\n\n"
    for r in ROLES:
        biztos = ", ".join([m.display_name for m in team["members"][r]["Biztos"]]) or "..."
        csere = ", ".join([m.display_name for m in team["members"][r]["Csere"]]) or "..."
        text += f"**{r}**\n✅ Biztos: {biztos}\n🔵 Csere: {csere}\n\n"

    if team["start_day"] and team["start_time"] is not None:
        text += f"🕒 Kezdés: {team['start_day']} {team['start_time']}:00\n"
    if team["end_day"] and team["end_time"] is not None:
        text += f"⏹ Keresés vége: {team['end_day']} {team['end_time']}:00\n"

    await ctx.send(text)

# ------------------- Dashboard (open port) -------------------
async def run_dashboard():
    app = web.Application()
    async def root(req): return web.Response(text="Bot dashboard él!")
    app.router.add_get("/", root)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Dashboard fut a {port} porton.")

# ------------------- Keep-alive (prevent sleep on Render) -------------------
async def keep_alive():
    url = os.environ.get("RENDER_EXTERNAL_URL")
    if not url:
        print("RENDER_EXTERNAL_URL nincs beállítva — keep-alive nem fut.")
        return
    async with ClientSession() as session:
        while True:
            try:
                async with session.get(url) as r:
                    print("KeepAlive ping:", r.status)
            except Exception as e:
                print("KeepAlive error:", e)
            await asyncio.sleep(600)  # 10 perc

# ------------------- Main entry -------------------
async def main():
    # indítjuk a dashboardot és a keep-alive-t
    asyncio.create_task(run_dashboard())
    asyncio.create_task(keep_alive())

    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        print("HIBA: DISCORD_TOKEN nincs beállítva az environment változókban.")
        return

    # elindítjuk a botot
    await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
