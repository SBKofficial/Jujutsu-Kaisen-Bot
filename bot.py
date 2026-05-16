from dotenv import load_dotenv
load_dotenv()

import os
import asyncio
import time
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import db
from utils import ui, media
from utils.handlers import (
    registration, gacha, explore, inventory, shop, train, pvp,
    team, upgrades, roster, quests, clans, utility, social, admin, # <-- Make sure social is here!
    domains, minigame, tournament, competition, challenge, school,
    lvltrain
)
from utils.handlers import Keyboard_handler, charview   # ← NEW
from services.matchmaking import matchmaking_service
from services.admin_service import AdminService
from services.cache_service import cache_service
from services.user_service import user_service
from utils.combat.visual import visual_engine

from aiogram import Router
catch_all_router = Router()

_admin_service = AdminService()

# load_dotenv()

# ── ERROR COLLECTOR ─────────────────────────────────────────────────────────
import traceback as _tb
import io as _io

_error_log = []

def _collect_error(e: Exception, context: str = ""):
    ts  = __import__('datetime').datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    err = f"[{ts}] {context}\n{''.join(_tb.format_exception(type(e), e, e.__traceback__))}".strip()
    _error_log.append(err)
    if len(_error_log) > 500:
        _error_log.pop(0)

TOKEN    = os.getenv('BOT_TOKEN')
BOT_USERNAME = os.getenv('BOT_USERNAME', '')
ADMIN_IDS = [int(i.strip()) for i in os.getenv('ADMIN_IDS', '').split(',') if i.strip()]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
dp  = Dispatcher(storage=MemoryStorage())

import subprocess

def get_latest_commit():
    """Fetches the latest git commit hash, message, and relative time."""
    try:
        # Format: [Hash] - [Message] ([Time ago])
        result = subprocess.check_output(
            ['git', 'log', '-1', '--pretty=format:<code>%h</code> - <b>%s</b> (%ar)'], 
            stderr=subprocess.STDOUT
        )
        return result.decode('utf-8').strip()
    except Exception as e:
        print(f"Git fetch error: {e}")
        return "<i>Unknown commit (Git context unavailable)</i>"

# --- MIDDLEWARES ---

@dp.callback_query.outer_middleware()
async def ownership_middleware(handler, event: types.CallbackQuery, data):
    cb_data = event.data or ""
    if ":uid_" in cb_data:
        try:
            base_data, uid_part = cb_data.rsplit(":uid_", 1)
            if uid_part.isdigit():
                owner_id = int(uid_part)
                if event.from_user.id != owner_id:
                    logger.warning(f"OWNERSHIP REJECT: {event.from_user.id} clicked button for {owner_id}")
                    await event.answer("❌ This is not your menu.", show_alert=True)
                    return
                logger.info(f"OWNERSHIP STRIP: {cb_data} -> {base_data}")
                event = event.model_copy(update={'data': base_data})
        except Exception as e:
            logger.error(f"OWNERSHIP ERROR: {e}")
            pass
    return await handler(event, data)

@dp.update.outer_middleware()
async def user_loader_middleware(handler, event, data):
    user_event = None
    if event.message:
        user_event = event.message
    elif event.callback_query:
        user_event = event.callback_query

    if not user_event or not user_event.from_user:
        return await handler(event, data)

    user_id = user_event.from_user.id
    now     = time.time()
    user    = None
    if user_id:
        user = await db.users.find_one({"telegramId": user_id})
        if user:
            cache_service.set_user(user_id, user)



    if user and user.get('banned'):
        ban_until = user.get('banUntil', -1)
        if ban_until == -1 or (now * 1000) < ban_until:
            if event.message:
                await event.message.reply(
                    f"🚫 You are currently banned.\nReason: {user.get('banReason', 'Unspecified')}"
                )
            return
        else:
            await db.users.update({"telegramId": user_id}, {"$set": {"banned": False}})
            user['banned'] = False
            cache_service.invalidate(user_id)


    is_maint = await get_maintenance()
    if is_maint and (not user or user.get('adminRole', 0) < 2):
        text = event.message.text or "" if event.message else ""
        is_admin_cmd = text.lower().startswith('/admin')
        if not is_admin_cmd:
            if event.message:
                await event.message.reply(
                    "🚧 SYSTEM MAINTENANCE\nThe Higher-Ups are currently reinforcing the barriers.",
                    parse_mode='HTML'
                )
            elif event.callback_query:
                await event.callback_query.answer("🚧 System Maintenance", show_alert=True)
            return

    data['user'] = user
    
    start_time = time.time()
    result = await handler(event, data)
    duration = time.time() - start_time
    if duration > 0.5:
        logger.warning(f"SLOW UPDATE: {type(event).__name__} took {duration:.2f}s")
        
    return result

@dp.error()
async def error_handler(event: types.ErrorEvent):
    logger.error(f"⚠️ GLOBAL ERROR: {event.exception}", exc_info=True)
    try:
        msg = "🆘 <b>SYSTEM ANOMALY</b>\nA cursed energy surge has caused a temporary disruption. Please try again later."
        if event.update.callback_query:
            await event.update.callback_query.answer("⚠️ An internal error occurred.", show_alert=True)
        elif event.update.message:
            await event.update.message.answer(msg, parse_mode='HTML')
    except Exception:
        pass

# Routers are now registered inside main() to prevent circular import errors


async def set_commands():
    commands = [
        # Profile & Team
        types.BotCommand(command="start",        description="Start the bot"),
        types.BotCommand(command="menu",         description="Open the main navigation hub"),
        types.BotCommand(command="profile",      description="View your Sorcerer License & Profile"),
        types.BotCommand(command="roster",       description="Manage your character collection"),
        types.BotCommand(command="myteam",       description="View and manage your team squad"),
        types.BotCommand(command="inventory",    description="Open your item bag"),
        types.BotCommand(command="school",       description="Choose your academy (Tokyo/Kyoto)"),
        # Combat
        types.BotCommand(command="hunt",         description="Explore for cursed spirits"),
        types.BotCommand(command="duel",         description="Challenge someone (reply in group)"),
        types.BotCommand(command="ranked",       description="Join ranked matchmaking"),
        types.BotCommand(command="bf",           description="Black Flash minigame (+crit buff)"),
        # Growth
        types.BotCommand(command="gacha",        description="Summon new sorcerers"),
        types.BotCommand(command="upgrades",     description="Level up & upgrade characters"),
        types.BotCommand(command="lvltrain",     description="Fast coin-based Dojo leveling"),
        types.BotCommand(command="daily",        description="Claim daily rewards & stamina"),
        types.BotCommand(command="quests",       description="View & claim daily quests"),
        types.BotCommand(command="achievements", description="View your achievement milestones"),
        # Info
        types.BotCommand(command="view",         description="View character stats & moves"),
        types.BotCommand(command="inspect",      description="Detailed character inspection dashboard"),
        types.BotCommand(command="data",         description="Full character data sheet"),
        # Social
        types.BotCommand(command="clan",         description="Clan / Syndicate hub"),
        types.BotCommand(command="tournament",   description="Zenin Tournament info & sign-up"),
        # Economy
        types.BotCommand(command="shop",         description="Visit the Cursed Market"),
        types.BotCommand(command="buy",          description="Buy items from the market"),
        types.BotCommand(command="sell",         description="Sell items back for coins"),
        types.BotCommand(command="send",         description="Send/Gift an item to a friend (reply)"),
        # Utility
        types.BotCommand(command="unstuck",      description="Reset your stuck session"),
        types.BotCommand(command="help",         description="Show all commands & guide"),
        types.BotCommand(command="refer",        description="Invite friends & earn rewards"),
        # Admin
        types.BotCommand(command="admin",        description="Open Admin Dashboard"),
        types.BotCommand(command="reset",        description="[Admin] Reset a user's data"),
    ]
    await bot.set_my_commands(commands)


# --- CACHE & HELPERS ---
MAINTENANCE_CACHE = {"value": False, "last_check": 0}


async def get_maintenance():
    now = time.time()
    if now - MAINTENANCE_CACHE["last_check"] < 60:
        return MAINTENANCE_CACHE["value"]
    setting = await db.settings.find_one({"key": "maintenance"})
    MAINTENANCE_CACHE["value"]      = bool(setting and setting.get('value'))
    MAINTENANCE_CACHE["last_check"] = now
    return MAINTENANCE_CACHE["value"]



@dp.message.outer_middleware()
async def group_reply_middleware(handler, event: types.Message, data):
    data['send'] = event.reply
    return await handler(event, data)


@dp.callback_query(F.data.startswith("back_to_hub"))
async def cb_back_to_hub(callback: types.CallbackQuery, user: dict):
    await callback.answer()
    if not user:
        return await callback.message.reply("Please /start first.")
    await show_profile(callback.message, user, callback.from_user.id, edit=True)


# --- HANDLERS ---




@dp.message(Command("start", "menu", "profile"))
async def cmd_start(message: types.Message, user: dict, state: FSMContext):

    command_text = message.text.lower() if message.text else ""
    
    # Look up target user if arguments provided or reply
    target_user = user
    target_id = message.from_user.id
    
    args = message.text.split() if message.text else []
    if len(args) > 1:
        val = args[1].lstrip('@')
        if val.isdigit():
            target_id = int(val)
            target_user = await db.users.find_one({"telegramId": target_id})
        else:
            target_user = await db.users.find_one({"username": val})
            if target_user: target_id = target_user['telegramId']
    elif message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        target_user = await db.users.find_one({"telegramId": target_id})

    # Handle Groups
    if message.chat.type in ("group", "supergroup"):
        if "start" in command_text and len(args) == 1:

            bot_info = await message.bot.get_me()
            builder  = InlineKeyboardBuilder()
            builder.row(types.InlineKeyboardButton(
                text="💬 DM",
                url=f"https://t.me/{bot_info.username}?start=start"
            ))
            return await message.reply(
                "⚠️ Use <b>/start</b> in the bot's DM to register yourself.",
                parse_mode='HTML', reply_markup=builder.as_markup()
            )
        
        if not target_user:
            return await message.reply("⚠️ User not found or not registered.")
        
        return await show_profile(message, target_user, target_id)

    # DM Logic
    if not user:


        # Check for referral code
        args = message.text.split()
        referrer_id = None
        if len(args) > 1 and args[1].startswith("ref_"):
            try:
                referrer_id = int(args[1].replace("ref_", ""))
                if referrer_id == message.from_user.id:
                    referrer_id = None
                else:
                    await state.update_data(referrer_id=referrer_id)
            except:
                pass

        msg = (
            ui.format_header("WELCOME SORCERER") + "\n\n"
            "🏮 <b>Register your account</b> to begin your journey at Jujutsu High.\n\n"
            "<i>\"The power of a sorcerer begins with a single step.\"</i>"
        )
        if referrer_id:
            msg += f"\n\n✨ <b>Referral Detected!</b>\nYou were invited by a fellow sorcerer. Complete registration to claim your bonus!"

        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="✨ Start Registration", callback_data="cmd_start_reg"))
        return await message.reply(msg, parse_mode='HTML', reply_markup=builder.as_markup())

    payload = message.text.split()[-1] if message.text and len(message.text.split()) > 1 else ''
    if payload == 'hunt' and user:
        from utils.handlers.explore import handle_explore
        return await handle_explore(message, user)

    return await show_profile(message, user, message.from_user.id)


@dp.callback_query(F.data == "cmd_start_reg")
async def cb_start_reg(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    from utils.handlers.registration import start_registration
    await start_registration(callback.message, state)


async def show_profile(message: types.Message, user: dict, user_id: int, edit: bool = False):
    print(f"DEBUG: show_profile for {user_id}, edit={edit}")
    if not user:
        return await message.reply("Please use /start to register first.")

    # 1. Fetch Player Photo
    photo_bytes = None
    try:
        print("DEBUG: Fetching photo...")
        photos = await message.bot.get_user_profile_photos(user_id, limit=1)
        if photos.total_count > 0:
            file = await message.bot.get_file(photos.photos[0][-1].file_id)
            photo_io = await message.bot.download_file(file.file_path)
            photo_bytes = photo_io.read()
            print(f"DEBUG: Photo fetched ({len(photo_bytes)} bytes)")
        else:
            print("DEBUG: No profile photos found.")
    except Exception as e:
        print(f"DEBUG Error fetching profile photo: {e}")

    # 2. Prepare Data
    print("DEBUG: Preparing data...")
    grade_title = user_service.get_grade_by_level(user.get('playerLevel', 1))
    user_data = {
        **user,
        "grade": grade_title,
    }
    
    # Active Char
    active_char = None
    team_ids = user.get('teamIds', [])
    if team_ids:
        active_char = team_ids[0]

    # 3. Generate Image
    try:
        buffer = await visual_engine.generate_license_card(user_data, photo_bytes, active_char)
    except Exception as e:
        logger.error(f"Image Gen Error: {e}")
        buffer = None

    # 4. Text Content (minimalist)
    battles  = user.get('battles', 0)
    win_rate = int((user.get('battlesWon', 0) / battles * 100)) if battles > 0 else 0

    caption = (
        f"㊙️ <b>{ui.sc('SORCERER DOSSIER')}</b>\n"
        f"<i>\"{user.get('title', 'Wandering Soul')}\"</i>\n\n"
        f"💰 <b>{ui.sc('COINS')}:</b> <code>{user.get('coins', 0):,}</code> | ✨ <b>{ui.sc('DUST')}:</b> <code>{user.get('dust', 0):,}</code>\n"
        f"⚔️ <b>{ui.sc('BATTLES')}:</b> <code>{battles}</code> | 🎯 <b>{ui.sc('WIN')}:</b> <code>{win_rate}%</code>\n"
        f"🔋 <b>{ui.sc('STAMINA')}:</b> <code>{user.get('stamina', 0)}/100</code>\n"
    )


    uid = f":uid_{user_id}"
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="👥 Team",  callback_data=f"cmd_team{uid}"),
        types.InlineKeyboardButton(text="🎒 Bag",   callback_data=f"cmd_inv{uid}"),
        types.InlineKeyboardButton(text="🔍 Inspect", callback_data=f"roster_nav_details{uid}")
    )
    builder.row(
        types.InlineKeyboardButton(text="🏮 Hunt",  callback_data=f"cmd_explore{uid}"),
        types.InlineKeyboardButton(text="🛡 Clans", callback_data=f"clan_home{uid}"),
        types.InlineKeyboardButton(text="🎖 Rank", callback_data=f"matchmaking_menu{uid}")
    )
    builder.row(
        types.InlineKeyboardButton(text="🏅 Achievements", callback_data=f"cmd_achievements{uid}"),
        types.InlineKeyboardButton(text="📢 Invite", callback_data=f"cmd_refer{uid}"),
        types.InlineKeyboardButton(text="❓ Help", callback_data=f"cmd_help{uid}")
    )

    print("DEBUG: Sending message...")
    try:
        if buffer:
            photo = types.BufferedInputFile(buffer, filename=f"license_{user_id}.jpg")
            if edit:
                try:
                    return await message.edit_media(
                        media=types.InputMediaPhoto(media=photo, caption=caption, parse_mode='HTML'),
                        reply_markup=builder.as_markup()
                    )
                except Exception:
                    pass
            return await message.reply_photo(photo=photo, caption=caption, parse_mode='HTML', reply_markup=builder.as_markup())
        else:
            if edit:
                try:
                    return await message.edit_text(caption, parse_mode='HTML', reply_markup=builder.as_markup())
                except Exception:
                    pass
            return await message.reply(caption, parse_mode='HTML', reply_markup=builder.as_markup())
    except Exception as e:
        print(f"DEBUG: Send Error: {e}")

@dp.callback_query(F.data.startswith("cmd_profile"))
async def cb_profile(callback: types.CallbackQuery, user: dict):
    await callback.answer()
    await show_profile(callback.message, user, callback.from_user.id, edit=True)



@dp.callback_query(F.data.startswith("cmd_close"))
async def cb_close(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.answer("Closed.")


@dp.message(Command("unstuck"))
async def cmd_unstuck(message: types.Message, user: dict, state: FSMContext):
    if not user:
        return await message.reply("Please /start first.")
    await state.clear()
    await db.users.update({"telegramId": message.from_user.id}, {"$set": {"activeExplore": None}})
    await message.reply(
        "✅ <b>UNSTUCK SUCCESSFUL</b>\nAll active battles and hunts have been cleared.",
        parse_mode='HTML'
    )


# ── AUTO-REPLY context ──────────────────────────────────────────────────────
@dp.update.outer_middleware()
async def reply_context_middleware(handler, event, data):
    try:
        return await handler(event, data)
    except Exception as _e:
        _collect_error(_e, "Update handler")
        raise


# ── ADMIN /reset ────────────────────────────────────────────────────────────
@dp.message(Command("reset"))
async def cmd_reset(message: types.Message, user: dict):
    requester_id = message.from_user.id
    role = await _admin_service.get_user_role(requester_id)
    if role < 2:
        return await message.reply("❌ Unauthorized. Admin only.")

    target_user = None
    target_id   = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target_id   = message.reply_to_message.from_user.id
        target_user = await db.users.find_one({"telegramId": target_id})
    else:
        args = message.text.split()[1:]
        if args:
            val = args[0].lstrip('@')
            if val.isdigit():
                target_id   = int(val)
                target_user = await db.users.find_one({"telegramId": target_id})
            else:
                target_user = await db.users.find_one({"username": val})
                if target_user:
                    target_id = target_user['telegramId']

    if not target_user or not target_id:
        return await message.reply("❌ User not found. Reply to their message or use /reset @username")

    try:
        reset_data = {
            "coins": 0, "dust": 0, "gems": 0, "gachaTickets": 0,
            "stamina": 100, "playerLevel": 1, "playerXp": 0,
            "elo": 1000, "rank": "Iron", "battles": 0, "battlesWon": 0,
            "dailyExploreCount": 0, "activeExplore": None,
            "banned": False, "warnings": 0, "title": "Wandering Soul",
            "school": None, "team": [], "activeTeam": None,
        }
        await db.users.update({"telegramId": target_id}, {"$set": reset_data})
        await db.roster.remove({"userId": target_id}, multi=True)
        cache_service.invalidate(target_id)


        uname = target_user.get('username', str(target_id))
        await message.reply(
            f"✅ <b>RESET COMPLETE</b>\n\n"
            f"User <code>@{uname}</code> (<code>{target_id}</code>) has been fully reset.\n"
            f"All data, roster, and progress wiped.",
            parse_mode='HTML'
        )
    except Exception as e:
        await message.reply(f"❌ Reset failed: {e}")


@dp.message(Command("give_error"))
async def cmd_give_error(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        return await message.reply("❌ Admin only.")

    if not _error_log:
        return await message.reply("✅ No errors recorded since last reset.")

    report    = f"🐛 <b>ERROR LOG</b> ({len(_error_log)} errors)\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    full_text = "\n\n" + ("─" * 40) + "\n\n".join(_error_log)
    _error_log.clear()

    if len(full_text) > 3500:
        buf = _io.BytesIO((report.replace("<b>","").replace("</b>","") + full_text).encode())
        buf.name = "errors.txt"
        await message.reply_document(document=buf, caption="🐛 Error log — cleared after this send.")
    else:
        await message.reply(
            report + f"<pre>{full_text[:3000]}</pre>\n<i>Cleared.</i>",
            parse_mode='HTML'
        )



@catch_all_router.callback_query()
async def catch_all_callback(callback: types.CallbackQuery):
    # This catches any callback that wasn't handled by the routers above
    cb_data = callback.data or ""
    logger.warning(f"Unmatched callback from {callback.from_user.id}: {cb_data}")
    
    # Check if it was an ownership issue that stripped the UID
    if ":" not in cb_data and not any(cb_data.startswith(prefix) for prefix in ["cmd_", "gacha_", "clan_", "exp_"]):
        # Might be an old or malformed button
        await callback.answer("⚠️ This menu has expired or is no longer active.", show_alert=True)
    else:
        await callback.answer("⚠️ Action unavailable in current state.", show_alert=True)


async def main():
    print("--- BOT INITIALIZING ---")
    await db.connect()
    print("--- DB CONNECTED ---")

    await set_commands()
    await db.users.ensure_index('telegramId', unique=True)
    await db.users.ensure_index('username')
    await db.roster.ensure_index('userId')
    await db.clans.ensure_index('name', unique=True)

    # ── Register all routers ─────────────────────────────────────────────────────
    dp.include_router(registration.router)
    dp.include_router(gacha.router)
    dp.include_router(explore.router)
    dp.include_router(inventory.router)
    dp.include_router(shop.router)
    dp.include_router(train.router)
    dp.include_router(pvp.router)
    dp.include_router(team.router)
    dp.include_router(upgrades.router)
    dp.include_router(roster.router)
    dp.include_router(quests.router)
    dp.include_router(clans.router)
    dp.include_router(utility.router)
    dp.include_router(admin.router)
    dp.include_router(domains.router)
    dp.include_router(minigame.router)
    dp.include_router(tournament.router)
    dp.include_router(challenge.router)
    dp.include_router(school.router)
    dp.include_router(charview.router)           # /view  /data
    dp.include_router(lvltrain.router)
    
    # Add the social router here so /send works!
    dp.include_router(social.router)           
    
    # THIS MUST BE THE ABSOLUTE LAST ROUTER!
    dp.include_router(catch_all_router)          

    print("Bot starting...")
    asyncio.create_task(matchmaking_service.process_queue())

    # ==========================================
    #            STARTUP PING LOGIC
    # ==========================================
    # Replace this with your actual Telegram Group ID (Usually starts with -100)
    MAIN_GROUP_ID = os.getenv('MAIN_GROUP_ID', '-1003845254351') 
    
    if MAIN_GROUP_ID and MAIN_GROUP_ID != '-100XXXXXXXXXX':
        try:
            commit_info = get_latest_commit()
            startup_msg = (
                "🟢 <b>SYSTEM ONLINE</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "The Cursed Clash servers have been restarted and updated successfully.\n\n"
                f"📦 <b>Latest Update:</b>\n{commit_info}"
            )
            await bot.send_message(chat_id=MAIN_GROUP_ID, text=startup_msg, parse_mode='HTML')
        except Exception as e:
            # SEND ERROR TO YOUR DM IF IT FAILS
            await bot.send_message(chat_id="7708811819", text=f"⚠️ Startup Ping Error: {e}")

    # ==========================================

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

