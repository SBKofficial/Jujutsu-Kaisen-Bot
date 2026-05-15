import difflib
from aiogram import Router, types, F
from aiogram.filters import Command

from database import db
from utils import ui
from utils.data.items import ITEMS
from services.social_service import social_service
from services.admin_service import admin_service

router = Router()

@router.message(Command("addfriend"))
async def handle_add_friend(message: types.Message, user: dict):
    parts = message.text.split()
    if len(parts) < 2:
        return await message.reply("Usage: /addfriend @username")
    
    target_username = parts[1].replace('@', '')
    target = await db.users.find_one({"username": target_username})
    
    if not target:
        return await message.reply("Could not find that sorcerer.")
    
    if target['telegramId'] == user['telegramId']:
        return await message.reply("You cannot friend yourself.")
    
    user_friends = user.get('friends', [])
    if any(f['userId'] == target['telegramId'] for f in user_friends):
        return await message.reply("You are already connected with this user.")
    
    # Add to friends
    user_friends.append({"userId": target['telegramId'], "username": target['username'], "status": 'accepted'})
    target_friends = target.get('friends', [])
    target_friends.append({"userId": user['telegramId'], "username": user['username'], "status": 'accepted'})
    
    await db.users.update({"telegramId": user['telegramId']}, {"$set": {"friends": user_friends}})
    await db.users.update({"telegramId": target['telegramId']}, {"$set": {"friends": target_friends}})
    
    await message.reply(f"🤝 <b>Bond Formed!</b> You and @{target['username']} are now friends.", parse_mode='HTML')

@router.message(Command("friends"))
async def handle_show_friends(message: types.Message, user: dict):
    friends = user.get('friends', [])
    if not friends:
        return await message.reply("Your contact list is empty. Use /addfriend to connect.")
    
    msg = ui.format_header("FRIENDS LIST") + "\n\n"
    for f in friends:
        friend_data = await db.users.find_one({"telegramId": f['userId']})
        status = f"🎖 {friend_data.get('rank', 'Sorcerer')}" if friend_data else "Unknown"
        msg += f"👤 @{f['username']} - {status}\n"
    
    await message.reply(msg, parse_mode='HTML')

# --- ITEM RESOLUTION HELPER ---
ITEM_NICKNAMES = {
    "katana": "katana", "nails": "nails", "cloud": "cloud", "spear": "spear",
    "elixir": "elixir", "fragment": "fragment", "pill": "pill", "shard": "dshard",
    "scroll": "scroll", "finger": "finger", "orb": "reset_orb", "potion": "minor_hp_potion"
}
CORE_CURRENCIES = ["coins", "dust", "gems", "tickets", "gachatickets", "shards"]

def resolve_item(name: str):
    """Identifies if a string is a currency or an inventory item, with auto-correction."""
    name = name.lower().strip()
    if name in CORE_CURRENCIES:
        if name in ["tickets", "gachatickets"]: return "gachaTickets", True
        if name == "shards": return "shardsCurrency", True
        return name, True # is_currency = True
    
    if name in ITEM_NICKNAMES: return ITEM_NICKNAMES[name], False
    if name in ITEMS: return name, False
        
    # Fuzzy match for exact item names or IDs
    all_keys = list(ITEM_NICKNAMES.keys()) + list(ITEMS.keys()) + [i['name'].lower() for i in ITEMS.values()]
    matches = difflib.get_close_matches(name, all_keys, n=1, cutoff=0.5)
    
    if matches:
        match = matches[0]
        if match in ITEM_NICKNAMES: return ITEM_NICKNAMES[match], False
        if match in ITEMS: return match, False
        for k, v in ITEMS.items():
            if v['name'].lower() == match: return k, False
                
    return None, False


# --- UNIFIED /SEND COMMAND ---
@router.message(Command("send", "gift", "give", "take", "tool"))
async def cmd_unified_send(message: types.Message, user: dict):
    # 1. Require replying to a message
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return await message.reply("⚠️ You must **reply to a user's message** to send or modify items.", parse_mode='HTML')

    target_id = message.reply_to_message.from_user.id
    sender_id = message.from_user.id

    if target_id == sender_id:
        return await message.reply("❌ You cannot send items to yourself.")

    target_user = await db.users.find_one({"telegramId": target_id})
    if not target_user:
        return await message.reply("⚠️ The user you replied to is not registered in the archives.")

    # 2. Parse command: /send [item name] [amount]
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.reply("📝 **Usage:** Reply to a user with <code>/send [item name] [amount]</code>\n*Example:* <code>/send sukuna finger 2</code>", parse_mode='HTML')

    parts = args[1].split()
    try:
        # Check if the last word is a number
        amount = int(parts[-1])
        item_name = " ".join(parts[:-1]).strip()
        if not item_name:
            return await message.reply("⚠️ Please specify an item name.")
    except ValueError:
        # If the last word isn't a number, assume amount is 1
        amount = 1
        item_name = args[1].strip()

    # 3. Check Admin Privileges (Using your admin_service)
    role = await admin_service.get_user_role(sender_id)
    is_admin = role >= 2  # Allows MODERATOR and above to use admin commands
    
    if not is_admin and amount <= 0:
        return await message.reply("❌ You can only send positive amounts.")
    if is_admin and amount == 0:
        return await message.reply("⚠️ Amount cannot be zero.")

    # 4. Resolve the item to database IDs
    item_id, is_currency = resolve_item(item_name)
    if not item_id:
        return await message.reply(f"❌ Item or currency '<b>{item_name}</b>' not found.", parse_mode='HTML')

    item_display_name = item_id.capitalize() if is_currency else ITEMS.get(item_id, {}).get('name', item_id)
    target_name = target_user.get('username', message.reply_to_message.from_user.first_name)

    # ==========================================
    #             ADMIN LOGIC
    # ==========================================
    if is_admin:
        if is_currency:
            await db.users.update({"telegramId": target_id}, {"$inc": {item_id: amount}})
        else:
            inv = target_user.get('inventory', [])
            idx = next((i for i, x in enumerate(inv) if x['id'] == item_id), -1)
            if idx > -1:
                inv[idx]['qty'] += amount
            elif amount > 0:
                inv.append({"id": item_id, "qty": amount})
            
            inv = [i for i in inv if i['qty'] > 0] # Clean up 0 qty items
            await db.users.update({"telegramId": target_id}, {"$set": {"inventory": inv}})

        if amount > 0:
            return await message.reply(f"🪄 **ADMIN SPAWN:** Granted {amount:,}x **{item_display_name}** to @{target_name}.", parse_mode='HTML')
        else:
            return await message.reply(f"⚖️ **ADMIN TAKE:** Removed {abs(amount):,}x **{item_display_name}** from @{target_name}.", parse_mode='HTML')

    # ==========================================
    #             PLAYER LOGIC
    # ==========================================
    else:
        if is_currency:
            sender_bal = user.get(item_id, 0)
            if sender_bal < amount:
                return await message.reply(f"❌ You don't have enough **{item_display_name}**. (Balance: {sender_bal:,})", parse_mode='HTML')
            
            await db.users.update({"telegramId": sender_id}, {"$inc": {item_id: -amount}})
            await db.users.update({"telegramId": target_id}, {"$inc": {item_id: amount}})

        else:
            inv_sender = user.get('inventory', [])
            idx_sender = next((i for i, x in enumerate(inv_sender) if x['id'] == item_id), -1)
            
            if idx_sender == -1 or inv_sender[idx_sender]['qty'] < amount:
                has_qty = inv_sender[idx_sender]['qty'] if idx_sender != -1 else 0
                return await message.reply(f"❌ You don't have enough **{item_display_name}**. (You have: {has_qty:,})", parse_mode='HTML')

            # Deduct from sender
            inv_sender[idx_sender]['qty'] -= amount
            inv_sender = [i for i in inv_sender if i['qty'] > 0]
            await db.users.update({"telegramId": sender_id}, {"$set": {"inventory": inv_sender}})

            # Add to target
            inv_target = target_user.get('inventory', [])
            idx_target = next((i for i, x in enumerate(inv_target) if x['id'] == item_id), -1)
            if idx_target > -1:
                inv_target[idx_target]['qty'] += amount
            else:
                inv_target.append({"id": item_id, "qty": amount})
            await db.users.update({"telegramId": target_id}, {"$set": {"inventory": inv_target}})

        return await message.reply(f"🎁 **GIFT SENT:** You gave {amount:,}x **{item_display_name}** to @{target_name}!", parse_mode='HTML')

