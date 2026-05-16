import random
import time
import re
from aiogram import Router, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command

from database import db
from utils import ui, media
from utils.data.items import ITEMS

router = Router()

async def render_inventory(callback_or_message, user, category=None):
    inv = user.get('inventory', [])
    uid = f":uid_{user['telegramId']}"
    
    # Import CF_ITEMS here to prevent circular imports
    from utils.handlers.shop import CF_ITEMS
    
    if not category:
        msg = (
            "⚡ <b>Yᴏᴜʀ Iɴᴠᴇɴᴛᴏʀʏ</b> 👇\n\n"
            f"💰 <b>Cᴏɪɴꜱ :</b> <code>{user.get('coins', 0):,}</code>\n"
            f"✨ <b>Dᴜꜱᴛ :</b> <code>{user.get('dust', 0):,}</code>\n"
            f"💎 <b>Gᴇᴍꜱ :</b> <code>{user.get('gems', 0):,}</code>\n"
            f"🎟️ <b>Tɪᴄᴋᴇᴛꜱ :</b> <code>{user.get('gachaTickets', 0):,}</code>\n\n"
            "<i>Select a category below to view your items.</i>"
        )
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="🗡️ Weapons", callback_data=f"inv_cat_weapons{uid}"))
        builder.row(types.InlineKeyboardButton(text="🎒 Items", callback_data=f"inv_cat_items{uid}"))
        builder.row(types.InlineKeyboardButton(text="🧩 Fragments (CF)", callback_data=f"inv_cat_cfs{uid}"))
        builder.row(types.InlineKeyboardButton(text="🔙 Return to Hub", callback_data=f"back_to_hub{uid}"))

        if isinstance(callback_or_message, types.CallbackQuery):
            await media.edit_banner(callback_or_message.message, "inventory", msg, reply_markup=builder.as_markup())
        else:
            await media.send_banner(callback_or_message.bot, callback_or_message.chat.id, "inventory", msg, reply_markup=builder.as_markup())
        return

    weapons_ids = ['katana', 'nails', 'cloud', 'spear']
    
    filtered_inv = []
    for entry in inv:
        item_id = str(entry['id'])
        item_data = ITEMS.get(item_id) or CF_ITEMS.get(item_id)
        if not item_data: continue
        
        is_weapon = item_id in weapons_ids
        is_cf = item_id.startswith('cf')
        
        if category == 'weapons' and is_weapon:
            filtered_inv.append((entry, item_data))
        elif category == 'cfs' and is_cf:
            filtered_inv.append((entry, item_data))
        elif category == 'items' and not is_weapon and not is_cf:
            filtered_inv.append((entry, item_data))

    if category == 'weapons': cat_name = "Weapons"
    elif category == 'cfs': cat_name = "Cursed Fragments"
    else: cat_name = "Items"
    
    msg = f"⚡ <b>Yᴏᴜʀ Iɴᴠᴇɴᴛᴏʀʏ - {cat_name}</b> 👇\n\n"
    builder = InlineKeyboardBuilder()
    
    if not filtered_inv:
        msg += "<i>You don't have any items in this category.</i>\n\n"
    elif category == 'cfs':
        # Text-based format for CFs
        msg += "🧩 <b>CFs:</b>\n\n"
        for entry, item_data in filtered_inv:
            raw_id = item_data['id']
            # Clean up the name (e.g. "CF: Divergent Fist" -> "Divergent Fist")
            clean_name = item_data['name'].replace("CF:", "").replace("CF: ", "").strip()
            msg += f"  • /{raw_id} [{clean_name}]: {entry['qty']}\n"
        msg += "\n<i>Tap a command above to view details.</i>"
    else:
        # Button-based format for Weapons & Items
        msg += "<i>Tap an item to view details.</i>\n\n"
        for entry, item_data in filtered_inv:
            icon = item_data.get('icon', '📦')
            builder.row(types.InlineKeyboardButton(
                text=f"{icon} {item_data['name']} (x{entry['qty']})", 
                callback_data=f"view_inv_{entry['id']}{uid}"
            ))
    
    builder.row(types.InlineKeyboardButton(text="🔙 Back to Categories", callback_data=f"cmd_inv{uid}"))

    if isinstance(callback_or_message, types.CallbackQuery):
        await media.edit_banner(callback_or_message.message, "inventory", msg, reply_markup=builder.as_markup())
    else:
        await media.send_banner(callback_or_message.bot, callback_or_message.chat.id, "inventory", msg, reply_markup=builder.as_markup())

# --- COMMAND HANDLER FOR CLICKING A CF COMMAND (e.g. /cf109) ---
@router.message(F.text.regexp(r"^/(cf\d+)$"))
async def cmd_view_cf_direct(message: types.Message, user: dict):
    if not user: return
    
    cf_id = message.text.strip()[1:].lower() # Gets "cf109" from "/cf109"
    from utils.handlers.shop import CF_ITEMS
    
    item = CF_ITEMS.get(cf_id)
    if not item: 
        return await message.reply("❌ Cursed Fragment not found in the archives.")

    inv_entry = next((i for i in user.get('inventory', []) if i['id'] == cf_id), None)
    if not inv_entry or inv_entry['qty'] <= 0: 
        return await message.reply("❌ You do not own this Cursed Fragment.")

    uid = f":uid_{user['telegramId']}"
    builder = InlineKeyboardBuilder()

    type_str = "CURSED FRAGMENT"
    desc = (
        f"⚔️ <b>Power:</b> {item.get('power', 0)}\n"
        f"🎯 <b>Accuracy:</b> {item.get('accuracy', 0)}%\n\n"
        f"<i>A fragment holding a cursed technique. This can be equipped to your sorcerers to grant them new abilities in combat.</i>"
    )
    
    msg = (
        ui.format_header(item['name']) + "\n\n"
        f"Type: <b>{type_str}</b>\n"
        f"Quantity: <b>{inv_entry['qty']}</b>\n\n"
        f"{desc}"
    )

    builder.row(types.InlineKeyboardButton(text="⬅️ Back to CFs", callback_data=f"inv_cat_cfs{uid}"))
    await media.send_banner(message.bot, message.chat.id, "inventory", msg, reply_markup=builder.as_markup())


@router.message(Command("inventory", "inv"))
@router.callback_query(F.data.startswith("cmd_inv"))
async def cmd_inventory(callback_or_message: types.CallbackQuery | types.Message, user: dict):
    if not user:
        if isinstance(callback_or_message, types.CallbackQuery):
            await callback_or_message.answer("❌ Please /start first.", show_alert=True)
        else:
            await callback_or_message.reply("❌ Please /start first.")
        return
    if isinstance(callback_or_message, types.CallbackQuery):
        await callback_or_message.answer()
    await render_inventory(callback_or_message, user)

@router.callback_query(F.data.startswith("inv_cat_"))
async def cmd_inventory_category(callback: types.CallbackQuery, user: dict):
    cat = callback.data.replace("inv_cat_", "").split(":")[0]
    await callback.answer()
    await render_inventory(callback, user, category=cat)

@router.callback_query(F.data.startswith("view_inv_"))
async def view_item_details(callback: types.CallbackQuery, user: dict):
    item_id = callback.data.replace("view_inv_", "").split(":")[0]
    
    from utils.handlers.shop import CF_ITEMS
    
    item = ITEMS.get(item_id) or CF_ITEMS.get(item_id)
    if not item: 
        return await callback.answer("Item not found.")
    await callback.answer()

    inv_entry = next((i for i in user.get('inventory', []) if i['id'] == item_id), None)
    if not inv_entry or inv_entry['qty'] <= 0: 
        return await callback.answer("You no longer own this item.")

    uid = f":uid_{user['telegramId']}"
    builder = InlineKeyboardBuilder()

    if item_id.startswith('cf'):
        type_str = "CURSED FRAGMENT"
        desc = (
            f"⚔️ <b>Power:</b> {item.get('power', 0)}\n"
            f"🎯 <b>Accuracy:</b> {item.get('accuracy', 0)}%\n\n"
            f"<i>A fragment holding a cursed technique. This can be equipped to your sorcerers to grant them new abilities in combat.</i>"
        )
    else:
        type_str = item.get('shop', {}).get('category', 'Consumable').upper()
        desc = f"<i>{item.get('description', '')}</i>"
        usable_out_of_battle = [
            'energy_drink', 'exp_ticket', 'cursed_charm', 'exp_charm', 
            'minor_hp_potion', 'ce_charge', 'elixir', 'fragment', 
            'pill', 'dshard', 'reset_orb'
        ]
        if item_id in usable_out_of_battle:
            builder.row(types.InlineKeyboardButton(text=f"✨ Use {item['name']}", callback_data=f"use_inv_{item_id}{uid}"))

    msg = (
        ui.format_header(item['name']) + "\n\n"
        f"Type: <b>{type_str}</b>\n"
        f"Quantity: <b>{inv_entry['qty']}</b>\n\n"
        f"{desc}"
    )

    builder.row(types.InlineKeyboardButton(text="⬅️ Back to Bag", callback_data=f"cmd_inv{uid}"))
    await media.edit_banner(callback.message, item_id, msg, reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("use_inv_"))
async def use_item(callback: types.CallbackQuery, user: dict):
    item_id = callback.data.replace("use_inv_", "").split(":")[0]
    inv = user.get('inventory', [])
    inv_entry = next((i for i in inv if i['id'] == item_id), None)

    if not inv_entry or inv_entry['qty'] <= 0:
        return await callback.answer("❌ You don't have enough of this item!", show_alert=True)

    update_result = ""
    set_ops = {}
    inc_ops = {}

    if item_id == 'energy_drink':
        inc_ops['dailyExploreCount'] = -100
        update_result = "✅ Hunt Limit Restored! (Daily hunt count reduced by 100)"
    elif item_id == 'max_stamina_potion':
        set_ops['dailyExploreCount'] = 0
        update_result = "🔥 EXPEDITION BURST! Daily limit reset to 0/1000."
    elif item_id == 'soul_shard':
        inc_ops['dust'] = 100
        update_result = "✨ Soul Shard Shattered! +100 Dust acquired."
    elif item_id == 'mystery_box':
        roll = random.random()
        if roll < 0.4:
            inc_ops['coins'] = 1000
            update_result = "🎁 Mystery Box Opened: Found 1000 Coins!"
        elif roll < 0.7:
            inc_ops['gachaTickets'] = 2
            update_result = "🎁 Mystery Box Opened: Found 2x Gacha Tickets!"
        else:
            inc_ops['dust'] = 50
            update_result = "🎁 Mystery Box Opened: Found +50 Dust!"
    elif item_id == 'exp_ticket':
        expiry = int((time.time() + (24 * 60 * 60)) * 1000)
        set_ops['hasExplorationTicket'] = True
        set_ops['expTicketExpiry'] = expiry
        update_result = "✅ Activation Successful! You have unlimited explorations for 24h."
    elif item_id == 'cursed_charm':
        set_ops['activeCursedCharm'] = True
        update_result = "🧿 Cursed Charm Active! Your next hunt will have a massive capture bonus."
    elif item_id == 'exp_charm':
        set_ops['activeExpCharm'] = True
        update_result = "✨ EXP Charm Active! Your team will gain double XP in their next battle."
    elif item_id == 'pill':
        inc_ops['stamina'] = 50
        update_result = "💊 Energy Pill consumed! Restored 50 Stamina."
    elif item_id == 'elixir':
        set_ops['activeElixir'] = True
        update_result = "🍷 Reverse Elixir Active! Your team will start the next battle with massive HP regeneration potential."
    elif item_id == 'fragment':
        set_ops['activeFragment'] = True
        update_result = "🧿 Cursed Fragment Absorbed! Your team starts the next battle with +50 initial CE."
    elif item_id == 'dshard':
        set_ops['activeDomainShard'] = True
        update_result = "🔥 Domain Shard Resonating! Your team's Ultimate Techniques will deal +50% damage in the next battle."
    elif item_id == 'reset_orb':
        return await callback.answer("🌀 Use the Technique Reset Orb from the /upgrades menu to select a character!", show_alert=True)
    elif item_id in ['minor_hp_potion', 'ce_charge']:
        return await callback.answer("⚔️ This is a combat item! Use it during a battle.", show_alert=True)

    inv_entry['qty'] -= 1
    final_inv = [i for i in inv if i['qty'] > 0]
    
    set_ops['inventory'] = final_inv
    
    await db.users.update({"telegramId": user['telegramId']}, {
        "$set": set_ops,
        "$inc": inc_ops
    })

    user.update(set_ops)
    for k, v in inc_ops.items():
        user[k] = user.get(k, 0) + v

    await callback.answer(update_result, show_alert=True)
    await render_inventory(callback, user)

