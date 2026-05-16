import math
from aiogram import Router, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import db
from utils import ui, media
from utils.data import characters
from utils.handlers.shop import CF_ITEMS

router = Router()

# ==========================================
# 📱 SCREEN 1: THE COMMAND (/cf109)
# ==========================================
@router.message(F.text.regexp(r"^/(cf\d+)$"))
async def cmd_cf_direct(message: types.Message, user: dict):
    if not user: return
    
    cf_id = message.text.strip()[1:].lower() 
    
    item = CF_ITEMS.get(cf_id)
    if not item: 
        return await message.reply("❌ Cursed Fragment not found in the archives.")

    inv_entry = next((i for i in user.get('inventory', []) if i['id'] == cf_id), None)
    if not inv_entry or inv_entry['qty'] <= 0: 
        return await message.reply("❌ You do not own this Cursed Fragment.")

    uid = f":uid_{user['telegramId']}"
    builder = InlineKeyboardBuilder()

    clean_name = item['name'].replace("CF: ", "").replace("CF:", "").strip()
    
    desc = (
        f"⚔️ <b>Power:</b> {item.get('power', 0)}\n"
        f"🎯 <b>Accuracy:</b> {item.get('accuracy', 0)}%\n\n"
        f"<i>A fragment holding a cursed technique. This can be equipped to your sorcerers to grant them new abilities in combat.</i>"
    )
    
    msg = (
        ui.format_header(item['name']) + "\n\n"
        f"Type: <b>CURSED FRAGMENT</b>\n"
        f"Quantity: <b>{inv_entry['qty']}</b>\n\n"
        f"{desc}"
    )

    # The new "Use Fragment" button
    builder.row(types.InlineKeyboardButton(text="✨ Use Fragment", callback_data=f"cf_use_{cf_id}_0{uid}"))
    builder.row(types.InlineKeyboardButton(text="❌ Close", callback_data=f"delete_msg{uid}"))
    
    await media.send_banner(message.bot, message.chat.id, "inventory", msg, reply_markup=builder.as_markup())


# ==========================================
# 📱 SCREEN 2: CHARACTER SELECTION
# ==========================================
@router.callback_query(F.data.startswith("cf_use_"))
async def cb_cf_use(callback: types.CallbackQuery, user: dict):
    data_parts = callback.data.split(":")[0].split("_")
    cf_id = data_parts[2]
    page = int(data_parts[3])

    cf_data = CF_ITEMS.get(cf_id)
    if not cf_data:
        return await callback.answer("Fragment data lost.", show_alert=True)

    inv_entry = next((i for i in user.get('inventory', []) if i['id'] == cf_id), None)
    if not inv_entry or inv_entry['qty'] <= 0:
        return await callback.answer("❌ You don't have this fragment anymore!", show_alert=True)

    roster = await db.roster.find({"userId": user['telegramId']}).to_list(length=None)
    if not roster:
        return await callback.answer("❌ You don't own any sorcerers yet!", show_alert=True)

    items_per_page = 10
    total_pages = math.ceil(len(roster) / items_per_page)
    start_idx = page * items_per_page
    current_roster = roster[start_idx:start_idx + items_per_page]

    msg = (
        f"👤 <b>SELECT A SORCERER</b>\n"
        f"{ui.divider()}\n"
        f"Who will absorb the <b>{cf_data['name'].replace('CF: ', '')}</b> technique?\n\n"
        f"<i>(Note: Only characters that you currently own are shown below).</i>"
    )

    builder = InlineKeyboardBuilder()
    for char in current_roster:
        char_id = char['charId']
        base_char = characters.DATA.get(char_id, {})
        char_name = base_char.get('name', char_id.title().replace('_', ' '))
        builder.row(types.InlineKeyboardButton(
            text=f"{char_name} (Lv.{char.get('level', 1)})",
            callback_data=f"cf_sel_{cf_id}_{char_id}"
        ))

    uid = f":uid_{user['telegramId']}"
    nav_row = []
    if page > 0:
        nav_row.append(types.InlineKeyboardButton(text="⬅️ Prev Page", callback_data=f"cf_use_{cf_id}_{page-1}{uid}"))
    if page < total_pages - 1:
        nav_row.append(types.InlineKeyboardButton(text="Next Page ➡️", callback_data=f"cf_use_{cf_id}_{page+1}{uid}"))
    if nav_row:
        builder.row(*nav_row)

    builder.row(types.InlineKeyboardButton(text="🔙 Cancel", callback_data=f"delete_msg{uid}"))
    await media.smart_edit(callback.message, msg, reply_markup=builder.as_markup())


# ==========================================
# 📱 SCREEN 3: MOVE SELECTION
# ==========================================
@router.callback_query(F.data.startswith("cf_sel_"))
async def cb_cf_select_move(callback: types.CallbackQuery, user: dict):
    data_parts = callback.data.split(":")[0].split("_")
    cf_id = data_parts[2]
    char_id = "_".join(data_parts[3:])

    cf_data = CF_ITEMS.get(cf_id)
    base_char = characters.DATA.get(char_id)
    char_entry = await db.roster.find_one({"userId": user['telegramId'], "charId": char_id})

    if not cf_data or not base_char or not char_entry:
        return await callback.answer("Error loading data.", show_alert=True)

    current_moves = char_entry.get('custom_moves', base_char.get('moves', []))
    clean_cf_name = cf_data['name'].replace('CF: ', '')
    char_display_name = base_char.get('name', char_id.title().replace('_', ' '))

    msg = (
        f"🥋 <b>EQUIP TECHNIQUE: {char_display_name.upper()}</b>\n"
        f"{ui.divider()}\n"
        f"You are equipping <b>{clean_cf_name}</b>.\n"
        f"Select which current technique you want to overwrite:\n\n"
    )

    builder = InlineKeyboardBuilder()
    for i, move in enumerate(current_moves):
        name = move.get('name', 'Unknown')
        dmg = move.get('dmg', [0, 0])
        dmg_str = f"{dmg[0]}-{dmg[1]}" if isinstance(dmg, list) else str(dmg)
        ce = move.get('ce', 0)
        ce_str = "Free" if ce <= 0 else f"{ce} CE"

        msg += f"{i+1}️⃣ <b>{name}</b> (DMG: {dmg_str} | CE: {ce_str})\n"
        builder.row(types.InlineKeyboardButton(
            text=f"♻️ Replace Slot {i+1}",
            callback_data=f"cf_conf_{cf_id}_{char_id}_{i}"
        ))

    if len(current_moves) < 4:
        builder.row(types.InlineKeyboardButton(
            text="➕ Add to Empty Slot",
            callback_data=f"cf_conf_{cf_id}_{char_id}_{len(current_moves)}"
        ))

    uid = f":uid_{user['telegramId']}"
    builder.row(types.InlineKeyboardButton(text="🔙 Back to Sorcerers", callback_data=f"cf_use_{cf_id}_0{uid}"))
    await media.smart_edit(callback.message, msg, reply_markup=builder.as_markup())


# ==========================================
# 📱 SCREEN 4: CONFIRMATION & EXECUTION
# ==========================================
@router.callback_query(F.data.startswith("cf_conf_"))
async def cb_cf_confirm(callback: types.CallbackQuery, user: dict):
    data_parts = callback.data.split(":")[0].split("_")
    cf_id = data_parts[2]
    char_id = "_".join(data_parts[3:-1])
    slot_idx = int(data_parts[-1])

    cf_data = CF_ITEMS.get(cf_id)
    base_char = characters.DATA.get(char_id)
    char_entry = await db.roster.find_one({"userId": user['telegramId'], "charId": char_id})

    current_moves = char_entry.get('custom_moves', base_char.get('moves', []))
    clean_cf_name = cf_data['name'].replace('CF: ', '')
    char_display_name = base_char.get('name', char_id.title().replace('_', ' '))

    losing_move_name = "None (Empty Slot)"
    if slot_idx < len(current_moves):
        losing_move_name = current_moves[slot_idx].get('name', 'Unknown')

    msg = (
        f"⚠️ <b>CONFIRM OVERWRITE</b>\n"
        f"{ui.divider()}\n"
        f"Are you absolutely sure you want to alter <b>{char_display_name}</b>'s abilities?\n\n"
        f"❌ <b>Losing:</b> {losing_move_name}\n"
        f"✨ <b>Gaining:</b> {clean_cf_name} (Power: {cf_data['power']})\n\n"
        f"<i>This action will consume 1x CF: {clean_cf_name} from your inventory.</i>"
    )

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="✅ Confirm & Equip", callback_data=f"cf_apply_{cf_id}_{char_id}_{slot_idx}"))
    builder.row(types.InlineKeyboardButton(text="❌ Cancel", callback_data=f"cf_sel_{cf_id}_{char_id}"))
    await media.smart_edit(callback.message, msg, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("cf_apply_"))
async def cb_cf_apply(callback: types.CallbackQuery, user: dict):
    data_parts = callback.data.split(":")[0].split("_")
    cf_id = data_parts[2]
    char_id = "_".join(data_parts[3:-1])
    slot_idx = int(data_parts[-1])

    inv = user.get('inventory', [])
    inv_idx = next((i for i, x in enumerate(inv) if x['id'] == cf_id), -1)

    if inv_idx == -1 or inv[inv_idx]['qty'] <= 0:
        return await callback.answer("❌ You don't have this fragment anymore!", show_alert=True)

    cf_data = CF_ITEMS.get(cf_id)
    base_char = characters.DATA.get(char_id)
    char_entry = await db.roster.find_one({"userId": user['telegramId'], "charId": char_id})

    # Pull existing custom moves, or copy base moves to start modifying
    current_moves = char_entry.get('custom_moves', base_char.get('moves', []).copy())

    calculated_ce = int(cf_data.get('power', 0) * 0.4)
    if calculated_ce < 10 and cf_data.get('power', 0) > 0:
        calculated_ce = 10

    new_move = {
        "name": cf_data['name'].replace('CF: ', '').strip(),
        "dmg": cf_data.get('power', 0),
        "ce": calculated_ce,
        "type": "Cursed Technique",
        "accuracy": cf_data.get('accuracy', 100),
        "is_cf": True,
        "cf_id": cf_id
    }

    if slot_idx < len(current_moves):
        current_moves[slot_idx] = new_move
    else:
        current_moves.append(new_move)

    # Consume Item & Save DB
    inv[inv_idx]['qty'] -= 1
    inv = [i for i in inv if i['qty'] > 0]
    
    await db.users.update({"telegramId": user['telegramId']}, {"$set": {"inventory": inv}})
    await db.roster.update({"_id": char_entry["_id"]}, {"$set": {"custom_moves": current_moves}})

    clean_cf_name = cf_data['name'].replace('CF: ', '')
    char_display_name = base_char.get('name', char_id.title().replace('_', ' '))

    # Final Success Screen
    msg = (
        f"🎉 <b>TECHNIQUE ASSIMILATED</b>\n"
        f"{ui.divider()}\n"
        f"<b>{char_display_name}</b> has successfully learned <b>{clean_cf_name}</b>!\n\n"
        f"You can view their updated stats using <code>/view {char_display_name}</code>."
    )
    
    uid = f":uid_{user['telegramId']}"
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="❌ Close", callback_data=f"delete_msg{uid}"))
    
    await callback.answer("✅ Technique Equipped!", show_alert=False)
    await media.smart_edit(callback.message, msg, reply_markup=builder.as_markup())


# Clean up handler for deleting the message
@router.callback_query(F.data.startswith("delete_msg"))
async def cb_delete_msg(callback: types.CallbackQuery):
    await callback.message.delete()

