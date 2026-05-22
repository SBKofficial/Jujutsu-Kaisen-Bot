import asyncio
# pyrefly: ignore [missing-import]
from aiogram import Router, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from database import db
from utils import ui, media
from utils.data import characters
from services.user_service import user_service
from services.cache_service import cache_service
from bson import ObjectId

router = Router()

async def get_user_roster(user_id):
    cached = cache_service.get_roster(user_id)
    if cached is not None:
        return cached
    try:
        roster = await db.roster.find({"userId": user_id})
    except Exception:
        roster = []
    cache_service.set_roster(user_id, roster)
    return roster

@router.message(Command("mysorcerers", "collection", "mycharacter"))
@router.callback_query(F.data.startswith("cmd_roster"))
async def cmd_roster(callback_or_message: types.CallbackQuery | types.Message, user: dict):
    if not user:
        if isinstance(callback_or_message, types.CallbackQuery):
            await callback_or_message.answer("❌ Please /start first.", show_alert=True)
        else:
            await callback_or_message.reply("❌ Please /start first.")
        return
    if isinstance(callback_or_message, types.CallbackQuery):
        await callback_or_message.answer()
    await render_roster(callback_or_message, user, 1)

@router.callback_query(F.data.startswith("roster_page_"))
async def roster_page(callback: types.CallbackQuery, user: dict):
    page = int(callback.data.split("_")[-1])
    await callback.answer()
    await render_roster(callback, user, page)

RARITY_ICON = {
    "Common":    "⬜",
    "Rare":      "🟦",
    "Epic":      "🟪",
    "Legendary": "🟨",
    "Mythic":    "🟥",
}

async def render_roster(callback_or_message, user, page=1):
    user_id = user['telegramId']
    roster = await get_user_roster(user_id)
    team_ids = user.get('teamIds', [])

    per_page = 5
    total = len(roster)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    items = roster[start:start + per_page]

    msg = "here is your all jujitsu -high Characters\n\n"

    if not items:
        msg += "Your roster is empty.\n"
    else:
        for idx, entry in enumerate(items, start=start + 1):
            char_id = entry.get('charId', '???')
            msg += f"{idx}. {char_id}\n"

    msg += f"\npage ({page}\\{total_pages})"

    builder = InlineKeyboardBuilder()
    if total_pages > 1:
        nav_row = []
        uid = f":uid_{user_id}"
        if page > 1:
            nav_row.append(types.InlineKeyboardButton(text="⬅️", callback_data=f"roster_page_{page - 1}{uid}"))
        nav_row.append(types.InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="none"))
        if page < total_pages:
            nav_row.append(types.InlineKeyboardButton(text="➡️", callback_data=f"roster_page_{page + 1}{uid}"))
        builder.row(*nav_row)

    uid = f":uid_{user_id}"
    builder.row(
        types.InlineKeyboardButton(text="🔍 Details", callback_data=f"roster_nav_details{uid}"),
        types.InlineKeyboardButton(text="💸 Sell", callback_data=f"roster_nav_sell_menu{uid}")
    )
    builder.row(types.InlineKeyboardButton(text="🔙 Back to Hub", callback_data=f"back_to_hub{uid}"))

    msg_obj = callback_or_message.message if isinstance(callback_or_message, types.CallbackQuery) else callback_or_message
    try:
        if isinstance(callback_or_message, types.CallbackQuery):
            await msg_obj.edit_text(msg, parse_mode='HTML', reply_markup=builder.as_markup())
        else:
            await callback_or_message.reply(msg, parse_mode='HTML', reply_markup=builder.as_markup())
    except Exception:
        await msg_obj.answer(msg, parse_mode='HTML', reply_markup=builder.as_markup())

@router.callback_query(F.data == "roster_nav_sell_menu")
async def handle_sell_menu(callback: types.CallbackQuery):
    msg = (
        ui.format_header("💰 SPIRIT DISPOSAL", "ROSTER") + "\n\n"
        "Release spirits back into the veil to recover Coins and Soul Dust.\n\n"
        "• <b>Common:</b> 50 Coins, 10 Dust\n"
        "• <b>Rare+:</b> Higher yields based on grade."
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🎯 SELECT INDIVIDUALS", callback_data="roster_nav_release"))
    builder.row(types.InlineKeyboardButton(text="🧹 SELL ALL COMMONS", callback_data="roster_nav_release_commons"))
    builder.row(types.InlineKeyboardButton(text="🔥 SELL ALL UNASSIGNED", callback_data="roster_mass_release_all"))
    builder.row(types.InlineKeyboardButton(text="⬅️ BACK", callback_data="cmd_roster"))

    await callback.answer()
    await media.edit_banner(callback.message, "Academy", msg, reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("roster_nav_release"))
async def handle_release_menu_router(callback: types.CallbackQuery, user: dict, state: FSMContext):
    filter_commons = "commons" in callback.data
    page = 0
    if "_page_" in callback.data:
        page = int(callback.data.split("_")[-1])
    
    await callback.answer()
    await render_release_menu(callback, user, state, filter_commons, page)

async def render_release_menu(callback, user, state: FSMContext, filter_commons=False, page=0):
    user_id = user['telegramId']
    roster = await get_user_roster(user_id)
    team_ids = user.get('teamIds', [])
    
    targets = roster
    if filter_commons:
        targets = [c for c in roster if characters.DATA.get(c['charId'], {}).get('rarity') == 'Common' and c['charId'] not in team_ids]

    # Sort: Non-team first
    targets.sort(key=lambda x: 1 if x['charId'] in team_ids else 0)

    page_size = 8
    start = page * page_size
    visible = targets[start:start + page_size]

    data = await state.get_data()
    selected_ids = data.get('selected_for_release', [])

    title = "SELL COMMONS" if filter_commons else "SELECT FOR RELEASE"
    msg = ui.format_header(title) + f"\n\nSelected: <b>{len(selected_ids)}</b> spirits\n\n"

    builder = InlineKeyboardBuilder()
    for c in visible:
        is_team = c['charId'] in team_ids
        is_selected = str(c['_id']) in [str(sid) for sid in selected_ids]
        icon = '🛡️' if is_team else ('✅' if is_selected else '⬜️')
        label = f"{icon} {c['charId']} (Lvl {c.get('level', 1)})"
        callback_data = "none" if is_team else f"roster_release_toggle_{c['_id']}"
        builder.row(types.InlineKeyboardButton(text=label, callback_data=callback_data))

    nav_row = []
    prefix = "roster_nav_release_" + ("commons_" if filter_commons else "")
    if page > 0:
        nav_row.append(types.InlineKeyboardButton(text="⬅️", callback_data=f"{prefix}page_{page - 1}"))
    if start + page_size < len(targets):
        nav_row.append(types.InlineKeyboardButton(text="➡️", callback_data=f"{prefix}page_{page + 1}"))
    if nav_row: builder.row(*nav_row)

    if selected_ids:
        builder.row(types.InlineKeyboardButton(text="🔥 CONFIRM RELEASE SELECTED", callback_data="roster_mass_release_selected"))

    if filter_commons:
        builder.row(types.InlineKeyboardButton(text="🧹 SELL ALL COMMONS NOW", callback_data="roster_mass_release_commons"))

    await media.edit_banner(callback.message, "Academy", msg, reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("roster_release_toggle_"))
async def toggle_release_select(callback: types.CallbackQuery, state: FSMContext, user: dict):
    roster_id = callback.data.replace("roster_release_toggle_", "")
    data = await state.get_data()
    selected = data.get('selected_for_release', [])
    
    if roster_id in selected:
        selected.remove(roster_id)
    else:
        if len(selected) >= 10:
            return await callback.answer("⚠️ Max 10 at once!", show_alert=True)
        selected.append(roster_id)
    
    await state.update_data(selected_for_release=selected)
    await callback.answer("Selection updated.")
    await render_release_menu(callback, user, state, False, 0)

@router.callback_query(F.data == "roster_nav_details")
async def handle_details_nav(callback: types.CallbackQuery, user: dict):
    user_id = user['telegramId']
    roster = await get_user_roster(user_id)
    
    if not roster:
        return await callback.answer("Roster is empty.")

    msg = "🔍 <b>SELECT A CHARACTER TO INSPECT:</b>"
    builder = InlineKeyboardBuilder()
    for c in roster[:20]: # Limit for UI
        builder.row(types.InlineKeyboardButton(text=f"{c['charId']} (Lvl {c.get('level', 1)})", callback_data=f"roster_view_{c['_id']}"))
    
    builder.row(types.InlineKeyboardButton(text="⬅️ BACK TO ROSTER", callback_data="cmd_roster"))
    
    await callback.answer()
    await media.edit_banner(callback.message, "Academy", msg, reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("roster_view_"))
async def show_character_details(callback: types.CallbackQuery, user: dict):
    roster_id = callback.data.replace("roster_view_", "")
    user_id = user['telegramId']
    roster = await get_user_roster(user_id)
    char = next((c for c in roster if str(c['_id']) == roster_id), None)
    if not char: return await callback.answer("Data missing.")

    char_roster = [c for c in roster if c['charId'] == char['charId']]
    char_roster.sort(key=lambda x: (x.get('level', 1), x.get('xp', 0)), reverse=True)
    idx = next((i for i, x in enumerate(char_roster) if str(x['_id']) == roster_id), 0)
    
    await callback.answer()
    await render_inspection(callback, char_roster, idx, user_id, user)

@router.callback_query(F.data.startswith("rost_dep_"))
async def handle_deployment(callback: types.CallbackQuery, user: dict):
    parts = callback.data.split("_")
    char_id = parts[2]
    slot_idx = int(parts[3])
    
    team_ids = user.get('teamIds', ["Yuji Itadori", "Megumi Fushiguro", "Nobara Kugisaki"])
    # Ensure team_ids is long enough
    while len(team_ids) <= slot_idx: team_ids.append(None)
    
    team_ids[slot_idx] = char_id
    await db.users.update({"telegramId": user['telegramId']}, {"$set": {"teamIds": team_ids}})
    
    await callback.answer(f"✅ {char_id} deployed to Slot {slot_idx + 1}!", show_alert=True)
    # Refresh view
    roster = await get_user_roster(user['telegramId'])
    char = next((c for c in roster if c['charId'] == char_id), None)
    if char:
        new_callback = callback.model_copy(update={'data': f"roster_view_{char['_id']}"})
        await show_character_details(new_callback, user)

@router.callback_query(F.data.startswith("roster_upg_lvl_"))
async def handle_roster_lvl_up(callback: types.CallbackQuery, user: dict):
    roster_id = callback.data.replace("roster_upg_lvl_", "")
    from services.upgrade_service import upgrade_service
    res = await upgrade_service.level_up_character(callback.from_user.id, roster_id)
    
    if not res['success']:
        return await callback.answer(res['msg'].replace("<b>", "").replace("</b>", ""), show_alert=True)
    
    await callback.answer("✨ Level Up Successful!")
    # Refresh the view
    await show_character_details(callback.model_copy(update={'data': f"roster_view_{roster_id}"}), user)

@router.callback_query(F.data.startswith("roster_upg_star_"))
async def handle_roster_star_up(callback: types.CallbackQuery, user: dict):
    roster_id = callback.data.replace("roster_upg_star_", "")
    # Add star up logic here if available in upgrade_service, or placeholder
    await callback.answer("⭐ Awakening system is under maintenance. Shards collected!", show_alert=True)

@router.callback_query(F.data.startswith("roster_release_conf_"))
async def handle_roster_release_conf(callback: types.CallbackQuery, user: dict):
    roster_id = callback.data.replace("roster_release_conf_", "")
    roster = await get_user_roster(user['telegramId'])
    char = next((c for c in roster if str(c['_id']) == roster_id), None)
    if not char: return await callback.answer("Spirit already departed.")
    
    msg = (
        f"⚠️ <b>CONFIRM DISPOSAL</b>\n\n"
        f"Are you sure you want to release <b>{char['charId']}</b> (Lv.{char.get('level', 1)})?\n"
        f"This action cannot be undone."
    )
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="🔥 YES, RELEASE", callback_data=f"roster_release_exec_{roster_id}:uid_{user['telegramId']}"),
        types.InlineKeyboardButton(text="🔙 CANCEL", callback_data=f"roster_view_{roster_id}:uid_{user['telegramId']}")
    )
    await callback.answer()
    await media.edit_banner(callback.message, "Academy", msg, reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("roster_release_exec_"))
async def handle_roster_release_exec(callback: types.CallbackQuery, user: dict):
    roster_id = callback.data.replace("roster_release_exec_", "")
    roster = await get_user_roster(user['telegramId'])
    char = next((c for c in roster if str(c['_id']) == roster_id), None)
    if not char: return await callback.answer("Spirit already departed.")

    # Calculate rewards based on rarity/level
    base = characters.DATA.get(char['charId'], {})
    rarity = base.get('rarity', 'Common')
    yield_map = {"Common": 50, "Rare": 150, "Epic": 400, "Legendary": 1000, "Mythic": 2500}
    coins = yield_map.get(rarity, 50)
    dust = 10 + (char.get('level', 1) * 2)

    await db.roster.remove({"_id": roster_id})
    await db.users.update({"telegramId": user['telegramId']}, {"$inc": {"coins": coins, "dust": dust}})
    
    await callback.answer(f"✅ Released {char['charId']}! Gained {coins} Coins & {dust} Dust.", show_alert=True)
    await cmd_roster(callback, user)

@router.message(Command("view", "archive"))
async def cmd_archive(message: types.Message):
    await show_global_archive(message, 0)

@router.callback_query(F.data.startswith("view_archive_"))
async def view_archive_callback(callback: types.CallbackQuery):
    page = int(callback.data.split("_")[-1])
    await callback.answer()
    await show_global_archive(callback, page)

async def show_global_archive(callback_or_message, page=0):
    char_names = sorted(characters.DATA.keys())
    limit = 12
    max_page = (len(char_names) + limit - 1) // limit
    page = max(0, min(page, max_page - 1))
    
    slice_names = char_names[page * limit: (page + 1) * limit]
    msg = ui.format_header(f"ARCHIVE ({page + 1}/{max_page})") + "\n\nSelect a soul to inspect its vessel:\n"
    
    builder = InlineKeyboardBuilder()
    for name in slice_names:
        builder.row(types.InlineKeyboardButton(text=name, callback_data=f"cmd_view_char_{name}"))
    
    nav_row = []
    if page > 0:
        nav_row.append(types.InlineKeyboardButton(text="⬅️ PREV", callback_data=f"view_archive_{page - 1}"))
    if page < max_page - 1:
        nav_row.append(types.InlineKeyboardButton(text="NEXT ➡️", callback_data=f"view_archive_{page + 1}"))
    if nav_row: builder.row(*nav_row)
    
    builder.row(types.InlineKeyboardButton(text="🔙 HUB", callback_data="back_to_hub"))

    if isinstance(callback_or_message, types.CallbackQuery):
        await media.edit_banner(callback_or_message.message, "Academy", msg, reply_markup=builder.as_markup())
    else:
        await media.send_banner(callback_or_message.bot, callback_or_message.chat.id, "Academy", msg, reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("cmd_view_char_"))
async def view_char_details_archive(callback: types.CallbackQuery, user: dict):
    char_name = callback.data.replace("cmd_view_char_", "")
    # Find in roster first
    roster = await get_user_roster(user['telegramId'])
    roster_entry = next((c for c in roster if c['charId'] == char_name), None)
    if roster_entry:
        return await show_character_details(callback.model_copy(update={'data': f"roster_view_{roster_entry['_id']}"}), user)
    
    # Otherwise show archive view
    base = characters.DATA.get(char_name)
    if not base: return await callback.answer("Spirit not found.")
    
    msg = ui.format_header(f"ARCHIVE: {base['name']}") + "\n\n"
    msg += "🏮 <b>STATUS:</b> <i>NOT OWNED</i>\n"
    msg += f"🎭 <b>Rarity:</b> {base['rarity']}\n"
    msg += f"🏮 <b>Base Grade:</b> {base.get('grade', 'Unrated')}\n\n"
    msg += f"❤️ <b>Base HP:</b> {base.get('hp', 100)} | 🌀 <b>Base CE:</b> {base.get('ce', 20)}\n"
    msg += f"⚔️ <b>STR:</b> {base.get('attack', 100)} | ⚡ <b>SPD:</b> {base.get('speed', 100)}\n\n"
    msg += f"📝 <b>Description:</b>\n<i>{base.get('description', 'A manifestation of cursed energy.')}</i>\n"
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="⬅️ BACK TO ARCHIVE", callback_data="view_archive_0"))
    
    await callback.answer()
    return await media.edit_portrait(callback.message, base, msg, reply_markup=builder.as_markup())

@router.message(Command("inspect"))
async def cmd_inspect(message: types.Message, user: dict):
    if not user:
        return await message.reply("❌ Please /start first.")
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.reply("❌ <b>USAGE:</b> /inspect &lt;character_name&gt;\nExample: <code>/inspect sukuna</code>", parse_mode='HTML')
    
    import difflib
    query = args[1].lower()
    user_id = user['telegramId']
    
    # 1. Resolve character IDs with fuzzy matching
    all_names = list(characters.DATA.keys())
    ALIASES = getattr(characters, 'ALIASES', {})
    
    matching_ids = []
    for name in characters.DATA:
        if query == name.lower() or query in name.lower():
            matching_ids.append(name)
    
    for alias, target in ALIASES.items():
        if query == alias.lower() or query in alias.lower():
            if target not in matching_ids: matching_ids.append(target)

    if not matching_ids:
        matches = difflib.get_close_matches(query, all_names, n=1, cutoff=0.5)
        if matches:
            best_match = matches[0]
            resolved_id = ALIASES.get(best_match, best_match)
            if resolved_id in characters.DATA:
                matching_ids = [resolved_id]

    if not matching_ids:
        return await message.reply(f"❌ No character found matching '<b>{query}</b>'.", parse_mode='HTML')

    # 2. Search roster for ANY of these IDs
    full_roster = await get_user_roster(user_id)
    roster = [c for c in full_roster if c['charId'] in matching_ids]
    
    if not roster:
        # Show archive for the best match
        target_char = matching_ids[0]
        base = characters.DATA.get(target_char)
        stats = base.get('base_stats', {})
        
        msg = ui.format_header(f"ARCHIVE: {base['name']}") + "\n\n"
        msg += "🏮 <b>STATUS:</b> <i>NOT OWNED (Archive View)</i>\n"
        msg += f"🎭 <b>Rarity:</b> {base['rarity']} | 🏮 <b>Grade:</b> {base.get('grade', 'Unrated')}\n\n"
        
        # Display Max Base Potentials
        msg += f"<b>POTENTIAL STATS:</b>\n"
        msg += f"❤️ <b>HP:</b> {stats.get('TS', [0,100])[1] + stats.get('DUR', [0,10])[1] * 10}\n"
        msg += f"⚔️ <b>STR:</b> {stats.get('STR', [0,5])[1]} | ⚡ <b>SPD:</b> {stats.get('SPD', [0,5])[1]}\n"
        msg += f"🛡️ <b>DUR:</b> {stats.get('DUR', [0,5])[1]} | 🌀 <b>CE:</b> {stats.get('CE', [0,5])[1]}\n"
        msg += f"✨ <b>TS:</b> {stats.get('TS', [0,50])[1]}\n\n"
        
        msg += f"📝 <b>Description:</b>\n<i>{base.get('description', 'A manifestation of cursed energy.')}</i>\n"
        
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="⬅️ BACK TO HUB", callback_data="back_to_hub"))
        return await media.send_portrait(message.bot, message.chat.id, base, msg, reply_markup=builder.as_markup())

    # 3. Sort logic: Level Descending (High to Low)
    roster.sort(key=lambda x: (x.get('level', 1), x.get('xp', 0)), reverse=True)
    
    await render_inspection_selection(message, roster, 0, user_id)

async def render_inspection_selection(callback_or_message, roster, page, user_id):
    items_per_page = 5
    max_page = max(1, (len(roster) - 1) // items_per_page + 1)
    page = max(0, min(page, max_page - 1))
    
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    current_page_items = roster[start_idx:end_idx]
    
    char_id = roster[0]['charId']
    base = characters.DATA[char_id]
    
    msg = f"🔍 <b>SELECT A VESSEL TO INSPECT</b>\n"
    msg += f"<b>Character:</b> {base['name'].upper()}\n"
    msg += f"<b>Total Owned:</b> {len(roster)}\n\n"
    msg += "<i>Select a specific instance from your collection to view its detailed stats, moves, and upgrade options.</i>"
    
    uid = f":uid_{user_id}"
    builder = InlineKeyboardBuilder()
    
    for i, entry in enumerate(current_page_items):
        actual_index = start_idx + i
        lvl = entry.get('level', 1)
        stars = entry.get('stars', 0)
        grade = entry.get('grade', 'Grade 4')
        star_str = f" | {'⭐'*stars}" if stars > 0 else ""
        btn_text = f"Lvl {lvl} • {grade}{star_str}"
        builder.row(types.InlineKeyboardButton(text=btn_text, callback_data=f"ins_view_item_{char_id}_{actual_index}{uid}"))
    
    if max_page > 1:
        nav_row = []
        if page > 0:
            nav_row.append(types.InlineKeyboardButton(text="⬅️", callback_data=f"ins_sel_nav_{char_id}_{page - 1}{uid}"))
        nav_row.append(types.InlineKeyboardButton(text=f"[{page + 1}/{max_page}]", callback_data="none"))
        if page < max_page - 1:
            nav_row.append(types.InlineKeyboardButton(text="➡️", callback_data=f"ins_sel_nav_{char_id}_{page + 1}{uid}"))
        builder.row(*nav_row)
        
    builder.row(types.InlineKeyboardButton(text="🔙 Back to Hub", callback_data="back_to_hub"))

    if isinstance(callback_or_message, types.CallbackQuery):
        await media.edit_portrait(callback_or_message.message, base, msg, reply_markup=builder.as_markup())
    else:
        await media.send_portrait(callback_or_message.bot, callback_or_message.chat.id, base, msg, reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("ins_sel_nav_"))
async def handle_ins_sel_nav(callback: types.CallbackQuery, user: dict):
    parts = callback.data.split("_")
    char_id = parts[3]
    page = int(parts[4].split(":")[0])
    user_id = user['telegramId']
    
    full_roster = await get_user_roster(user_id)
    roster = [c for c in full_roster if c['charId'] == char_id]
    roster.sort(key=lambda x: (x.get('level', 1), x.get('xp', 0)), reverse=True)
    
    await callback.answer()
    await render_inspection_selection(callback, roster, page, user_id)

@router.callback_query(F.data.startswith("ins_view_item_"))
async def handle_ins_view_item(callback: types.CallbackQuery, user: dict):
    parts = callback.data.split("_")
    char_id = parts[3]
    index = int(parts[4].split(":")[0])
    user_id = user['telegramId']
    
    roster = await db.roster.find({"userId": user_id, "charId": char_id})
    roster.sort(key=lambda x: (x.get('level', 1), x.get('xp', 0)), reverse=True)
    
    await callback.answer()
    await render_inspection(callback, roster, index, user_id)

def _build_tp_ts_table(entry, base):
    lvl = entry.get('level', 1)
    rarity_mult = {"Common": 1.0, "Rare": 1.1, "Epic": 1.25, "Legendary": 1.4, "Mythic": 1.6}.get(base.get('rarity', 'Common'), 1.0)
    
    tp = entry.get('tp', 100 + int((rarity_mult-1)*1000) + (lvl * 5))
    ts = entry.get('ts', 100 + (lvl * 10))
    
    tp_mult = 1.0 + (tp / 2000.0)
    ts_flat = ts / 5.0
    
    # Base values for breakdown (mirroring user_service logic)
    b_pwr = base.get('atk', 15) * 5 * rarity_mult
    b_spd = base.get('speed', 12) * 5 * rarity_mult
    b_stm = (base.get('maxHp', 200) / 10) * 5 * rarity_mult
    b_ce  = base.get('maxCe', 100) * rarity_mult
    b_tec = (base.get('speed', 12) + base.get('resilience', 5)) * 5 * rarity_mult
    
    table = (
        f"<code>"
        f"Points        TP   |  TS\n"
        f"————————————————————————\n"
        f"HP           {int((b_stm*tp_mult*10)+(b_tec*tp_mult*2)):>4} | {int((ts_flat*10)+(ts_flat*2)):>4}\n"
        f"Attack       {int(b_pwr*tp_mult):>4} | {int(ts_flat):>4}\n"
        f"Defense      {int(b_stm*tp_mult):>4} | {int(ts_flat):>4}\n"
        f"Speed        {int(b_spd*tp_mult):>4} | {int(ts_flat):>4}\n"
        f"Stamina      {int(b_ce*tp_mult):>4} | {int(ts_flat):>4}\n"
        f"————————————————————————\n"
        f"Total        {int(tp):>4} | {int(ts):>4}"
        f"</code>"
    )
    return table


@router.callback_query(F.data.startswith("ins_tp_ts_menu_"))
async def handle_inspect_tp_ts_menu(callback: types.CallbackQuery, user: dict):
    rid = callback.data.split("_")[4].split(":")[0]
    uid = f":uid_{user['telegramId']}"
    
    from bson import ObjectId
    roster = await get_user_roster(user['telegramId'])
    entry = next((c for c in roster if str(c['_id']) == rid), None)
    if not entry: return await callback.answer("Spirit not found.")
    base = characters.DATA.get(entry['charId'])
    
    table = _build_tp_ts_table(entry, base)
    msg = (
        f"📊 <b>POTENTIAL & STATS — {base['name'].upper()}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{table}\n\n"
        f"<i>Potential (TP) is expanded using Sukuna Fingers/Scrolls.\n"
        f"Raw Stats (TS) are boosted using Fragments/Shards.</i>"
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="🧬 Boost Potential (TP)", callback_data=f"ins_boost_tp_{rid}{uid}"),
        types.InlineKeyboardButton(text="📈 Boost Raw Stats (TS)", callback_data=f"ins_boost_ts_{rid}{uid}")
    )
    builder.row(types.InlineKeyboardButton(text="🔙 Back to Inspect", callback_data=f"ins_v_back_{rid}{uid}"))
    
    await callback.answer()
    await media.smart_edit(callback.message, msg, reply_markup=builder.as_markup())

async def render_inspection(callback_or_message, roster, index, user_id, user=None):
    entry = roster[index]
    char_id = entry['charId']
    base = characters.DATA[char_id]
    if user is None:
        user = cache_service.get_user(user_id)
        if user is None:
            user = await db.users.find_one({"telegramId": user_id})
    
    # Calculate stats
    from services.user_service import user_service
    full_stats = user_service.calculate_final_stats(entry, base)
    lvl = entry.get('level', 1)
    xp = entry.get('xp', 0)
    needed = lvl * 15 # Required EXP for level up
    
    header = f"💎 <b>{base['name'].upper()}</b>"
    
    body = (
        f"<b>╔{'═' * 20}╗</b>\n"
        f"  <b>Character:</b> {base['name']}\n"
        f"  <b>Grade:</b> {full_stats['grade']}\n"
        f"  <b>XP:</b> <code>{xp}/{needed}</code>\n"
        f"<b>╚{'═' * 20}╝</b>"
    )

    uid = f":uid_{user_id}"
    rid = str(entry['_id'])
    builder = InlineKeyboardBuilder()
    
    # Top Row: Moves & Stats
    builder.row(
        types.InlineKeyboardButton(text="🥋 Moves", callback_data=f"ins_moves_{rid}{uid}"),
        types.InlineKeyboardButton(text="📊 TP/TS", callback_data=f"ins_tp_ts_menu_{rid}{uid}")
    )
    
    # Mid Row: Management
    builder.row(
        types.InlineKeyboardButton(text="⚔️ Item Hold", callback_data=f"ins_equip_{rid}{uid}"),
        types.InlineKeyboardButton(text="🏮 Grade Up", callback_data=f"ins_gradeup_{rid}{uid}"),
        types.InlineKeyboardButton(text="🆙 Level Up", callback_data=f"ins_lvlup_{rid}{uid}")
    )
    
    # Team Management
    current_stars = entry.get('stars', 0)
    user_shards = user.get('shards', {})
    available_shards = user_shards.get(char_id, 0)
    awaken_txt = f"⭐️ AWAKEN{' (!)' if available_shards >= (current_stars + 1) else ''}"
    
    is_team = char_id in user.get('teamIds', [])
    builder.row(
        types.InlineKeyboardButton(text=awaken_txt, callback_data=f"roster_upg_star_{rid}{uid}"),
        types.InlineKeyboardButton(text="💸 SELL", callback_data=f"roster_release_conf_{rid}{uid}" if not is_team else "none")
    )
    builder.row(
        types.InlineKeyboardButton(text="🛰 DEPLOY: 1", callback_data=f"rost_dep_{char_id}_0{uid}"),
        types.InlineKeyboardButton(text="🛰 DEPLOY: 2", callback_data=f"rost_dep_{char_id}_1{uid}"),
        types.InlineKeyboardButton(text="🛰 DEPLOY: 3", callback_data=f"rost_dep_{char_id}_2{uid}")
    )
    
    # Navigation if multiple instances
    if len(roster) > 1:
        nav_row = []
        if index > 0:
            nav_row.append(types.InlineKeyboardButton(text="⬅️", callback_data=f"ins_v_{char_id}_{index - 1}{uid}"))
        nav_row.append(types.InlineKeyboardButton(text=f"[{index+1}/{len(roster)}]", callback_data="none"))
        if index < len(roster) - 1:
            nav_row.append(types.InlineKeyboardButton(text="➡️", callback_data=f"ins_v_{char_id}_{index + 1}{uid}"))
        builder.row(*nav_row)
    
    builder.row(
        types.InlineKeyboardButton(text="📋 Back to List", callback_data=f"ins_sel_nav_{char_id}_0{uid}"),
        types.InlineKeyboardButton(text="🔙 Hub", callback_data="back_to_hub")
    )

    from utils.combat.visual import visual_engine
    buffer = await visual_engine.generate_inspection_card(entry, base, full_stats)
    
    if buffer:
        cache_key = f"ins_{rid}_{lvl}_{full_stats.get('hp', 0)}"
        if isinstance(callback_or_message, types.CallbackQuery):
            await media.edit_generated_photo(callback_or_message.message, buffer, cache_key, body, reply_markup=builder.as_markup())
        else:
            await media.send_generated_photo(callback_or_message.bot, callback_or_message.chat.id, buffer, cache_key, body, reply_markup=builder.as_markup())
    else:
        if isinstance(callback_or_message, types.CallbackQuery):
            await media.edit_portrait(callback_or_message.message, base, body, reply_markup=builder.as_markup())
        else:
            await media.send_portrait(callback_or_message.bot, callback_or_message.chat.id, base, body, reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("ins_v_"))
async def handle_inspection_nav(callback: types.CallbackQuery, user: dict):
    parts = callback.data.split("_")
    if len(parts) < 4: return await callback.answer("Invalid data.")
    char_id = parts[2]
    index = int(parts[3].split(":")[0])
    user_id = user['telegramId']
    
    # Search roster for these IDs to re-sort
    full_roster = await get_user_roster(user_id)
    roster = [c for c in full_roster if c['charId'] == char_id]
    roster.sort(key=lambda x: (x.get('level', 1), x.get('xp', 0)), reverse=True)
    
    await callback.answer()
    await render_inspection(callback, roster, index, user_id, user)

@router.callback_query(F.data.startswith("ins_v_back_"))
async def handle_inspect_back(callback: types.CallbackQuery, user: dict):
    rid = callback.data.split("_")[-1].split(":")[0]
    user_id = user['telegramId']
    
    full_roster = await get_user_roster(user_id)
    entry = next((c for c in full_roster if str(c['_id']) == rid), None)
    if not entry: return await callback.answer("Error.")
    
    roster = [c for c in full_roster if c['charId'] == entry['charId']]
    roster.sort(key=lambda x: (x.get('level', 1), x.get('xp', 0)), reverse=True)
    idx = next((i for i, x in enumerate(roster) if str(x['_id']) == rid), 0)
    
    await callback.answer()
    await render_inspection(callback, roster, idx, user_id, user)

@router.callback_query(F.data.startswith("ins_lvlup_"))
async def handle_inspect_lvlup(callback: types.CallbackQuery, user: dict):
    rid = callback.data.split("_")[2].split(":")[0]
    user_id = user['telegramId']
    
    from services.upgrade_service import upgrade_service
    res = await upgrade_service.level_up_character(user_id, rid)
    
    if not res['success']:
        return await callback.answer(res['msg'].replace("<b>", "").replace("</b>", "").replace("❌", "").strip(), show_alert=True)
    
    await callback.answer("🆙 Leveled Up!", show_alert=True)
    
    # Re-render
    full_roster = await get_user_roster(user_id)
    entry = next((c for c in full_roster if str(c['_id']) == rid), None)
    if entry:
        roster = [c for c in full_roster if c['charId'] == entry['charId']]
        roster.sort(key=lambda x: (x.get('level', 1), x.get('xp', 0)), reverse=True)
        idx = next((i for i, x in enumerate(roster) if str(x['_id']) == rid), 0)
        await render_inspection(callback, roster, idx, user_id, user)

@router.callback_query(F.data.startswith("ins_boost_tp_"))
async def handle_inspect_boost_tp(callback: types.CallbackQuery, user: dict):
    rid = callback.data.split("_")[3].split(":")[0]
    # Uses Scroll or Finger
    inv = user.get('inventory', [])
    item = next((i for i in inv if i['id'] in ["finger", "scroll"] and i['qty'] > 0), None)
    
    if not item:
        return await callback.answer("❌ Need a Sukuna Finger or Six Eyes Scroll to boost Potential!", show_alert=True)
    
    # Update inventory
    item['qty'] -= 1
    final_inv = [i for i in inv if i['qty'] > 0]
    
    # Update character TP
    boost = 250 if item['id'] == "finger" else 100
    from bson import ObjectId
    await db.users.update({"telegramId": user['telegramId']}, {"$set": {"inventory": final_inv}})
    await db.roster.update({"_id": ObjectId(rid)}, {"$inc": {"tp": boost}})
    
    await callback.answer(f"🧬 TP BOOSTED BY {boost}!", show_alert=True)
    
    # Re-render
    full_roster = await get_user_roster(user['telegramId'])
    entry = next((c for c in full_roster if str(c['_id']) == rid), None)
    if entry:
        roster = [c for c in full_roster if c['charId'] == entry['charId']]
        roster.sort(key=lambda x: (x.get('level', 1), x.get('xp', 0)), reverse=True)
        idx = next((i for i, x in enumerate(roster) if str(x['_id']) == rid), 0)
        await render_inspection(callback, roster, idx, user['telegramId'], user)

@router.callback_query(F.data.startswith("ins_boost_ts_"))
async def handle_inspect_boost_ts(callback: types.CallbackQuery, user: dict):
    rid = callback.data.split("_")[3].split(":")[0]
    # Uses Fragment or Shard
    inv = user.get('inventory', [])
    item = next((i for i in inv if i['id'] in ["fragment", "dshard"] and i['qty'] > 0), None)
    
    if not item:
        return await callback.answer("❌ Need a Cursed Fragment or Domain Shard to boost Stats!", show_alert=True)
    
    # Update inventory
    item['qty'] -= 1
    final_inv = [i for i in inv if i['qty'] > 0]
    
    # Update character TS
    boost = 50 if item['id'] == "dshard" else 15
    from bson import ObjectId
    await db.users.update({"telegramId": user['telegramId']}, {"$set": {"inventory": final_inv}})
    await db.roster.update({"_id": ObjectId(rid)}, {"$inc": {"ts": boost}})
    
    await callback.answer(f"📈 TS BOOSTED BY {boost}!", show_alert=True)
    
    # Re-render
    full_roster = await get_user_roster(user['telegramId'])
    entry = next((c for c in full_roster if str(c['_id']) == rid), None)
    if entry:
        roster = [c for c in full_roster if c['charId'] == entry['charId']]
        roster.sort(key=lambda x: (x.get('level', 1), x.get('xp', 0)), reverse=True)
        idx = next((i for i, x in enumerate(roster) if str(x['_id']) == rid), 0)
        await render_inspection(callback, roster, idx, user['telegramId'], user)

@router.callback_query(F.data.startswith("ins_nick_"))
async def handle_inspect_nick(callback: types.CallbackQuery):
    await callback.answer("🏷️ Nickname system coming soon!", show_alert=True)

@router.message(Command("nickname"))
async def cmd_nickname(message: types.Message, user: dict):
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        return await message.reply("❌ Usage: <code>/nickname [ID] [New Name]</code>", parse_mode='HTML')
    
    rid = args[1]
    new_nick = args[2].strip()[:20] # Limit length
    
    from bson import ObjectId
    try:
        res = await db.roster.update({"_id": ObjectId(rid), "userId": user['telegramId']}, {"$set": {"nickname": new_nick}})
        if res:
            await message.reply(f"✅ Nickname set to: <b>{new_nick}</b>", parse_mode='HTML')
        else:
            await message.reply("❌ Character not found or not yours.")
    except:
        await message.reply("❌ Invalid Character ID.")

@router.callback_query(F.data.startswith("ins_equip_"))
async def handle_inspect_equip(callback: types.CallbackQuery, user: dict):
    rid = callback.data.split("_")[2].split(":")[0]
    uid = f":uid_{user['telegramId']}"
    
    # List tools from inventory
    tools = ["katana", "nails", "cloud", "spear"]
    inv = user.get('inventory', [])
    owned_tools = [i for i in inv if i['id'] in tools and i['qty'] > 0]
    
    if not owned_tools:
        return await callback.answer("❌ You don't have any Cursed Tools in your inventory!", show_alert=True)
    
    msg = "⚔️ <b>EQUIP CURSED TOOL</b>\n\nSelect a tool to hold:"
    builder = InlineKeyboardBuilder()
    for tool in owned_tools:
        item = ITEMS.get(tool['id'])
        builder.row(types.InlineKeyboardButton(text=f"{item['icon']} {item['name']}", callback_data=f"ins_do_equip_{rid}_{tool['id']}{uid}"))
    
    builder.row(types.InlineKeyboardButton(text="❌ Unequip", callback_data=f"ins_do_equip_{rid}_none{uid}"))
    builder.row(types.InlineKeyboardButton(text="🔙 Back", callback_data=f"ins_v_back_{rid}{uid}"))
    
    await callback.answer()
    await media.smart_edit(callback.message, msg, reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("ins_do_equip_"))
async def handle_inspect_do_equip(callback: types.CallbackQuery, user: dict):
    parts = callback.data.split("_")
    rid = parts[3]
    item_id = parts[4].split(":")[0]
    
    from bson import ObjectId
    try:
        new_item = None if item_id == "none" else item_id
        await db.roster.update({"_id": ObjectId(rid), "userId": user['telegramId']}, {"$set": {"heldItem": new_item}})
        await callback.answer(f"✅ Item {'unequipped' if not new_item else 'equipped'}!", show_alert=True)
        
        # Re-render inspection
        full_roster = await get_user_roster(user['telegramId'])
        entry = next((c for c in full_roster if str(c['_id']) == rid), None)
        if entry:
            roster = [c for c in full_roster if c['charId'] == entry['charId']]
            roster.sort(key=lambda x: (x.get('level', 1), x.get('xp', 0)), reverse=True)
            idx = next((i for i, x in enumerate(roster) if str(x['_id']) == rid), 0)
            await render_inspection(callback, roster, idx, user['telegramId'], user)
    except:
        await callback.answer("❌ Error equipping item.")

@router.callback_query(F.data.startswith("ins_moves_"))
async def handle_inspect_moves(callback: types.CallbackQuery, user: dict):
    rid = callback.data.split("_")[2].split(":")[0]
    uid = f":uid_{user['telegramId']}"
    
    full_roster = await get_user_roster(user['telegramId'])
    entry = next((c for c in full_roster if str(c['_id']) == rid), None)
    if not entry: return await callback.answer("Character not found.")
    
    base = characters.DATA.get(entry['charId'])
    moves = base.get('moves', [])
    
    msg = f"🥋 <b>{base['name'].upper()} TECHNIQUES</b>\n━━━━━━━━━━━━━━\n\n"
    
    TYPE_ICONS = {
        "Fire": "🔥", "Water": "💧", "Ice": "❄️", "Wind": "🌪", "Electric": "⚡",
        "Normal": "🔘", "Dragon": "🐉", "Poison": "☣️", "Barrier": "🔮", 
        "Close-range": "👊", "Long-range": "🏹", "Psychic": "🌀"
    }

    for m in moves:
        m_type = m.get('type', 'Normal')
        icon = TYPE_ICONS.get(m_type, "🔘")
        dmg = m.get('dmg', [0,0])
        pwr = dmg[0] if isinstance(dmg, list) else dmg
        acc = m.get('accuracy', 100)
        cat = "Physical" if m_type == "Close-range" else "Special"
        
        msg += (
            f"╭─「 {m['name']} 」\n"
            f"├─ Type: {m_type} ({icon})\n"
            f"├─ Power: {pwr} | Accuracy: {acc}\n"
            f"└─ Category: {cat}\n\n"
        )

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔙 Back", callback_data=f"ins_v_back_{rid}{uid}"))
    
    await callback.answer()
    await media.smart_edit(callback.message, msg, reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("ins_gradeup_"))
async def handle_inspect_gradeup(callback: types.CallbackQuery, user: dict):
    rid = callback.data.split("_")[2].split(":")[0]
    uid = f":uid_{user['telegramId']}"
    
    from services.upgrade_service import upgrade_service
    res = await upgrade_service.promote_grade(user['telegramId'], rid)
    
    if not res['success']:
        return await callback.answer(res['msg'].replace("<b>", "").replace("</b>", "").replace("❌", "").strip(), show_alert=True)
    
    await callback.answer("🎖 Grade Promoted!", show_alert=True)
    # Re-render inspection
    full_roster = await get_user_roster(user['telegramId'])
    entry = next((c for c in full_roster if str(c['_id']) == rid), None)
    if entry:
        roster = [c for c in full_roster if c['charId'] == entry['charId']]
        roster.sort(key=lambda x: (x.get('level', 1), x.get('xp', 0)), reverse=True)
        idx = next((i for i, x in enumerate(roster) if str(x['_id']) == rid), 0)
        await render_inspection(callback, roster, idx, user['telegramId'], user)
