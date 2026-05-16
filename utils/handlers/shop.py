import time
import difflib
from datetime import datetime, timedelta
from aiogram import Router, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command

from database import db
from utils import ui, media
from utils.data.items import ITEMS
from services.shop_service import shop_service

router = Router()

ITEM_NICKNAMES = {
    "katana": "katana",
    "nails": "nails",
    "cloud": "cloud",
    "spear": "spear",
    "elixir": "elixir",
    "fragment": "fragment",
    "pill": "pill",
    "shard": "dshard",
    "scroll": "scroll",
    "finger": "finger",
    "orb": "reset_orb"
}

def resolve_item_id(nick: str) -> str:
    """Resolves an item ID from a nickname with auto-correction."""
    nick = nick.lower().strip()
    if nick in ITEM_NICKNAMES:
        return ITEM_NICKNAMES[nick]
    
    # Fuzzy matching
    matches = difflib.get_close_matches(nick, ITEM_NICKNAMES.keys(), n=1, cutoff=0.6)
    if matches:
        return ITEM_NICKNAMES[matches[0]]
    return None

@router.message(Command("shop"))
@router.callback_query(F.data == "shop_menu")
async def cmd_shop(callback_or_message: types.CallbackQuery | types.Message, user: dict):
    if isinstance(callback_or_message, types.CallbackQuery):
        await callback_or_message.answer()

    msg = (
        "🛒 <b>Cᴜʀꜱᴇᴅ Mᴀʀᴋᴇᴛ</b>\n"
        "━━━━━━━━━━━━━━\n"
        f" 🪙 <b>Yᴏᴜʀ Cᴏɪɴꜱ:</b> <code>{user.get('coins', 0):,}</code>\n\n"
        "🔮 <b>Cᴜʀꜱᴇᴅ Tᴏᴏʟꜱ:</b>\n"
        "🗡️ Split Soul Katana — 500 🪙\n"
        "🔨 Resonance Nails — 250 🪙\n"
        "🗃️ Playful Cloud — 800 🪙\n"
        "📿 Inverted Spear — 1,200 🪙\n\n"
        "⚡ <b>Cᴏɴꜱᴜᴍᴀʙʟᴇꜱ:</b>\n"
        "🍷 Reverse Elixir — 150 🪙\n"
        "🧿 Cursed Fragment — 300 🪙\n"
        "💊 Energy Pill — 100 🪙\n"
        "🔥 Domain Shard — 750 🪙\n\n"
        "🎴 <b>Sᴩᴇᴄɪᴀʟ Iᴛᴇᴍꜱ:</b>\n"
        "👁️ Six Eyes Scroll — 5,000 🪙\n"
        "👑 Sukuna Finger — 10,000 🪙\n"
        "🌀 Technique Reset Orb — 3,500 🪙\n\n"
        "━━━━━━━━━━━━━━\n"
        "🛍️ <b>Bᴜʏ:</b> <code>/buy [item] [qty]</code>\n"
        "💰 <b>Sᴇʟʟ:</b> <code>/sell [item] [qty]</code>\n\n"
        "<i>Exᴀᴍᴩʟᴇ:</i>\n"
        " <code>/buy katana 1</code>\n"
        " <code>/buy finger</code>\n"
        " <code>/sell shard 2</code>"
    )

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🏪 CF Store", callback_data="shop_cf_store"))

    if isinstance(callback_or_message, types.CallbackQuery):
        await media.edit_banner(callback_or_message.message, "Market", msg, reply_markup=builder.as_markup())
    else:
        await media.send_banner(callback_or_message.bot, callback_or_message.chat.id, "Market", msg, reply_markup=builder.as_markup())


@router.message(Command("buy"))
async def handle_buy(message: types.Message, user: dict):
    args = message.text.split()
    if len(args) < 2:
        return await message.reply("🛍️ <b>Usage:</b> <code>/buy [item] [qty]</code>\nExample: <code>/buy katana 1</code>", parse_mode='HTML')

    nick = args[1].lower()
    qty = 1
    if len(args) > 2 and args[2].isdigit():
        qty = int(args[2])

    item_id = resolve_item_id(nick)
    if not item_id:
        return await message.reply("❌ That item is not in the market archives. Check for typos!")

    item = ITEMS.get(item_id)
    total_cost = item['price'] * qty

    if user.get('coins', 0) < total_cost:
        msg = f"❌ You don't have enough coins. Need 🪙 {total_cost:,}."
        return await media.send_banner(message.bot, message.chat.id, item_id, msg)

    # Execute purchase via shop_service
    for _ in range(qty):
        res = await shop_service.buy_item(user['telegramId'], item_id)
        if not res['success']:
            msg = f"❌ Purchase failed: {res['msg']}"
            return await media.send_banner(message.bot, message.chat.id, item_id, msg)

    msg = (
        f"✅ <b>PURCHASE SUCCESSFUL!</b>\n\n"
        f"You bought <b>{qty}x {item['name']}</b> for 🪙 <b>{total_cost:,}</b>.\n"
        f"Remaining Balance: 🪙 <b>{user.get('coins', 0) - total_cost:,}</b>"
    )
    await media.send_banner(message.bot, message.chat.id, item_id, msg)


@router.message(Command("sell"))
async def handle_sell(message: types.Message, user: dict):
    args = message.text.split()
    if len(args) < 2:
        return await message.reply("💰 <b>Usage:</b> <code>/sell [item] [qty]</code>\nExample: <code>/sell shard 2</code>", parse_mode='HTML')

    nick = args[1].lower()
    qty = 1
    if len(args) > 2 and args[2].isdigit():
        qty = int(args[2])

    item_id = resolve_item_id(nick)
    if not item_id:
        return await message.reply("❌ That item cannot be sold here. Check for typos!")

    item = ITEMS.get(item_id)
    # Sell price is usually 50% of buy price
    sell_price = int(item['price'] * 0.5)
    total_gain = sell_price * qty

    # Check inventory
    inv = user.get('inventory', [])
    inv_entry = next((i for i in inv if i['id'] == item_id), None)
    
    if not inv_entry or inv_entry['qty'] < qty:
        msg = f"❌ You don't have {qty}x {item['name']} in your bag."
        return await media.send_banner(message.bot, message.chat.id, item_id, msg)

    # Execute sell
    inv_entry['qty'] -= qty
    final_inv = [i for i in inv if i['qty'] > 0]
    
    await db.users.update({"telegramId": user['telegramId']}, {
        "$set": {"inventory": final_inv},
        "$inc": {"coins": total_gain}
    })

    msg = (
        f"🤝 <b>SALE COMPLETE!</b>\n\n"
        f"You sold <b>{qty}x {item['name']}</b> for 🪙 <b>{total_gain:,}</b>.\n"
        f"New Balance: 🪙 <b>{user.get('coins', 0) + total_gain:,}</b>"
    )
    await media.send_banner(message.bot, message.chat.id, item_id, msg)

@router.message(Command("give"))
async def handle_give_admin(message: types.Message, user: dict):
    # Admin Check (Owner ID from logs)
    if message.from_user.id != 7454452968:
        return

    args = message.text.split()
    if len(args) < 2:
        return await message.reply("🛠 <b>Admin Give:</b> <code>/give [item_nick] [qty]</code>", parse_mode='HTML')

    nick = args[1].lower()
    qty = 1
    if len(args) > 2 and args[2].isdigit():
        qty = int(args[2])

    item_id = resolve_item_id(nick)
    if not item_id:
        return await message.reply("❌ Invalid item nickname.")

    item = ITEMS.get(item_id)
    
    # Determine target
    target_id = message.from_user.id
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
    
    target_user = await db.users.find_one({"telegramId": target_id})
    if not target_user:
        return await message.reply("❌ Target user not found in database.")

    # Add to inventory
    inv = target_user.get('inventory', [])
    found = False
    for entry in inv:
        if entry['id'] == item_id:
            entry['qty'] += qty
            found = True
            break
    if not found:
        inv.append({"id": item_id, "qty": qty})
    
    await db.users.update({"telegramId": target_id}, {"$set": {"inventory": inv}})
    
    await message.reply(f"🎁 <b>GIFT SENT!</b>\n\nTarget: <code>{target_id}</code>\nItem: <b>{qty}x {item['name']}</b>", parse_mode='HTML')

@router.message(Command("gift"))
async def handle_gift(message: types.Message, user: dict):
    if not message.reply_to_message:
        return await message.reply("🎁 <b>Usage:</b> Reply to someone with <code>/gift [item] [qty]</code>", parse_mode='HTML')

    args = message.text.split()
    if len(args) < 2:
        return await message.reply("🎁 <b>Usage:</b> <code>/gift [item] [qty]</code>", parse_mode='HTML')

    nick = args[1].lower()
    qty = 1
    if len(args) > 2 and args[2].isdigit():
        qty = int(args[2])

    item_id = resolve_item_id(nick)
    if not item_id:
        return await message.reply("❌ Item not found. Check for typos!")

    item = ITEMS.get(item_id)
    
    # Check sender inventory
    inv = user.get('inventory', [])
    sender_entry = next((i for i in inv if i['id'] == item_id), None)
    
    if not sender_entry or sender_entry['qty'] < qty:
        return await message.reply(f"❌ You don't have {qty}x {item['name']} to gift.")

    target_id = message.reply_to_message.from_user.id
    if target_id == message.from_user.id:
        return await message.reply("❌ You can't gift to yourself!")

    target_user = await db.users.find_one({"telegramId": target_id})
    if not target_user:
        return await message.reply("❌ Recipient must be a registered sorcerer.")

    # Transaction
    sender_entry['qty'] -= qty
    final_inv_sender = [i for i in inv if i['qty'] > 0]
    
    target_inv = target_user.get('inventory', [])
    found = False
    for entry in target_inv:
        if entry['id'] == item_id:
            entry['qty'] += qty
            found = True
            break
    if not found:
        target_inv.append({"id": item_id, "qty": qty})
    
    await db.users.update({"telegramId": user['telegramId']}, {"$set": {"inventory": final_inv_sender}})
    await db.users.update({"telegramId": target_id}, {"$set": {"inventory": target_inv}})
    
    await message.reply(
        f"🎁 <b>GIFT DELIVERED!</b>\n\n"
        f"You sent <b>{qty}x {item['name']}</b> to "
        f"<b>{message.reply_to_message.from_user.full_name}</b>!",
        parse_mode='HTML'
    )

@router.callback_query(F.data == "nop")
async def nop(callback: types.CallbackQuery):
    await callback.answer("This item is sold out!")

import random

# ==========================================
#              CF STORE LOGIC
# ==========================================

CF_ITEMS = {
    "cf109": {"id": "cf109", "name": "CF: Divergent Fist", "price": 5000, "power": 70, "accuracy": 100},
    "cf16":  {"id": "cf16", "name": "CF: Black Flash", "price": 12000, "power": 120, "accuracy": 85},
    "cf287": {"id": "cf287", "name": "CF: Cleave", "price": 10000, "power": 110, "accuracy": 95},
    "cf54":  {"id": "cf54", "name": "CF: Dismantle", "price": 8000, "power": 90, "accuracy": 100},
    "cf193": {"id": "cf193", "name": "CF: Blast Away", "price": 8000, "power": 85, "accuracy": 95},
    "cf72":  {"id": "cf72", "name": "CF: Don't Move", "price": 5000, "power": 40, "accuracy": 100},
    "cf241": {"id": "cf241", "name": "CF: Boogie Woogie", "price": 8000, "power": 0, "accuracy": 100},
    "cf8":   {"id": "cf8", "name": "CF: Ratio Technique", "price": 8000, "power": 95, "accuracy": 95},
    "cf156": {"id": "cf156", "name": "CF: Resonance", "price": 8000, "power": 100, "accuracy": 90},
    "cf299": {"id": "cf299", "name": "CF: Hairpin", "price": 5000, "power": 75, "accuracy": 100},
    "cf44":  {"id": "cf44", "name": "CF: Piercing Blood", "price": 10000, "power": 105, "accuracy": 90},
    "cf211": {"id": "cf211", "name": "CF: Supernova", "price": 8000, "power": 95, "accuracy": 95},
    "cf95":  {"id": "cf95", "name": "CF: Blood Edge", "price": 8000, "power": 80, "accuracy": 100},
    "cf268": {"id": "cf268", "name": "CF: Hollow Purple", "price": 15000, "power": 160, "accuracy": 75},
    "cf131": {"id": "cf131", "name": "CF: Red", "price": 10000, "power": 110, "accuracy": 90},
    "cf27":  {"id": "cf27", "name": "CF: Blue", "price": 8000, "power": 85, "accuracy": 100},
    "cf184": {"id": "cf184", "name": "CF: Infinity Crush", "price": 8000, "power": 0, "accuracy": 100},
    "cf300": {"id": "cf300", "name": "CF: Maximum Uzumaki", "price": 15000, "power": 145, "accuracy": 80},
    "cf63":  {"id": "cf63", "name": "CF: CS Manipulation", "price": 8000, "power": 90, "accuracy": 95},
    "cf147": {"id": "cf147", "name": "CF: Idle Transfiguration", "price": 12000, "power": 130, "accuracy": 85},
    "cf11":  {"id": "cf11", "name": "CF: Soul Touch", "price": 5000, "power": 75, "accuracy": 100},
    "cf222": {"id": "cf222", "name": "CF: HR Strike", "price": 10000, "power": 100, "accuracy": 100},
    "cf88":  {"id": "cf88", "name": "CF: Split Soul Katana", "price": 10000, "power": 115, "accuracy": 90},
    "cf175": {"id": "cf175", "name": "CF: Playful Cloud Smash", "price": 8000, "power": 95, "accuracy": 100},
    "cf259": {"id": "cf259", "name": "CF: Jacob's Ladder", "price": 15000, "power": 140, "accuracy": 80},
    "cf39":  {"id": "cf39", "name": "CF: Angel Wings", "price": 8000, "power": 85, "accuracy": 95},
    "cf118": {"id": "cf118", "name": "CF: Granite Blast", "price": 12000, "power": 125, "accuracy": 85},
    "cf203": {"id": "cf203", "name": "CF: Sky Manipulation", "price": 8000, "power": 90, "accuracy": 95},
    "cf67":  {"id": "cf67", "name": "CF: Thin Ice Breaker", "price": 10000, "power": 110, "accuracy": 90},
    "cf290": {"id": "cf290", "name": "CF: Projection Sorcery", "price": 5000, "power": 70, "accuracy": 100},
    "cf14":  {"id": "cf14", "name": "CF: Frame Freeze", "price": 8000, "power": 85, "accuracy": 95},
    "cf233": {"id": "cf233", "name": "CF: Divine Dogs", "price": 8000, "power": 80, "accuracy": 100},
    "cf81":  {"id": "cf81", "name": "CF: Nue Lightning", "price": 8000, "power": 95, "accuracy": 95},
    "cf170": {"id": "cf170", "name": "CF: Toad Bind", "price": 5000, "power": 60, "accuracy": 100},
    "cf276": {"id": "cf276", "name": "CF: Max Elephant", "price": 12000, "power": 120, "accuracy": 85},
    "cf52":  {"id": "cf52", "name": "CF: Rabbit Escape", "price": 5000, "power": 0, "accuracy": 100},
    "cf198": {"id": "cf198", "name": "CF: Mahoraga Slash", "price": 15000, "power": 150, "accuracy": 70},
    "cf124": {"id": "cf124", "name": "CF: Ice Formation", "price": 8000, "power": 100, "accuracy": 90},
    "cf35":  {"id": "cf35", "name": "CF: Frost Calm", "price": 8000, "power": 80, "accuracy": 100},
    "cf214": {"id": "cf214", "name": "CF: Lightning God Strike", "price": 12000, "power": 130, "accuracy": 85},
    "cf91":  {"id": "cf91", "name": "CF: Star Rage Punch", "price": 10000, "power": 115, "accuracy": 90},
    "cf261": {"id": "cf261", "name": "CF: Garuda Whip", "price": 8000, "power": 90, "accuracy": 100},
    "cf19":  {"id": "cf19", "name": "CF: Sword Draw", "price": 8000, "power": 95, "accuracy": 100},
    "cf145": {"id": "cf145", "name": "CF: Tool Barrage", "price": 10000, "power": 110, "accuracy": 90},
    "cf227": {"id": "cf227", "name": "CF: RCT Heal", "price": 10000, "power": 0, "accuracy": 100},
    "cf78":  {"id": "cf78", "name": "CF: Meteor Strike", "price": 15000, "power": 155, "accuracy": 75},
    "cf186": {"id": "cf186", "name": "CF: Lava Blast", "price": 10000, "power": 110, "accuracy": 90},
    "cf104": {"id": "cf104", "name": "CF: Earthquake Fist", "price": 8000, "power": 100, "accuracy": 95},
    "cf248": {"id": "cf248", "name": "CF: Curse Absorption", "price": 8000, "power": 0, "accuracy": 100},
    "cf57":  {"id": "cf57", "name": "CF: Soul Splitter", "price": 12000, "power": 125, "accuracy": 85}
}

async def get_or_generate_cf_store(user: dict):
    """Fetches the user's CF store, handling daily auto-resets and migrations."""
    now_date = datetime.utcnow()
    today_str = now_date.strftime('%Y-%m-%d')
    
    shop_state = user.get('shopState', {})
    cf_state = shop_state.get('cf_store', {})
    
    # Migrate old data format (if they used the previous version of the shop)
    if isinstance(cf_state, list):
        cf_state = {
            'items': cf_state[:4], # Cut to 4 items for the new layout
            'last_reset_day': '1970-01-01',
            'manual_refreshes': 0
        }
        
    # Check if a 24hr auto-refresh is needed
    if cf_state.get('last_reset_day') != today_str:
        available_cfs = list(CF_ITEMS.keys())
        # Generate exactly 4 items for the new layout
        cf_state['items'] = random.sample(available_cfs, min(4, len(available_cfs)))
        cf_state['last_reset_day'] = today_str
        cf_state['manual_refreshes'] = 0
        shop_state['cf_store'] = cf_state
        await db.users.update({"telegramId": user['telegramId']}, {"$set": {"shopState": shop_state}})
        
    return cf_state, shop_state

@router.callback_query(F.data == "shop_cf_store")
async def cb_shop_cf_store(callback: types.CallbackQuery, user: dict):
    cf_state, _ = await get_or_generate_cf_store(user)
    
    msg = "🧩 <b>Cursed Fragments:</b>\n"
    msg += f"Your Coins: <code>{user.get('coins', 0):,}</code> 💰\n\n"
    
    builder = InlineKeyboardBuilder()
    buy_buttons = []
    number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]
    
    for i, cf_id in enumerate(cf_state.get('items', [])):
        cf = CF_ITEMS.get(cf_id)
        if not cf: continue
            
        # Format the name (e.g., "CF: Divergent Fist" -> "Divergent Fist")
        raw_num = cf_id.replace('cf', '')
        real_name = cf['name'].replace("CF: ", "").replace("CF:", "").strip()
        
        msg += f"<b>{i+1}) CF #{raw_num} : {real_name}</b>\n"
        msg += f"   Power: {cf.get('power', 0)}\n"
        msg += f"   Accuracy: {cf.get('accuracy', 0)}\n"
        msg += f"   Price: {cf.get('price', 0):,} 💰\n\n"
        
        # Add a buy button for this item
        buy_buttons.append(
            types.InlineKeyboardButton(text=f"{number_emojis[i]} Buy", callback_data=f"shop_buy_cf_{cf_id}")
        )
        
    # Arrange buy buttons in rows of 2 for a clean grid
    for i in range(0, len(buy_buttons), 2):
        builder.row(*buy_buttons[i:i+2])

    # Calculate time until next auto-refresh (Midnight UTC)
    now = datetime.utcnow()
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    time_left = tomorrow - now
    hours, remainder = divmod(int(time_left.total_seconds()), 3600)
    minutes, _ = divmod(remainder, 60)
    
    msg += f"🌟 <i>CF Store will refresh in: {hours}h {minutes}m</i>"

    # Calculate dynamic refresh cost
    current_refreshes = cf_state.get('manual_refreshes', 0)
    refresh_cost = 3000 * (current_refreshes + 1)
    
    builder.row(types.InlineKeyboardButton(text=f"🔄 Refresh ({refresh_cost:,} 💰)", callback_data="shop_cf_refresh"))
    builder.row(types.InlineKeyboardButton(text="🔙 Cursed Market", callback_data="shop_menu"))
    
    await callback.answer()
    await media.smart_edit(callback.message, msg, reply_markup=builder.as_markup())

@router.callback_query(F.data == "shop_cf_refresh")
async def cb_shop_cf_refresh(callback: types.CallbackQuery, user: dict):
    cf_state, shop_state = await get_or_generate_cf_store(user)
    
    # Calculate current cost
    current_refreshes = cf_state.get('manual_refreshes', 0)
    cost = 3000 * (current_refreshes + 1)
    
    if user.get('coins', 0) < cost:
        return await callback.answer(f"❌ You need {cost:,} Coins to refresh the store!", show_alert=True)
        
    # 1. Deduct coins
    await db.users.update({"telegramId": user['telegramId']}, {"$inc": {"coins": -cost}})
    user['coins'] = user.get('coins', 0) - cost # Update local dict for UI
    
    # 2. Generate 4 new items & increment manual refresh count
    available_cfs = list(CF_ITEMS.keys())
    cf_state['items'] = random.sample(available_cfs, min(4, len(available_cfs)))
    cf_state['manual_refreshes'] += 1
    shop_state['cf_store'] = cf_state
    
    # 3. Save state
    await db.users.update({"telegramId": user['telegramId']}, {"$set": {"shopState": shop_state}})
    
    await callback.answer(f"🔄 Store Refreshed for {cost:,} Coins!", show_alert=False)
    await cb_shop_cf_store(callback, user) # Re-render the menu
    
@router.callback_query(F.data.startswith("shop_buy_cf_"))
async def cb_shop_buy_cf(callback: types.CallbackQuery, user: dict):
    cf_id = callback.data.replace("shop_buy_cf_", "")
    cf_data = CF_ITEMS.get(cf_id)
    
    if not cf_data:
        return await callback.answer("❌ Item no longer exists.", show_alert=True)
        
    price = cf_data['price']
    if user.get('coins', 0) < price:
        return await callback.answer(f"❌ You need {price:,} Coins to buy this!", show_alert=True)
        
    # Deduct coins and add CF to inventory array
    inv = user.get('inventory', [])
    idx = next((i for i, x in enumerate(inv) if x['id'] == cf_id), -1)
    if idx > -1:
        inv[idx]['qty'] += 1
    else:
        inv.append({"id": cf_id, "qty": 1})
        
    await db.users.update({"telegramId": user['telegramId']}, {
        "$inc": {"coins": -price},
        "$set": {"inventory": inv}
    })
    user['coins'] -= price # Update local dict so the UI refreshes instantly
    
    await callback.answer(f"✅ Successfully purchased {cf_data['name']}!", show_alert=True)
    await cb_shop_cf_store(callback, user) # Refresh UI to show new coin balance

