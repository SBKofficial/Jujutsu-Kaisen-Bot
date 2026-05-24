import asyncio
import time
from aiogram import Router, types, F, Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command

from database import db
from utils import ui, media
from utils.data import characters
from utils.combat.engine import combat_engine
from services.user_service import user_service
from services.matchmaking import matchmaking_service

router = Router()

async def on_match_found(p1_queue, p2_queue, mode):
    # This is called by matchmaking service
    from bot import bot
    await start_pvp_battle(p1_queue, p2_queue, mode, bot)

matchmaking_service.on_match_found = on_match_found

async def start_pvp_battle(p1_q, p2_q, mode, bot: Bot):
    from services.cache_service import cache_service
    u1 = cache_service.get_user(p1_q['userId'])
    u2 = cache_service.get_user(p2_q['userId'])
    r1 = cache_service.get_roster(p1_q['userId'])
    r2 = cache_service.get_roster(p2_q['userId'])

    tasks = []
    task_keys = []
    
    if u1 is None:
        tasks.append(db.users.find_one({"telegramId": p1_q['userId']}))
        task_keys.append('u1')
    if u2 is None:
        tasks.append(db.users.find_one({"telegramId": p2_q['userId']}))
        task_keys.append('u2')
    if r1 is None:
        tasks.append(db.roster.find({"userId": p1_q['userId']}))
        task_keys.append('r1')
    if r2 is None:
        tasks.append(db.roster.find({"userId": p2_q['userId']}))
        task_keys.append('r2')
        
    if tasks:
        db_results = await asyncio.gather(*tasks)
        for key, res in zip(task_keys, db_results):
            if key == 'u1':
                u1 = res
                if u1: cache_service.set_user(p1_q['userId'], u1)
            elif key == 'u2':
                u2 = res
                if u2: cache_service.set_user(p2_q['userId'], u2)
            elif key == 'r1':
                r1 = res or []
                cache_service.set_roster(p1_q['userId'], r1)
            elif key == 'r2':
                r2 = res or []
                cache_service.set_roster(p2_q['userId'], r2)

    def hydrate_team(user, roster):
        team = []
        for char_id in user.get('teamIds', []):
            if not char_id or char_id not in characters.DATA: continue
            entry = next((r for r in roster if r['charId'] == char_id), {"level": 1})
            team.append(user_service.calculate_final_stats(entry, characters.DATA[char_id]))
        return team

    t1 = hydrate_team(u1, r1)
    t2 = hydrate_team(u2, r2)

    if not t1 or not t2:
        error_msg = "❌ Both players must have at least one character in their team to duel!"
        await bot.send_message(u1['telegramId'], error_msg)
        if u1['telegramId'] != u2['telegramId']:
            await bot.send_message(u2['telegramId'], error_msg)
        return

    battle = combat_engine.init_battle(
        {"telegramId": u1['telegramId'], "username": u1['username'], "teamMembers": t1},
        {"telegramId": u2['telegramId'], "username": u2['username'], "teamMembers": t2}
    )

    # Check if we should render in group
    is_group = p1_q.get('isGroup', False)
    battle['isGroup'] = is_group
    battle['groupId'] = p1_q.get('chatId')
    battle['mode'] = mode
    battle['status'] = 'active'
    battle['p1Choice'] = None
    battle['p2Choice'] = None
    battle['createdAt'] = int(time.time() * 1000)

    res = await db.battles.insert(battle)
    battle_id = res['_id']

    if is_group:
        msg = (
            ui.format_header(f"{mode.upper()} CLASH", "GROUP BATTLE") + "\n\n"
            f"🔥 <b>{u1['username']}</b> vs <b>{u2['username']}</b>\n\n"
            "The battleground has materialized in this realm!\n"
            "<i>Participants, prepare your moves below.</i>"
        )
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="⚔️ BEGIN CLASH", callback_data=f"pvp_enter_{battle_id}"))
        
        await bot.send_message(battle['groupId'], msg, parse_mode='HTML', reply_markup=builder.as_markup())
        return

    msg = (
        ui.format_header(f"{mode.upper()} CLASH", "BATTLE") + "\n\n"
        "💥 CHALLENGER APPROACHES!\n\n"
        f"   ⚔️ @{u1['username']} vs @{u2['username']}\n\n"
        "<i>Prepare your cursed techniques...</i>"
    )

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🚀 ENTER BATTLE", callback_data=f"pvp_enter_{battle_id}"))

    await bot.send_message(u1['telegramId'], msg, parse_mode='HTML', reply_markup=builder.as_markup())
    await bot.send_message(u2['telegramId'], msg, parse_mode='HTML', reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("pvp_enter_"))
async def handle_pvp_enter(callback: types.CallbackQuery):
    battle_id = callback.data.split("_")[-1]
    battle = await db.battles.find_one({"_id": battle_id})
    if not battle or battle['status'] != 'active':
        return await callback.answer("❌ Battle expired.")

    if callback.from_user.id not in [battle['p1']['id'], battle['p2']['id']]:
        return await callback.answer("🚫 You are not a participant in this clash!", show_alert=True)

    is_p1 = callback.from_user.id == battle['p1']['id']
    msg_key = 'p1Mid' if is_p1 else 'p2Mid'
    
    # If it's a group battle, we use the same message ID
    if battle.get('isGroup'):
        await db.battles.update({"_id": battle_id}, {"$set": {"groupMid": callback.message.message_id, "lastActionAt": int(time.time() * 1000)}})
    else:
        await db.battles.update({"_id": battle_id}, {"$set": {msg_key: callback.message.message_id, "lastActionAt": int(time.time() * 1000)}})
    battle[msg_key] = callback.message.message_id
    
    await callback.answer()
    await render_pvp_battle(callback.message, battle, callback.from_user.id)

async def render_pvp_battle(message: types.Message, battle, user_id):
    p1 = battle['p1']
    p2 = battle['p2']
    is_p1 = user_id == p1['id']
    my_side = p1 if is_p1 else p2
    my_active = my_side['team'][my_side['activeIdx']]
    
    msg = ui.render_pokemon_ui(battle, user_id)

    if battle['status'] == 'finished':
        is_winner = battle.get('winnerId') == user_id
        rewards = battle.get('rewards', {})
        my_rew = rewards.get('winner' if is_winner else 'loser', {})
        
        status_text = "🎉 VICTORY!" if is_winner else "💀 DEFEAT!"
        result_msg = f"\n\n{status_text}\n"
        if my_rew:
            result_msg += f"💰 +{my_rew.get('coins', 0)} Coins\n"
            result_msg += f"📈 +{my_rew.get('xp', 0)} XP\n"
            if my_rew.get('elo', 0) != 0:
                elo_tag = f"+{my_rew['elo']}" if my_rew['elo'] > 0 else str(my_rew['elo'])
                result_msg += f"🏆 Rank: {elo_tag} ELO\n"
        
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="🔙 Return to Hub", callback_data="back_to_hub"))
        return await media.smart_edit(message, msg + result_msg, reply_markup=builder.as_markup())

    has_acted = bool(battle.get('p1Choice')) if is_p1 else bool(battle.get('p2Choice'))
    if has_acted:
        return await media.smart_edit(message, msg + "\n⏳ Waiting for opponent...")

    builder = InlineKeyboardBuilder()
    move_buttons = []
    for i, move in enumerate(my_active['moves']):
        cost = move.get('ce', 0)
        label = f"{move['name']} [🌀{cost}]" if cost > 0 else move['name']
        move_buttons.append(types.InlineKeyboardButton(text=label, callback_data=f"pvp_atk_{battle['_id']}_{i}"))
    # 2x2 layout
    for i in range(0, len(move_buttons), 2):
        builder.row(*move_buttons[i:i+2])

    builder.row(
        types.InlineKeyboardButton(text="🔄 Switch", callback_data=f"pvp_swi_{battle['_id']}"),
        types.InlineKeyboardButton(text="🏳️ Run", callback_data=f"pvp_surr_{battle['_id']}")
    )

    from bot import bot
    return await media.send_battle_turn(
        bot, message.chat.id, battle, user_id, 
        reply_markup=builder.as_markup(), 
        message_id=message.message_id
    )

@router.callback_query(F.data.startswith("pvp_atk_"))
async def handle_pvp_attack(callback: types.CallbackQuery):
    await callback.answer()  # instant
    parts = callback.data.split("_")
    battle_id = parts[2]
    move_idx = int(parts[3])
    
    battle = await db.battles.find_one({"_id": battle_id})
    if not battle or battle['status'] != 'active': return await callback.answer("Battle ended.")

    if callback.from_user.id not in [battle['p1']['id'], battle['p2']['id']]:
        return await callback.answer("🚫 You are not a participant!", show_alert=True)

    is_p1 = callback.from_user.id == battle['p1']['id']
    choice_key = 'p1Choice' if is_p1 else 'p2Choice'
    
    if battle.get(choice_key): return await callback.answer("Action already locked!")

    await db.battles.update({"_id": battle_id}, {"$set": {
        choice_key: {"type": "attack", "moveIdx": move_idx}, 
        "lastActionAt": int(time.time() * 1000)
    }})
    await callback.answer("Action locked!")

    updated = await db.battles.find_one({"_id": battle_id})
    if updated.get('p1Choice') and updated.get('p2Choice'):
        await resolve_pvp_turn(updated)
    else:
        await render_pvp_battle(callback.message, updated, callback.from_user.id)

@router.callback_query(F.data.startswith("pvp_swi_"))
async def handle_pvp_switch(callback: types.CallbackQuery):
    battle_id = callback.data.split("_")[-1]
    battle = await db.battles.find_one({"_id": battle_id})
    if not battle or battle['status'] != 'active': return await callback.answer("Battle ended.")

    is_p1 = callback.from_user.id == battle['p1']['id']
    my_side = battle['p1'] if is_p1 else battle['p2']
    
    builder = InlineKeyboardBuilder()
    for i, char in enumerate(my_side['team']):
        status = " (ACTIVE)" if i == my_side['activeIdx'] else (" (KO)" if char['hp'] <= 0 else "")
        builder.row(types.InlineKeyboardButton(text=f"{char['name']}{status}", callback_data=f"pvp_exec_swi_{battle_id}_{i}"))
    builder.row(types.InlineKeyboardButton(text="🔙 Back", callback_data=f"pvp_back_{battle_id}"))
    
    await callback.answer()
    await media.smart_edit(callback.message, "🔄 <b>SELECT REINFORCEMENT</b>\nChoose a character to switch into battle.", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("pvp_exec_swi_"))
async def handle_pvp_exec_switch(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    battle_id = parts[3]
    next_idx = int(parts[4])
    
    battle = await db.battles.find_one({"_id": battle_id})
    if not battle or battle['status'] != 'active': return await callback.answer("Battle ended.")

    if callback.from_user.id not in [battle['p1']['id'], battle['p2']['id']]:
        return await callback.answer("🚫 You are not a participant!", show_alert=True)

    is_p1 = callback.from_user.id == battle['p1']['id']
    my_side = battle['p1'] if is_p1 else battle['p2']
    choice_key = 'p1Choice' if is_p1 else 'p2Choice'

    if next_idx == my_side['activeIdx']: return await callback.answer("Already active!", show_alert=True)
    if my_side['team'][next_idx]['hp'] <= 0: return await callback.answer("This character is KO'd!", show_alert=True)
    if battle.get(choice_key): return await callback.answer("Action already locked!")

    await db.battles.update({"_id": battle_id}, {"$set": {
        choice_key: {"type": "switch", "nextIdx": next_idx}, 
        "lastActionAt": int(time.time() * 1000)
    }})
    await callback.answer("Switch locked!")

    updated = await db.battles.find_one({"_id": battle_id})
    if updated.get('p1Choice') and updated.get('p2Choice'):
        await resolve_pvp_turn(updated)
    else:
        await render_pvp_battle(callback.message, updated, callback.from_user.id)

@router.callback_query(F.data.startswith("pvp_back_"))
async def handle_pvp_back(callback: types.CallbackQuery):
    battle_id = callback.data.split("_")[-1]
    battle = await db.battles.find_one({"_id": battle_id})
    if not battle: return
    await callback.answer()
    await render_pvp_battle(callback.message, battle, callback.from_user.id)

@router.callback_query(F.data.startswith("pvp_surr_"))
async def handle_pvp_surrender(callback: types.CallbackQuery):
    battle_id = callback.data.split("_")[-1]
    battle = await db.battles.find_one({"_id": battle_id})
    if not battle or battle['status'] != 'active': return
    
    is_p1 = callback.from_user.id == battle['p1']['id']
    winner_id = battle['p2']['id'] if is_p1 else battle['p1']['id']
    winner_name = battle['p2']['username'] if is_p1 else battle['p1']['username']
    
    await db.battles.update({"_id": battle_id}, {"$set": {
        "status": "finished",
        "winner": winner_name,
        "winnerId": winner_id,
        "surrendered": True
    }})
    await callback.answer("You surrendered.")
    
    updated = await db.battles.find_one({"_id": battle_id})
    # Notify both
    from bot import bot
    await asyncio.gather(
        push_pvp_update(bot, updated, battle['p1']['id'], battle.get('p1Mid')),
        push_pvp_update(bot, updated, battle['p2']['id'], battle.get('p2Mid'))
    )

async def resolve_pvp_turn(battle):
    if battle.get('processing'): return
    await db.battles.update({"_id": battle['_id']}, {"$set": {"processing": True}})
    
    from bot import bot
    # Ordered resolution
    actors = combat_engine.get_ordered_actors(battle, battle['p1Choice'], battle['p2Choice'])
    
    battle['p1Choice'] = None
    battle['p2Choice'] = None
    
    for actor in actors:
        logs = combat_engine.process_action(battle, actor)
        if logs:
            battle['log'].append("\n".join(logs))
            # Optional intermediate updates here
        if battle['status'] == 'finished': break

    if battle['status'] != 'finished':
        cleanup = combat_engine.post_turn_cleanup(battle)
        if cleanup: battle['log'].append("\n".join(cleanup))

    if battle['status'] == 'finished':
        battle['winnerId'] = battle['p1']['id'] if battle['winner'] == battle['p1']['username'] else battle['p2']['id']
        loser_id = battle['p2']['id'] if battle['winnerId'] == battle['p1']['id'] else battle['p1']['id']
        
        # Award Rewards
        is_ranked = battle.get('mode') == 'ranked'
        
        # Winner Rewards
        win_coins = 500 if is_ranked else 300
        win_xp = 200 if is_ranked else 100
        win_elo = 25 if is_ranked else 0
        
        await db.users.update({"telegramId": battle['winnerId']}, {
            "$inc": {"coins": win_coins, "playerXp": win_xp, "elo": win_elo}
        })
        
        # Loser Rewards
        lose_coins = 100 if is_ranked else 50
        lose_xp = 50 if is_ranked else 20
        lose_elo = -15 if is_ranked else 0
        
        await db.users.update({"telegramId": loser_id}, {
            "$inc": {"coins": lose_coins, "playerXp": lose_xp, "elo": lose_elo}
        })
        
        battle['rewards'] = {
            "winner": {"coins": win_coins, "xp": win_xp, "elo": win_elo},
            "loser": {"coins": lose_coins, "xp": lose_xp, "elo": lose_elo}
        }

    await db.battles.update({"_id": battle['_id']}, {"$set": {
        "p1": battle['p1'], "p2": battle['p2'], "turn": battle['turn'],
        "log": battle['log'], "status": battle['status'], "winner": battle['winner'],
        "winnerId": battle.get('winnerId'), "sharedData": battle['sharedData'], 
        "processing": False, "p1Choice": None, "p2Choice": None,
        "rewards": battle.get('rewards')
    }})

    # Push updates
    tasks = []
    if battle.get('isGroup') and battle.get('groupMid'):
        tasks.append(push_pvp_update(bot, battle, battle['groupId'], battle['groupMid'], is_group_msg=True))
    else:
        if battle.get('p1Mid'):
            tasks.append(push_pvp_update(bot, battle, battle['p1']['id'], battle['p1Mid']))
        if battle.get('p2Mid'):
            tasks.append(push_pvp_update(bot, battle, battle['p2']['id'], battle['p2Mid']))
    
    if tasks:
        await asyncio.gather(*tasks)

async def push_pvp_update(bot, battle, target_id, msg_id, is_group_msg=False):
    if not msg_id: return
    # Mock message for render
    class MockMsg:
        def __init__(self, chat_id, message_id):
            self.chat = type('obj', (object,), {"id": chat_id})
            self.message_id = message_id
            self.photo = True # Assume photo for smart_edit
            self.bot = bot
        async def edit_caption(self, **kwargs):
            return await bot.edit_message_caption(chat_id=self.chat.id, message_id=self.message_id, **kwargs)

    # For group messages, we need to decide WHICH user view to show. 
    # Usually we show a neutral view or P1's view. 
    # Let's show P1's view but with neutral buttons if it's a group? 
    # Actually, render_pokemon_ui handles user_id.
    viewer_id = battle['p1']['id'] # Default viewer for group
    await render_pvp_battle(MockMsg(target_id, msg_id), battle, viewer_id)

@router.message(Command("duel"))
async def cmd_duel(message: types.Message, user: dict):
    if not message.reply_to_message:
        return await message.reply("❌ <b>USAGE:</b> Reply to someone's message with /duel to challenge them!", parse_mode='HTML')
    
    opponent_user = message.reply_to_message.from_user
    if opponent_user.id == message.from_user.id:
        return await message.reply("❌ You cannot duel yourself!")
    
    if opponent_user.is_bot:
        return await message.reply("❌ You cannot duel a bot!")

    # Check if opponent exists in DB
    opp_doc = await db.users.find_one({"telegramId": opponent_user.id})
    if not opp_doc:
        return await message.reply(f"❌ <b>{opponent_user.first_name}</b> is not a registered sorcerer! They must /start first.", parse_mode='HTML')

    msg = (
        ui.format_header("🤞 DUEL CHALLENGE") + "\n\n"
        f"🔥 <b>{message.from_user.first_name}</b> has challenged <b>{opponent_user.first_name}</b> to a Cursed Clash!\n\n"
        "Do you accept this challenge?"
    )

    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="✅ ACCEPT", callback_data=f"pvp_accept_{message.from_user.id}_{opponent_user.id}"),
        types.InlineKeyboardButton(text="❌ DECLINE", callback_data=f"pvp_decline_{message.from_user.id}_{opponent_user.id}")
    )

    await message.reply(msg, parse_mode='HTML', reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("pvp_accept_"))
async def handle_duel_accept(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    challenger_id = int(parts[2])
    opponent_id = int(parts[3])

    if callback.from_user.id != opponent_id:
        return await callback.answer("🚫 This challenge is not for you!", show_alert=True)

    await callback.answer("Challenge Accepted! Initializing...")
    
    # Trigger match found logic
    is_group = callback.message.chat.type in ("group", "supergroup")
    p1_q = {"userId": challenger_id, "isGroup": is_group, "chatId": callback.message.chat.id}
    p2_q = {"userId": opponent_id}
    
    from bot import bot
    await callback.message.delete()
    await start_pvp_battle(p1_q, p2_q, "duel", bot)

@router.callback_query(F.data.startswith("pvp_decline_"))
async def handle_duel_decline(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    challenger_id = int(parts[2])
    opponent_id = int(parts[3])
    
    if callback.from_user.id == challenger_id:
        await callback.message.delete()
        return await callback.answer("Challenge cancelled.")
    
    if callback.from_user.id != opponent_id:
        return await callback.answer("🚫 This challenge is not for you!", show_alert=True)
    
    # Opponent declining
    await callback.message.edit_text(f"❌ Challenge declined by <b>{callback.from_user.first_name}</b>.", parse_mode='HTML')

@router.message(Command("ranked"))
async def cmd_ranked(message: types.Message, user: dict):
    res = await matchmaking_service.join_queue(user, is_casual=False)
    if "error" in res:
        return await message.reply(res['error'])
    await message.reply(f"🔎 <b>RANKED MATCHMAKING</b>\nSearching for opponent... (TPS: {res['tps']})", parse_mode='HTML')

@router.message(Command("casual"))
async def cmd_casual(message: types.Message, user: dict):
    res = await matchmaking_service.join_queue(user, is_casual=True)
    if "error" in res:
        return await message.reply(res['error'])
    await message.reply(f"🔎 <b>CASUAL MATCHMAKING</b>\nSearching for opponent... (TPS: {res['tps']})", parse_mode='HTML')
