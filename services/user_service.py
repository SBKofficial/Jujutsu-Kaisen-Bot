import time
from datetime import datetime
from database import db

class UserService:
    def __init__(self):
        self.MILESTONES = {
            2: {"coins": 500, "dust": 50},
            5: {"gachaTickets": 1, "shards": 100},
            10: {"items": [{"id": "gacha_ticket", "qty": 2}], "coins": 1000},
            15: {"coins": 2000, "items": [{"id": "energy_drink", "qty": 2}]},
            20: {"items": [{"id": "cursed_seal_tag", "qty": 5}], "dust": 200},
            25: {"title": "Jujutsu Sorcerer", "gachaTickets": 3},
            30: {"gachaTickets": 5, "shards": 500},
            50: {"items": [{"id": "domain_essence", "qty": 1}], "title": "Domain Master"},
            100: {"title": "Special Grade", "gachaTickets": 50}
        }

    async def add_advanced_rewards(self, user_id, mode, won, streak=0, custom_coins=None, custom_xp=None, custom_dust=None, user=None):
        if not user:
            from services.cache_service import cache_service
            user = cache_service.get_user(user_id)
            if not user:
                user = await db.users.find_one({"telegramId": user_id})
        if not user: return None

        mode_map = {
            'training_easy': {'charXp': 10 if won else 2, 'playerXp': 10 if won else 5, 'coins': 20 if won else 10},
            'training_normal': {'charXp': 20 if won else 5, 'playerXp': 20 if won else 8, 'coins': 40 if won else 15},
            'training_hard': {'charXp': 30 if won else 10, 'playerXp': 30 if won else 10, 'coins': 60 if won else 20},
            'casual': {'charXp': 25 if won else 10, 'playerXp': 25 if won else 10, 'coins': 50 if won else 20},
            'ranked': {'charXp': 40 if won else 15, 'playerXp': 40 if won else 15, 'coins': 100 if won else 30},
            'challenge': {'charXp': 20 if won else 5, 'playerXp': 20 if won else 10, 'coins': 40 if won else 15}
        }

        base = mode_map.get(mode, mode_map['training_easy'] if mode != 'custom' else {'charXp': 0, 'playerXp': custom_xp or 0, 'coins': custom_coins or 0})

        # 1. Coin Gain
        coin_gain = custom_coins if custom_coins is not None else base['coins']
        if mode == 'ranked' and won and streak >= 3:
            coin_gain += 100

        # New Player Boost (14 days)
        reg_date_raw = user.get('registrationDate', 0)
        try:
            if isinstance(reg_date_raw, datetime):
                reg_date_ms = reg_date_raw.timestamp() * 1000
            elif isinstance(reg_date_raw, (int, float)):
                reg_date_ms = reg_date_raw
            else:
                reg_date_ms = 0
            days_since_reg = (time.time() * 1000 - reg_date_ms) / (1000 * 60 * 60 * 24)
        except Exception:
            days_since_reg = 999
        if days_since_reg <= 14 and mode != 'custom':
            coin_gain *= 2

        # Daily Cap (2000)
        today = datetime.utcnow().strftime('%Y-%m-%d')
        if user.get('lastCoinDate') != today:
            user['coinsEarnedToday'] = 0
            user['lastCoinDate'] = today
        
        coin_gain = min(coin_gain, 2000 - user.get('coinsEarnedToday', 0))
        user['coins'] = user.get('coins', 0) + coin_gain
        user['coinsEarnedToday'] = user.get('coinsEarnedToday', 0) + coin_gain

        # 2. Dust Gain
        dust_gain = custom_dust if custom_dust is not None else (10 if won else 2)
        if 'hard' in mode or mode == 'ranked':
            dust_gain += 10
        user['dust'] = user.get('dust', 0) + dust_gain

        # 3. Player XP & Level
        player_xp_gain = custom_xp if custom_xp is not None else (base['playerXp'] if won else base['playerXp'] // 2)
        user['playerXp'] = user.get('playerXp', 0) + player_xp_gain
        
        leveled_up = False
        next_xp = user.get('playerLevel', 1) * 50
        if user['playerXp'] >= next_xp:
            user['playerLevel'] = user.get('playerLevel', 1) + 1
            user['playerXp'] = 0
            user['coins'] += 500
            leveled_up = True
            m = self.MILESTONES.get(user['playerLevel'])
            if m:
                if 'coins' in m: user['coins'] += m['coins']
                if 'gachaTickets' in m: user['gachaTickets'] = user.get('gachaTickets', 0) + m['gachaTickets']
                if 'title' in m: user['title'] = m['title']
                if 'items' in m:
                    inv = user.get('inventory', [])
                    for itm in m['items']:
                        found = False
                        for entry in inv:
                            if entry['id'] == itm['id']:
                                entry['qty'] += itm['qty']
                                found = True
                                break
                        if not found:
                            inv.append(itm)
                    user['inventory'] = inv

        # 4. Character XP
        char_xp_gain = base['charXp']
        if user.get('activeExpCharm'):
            char_xp_gain *= 2

        # Roster Updates
        try:
            roster = await db.roster.find({"userId": user['telegramId']})
            user['_cached_roster'] = roster
        except Exception:
            roster = []
        team_ids = user.get('teamIds', [])
        
        for char_id in team_ids:
            if not char_id: continue
            entry = next((r for r in roster if r['charId'] == char_id), None)
            if entry:
                # Level Cap Check
                grade = entry.get('grade', 'Grade 4')
                caps = {"Grade 4": 25, "Grade 3": 45, "Grade 2": 65, "Grade 1": 85, "Special": 100, "Special Grade": 100}
                cap = caps.get(grade, 25)
                
                if entry.get('level', 1) < cap:
                    entry['xp'] = entry.get('xp', 0) + char_xp_gain
                    needed = entry.get('level', 1) * 10
                    if entry['xp'] >= needed:
                        entry['level'] = entry.get('level', 1) + 1
                        entry['xp'] = 0
                    await db.roster.update({"_id": entry['_id']}, {"$set": {"level": entry['level'], "xp": entry['xp']}})

        user['battles'] = user.get('battles', 0) + 1
        if won: user['battlesWon'] = user.get('battlesWon', 0) + 1

        await db.users.update({"telegramId": user_id}, {"$set": {
            "coins": user['coins'],
            "coinsEarnedToday": user['coinsEarnedToday'],
            "lastCoinDate": user['lastCoinDate'],
            "dust": user['dust'],
            "playerXp": user['playerXp'],
            "playerLevel": user['playerLevel'],
            "inventory": user.get('inventory', []),
            "title": user.get('title', 'Wandering Soul'),
            "gachaTickets": user.get('gachaTickets', 0),
            "battles": user['battles'],
            "battlesWon": user['battlesWon'],
            "activeExpCharm": False
        }})

        return {
            "user": user,
            "coinGain": coin_gain,
            "playerXpGain": player_xp_gain,
            "charXpGain": char_xp_gain,
            "dustGain": dust_gain,
            "leveledUp": leveled_up,
            "playerLevel": user['playerLevel']
        }

    def get_grade_by_level(self, level):
        if level < 20: return "Grade 4"
        if level < 40: return "Grade 3"
        if level < 60: return "Grade 2"
        if level < 80: return "Grade 1"
        return "Special Grade"

    def calculate_final_stats(self, roster_entry, base_char, clan_mult=1.0):
        if not base_char:
            return {
                "name": "Unknown", "level": 1, "hp": 100, "maxHp": 100, "ce": 50, "maxCe": 50,
                "power": 10, "speed": 10, "stamina": 10, "ce_stat": 10, "technique": 10, "grade": "Grade 4",
                "tp": 100, "ts": 100
            }
        
        level = roster_entry.get('level', 1) if roster_entry else 1
        stars = roster_entry.get('stars', 0) if roster_entry else 0
        
        # Grade logic
        grade = roster_entry.get('grade')
        if not grade:
            grade = self.get_grade_by_level(level)
            
        grade_mults = {"Grade 4": 0.50, "Grade 3": 0.70, "Grade 2": 1.00, "Grade 1": 1.30, "Special Grade": 1.80, "Special": 1.80}
        gm = grade_mults.get(grade, 1.0)
        
        growth_rates = {"S": 0.20, "A": 0.15, "B": 0.10, "C": 0.05, "D": 0.02, "-": 0}
        
        # Legacy fallback if character missing new stats
        b_stats = base_char.get('base_stats', {'TS':[50,60], 'STR':[5,5], 'SPD':[5,5], 'DUR':[5,5], 'CE':[5,5]})
        b_growth = base_char.get('growth', {'TS':'C', 'STR':'C', 'SPD':'C', 'DUR':'C', 'CE':'C'})
        
        # Rolled stats
        rolled = roster_entry.get('rolled_stats') if roster_entry else None
        if not rolled:
            # Fallback to max base
            rolled = {
                'TS': b_stats.get('TS', [0, 0])[1],
                'STR': b_stats.get('STR', [0, 0])[1],
                'SPD': b_stats.get('SPD', [0, 0])[1],
                'DUR': b_stats.get('DUR', [0, 0])[1],
                'CE': b_stats.get('CE', [0, 0])[1]
            }
            
        import math
        final = {}
        for stat in ['TS', 'STR', 'SPD', 'DUR', 'CE']:
            g_tier = b_growth.get(stat, 'D')
            g_rate = growth_rates.get(g_tier, 0.0)
            base_rolled = rolled.get(stat, 0)
            
            curr_base = base_rolled + math.floor((level - 1) * g_rate)
            final[stat] = math.floor(curr_base * gm)
            
        # Legacy enhancements
        star_mult = 1.0 + (stars * 0.15)
        for stat in final:
            final[stat] = int(final[stat] * star_mult)
            
        # TP Formula
        tp = final['STR']*2 + final['SPD']*2 + final['DUR']*2 + final['CE']*3 + final['TS']*5
        
        # Map to combat stats
        # Max HP relies on DUR and TS
        final_hp = int(final['TS'] + final['DUR'] * 10 * clan_mult)
        final_ce = int(final['CE'] * 5 * clan_mult)

        return {
            **base_char,
            **roster_entry,
            "grade": grade,
            "hp": final_hp,
            "maxHp": final_hp,
            "ce": final_ce,
            "maxCe": final_ce,
            "power": final['STR'],
            "speed": final['SPD'],
            "stamina": final['DUR'],
            "ce_stat": final['CE'],
            "technique": final['TS'],  # Map TS to technique for combat
            "biq": final['TS'],
            "atk": final['STR'], # Legacy bridge
            "level": level,
            "stars": stars,
            "tp": int(tp),
            "ts": int(final['TS'])
        }


user_service = UserService()
