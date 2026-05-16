from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import db
from utils import ui, media
from utils.data import characters

router = Router()

# ─────────────────────────────────────────────
#  /view & /inspect <character name>
#  Shows stats (Info page) with Info / Moves tabs
# ─────────────────────────────────────────────

@router.message(Command("view", "inspect"))
async def cmd_view(message: types.Message, user: dict):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.reply(
            "❌ <b>USAGE:</b> <code>/inspect &lt;character name&gt;</code>\n"
            "Example: <code>/inspect ryomen sukuna</code>",
            parse_mode='HTML'
        )

    query = args[1].strip()
    char_name, base = _resolve_char(query)

    # Check ownership
    owned_entry = None
    if base and user:
        owned_entry = await db.roster.find_one({"userId": user['telegramId'], "charId": char_name})

    # If the character doesn't exist OR the user doesn't own it
    if not owned_entry:
        error_msg = (
            "❌ <b>Cʜᴀʀᴀᴄᴛᴇʀ Nᴏᴛ Fᴏᴜɴᴅ</b>\n\n"
            "Yᴏᴜ Dᴏɴᴛ Oᴡɴ Aɴʏ Cʜᴀʀᴀᴄᴛᴇʀ Wɪᴛʜ Tʜɪꜱ Nᴀᴍᴇ\n\n"
            "<i>𝘔𝘢𝘺𝘣𝘦 :</i>\n"
            "• Cᴏʀʀᴇᴄᴛ Sᴩᴇʟʟɪɴɢ Yᴏᴜʀ Sᴩᴇʟʟɪɴɢ !\n\n"
            "🎫 Example\n\n"
            "<code>/inspect ryomen sukuna</code>"
        )
        return await message.reply(error_msg, parse_mode='HTML')

    msg = _build_info_msg(char_name, base, owned_entry)
    builder = _build_view_keyboard(char_name, "info")

    await media.send_portrait(
        message.bot,
        message.chat.id,
        base,
        msg,
        reply_markup=builder,
        reply_to_message_id=message.message_id
    )


# ─────────────────────────────────────────────
#  /data <character name>
#  Shows full character data + ownership badge (Global Pokedex)
# ─────────────────────────────────────────────

@router.message(Command("data"))
async def cmd_data(message: types.Message, user: dict):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.reply(
            "❌ <b>USAGE:</b> <code>/data &lt;character name&gt;</code>\n"
            "Example: <code>/data Sukuna</code>",
            parse_mode='HTML'
        )

    query = args[1].strip()
    char_name, base = _resolve_char(query)

    if not base:
        # Try partial match suggestions
        suggestions = _fuzzy_suggest(query)
        hint = "\n".join(f"• {s}" for s in suggestions[:5]) if suggestions else "None found."
        return await message.reply(
            f"❌ <b>{query}</b> not found.\n\n<b>Did you mean?</b>\n{hint}",
            parse_mode='HTML'
        )

    owned_entry = None
    if user:
        owned_entry = await db.roster.find_one({"userId": user['telegramId'], "charId": char_name})

    msg = _build_data_msg(char_name, base, owned_entry)
    builder = InlineKeyboardBuilder()
    
    # Only show the "View In-Game" button if they actually own it!
    if owned_entry:
        builder.row(types.InlineKeyboardButton(text="📖 View In-Game", callback_data=f"cmd_view_char_{char_name}"))
        
    builder.row(types.InlineKeyboardButton(text="🔙 Back", callback_data="back_to_hub"))

    await media.send_portrait(
        message.bot,
        message.chat.id,
        base,
        msg,
        reply_markup=builder.as_markup(),
        reply_to_message_id=message.message_id
    )


# ─────────────────────────────────────────────
#  Callback: view_tab_info / view_tab_moves
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("view_tab_info_"))
async def cb_view_info(callback: types.CallbackQuery, user: dict):
    char_name = callback.data.replace("view_tab_info_", "")
    base = characters.DATA.get(char_name)
    if not base:
        return await callback.answer("Character not found.", show_alert=True)

    owned_entry = None
    if user:
        owned_entry = await db.roster.find_one({"userId": user['telegramId'], "charId": char_name})
        
    if not owned_entry:
        return await callback.answer("❌ You don't own this character!", show_alert=True)

    msg = _build_info_msg(char_name, base, owned_entry)
    builder = _build_view_keyboard(char_name, "info")

    await callback.answer()
    await media.edit_portrait(callback.message, base, msg, reply_markup=builder)


@router.callback_query(F.data.startswith("view_tab_moves_"))
async def cb_view_moves(callback: types.CallbackQuery, user: dict):
    char_name = callback.data.replace("view_tab_moves_", "")
    base = characters.DATA.get(char_name)
    if not base:
        return await callback.answer("Character not found.", show_alert=True)

    owned_entry = None
    if user:
        owned_entry = await db.roster.find_one({"userId": user['telegramId'], "charId": char_name})
        
    if not owned_entry:
        return await callback.answer("❌ You don't own this character!", show_alert=True)

    msg = _build_moves_msg(char_name, base, owned_entry)
    builder = _build_view_keyboard(char_name, "moves")

    await callback.answer()
    await media.edit_portrait(callback.message, base, msg, reply_markup=builder)


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def _resolve_char(query: str):
    """Exact match first, then case-insensitive, then partial."""
    data = characters.DATA

    # 1. Exact
    if query in data:
        return query, data[query]

    # 2. Case-insensitive exact
    q_lower = query.lower()
    for k, v in data.items():
        if k.lower() == q_lower:
            return k, v

    # 3. Partial (starts-with priority)
    for k, v in data.items():
        if k.lower().startswith(q_lower):
            return k, v

    # 4. Contains
    for k, v in data.items():
        if q_lower in k.lower():
            return k, v

    return None, None


def _build_view_keyboard(char_name: str, active_tab: str):
    builder = InlineKeyboardBuilder()
    info_label  = "📋 Info ✅" if active_tab == "info"  else "📋 Info"
    moves_label = "🥋 Moves ✅" if active_tab == "moves" else "🥋 Moves"
    builder.row(
        types.InlineKeyboardButton(text=info_label,  callback_data=f"view_tab_info_{char_name}"),
        types.InlineKeyboardButton(text=moves_label, callback_data=f"view_tab_moves_{char_name}"),
    )
    builder.row(types.InlineKeyboardButton(text="🔙 Back", callback_data="back_to_hub"))
    return builder.as_markup()


def _fuzzy_suggest(query: str):
    q = query.lower()
    data = characters.DATA
    results = []
    for k in data:
        if q in k.lower():
            results.append(k)
    return sorted(results, key=lambda x: (not x.lower().startswith(q), x))


def _ownership_badge(owned_entry):
    if not owned_entry:
        return "🔒 <b>NOT OWNED</b>"
    stars = owned_entry.get('stars', 0)
    star_str = '⭐' * stars if stars > 0 else ''
    return f"✅ <b>OWNED</b> — Lv.{owned_entry.get('level', 1)} {star_str}"


def _build_info_msg(char_name: str, base: dict, owned_entry=None) -> str:
    rarity_icon = ui.ICONS.get(base['rarity'].upper(), "⬜")
    energy_label = 'Physical Energy' if base.get('energyType') == 'PE' else 'Cursed Energy'
    energy_icon = '💪' if base.get('energyType') == 'PE' else '🌀'

    if owned_entry and 'custom_moves' in owned_entry:
        moves = owned_entry['custom_moves']
    else:
        moves = base.get('moves', [])
        
    move_preview = ", ".join(m.get('name', 'Unknown') for m in moves[:3])
    if len(moves) > 3:
        move_preview += f" +{len(moves)-3} more"

    from services.user_service import user_service
    stats = user_service.calculate_final_stats(owned_entry or {}, base)

    msg = (
        f"📜 <b>{char_name.upper()}</b>\n"
        f"{ui.divider()}\n"
        f"{_ownership_badge(owned_entry)}\n\n"
        f"{rarity_icon} <b>Rarity:</b> {base['rarity']}\n"
        f"🏮 <b>Grade:</b> {base.get('grade', 'Unrated')}\n"
        f"🎯 <b>Type:</b> {base.get('type', 'Unknown')}\n\n"
        f"❤️ <b>HP:</b> <code>{stats['maxHp']}</code>\n"
        f"{energy_icon} <b>{energy_label}:</b> <code>{stats['maxCe']}</code>\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"⚔️ <b>Strength (STR):</b> <code>{int(stats['power'])}</code>\n"
        f"⚡ <b>Speed (SPD):</b> <code>{int(stats['speed'])}</code>\n"
        f"🛡 <b>Durability (DUR):</b> <code>{int(stats['stamina'])}</code>\n"
        f"🌀 <b>Cursed Energy (CE):</b> <code>{int(stats['ce_stat'])}</code>\n"
        f"🧠 <b>Technique (TEC):</b> <code>{int(stats['technique'])}</code>\n"
        f"💡 <b>Battle IQ (BIQ):</b> <code>{int(stats.get('biq', 10))}</code>\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"🥋 <b>Techniques:</b> {move_preview}\n"
    )

    return msg


def _build_moves_msg(char_name: str, base: dict, owned_entry=None) -> str:
    if owned_entry and 'custom_moves' in owned_entry:
        moves = owned_entry['custom_moves']
    else:
        moves = base.get('moves', [])

    msg = (
        f"🥋 <b>{char_name.upper()} — TECHNIQUES</b>\n"
        f"{ui.divider()}\n"
        f"{_ownership_badge(owned_entry)}\n\n"
    )

    if not moves:
        msg += "<i>No techniques recorded.</i>"
        return msg

    for i, move in enumerate(moves, 1):
        name = move.get('name', 'Unknown')
        ce_cost = move.get('ce', 0)
        dmg = move.get('dmg', [0, 0])
        move_type = move.get('type', 'Unknown')
        crit = move.get('crit', 10)
        aoe = move.get('aoe', False)
        effect = move.get('effect', {})
        is_dodge = move.get('isDodge', False)

        if is_dodge:
            msg += (
                f"<b>{i}. 🌬️ {name}</b>\n"
                f"   Type: Utility  |  CE: Free\n"
                f"   ↳ Evade next attack, gain +40 CE (2 uses/battle)\n\n"
            )
            continue

        dmg_str = f"{dmg[0]}–{dmg[1]}" if isinstance(dmg, list) and len(dmg) == 2 else str(dmg)

        extras = []
        if aoe:
            extras.append("AOE 💥")
        if crit and crit != 10:
            extras.append(f"Crit {crit}%")
        if effect:
            etype = effect.get('type', '')
            val = effect.get('val', '')
            chance = int(effect.get('chance', 1.0) * 100)
            if etype == 'bleed':
                extras.append(f"Bleed {int(val*100)}% ({chance}% chance)")
            elif etype == 'poison':
                extras.append(f"Poison {int(val*100)}% ({chance}% chance)")
            elif etype == 'stun':
                extras.append(f"Stun ({chance}% chance)")
            elif etype == 'lifesteal':
                extras.append(f"Lifesteal {int(val*100)}%")
            elif etype == 'heal':
                extras.append(f"Heal {int(val*100)}% HP")
            elif etype == 'buff':
                extras.append(f"ATK Buff x{val}")

        ce_display = f"Free (+{abs(ce_cost)} CE)" if ce_cost < 0 else f"{ce_cost} CE"
        extra_str = "  |  " + "  |  ".join(extras) if extras else ""

        msg += (
            f"<b>{i}. ⚔️ {name}</b>\n"
            f"   Type: {move_type}  |  DMG: {dmg_str}  |  CE: {ce_display}{extra_str}\n\n"
        )

    return msg


def _build_data_msg(char_name: str, base: dict, owned_entry=None) -> str:
    rarity_icon = ui.ICONS.get(base['rarity'].upper(), "⬜")
    energy_label = 'Physical Energy' if base.get('energyType') == 'PE' else 'Cursed Energy'
    energy_icon = '💪' if base.get('energyType') == 'PE' else '🌀'

    moves = base.get('moves', [])
    move_lines = ""
    for m in moves:
        dmg = m.get('dmg', [0, 0])
        dmg_str = f"{dmg[0]}–{dmg[1]}" if isinstance(dmg, list) else str(dmg)
        ce = m.get('ce', 0)
        ce_str = "Free" if ce <= 0 else f"{ce} CE"
        is_dodge = m.get('isDodge', False)
        move_lines += f"  • {m['name']}: {'Dodge utility' if is_dodge else f'DMG {dmg_str}, {ce_str}'}\n"

    from services.user_service import user_service
    stats = user_service.calculate_final_stats(owned_entry or {}, base)

    msg = (
        f"📊 <b>CHARACTER DATA — {char_name.upper()}</b>\n"
        f"{ui.divider()}\n"
        f"{_ownership_badge(owned_entry)}\n\n"
        f"{rarity_icon} <b>Rarity:</b> {base['rarity']}\n"
        f"🏮 <b>Grade:</b> {base.get('grade', 'Unrated')}\n"
        f"🎯 <b>Type:</b> {base.get('type', 'Unknown')}\n\n"
        f"<b>CURRENT STATS (Lv.{stats['level']})</b>\n"
        f"❤️ HP: {stats['maxHp']}\n"
        f"{energy_icon} {energy_label}: {stats['maxCe']}\n"
        f"⚔️ Strength (STR): {int(stats['power'])}\n"
        f"⚡ Speed (SPD): {int(stats['speed'])}\n"
        f"🛡 Durability (DUR): {int(stats['stamina'])}\n"
        f"🌀 Cursed Energy (CE): {int(stats['ce_stat'])}\n"
        f"🧠 Technique (TEC): {int(stats['technique'])}\n"
        f"💡 Battle IQ (BIQ): {int(stats.get('biq', 10))}\n\n"
        f"<b>TECHNIQUES ({len(moves)})</b>\n"
        f"{move_lines}"
    )

    return msg

