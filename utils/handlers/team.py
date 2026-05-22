from aiogram import Router, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command

from database import db
from utils import ui, media
from utils.data import characters
from utils.combat.visual import visual_engine

async def _text_send(bot_or_msg, *args, **kwargs):
    """Send team menu as plain text."""
    if hasattr(bot_or_msg, 'answer'):
        return await bot_or_msg.answer(kwargs.get('caption', args[2] if len(args)>2 else ''), parse_mode='HTML', reply_markup=kwargs.get('reply_markup'))
    return await bot_or_msg.send_message(args[0], kwargs.get('caption', args[2] if len(args)>2 else ''), parse_mode='HTML', reply_markup=kwargs.get('reply_markup'))

async def _text_edit(message, *args, **kwargs):
    try:
        return await message.edit_text(kwargs.get('caption', args[1] if len(args)>1 else ''), parse_mode='HTML', reply_markup=kwargs.get('reply_markup'))
    except Exception:
        return await message.reply(kwargs.get('caption', args[1] if len(args)>1 else ''), parse_mode='HTML', reply_markup=kwargs.get('reply_markup'))

router = Router()

async def render_team_menu(callback_or_message, user):
    user_id = user['telegramId']
    from services.cache_service import cache_service
    cached = cache_service.get_roster(user_id)
    if cached is not None:
        roster = cached
    else:
        try:
            roster = await db.roster.find({"userId": user_id})
        except Exception:
            roster = []
        cache_service.set_roster(user_id, roster)

    team_ids = user.get('teamIds', [])
    if not team_ids and roster:
        team_ids = [r['charId'] for r in roster[:3]]
        await db.users.update({"telegramId": user_id}, {"$set": {"teamIds": team_ids}})
        user['teamIds'] = team_ids

    # Prepare character data for visual card
    team_data = []
    for char_id in team_ids:
        if char_id in characters.DATA:
            char_info = characters.DATA[char_id].copy()
            char_info['name'] = char_id
            # Try to get level from roster
            entry = next((r for r in roster if r['charId'] == char_id), {})
            char_info['level'] = entry.get('level', 1)
            # Basic stats scaling for visual
            char_info['hp'] = char_info.get('hp', 100) + (char_info['level'] * 15)
            char_info['atk'] = char_info.get('atk', 10) + (char_info['level'] * 3)
            team_data.append(char_info)

    # Generate Image with Cache Key
    cache_key = f"team_{user_id}_" + "_".join([f"{c['name']}_{c['level']}" for c in team_data])
    buffer = await visual_engine.generate_team_card(team_data)
    
    caption = ui.format_header("SQUAD MANAGEMENT") + "\n\n"
    if not team_ids:
        caption += "⚠️ <b>Team Empty!</b> Add sorcerers to your squad to begin combat."
    else:
        pos_names = ["1️⃣ FRONT", "2️⃣ MIDDLE", "3️⃣ BACK"]
        for i, char_id in enumerate(team_ids):
            label = pos_names[i] if i < 3 else f"🔹 Slot {i+1}"
            caption += f"<b>{label}:</b> {char_id}\n"

    uid = f":uid_{user_id}"
    builder = InlineKeyboardBuilder()
    
    # Character specific actions (Front/Remove)
    for i, char_id in enumerate(team_ids):
        # We'll use short names for buttons
        short_name = char_id.split()[-1] if " " in char_id else char_id
        if i > 0:
            builder.row(
                types.InlineKeyboardButton(text=f"⏫ {short_name} to Front", callback_data=f"team_front_{i}{uid}"),
                types.InlineKeyboardButton(text="❌", callback_data=f"team_remove_exec_{i}{uid}")
            )
        else:
            builder.row(
                types.InlineKeyboardButton(text=f"⭐ {short_name} (Lead)", callback_data="nop"),
                types.InlineKeyboardButton(text="❌", callback_data=f"team_remove_exec_{i}{uid}")
            )

    builder.row(
        types.InlineKeyboardButton(text="➕ Add Sorcerer", callback_data=f"team_add_menu_0{uid}"),
        types.InlineKeyboardButton(text="🔄 Refresh", callback_data=f"cmd_team{uid}")
    )
    builder.row(types.InlineKeyboardButton(text="🔙 Back to Hub", callback_data=f"back_to_hub{uid}"))

    if buffer:
        if isinstance(callback_or_message, types.CallbackQuery):
            await media.edit_generated_photo(callback_or_message.message, buffer, cache_key, caption, reply_markup=builder.as_markup())
        else:
            await media.send_generated_photo(callback_or_message.bot, callback_or_message.chat.id, buffer, cache_key, caption, reply_markup=builder.as_markup())
    else:
        # Fallback to text
        if isinstance(callback_or_message, types.CallbackQuery):
            await media.smart_edit(callback_or_message.message, caption, reply_markup=builder.as_markup())
        else:
            await callback_or_message.answer(caption, parse_mode='HTML', reply_markup=builder.as_markup())

@router.message(Command("myteam", "myscorer"))
@router.callback_query(F.data.startswith("cmd_team"))
async def cmd_team(callback_or_message: types.CallbackQuery | types.Message, user: dict):
    if isinstance(callback_or_message, types.CallbackQuery):
        await callback_or_message.answer()
    if not user:
        msg = callback_or_message.message if isinstance(callback_or_message, types.CallbackQuery) else callback_or_message
        return await msg.answer("Please /start first to register.")
    await render_team_menu(callback_or_message, user)

@router.callback_query(F.data == "team_remove_menu")
async def team_remove_menu(callback: types.CallbackQuery, user: dict):
    msg = "Select a character to remove:"
    uid = f":uid_{user['telegramId']}"
    builder = InlineKeyboardBuilder()
    for i, char_id in enumerate(user.get('teamIds', [])):
        builder.row(types.InlineKeyboardButton(text=char_id, callback_data=f"team_remove_exec_{i}{uid}"))
    builder.row(types.InlineKeyboardButton(text="Back", callback_data=f"cmd_team{uid}"))
    await callback.answer()
    await media.smart_edit(callback.message, msg, reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("team_remove_exec_"))
async def team_remove_exec(callback: types.CallbackQuery, user: dict):
    slot_idx = int(callback.data.split("_")[-1])
    if len(user['teamIds']) > slot_idx:
        user['teamIds'].pop(slot_idx)
        await db.users.update({"telegramId": user['telegramId']}, {"$set": {"teamIds": user['teamIds']}})
    await callback.answer("Character removed.")
    await render_team_menu(callback, user)

@router.callback_query(F.data.startswith("team_add_menu_"))
async def team_add_menu(callback: types.CallbackQuery, user: dict):
    page = int(callback.data.split("_")[-1])
    user_id = user['telegramId']
    from services.cache_service import cache_service
    cached = cache_service.get_roster(user_id)
    if cached is not None:
        roster = cached
    else:
        try:
            roster = await db.roster.find({"userId": user_id})
        except Exception:
            roster = []
        cache_service.set_roster(user_id, roster)
    
    bench = [r for r in roster if r['charId'] not in user.get('teamIds', [])]
    bench.sort(key=lambda x: x.get('level', 1), reverse=True)
    
    page_size = 5
    total_pages = max(1, (len(bench) + page_size - 1) // page_size)
    start = page * page_size
    visible_bench = bench[start:start+page_size]

    if len(user.get('teamIds', [])) >= 4:
        await callback.answer("Team is full! Remove a character first.", show_alert=True)
        return

    msg = "Select a character to add:"
    uid = f":uid_{user['telegramId']}"
    builder = InlineKeyboardBuilder()
    for b in visible_bench:
        builder.row(types.InlineKeyboardButton(text=f"{b['charId']} (Lv{b.get('level', 1)})", callback_data=f"team_add_exec_{b['charId']}{uid}"))
    
    nav_row = []
    if page > 0:
        nav_row.append(types.InlineKeyboardButton(text="Prev", callback_data=f"team_add_menu_{page-1}{uid}"))
    if page < total_pages - 1:
        nav_row.append(types.InlineKeyboardButton(text="Next", callback_data=f"team_add_menu_{page+1}{uid}"))
    if nav_row: builder.row(*nav_row)

    builder.row(types.InlineKeyboardButton(text="Back", callback_data=f"cmd_team{uid}"))
    await callback.answer()
    await media.smart_edit(callback.message, msg, reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("team_add_exec_"))
async def team_add_exec(callback: types.CallbackQuery, user: dict):
    new_id = callback.data.split("team_add_exec_")[-1]
    
    if len(user.get('teamIds', [])) >= 4:
        await callback.answer("Team is full!", show_alert=True)
        return
        
    user['teamIds'].append(new_id)
    await db.users.update({"telegramId": user['telegramId']}, {"$set": {"teamIds": user['teamIds']}})
    
    await callback.answer("Character added.")
    await render_team_menu(callback, user)

@router.callback_query(F.data.startswith("team_front_"))
async def team_front(callback: types.CallbackQuery, user: dict):
    idx = int(callback.data.split("_")[2])
    if 0 < idx < len(user['teamIds']):
        # Shifting logic: Move character to front, others shift back
        char_id = user['teamIds'].pop(idx)
        user['teamIds'].insert(0, char_id)
        await db.users.update({"telegramId": user['telegramId']}, {"$set": {"teamIds": user['teamIds']}})
        await callback.answer(f"⭐ {char_id} is now your Lead!")
    else:
        await callback.answer()
    await render_team_menu(callback, user)

@router.callback_query(F.data == "team_reorder_menu")
async def team_reorder_menu(callback: types.CallbackQuery, user: dict):
    # This legacy menu is replaced by the 'Set as Front' buttons in the main view
    await callback.answer("Please use the main menu buttons to reorder.")
    await render_team_menu(callback, user)

@router.callback_query(F.data.startswith("team_move_"))
async def team_move(callback: types.CallbackQuery, user: dict):
    # Legacy move logic replaced by shifting
    await callback.answer()
    await render_team_menu(callback, user)
