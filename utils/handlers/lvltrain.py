from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import db
from utils import ui, media
from utils.data import characters
from services.user_service import user_service

router = Router()

COST_PER_LEVEL = 250

@router.message(Command("lvltrain"))
@router.callback_query(F.data == "cmd_lvltrain")
async def cmd_lvltrain(callback_or_message: types.CallbackQuery | types.Message, user: dict):
    # 1. Check if it's a DM (Private Chat)
    msg = callback_or_message.message if isinstance(callback_or_message, types.CallbackQuery) else callback_or_message
    if msg.chat.type != "private":
        reply_text = "⚠️ <b>TRAINING GROUNDS</b>\nTraining can only be done in DMs to maintain focus."
        if isinstance(callback_or_message, types.CallbackQuery):
            return await callback_or_message.answer(reply_text.replace("<b>", "").replace("</b>", ""), show_alert=True)
        else:
            return await msg.reply(reply_text, parse_mode='HTML')

    if isinstance(callback_or_message, types.CallbackQuery):
        await callback_or_message.answer()

    await render_train_menu(callback_or_message, user, page=0)

@router.callback_query(F.data.startswith("lvltrain_page_"))
async def cb_lvltrain_page(callback: types.CallbackQuery, user: dict):
    page = int(callback.data.replace("lvltrain_page_", ""))
    await callback.answer()
    await render_train_menu(callback, user, page)

async def render_train_menu(cob: types.CallbackQuery | types.Message, user: dict, page: int = 0):
    user_id = user['telegramId']
    roster = await db.roster.find({"userId": user_id})
    
    # Sort roster by level descending to show strongest characters first
    roster.sort(key=lambda x: x.get('level', 1), reverse=True)
    
    msg_text = (
        ui.format_header("TRAINING GROUNDS") + "\n\n"
        "Welcome to the dojo. Spend your coins to push your sorcerers past their limits!\n\n"
        f"💰 <b>Your Balance:</b> <code>{user.get('coins', 0):,} Coins</code>\n"
        f"🏷 <b>Cost per Level:</b> <code>{COST_PER_LEVEL} Coins</code>\n\n"
        "<i>Select a character to train:</i>"
    )
    
    builder = InlineKeyboardBuilder()
    
    # Pagination Logic
    items_per_page = 5
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    current_items = roster[start_idx:end_idx]
    
    for char in current_items:
        char_id_str = str(char['_id'])
        btn_text = f"🏮 {char['charId']} (Lv. {char.get('level', 1)})"
        builder.row(types.InlineKeyboardButton(text=btn_text, callback_data=f"lvltrain_exec_{char_id_str}"))
        
    # Navigation Row
    nav_row = []
    if page > 0:
        nav_row.append(types.InlineKeyboardButton(text="⬅️ Previous", callback_data=f"lvltrain_page_{page-1}"))
    if end_idx < len(roster):
        nav_row.append(types.InlineKeyboardButton(text="Next ➡️", callback_data=f"lvltrain_page_{page+1}"))
    if nav_row:
        builder.row(*nav_row)
        
    builder.row(types.InlineKeyboardButton(text="🔙 Back to Hub", callback_data="back_to_hub"))
    
    if isinstance(cob, types.CallbackQuery):
        await media.smart_edit(cob.message, msg_text, reply_markup=builder.as_markup())
    else:
        await cob.reply(msg_text, parse_mode='HTML', reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("lvltrain_exec_"))
async def cb_lvltrain_exec(callback: types.CallbackQuery, user: dict):
    roster_id = callback.data.replace("lvltrain_exec_", "")
    
    # 1. Fetch character from Roster
    char_entry = await db.roster.find_one({"_id": roster_id})
    if not char_entry or char_entry['userId'] != user['telegramId']:
        return await callback.answer("❌ Character not found.", show_alert=True)
        
    # 2. Check balance
    if user.get('coins', 0) < COST_PER_LEVEL:
        return await callback.answer(f"❌ Not enough coins! You need {COST_PER_LEVEL}.", show_alert=True)
        
    # 3. Calculate Old Stats
    base_char = characters.DATA.get(char_entry['charId'], {})
    old_stats = user_service.calculate_final_stats(char_entry, base_char)
    
    # 4. Process the Transaction
    await db.users.update({"telegramId": user['telegramId']}, {"$inc": {"coins": -COST_PER_LEVEL}})
    await db.roster.update({"_id": roster_id}, {"$inc": {"level": 1}})
    
    # Temporarily update the local dictionary so the success screen is accurate
    user['coins'] = user.get('coins', 0) - COST_PER_LEVEL
    char_entry['level'] = char_entry.get('level', 1) + 1
    
    # 5. Calculate New Stats
    new_stats = user_service.calculate_final_stats(char_entry, base_char)
    
    # 6. Build the Success Screen
    msg_text = (
        ui.format_header("TRAINING COMPLETE!") + "\n\n"
        f"<b>{char_entry['charId']}</b> endured the brutal training and leveled up!\n\n"
        f"📈 <b>Level:</b> <code>{old_stats['level']}</code> ➔ <code>{new_stats['level']}</code>\n"
        f"❤️ <b>Max HP:</b> <code>{old_stats['maxHp']:,}</code> ➔ <code>{new_stats['maxHp']:,}</code>\n"
        f"🌀 <b>Cursed Energy:</b> <code>{old_stats['maxCe']:,}</code> ➔ <code>{new_stats['maxCe']:,}</code>\n\n"
        f"💰 <b>Remaining Balance:</b> <code>{user['coins']:,} Coins</code>"
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text=f"🏋️‍♂️ Train Again (-{COST_PER_LEVEL} Coins)", callback_data=f"lvltrain_exec_{roster_id}"))
    builder.row(types.InlineKeyboardButton(text="🔙 Back to Roster", callback_data="cmd_lvltrain"))
    
    await callback.answer("✨ Level Up Successful!", show_alert=False)
    await media.smart_edit(callback.message, msg_text, reply_markup=builder.as_markup())

