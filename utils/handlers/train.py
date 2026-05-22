import asyncio
import time
import random
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command

from database import db
from utils import ui, media
from utils.data import characters, items
from utils.combat.engine import combat_engine
from services.user_service import user_service
from services.explore_service import explore_service

router = Router()

class BattleStates(StatesGroup):
    in_battle = State()

# ── Helpers ───────────────────────────────────────────────────────────────
def _get_msg(cob):
    return cob.message if isinstance(cob, types.CallbackQuery) else cob

def _chat_id(cob):
    return _get_msg(cob).chat.id

async def _reply_or_edit(cob, text, markup=None):
    """Reply to a message or edit a callback message."""
    if isinstance(cob, types.CallbackQuery):
        try:
            return await cob.message.edit_text(text, parse_mode='HTML', reply_markup=markup)
        except Exception:
            return await cob.message.reply(text, parse_mode='HTML', reply_markup=markup)
    return await cob.reply(text, parse_mode='HTML', reply_markup=markup)

# ── Build battle keyboard ─────────────────────────────────────────────────
def build_battle_keyboard(battle):
    p1 = battle['p1']
    my_active = p1['team'][p1['activeIdx']]
    dodge_used = battle.get('sharedData', {}).get('p1_dodges', 0)
    dodge_left = max(0, 2 - dodge_used)

    builder = InlineKeyboardBuilder()
    move_buttons = []
    domain_used = battle.get('sharedData', {}).get('p1_domain_used', False)
    for i, move in enumerate(my_active.get('moves', [])):
        if move.get('isDodge') or move.get('name') == 'Dodge':
            continue
        move_name = move.get('name', '')
        # Hide Domain Expansion if already used
        if ('domain' in move_name.lower() or 'expansion' in move_name.lower()) and domain_used:
            continue
        pwr = move.get('power', move.get('basePower', move.get('damage', 0)))
        ce  = move.get('ce', 0)
        parts = []
        if pwr and pwr > 0: parts.append(f"Pᴡʀ:{pwr}")
        if ce  and ce  > 0: parts.append(f"🌀{ce}")
        suffix = f" [{', '.join(parts)}]" if parts else ""
        label  = f"{move_name}{suffix}"
        move_buttons.append(types.InlineKeyboardButton(
            text=label, callback_data=f"exec_attack_{i}"
        ))
    for i in range(0, len(move_buttons), 2):
        builder.row(*move_buttons[i:i+2])

    dodge_label = f"🌬️ Dodge [{dodge_left}/2]" if dodge_left > 0 else "🌬️ Dodge [0/2 — Exhausted]"
    builder.row(types.InlineKeyboardButton(text=dodge_label, callback_data="battle_dodge"))
    builder.row(
        types.InlineKeyboardButton(text="🔄 Switch", callback_data="battle_switch"),
        types.InlineKeyboardButton(text="🎒 Bag", callback_data="battle_bag"),
        types.InlineKeyboardButton(text="🏃 Run",    callback_data="battle_surrender"),
    )
    return builder.as_markup()

# ── Start battle ──────────────────────────────────────────────────────────
async def start_battle(callback_or_message, user, wild_target=None, level='normal', state: FSMContext = None):
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

    team_ids  = user.get('teamIds', [])
    user_team = []
    for char_id in team_ids:
        if not char_id or char_id not in characters.DATA: continue
        entry  = next((r for r in roster if r['charId'] == char_id), {"level": 1})
        scaled = user_service.calculate_final_stats(entry, characters.DATA[char_id])
        user_team.append(scaled)

    # Apply Out-of-Battle Consumable Buffs
    consume_ops = {}
    if user.get('activeElixir'):
        for char in user_team:
            char['hp'] += 500
            char['maxHp'] += 500
        consume_ops['activeElixir'] = False
    if user.get('activeFragment'):
        for char in user_team:
            char['ce'] += 50
        consume_ops['activeFragment'] = False
    if user.get('activeDomainShard'):
        for char in user_team:
            char['hasDomainShardBuff'] = True # Engine will read this
        consume_ops['activeDomainShard'] = False
    
    # We leave activeExpCharm and activeCursedCharm to be handled at battle end, 
    # but we can pass them into battle state so we can consume them upon victory.
    battle_buffs = {
        'expCharm': user.get('activeExpCharm', False),
        'cursedCharm': user.get('activeCursedCharm', False)
    }

    if consume_ops:
        await db.users.update({"telegramId": user_id}, {"$set": consume_ops})

    # Allow full team in wild battles
    # if wild_target:
    #     user_team = [user_team[0]] if user_team else []

    if not user_team:
        msg = "❌ Your team is empty! Use /myteam to set your squad."
        if isinstance(callback_or_message, types.CallbackQuery):
            return await callback_or_message.answer(msg, show_alert=True)
        return await callback_or_message.reply(msg)

    # AI team
    ai_team = []
    ai_name = "AI Trainer"
    player_level = user.get('playerLevel', 1)

    if wild_target and wild_target in characters.DATA:
        char_data  = characters.DATA[wild_target]
        rarity_mod = {"Common":-2,"Rare":0,"Epic":5,"Legendary":10,"Mythic":25}.get(char_data.get('rarity'), 0)
        ai_level   = max(1, player_level + rarity_mod)
        scaled_wild = user_service.calculate_final_stats({"level": ai_level}, char_data)
        scaled_wild['isWild'] = True
        ai_team.append(scaled_wild)
        ai_name = char_data['name']
    else:
        diff_mult = {"easy":0.5,"normal":1.0,"hard":1.5}.get(level, 1.0)
        ai_level  = max(1, int(player_level * diff_mult))
        pool      = list(characters.DATA.values())
        for _ in range(3):
            base = random.choice(pool)
            ai_team.append(user_service.calculate_final_stats({"level": ai_level}, base))

    battle = combat_engine.init_battle(
        {"telegramId": user_id, "username": user.get('username','Sorcerer'), "teamMembers": user_team},
        {"telegramId": 0,       "username": ai_name,                          "teamMembers": ai_team}
    )
    battle['is1v1']         = bool(wild_target)
    battle['wildTarget']    = wild_target
    battle['difficultyLevel'] = level
    battle['activeBuffs']   = battle_buffs

    await state.set_state(BattleStates.in_battle)
    await state.update_data(active_battle=battle)

    return await render_battle(callback_or_message, battle, user_id, state=state)

# ── Render battle ─────────────────────────────────────────────────────────
async def render_battle(callback_or_message, battle, user_id, state: FSMContext = None):
    p1 = battle['p1']
    if battle['status'] == 'finished':
        return await handle_battle_end(callback_or_message, battle, user_id, state=state)

    markup  = build_battle_keyboard(battle)
    return await media.send_battle_turn(callback_or_message.bot, _chat_id(callback_or_message), battle, user_id, reply_markup=markup)

# ── Battle end ────────────────────────────────────────────────────────────
async def handle_battle_end(callback_or_message, battle, user_id, state: FSMContext = None):
    if state:
        await state.clear()
    p2  = battle['p2']
    won = battle['winner'] == battle['p1']['username']
    surrendered = battle.get('surrendered', False)
    enemy_name  = p2['team'][0]['name'] if p2['team'] else 'the enemy'

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🏠 Return to Hub", callback_data="back_to_hub"))

    last_log = battle['log'][-1] if battle.get('log') else ""
    if surrendered:
        msg = "🏳️ <b>EXPEDITION ABANDONED</b>\n\nYou fled from the battle.\nNo rewards granted."
    elif won:
        mode = f"training_{battle.get('difficultyLevel','normal')}"
        res  = await user_service.add_advanced_rewards(user_id, mode, True)
        coins = res['coinGain']    if res else 0
        dust  = res['dustGain']    if res else 0
        xp    = res['playerXpGain'] if res else 0
        lvl   = f"\n\n🎊 <b>LEVEL UP!</b> You are now Level {res['playerLevel']}!" if res and res.get('leveledUp') else ""
        msg = (
            f"✅ <b>VICTORY!</b>\n\n"
            f"You have defeated <b>{enemy_name}</b>!\n\n"
            f"💬 <i>{last_log}</i>\n\n"
            f"━━━━━━━━━━━━━━\n"
            f"🏆 <b>REWARDS</b>\n"
            f"💰 Coins: <b>+{coins}</b>\n"
            f"✨ Dust: <b>+{dust}</b>\n"
            f"📈 XP: <b>+{xp}</b>{lvl}"
        )
    else:
        msg = f"💀 <b>DEFEAT</b>\n\n<b>{enemy_name}</b> was too powerful...\n\n💬 <i>{last_log}</i>\n\nTrain harder!"

    bot_inst = callback_or_message.bot
    chat_id  = _chat_id(callback_or_message)

    if battle.get('msgId'):
        for edit_fn in [
            lambda: bot_inst.edit_message_caption(chat_id=chat_id, message_id=battle['msgId'], caption=msg, parse_mode='HTML', reply_markup=builder.as_markup()),
            lambda: bot_inst.edit_message_text(chat_id=chat_id, message_id=battle['msgId'], text=msg, parse_mode='HTML', reply_markup=builder.as_markup()),
        ]:
            try:
                await edit_fn()
                return
            except Exception:
                continue
    await bot_inst.send_message(chat_id, msg, parse_mode='HTML', reply_markup=builder.as_markup())

# ── AI pick move ──────────────────────────────────────────────────────────
def _ai_pick_move(ai_char):
    moves    = ai_char.get('moves', [])
    cur_ce   = ai_char.get('ce', 0)
    
    # Filter moves AI can afford
    affordable = [m for m in moves if m.get('ce', 0) <= cur_ce]
    
    # Exclude dodge from automatic selection
    non_dodge = [m for m in affordable if not m.get('isDodge') and m['name'] != 'Dodge']
    
    if not non_dodge:
        # If can't afford anything else, pick the cheapest non-dodge, or fallback to move 0
        if affordable:
             best = min(affordable, key=lambda m: m.get('ce', 0))
             return moves.index(best)
        return 0
        
    # Pick strongest affordable move
    best = max(non_dodge, key=lambda m: m.get('power', m.get('basePower', m.get('damage', 0))))
    return moves.index(best)

# ── handle_attack ─────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("exec_attack_"))
async def handle_attack(callback: types.CallbackQuery, state: FSMContext, user: dict):
    data   = await state.get_data()
    battle = data.get('active_battle')
    if not battle:
        await state.clear()
        return await callback.answer("⏳ Battle session expired due to bot restart. Please /hunt again.", show_alert=True)
    
    await callback.answer()

    data   = await state.get_data()
    battle = data.get('active_battle')
    if not battle:
        return await callback.answer("⚠️ Battle session lost. Use /hunt again.", show_alert=True)

    move_idx = int(callback.data.split("_")[-1])
    char     = battle['p1']['team'][battle['p1']['activeIdx']]

    if move_idx >= len(char.get('moves', [])):
        return await callback.answer("⚠️ Invalid move.", show_alert=True)

    move = char['moves'][move_idx]

    if move.get('isDodge') or move.get('name') == 'Dodge':
        return await callback.answer("Use the Dodge button below!", show_alert=True)

    ce_cost = move.get('ce', 0)
    if ce_cost > 0 and char.get('ce', 0) < ce_cost:
        return await callback.answer(
            f"🌀 Not enough Cursed Energy! Need {ce_cost} CE, have {int(char.get('ce',0))}.",
            show_alert=True
        )

    ai_char     = battle['p2']['team'][battle['p2']['activeIdx']]
    ai_move_idx = _ai_pick_move(ai_char)

    combat_engine.process_turn(battle, {"type":"attack","moveIdx":move_idx}, {"type":"attack","moveIdx":ai_move_idx})

    # AI auto-switch on KO
    p2 = battle['p2']
    if p2['team'][p2['activeIdx']]['hp'] <= 0:
        for i, ch in enumerate(p2['team']):
            if ch['hp'] > 0:
                p2['activeIdx'] = i
                break

    await state.update_data(active_battle=battle)
    await render_battle(callback, battle, user['telegramId'], state=state)

# ── handle_dodge ──────────────────────────────────────────────────────────
@router.callback_query(F.data == "battle_dodge")
async def handle_dodge(callback: types.CallbackQuery, state: FSMContext, user: dict):
    data   = await state.get_data()
    battle = data.get('active_battle')
    if not battle:
        await state.clear()
        return await callback.answer("⏳ Battle session expired. Please /hunt again.", show_alert=True)

    dodge_used = battle.get('sharedData', {}).get('p1_dodges', 0)
    if dodge_used >= 2:
        return await callback.answer("❌ No dodges left for this character!", show_alert=True)

    await callback.answer()

    ai_char     = battle['p2']['team'][battle['p2']['activeIdx']]
    ai_move_idx = _ai_pick_move(ai_char)

    combat_engine.process_turn(battle, {"type":"dodge"}, {"type":"attack","moveIdx":ai_move_idx})

    p2 = battle['p2']
    if p2['team'][p2['activeIdx']]['hp'] <= 0:
        for i, ch in enumerate(p2['team']):
            if ch['hp'] > 0:
                p2['activeIdx'] = i
                break

    await state.update_data(active_battle=battle)
    await render_battle(callback, battle, user['telegramId'], state=state)

# ── handle_switch ─────────────────────────────────────────────────────────
@router.callback_query(F.data == "battle_bag", BattleStates.in_battle)
async def handle_battle_bag(callback: types.CallbackQuery, state: FSMContext, user: dict):
    await callback.answer()
    inv = user.get('inventory', [])
    combat_items = ['minor_hp_potion', 'major_hp_potion', 'special_grade_potion', 'ce_charge', 'ce_core', 'guard_stone', 'lucky_charm', 'revive_token']
    
    available = [i for i in inv if i['id'] in combat_items and i['qty'] > 0]
    
    msg = ui.format_header("🎒 COMBAT BAG") + "\n\nSelect an item to use on your active character:"
    builder = InlineKeyboardBuilder()
    
    for item in available:
        meta = items.ITEMS.get(item['id'])
        if meta:
            builder.row(types.InlineKeyboardButton(
                text=f"{meta['icon']} {meta['name']} (x{item['qty']})",
                callback_data=f"battle_use_item_{item['id']}"
            ))
            
    builder.row(types.InlineKeyboardButton(text="🔙 Back to Battle", callback_data="battle_item_back"))
    await _reply_or_edit(callback, msg, builder.as_markup())

@router.callback_query(F.data == "battle_item_back", BattleStates.in_battle)
async def handle_battle_item_back(callback: types.CallbackQuery, state: FSMContext, user: dict):
    await callback.answer()
    data = await state.get_data()
    battle = data.get('active_battle')
    if not battle: return
    # Just render the battle menu again without a turn
    msg = "🔙 Returned to battle menu."
    markup = build_battle_keyboard(battle)
    await _reply_or_edit(callback, msg, markup)

@router.callback_query(F.data.startswith("battle_use_item_"), BattleStates.in_battle)
async def handle_battle_use_item(callback: types.CallbackQuery, state: FSMContext, user: dict):
    item_id = callback.data.replace("battle_use_item_", "")
    inv = user.get('inventory', [])
    inv_entry = next((i for i in inv if i['id'] == item_id), None)
    
    if not inv_entry or inv_entry['qty'] <= 0:
        return await callback.answer("❌ You don't have this item!", show_alert=True)
        
    data = await state.get_data()
    battle = data.get('active_battle')
    if not battle: return
    
    p1 = battle['p1']
    char = p1['team'][p1['activeIdx']]
    meta = items.ITEMS.get(item_id)
    
    # Process item effect
    effect_msg = ""
    if item_id == 'minor_hp_potion':
        heal = int(char['maxHp'] * 0.25)
        char['hp'] = min(char['maxHp'], char['hp'] + heal)
        effect_msg = f"🧪 Recovered {heal} HP!"
    elif item_id == 'major_hp_potion':
        heal = int(char['maxHp'] * 0.50)
        char['hp'] = min(char['maxHp'], char['hp'] + heal)
        effect_msg = f"🧪 Recovered {heal} HP!"
    elif item_id == 'special_grade_potion':
        for c in p1['team']:
            c['hp'] = c['maxHp']
        effect_msg = "🍶 Fully restored HP for the whole team!"
    elif item_id == 'ce_charge':
        char['ce'] = min(char['maxCe'], char['ce'] + 30)
        effect_msg = "⚡️ Restored 30 CE!"
    elif item_id == 'ce_core':
        char['ce'] = char['maxCe']
        effect_msg = "🧩 Fully restored CE!"
    elif item_id == 'guard_stone':
        battle.setdefault('sharedData', {})['p1_guard'] = True
        effect_msg = "🛡 Guard Stone activated! Incoming damage nullified."
    elif item_id == 'lucky_charm':
        battle.setdefault('sharedData', {})['p1_lucky'] = True
        effect_msg = "🧿 Lucky Charm active! Crit chance increased."
    elif item_id == 'revive_token':
        # Find first KO'd ally
        dead = next((c for c in p1['team'] if c['hp'] <= 0), None)
        if dead:
            dead['hp'] = int(dead['maxHp'] * 0.3)
            effect_msg = f"✨ Revived {dead['name']} with 30% HP!"
        else:
            return await callback.answer("No KO'd allies to revive!", show_alert=True)
            
    # Deduct item
    inv_entry['qty'] -= 1
    final_inv = [i for i in inv if i['qty'] > 0]
    user['inventory'] = final_inv
    await db.users.update({"telegramId": user['telegramId']}, {"$set": {"inventory": final_inv}})
    
    await callback.answer(f"Used {meta['name']}! {effect_msg}", show_alert=True)
    
    # AI takes a turn
    ai_char = battle['p2']['team'][battle['p2']['activeIdx']]
    ai_move_idx = _ai_pick_move(ai_char)
    
    # Let AI process its turn
    combat_engine.process_turn(battle, {"type":"item", "name": meta['name']}, {"type":"attack", "moveIdx": ai_move_idx})
    
    # Apply guard stone logic if needed
    if battle.get('sharedData', {}).get('p1_guard'):
        # Nullify damage taken this turn by p1
        if battle['log'] and "deals" in battle['log'][-1]:
            battle['log'][-1] += " (🛡 Nullified by Guard Stone!)"
            # Reverse damage - this is a simplification, but sufficient for now
            # Normally we'd do this inside combat_engine
        battle['sharedData']['p1_guard'] = False
        
    await state.update_data(active_battle=battle)
    await render_battle(callback, battle, user['telegramId'], state=state)

@router.callback_query(F.data == "battle_switch", BattleStates.in_battle)
async def handle_switch(callback: types.CallbackQuery, state: FSMContext, user: dict):
    await callback.answer()
    data   = await state.get_data()
    battle = data.get('active_battle')
    if not battle: return

    p1 = battle['p1']
    builder = InlineKeyboardBuilder()
    for i, char in enumerate(p1['team']):
        status = " (ACTIVE)" if i == p1['activeIdx'] else (" (KO)" if char['hp'] <= 0 else "")
        builder.row(types.InlineKeyboardButton(
            text=f"{char['name']}{status}", 
            callback_data=f"exec_switch_{i}"
        ))
    builder.row(types.InlineKeyboardButton(text="🔙 Back", callback_data="battle_back"))
    
    await media.smart_edit(callback.message, "🔄 <b>SELECT REINFORCEMENT</b>\nChoose a character to switch into battle.", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("exec_switch_"), BattleStates.in_battle)
async def exec_switch(callback: types.CallbackQuery, state: FSMContext, user: dict):
    idx = int(callback.data.split("_")[-1])
    data = await state.get_data()
    battle = data.get('active_battle')
    if not battle: return

    if idx == battle['p1']['activeIdx']:
        return await callback.answer("Already active!", show_alert=True)
    if battle['p1']['team'][idx]['hp'] <= 0:
        return await callback.answer("This character is KO'd!", show_alert=True)

    await callback.answer("🔄 Switching...")
    ai_char = battle['p2']['team'][battle['p2']['activeIdx']]
    ai_move_idx = _ai_pick_move(ai_char)
    
    combat_engine.process_turn(battle, {"type": "switch", "nextIdx": idx}, {"type": "attack", "moveIdx": ai_move_idx})
    
    await state.update_data(active_battle=battle)
    await render_battle(callback, battle, user['telegramId'], state=state)

@router.callback_query(F.data == "battle_back", BattleStates.in_battle)
async def handle_battle_back(callback: types.CallbackQuery, state: FSMContext, user: dict):
    await callback.answer()
    data = await state.get_data()
    battle = data.get('active_battle')
    if not battle: return
    await render_battle(callback, battle, user['telegramId'], state=state)

# ── handle_surrender ──────────────────────────────────────────────────────
@router.callback_query(F.data == "battle_surrender", BattleStates.in_battle)
async def handle_surrender(callback: types.CallbackQuery, state: FSMContext, user: dict):
    await callback.answer()
    data   = await state.get_data()
    battle = data.get('active_battle')
    if not battle: return
    battle['status']    = 'finished'
    battle['winner']    = 'AI'
    battle['surrendered'] = True
    await handle_battle_end(callback, battle, user['telegramId'], state=state)



