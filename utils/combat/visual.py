import os
import io
import time
import random
import asyncio
from PIL import Image, ImageDraw, ImageFont
from utils import assets

class VisualEngine:
    def __init__(self):
        self.bg_cache = {}
        self.asset_cache = {}
        self.font_cache = {}
        self.font_path = "arial.ttf"
        
        self.font_bold = self._get_font("arialbd.ttf", 22)
        self.font_mono = self._get_font("cour.ttf", 22)

    def _get_font(self, name, size):
        cache_key = (name, size)
        if cache_key in self.font_cache:
            return self.font_cache[cache_key]
        
        paths = [
            os.path.join("C:\\Windows\\Fonts", name),
            name,
            os.path.join(assets.BASE_DIR, name),
            os.path.join(assets.IMAGE_DIR, name)
        ]
        for p in paths:
            if os.path.exists(p):
                try:
                    f = ImageFont.truetype(p, size)
                    self.font_cache[cache_key] = f
                    return f
                except:
                    pass
        # Fallback to arial
        try:
            f = ImageFont.truetype("arial.ttf", size)
            self.font_cache[cache_key] = f
            return f
        except:
            f = ImageFont.load_default()
            self.font_cache[cache_key] = f
            return f

    def _get_image(self, path, size=None):
        cache_key = f"{path}_{size}"
        if cache_key in self.asset_cache:
            return self.asset_cache[cache_key]
        
        if os.path.exists(path):
            img = Image.open(path).convert("RGBA")
            if size:
                img = img.resize(size)
            self.asset_cache[cache_key] = img
            return img
        return None

    def get_hp_color(self, pct):
        if pct > 0.5: return (0, 255, 136) # Green
        if pct > 0.2: return (255, 204, 0) # Yellow
        return (255, 68, 68) # Red

    async def generate_battle_scene(self, p1_char, p2_char, active_side='p1'):
        return await asyncio.to_thread(self._generate_battle_scene_sync, p1_char, p2_char, active_side)

    def _generate_battle_scene_sync(self, p1_char, p2_char, active_side='p1'):
        try:
            # 1. Resolve Paths
            p1_path = assets.get_pixel_asset_path(p1_char)
            p2_path = assets.get_pixel_asset_path(p2_char)

            # 2. Open Sprites
            p1_img = self._get_image(p1_path, (320, 320)) if p1_path else None
            p2_img = self._get_image(p2_path, (320, 320)) if p2_path else None

            # 3. Create Canvas
            bg_path = assets.REGISTRY.get("Battle_BG")
            bg_img = self._get_image(bg_path, (1024, 600)) if bg_path else None
            
            canvas = bg_img.copy() if bg_img else Image.new("RGBA", (1024, 600), (10, 10, 20, 255))
            draw = ImageDraw.Draw(canvas)

            # 4. Composite Sprites
            if p1_img:
                canvas.paste(p1_img, (80, 110), p1_img)
            if p2_img:
                canvas.paste(p2_img, (644, 110), p2_img)

            # 5. UI Layer (HUDs)
            p1_hp_pct = max(0, min(1, p1_char.get('hp', 100) / p1_char.get('maxHp', 100)))
            p1_ce_pct = max(0, min(1, p1_char.get('ce', 50) / p1_char.get('maxCe', 100)))
            
            p2_hp_pct = max(0, min(1, p2_char.get('hp', 100) / p2_char.get('maxHp', 100)))
            p2_ce_pct = max(0, min(1, p2_char.get('ce', 50) / p2_char.get('maxCe', 100)))

            # P1 HUD (Left)
            draw.rounded_rectangle([40, 20, 460, 110], radius=15, fill=(10, 10, 25, 220), outline=(0, 229, 255), width=2)
            draw.text((60, 30), p1_char['name'].upper(), fill="white", font=self.font_bold)
            draw.text((440, 30), p1_char.get('grade', 'G3'), fill=(0, 229, 255), font=self.font_mono, anchor="rt")
            # HP Bar
            draw.rectangle([60, 65, 440, 75], fill=(30, 30, 40))
            draw.rectangle([60, 65, 60 + (380 * p1_hp_pct), 75], fill=self.get_hp_color(p1_hp_pct))
            # CE Bar
            draw.rectangle([60, 85, 440, 92], fill=(30, 30, 40))
            draw.rectangle([60, 85, 60 + (380 * p1_ce_pct), 92], fill=(0, 150, 255))

            # P2 HUD (Right)
            draw.rounded_rectangle([564, 20, 984, 110], radius=15, fill=(10, 10, 25, 220), outline=(255, 23, 68), width=2)
            draw.text((584, 30), p2_char['name'].upper(), fill="white", font=self.font_bold)
            draw.text((964, 30), p2_char.get('grade', 'G3'), fill=(255, 23, 68), font=self.font_mono, anchor="rt")
            # HP Bar
            draw.rectangle([584, 65, 964, 75], fill=(30, 30, 40))
            draw.rectangle([584, 65, 584 + (380 * p2_hp_pct), 75], fill=self.get_hp_color(p2_hp_pct))
            # CE Bar
            draw.rectangle([584, 85, 964, 92], fill=(30, 30, 40))
            draw.rectangle([584, 85, 584 + (380 * p2_ce_pct), 92], fill=(255, 100, 0) if p2_char.get('energyType') == 'PE' else (0, 150, 255))

            # Dialogue Bar & Black Flash indicator
            draw.rounded_rectangle([50, 520, 974, 585], radius=12, fill=(0, 0, 0, 230), outline=(255, 255, 255, 40), width=1)
            
            last_log = p1_char.get('lastAction', 'BATTLE START!').upper()
            if "BLACK FLASH" in last_log:
                draw.text((80, 540), "⚡ BLACK FLASH ⚡", fill=(255, 0, 0), font=self.font_bold)
                draw.text((320, 540), f"▶ {last_log}", fill=(255, 255, 255), font=self.font_mono)
            else:
                draw.text((80, 540), f"▶ {last_log}", fill=(0, 255, 136), font=self.font_mono)

            # 6. Return as Buffer
            img_byte_arr = io.BytesIO()
            canvas.convert("RGB").save(img_byte_arr, format='JPEG', quality=75)
            return img_byte_arr.getvalue()

        except Exception as e:
            print(f"Visual Error: {e}")
            return None

    async def generate_gacha_grid(self, results):
        return await asyncio.to_thread(self._generate_gacha_grid_sync, results)

    def _generate_gacha_grid_sync(self, results):
        # Implementation for 10-pull grid using Pillow
        canvas_w, canvas_h = 1600, 940
        item_w, item_h = 300, 420
        spacing_x, spacing_y = 15, 30
        start_x, start_y = 25, 50

        rarity_colors = {
            "Common": (176, 190, 197),
            "Rare": (33, 150, 243),
            "Epic": (156, 39, 176),
            "Legendary": (255, 202, 40),
            "Mythic": (244, 67, 54)
        }

        canvas = Image.new("RGB", (canvas_w, canvas_h), (10, 10, 15))
        draw = ImageDraw.Draw(canvas)

        for i, res in enumerate(results):
            char = res['character']
            img_path = assets.get_asset_path(char)
            col = i % 5
            row = i // 5
            left = start_x + col * (item_w + spacing_x)
            top = start_y + row * (item_h + spacing_y)

            # Frame
            color = rarity_colors.get(char['rarity'], (255, 255, 255))
            draw.rounded_rectangle([left, top, left + item_w, top + item_h], radius=20, fill=(20, 20, 30), outline=color, width=6)

            # Portrait
            try:
                portrait = self._get_image(img_path, (260, 260))
                if portrait:
                    canvas.paste(portrait, (left + 20, top + 20), portrait)
            except:
                pass

            # Text
            draw.text((left + item_w//2, top + 320), char['name'].upper(), fill="white", font=self.font_bold, anchor="mm")
            draw.text((left + item_w//2, top + 355), char['rarity'].upper(), fill=color, font=self.font_bold, anchor="mm")

            if res.get('isNew'):
                draw.ellipse([left + 230, top + 10, left + 290, top + 70], fill=(255, 68, 68))
                draw.text((left + 260, top + 40), "NEW", fill="white", font=self.font_bold, anchor="mm")

        img_byte_arr = io.BytesIO()
        canvas.save(img_byte_arr, format='JPEG', quality=80)
        return img_byte_arr.getvalue()

    async def generate_team_card(self, team_members):
        """Generate a premium team formation card with uniform layout."""
        return await asyncio.to_thread(self._generate_team_card_sync, team_members)

    def _generate_team_card_sync(self, team_members):
        try:
            canvas_w, canvas_h = 1024, 600
            canvas = Image.new("RGB", (canvas_w, canvas_h), (15, 15, 25))
            draw = ImageDraw.Draw(canvas)

            # 1. Background Styling
            bg_path = assets.REGISTRY.get("Team_BG")
            bg_key = f"Team_BG_composite_{canvas_w}_{canvas_h}"
            if bg_key in self.asset_cache:
                canvas.paste(self.asset_cache[bg_key], (0, 0))
            elif bg_path:
                bg = self._get_image(bg_path, (canvas_w, canvas_h))
                if bg:
                    overlay = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 160))
                    bg_composite = Image.alpha_composite(bg, overlay).convert("RGB")
                    self.asset_cache[bg_key] = bg_composite
                    canvas.paste(bg_composite, (0, 0))
            else:
                for i in range(canvas_h):
                    color = (15 + i//40, 15 + i//50, 25 + i//30)
                    draw.line([(0, i), (canvas_w, i)], fill=color)
                draw.rectangle([0, 0, 380, canvas_h], fill=(10, 10, 20, 200))
                draw.line([380, 0, 380, canvas_h], fill=(0, 229, 255), width=2)

            # 2. Left side: Character Portraits (Uniform List)
            img_size = 170
            start_y = 50
            gap = 15
            
            for i, member in enumerate(team_members[:3]):
                pos_y = start_y + (i * (img_size + gap))
                pos_x = 100
                
                rarity_colors = {"Common": (180, 180, 180), "Rare": (0, 180, 255), "Epic": (200, 0, 255), "Legendary": (255, 215, 0), "Mythic": (255, 0, 50)}
                color = rarity_colors.get(member.get('rarity', 'Common'), (0, 229, 255))
                
                draw.rounded_rectangle([pos_x - 5, pos_y - 5, pos_x + img_size + 5, pos_y + img_size + 5], radius=10, outline=color, width=3)
                
                img_path = assets.get_asset_path(member)
                if img_path:
                    char_img = self._get_image(img_path, (img_size, img_size))
                    if char_img:
                        canvas.paste(char_img, (pos_x, pos_y), char_img)
                
                draw.ellipse([pos_x - 35, pos_y + 10, pos_x - 5, pos_y + 40], fill=color)
                draw.text((pos_x - 20, pos_y + 25), str(i+1), fill="white", font=self.font_bold, anchor="mm")

            # 3. Right side: Details
            start_x = 420
            for i, member in enumerate(team_members[:3]):
                pos_y = start_y + (i * (img_size + gap))
                
                box_color = (25, 25, 40, 220)
                draw.rounded_rectangle([start_x, pos_y, 980, pos_y + img_size], radius=15, fill=box_color, outline=(255, 255, 255, 30), width=1)
                
                pos_labels = ["FRONT", "MIDDLE", "BACK"]
                label = pos_labels[i]
                draw.text((start_x + 20, pos_y + 20), label, fill=(0, 229, 255) if i == 0 else (150, 150, 150), font=self.font_bold)
                
                name_text = member['name'].upper()
                grade_text = f"[{member.get('grade', '???')}]"
                draw.text((start_x + 20, pos_y + 55), name_text, fill="white", font=self.font_bold)
                draw.text((start_x + 20, pos_y + 90), f"Level {member.get('level', 1)} {grade_text}", fill=(200, 200, 200), font=self.font_mono)
                
                # Stats Bar with explicit labels
                stats_str = f"⚔️ STR {member.get('atk', 0)}   ❤️ HP {member.get('hp', 0)}   ⚡ SPD {member.get('speed', 0)}"
                draw.text((start_x + 20, pos_y + 130), stats_str, fill=(0, 255, 136), font=self.font_bold)

            draw.text((canvas_w - 20, 20), "JUJUTSU HIGH SQUAD", fill=(0, 229, 255), font=self.font_bold, anchor="rt")

            img_byte_arr = io.BytesIO()
            canvas.save(img_byte_arr, format='JPEG', quality=90)
            return img_byte_arr.getvalue()
        except Exception as e:
            print(f"Team Card Error: {e}")
            import traceback; traceback.print_exc()
            return None

    async def generate_license_card(self, user_data, player_photo_bytes=None, active_char=None):
        """Generate a premium High-Tech Sorcerer License based on the requested PRO.jpg style."""
        return await asyncio.to_thread(self._generate_license_card_sync, user_data, player_photo_bytes, active_char)

    def _generate_license_card_sync(self, user_data, player_photo_bytes=None, active_char=None):
        try:
            canvas_w, canvas_h = 1024, 600
            
            # 1. Background
            bg_path = os.path.join(assets.IMAGE_DIR, "tech_bg.webp")
            if not os.path.exists(bg_path):
                bg_path = os.path.join(assets.IMAGE_DIR, "tech_bg.png")

            bg_key = f"license_bg_composite_{canvas_w}_{canvas_h}"
            if bg_key in self.asset_cache:
                canvas = self.asset_cache[bg_key].copy()
            else:
                bg_img = self._get_image(bg_path, (canvas_w, canvas_h))
                if bg_img:
                    overlay = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 120))
                    bg_composite = Image.alpha_composite(bg_img, overlay)
                    self.asset_cache[bg_key] = bg_composite
                    canvas = bg_composite.copy()
                else:
                    canvas = Image.new("RGBA", (canvas_w, canvas_h), (5, 15, 35, 255))
            
            draw = ImageDraw.Draw(canvas)
            
            # 2. Fonts Initialization
            header_font = self._get_font("arialbd.ttf", 40)
            sub_font = self._get_font("arial.ttf", 18)
            label_font_small = self._get_font("arialbd.ttf", 18)
            val_font_small = self._get_font("arialbd.ttf", 22)

            # 3. Header & Logos
            school = str(user_data.get('school', 'Tokyo'))
            is_kyoto = "kyoto" in school.lower()
            school_name = "Kyoto Jujutsu High" if is_kyoto else "Tokyo Jujutsu High"
            
            s_key = "Kyoto_Logo" if is_kyoto else "Tokyo_Logo"
            s_path = assets.REGISTRY.get(s_key)
            logo_key = f"{s_key}_circle_110"
            if logo_key in self.asset_cache:
                logo_circle = self.asset_cache[logo_key]
                canvas.paste(logo_circle, (45, 35), logo_circle)
            elif s_path:
                s_img = self._get_image(s_path, (110, 110))
                if s_img:
                    mask = Image.new("L", (110, 110), 0)
                    mask_draw = ImageDraw.Draw(mask)
                    mask_draw.ellipse((0, 0, 110, 110), fill=255)
                    
                    logo_circle = Image.new("RGBA", (110, 110), (0,0,0,0))
                    logo_circle.paste(s_img, (0,0), mask=mask)
                    self.asset_cache[logo_key] = logo_circle
                    canvas.paste(logo_circle, (45, 35), logo_circle)
            
            if s_path:
                # Outer glow for logo
                draw.ellipse([45, 35, 155, 145], outline=(0, 229, 255, 100), width=3)

            # Header Text
            draw.text((175, 50), "JUJUTSU HIGH LICENSES", fill=(255, 255, 255), font=header_font)
            draw.text((175, 100), "呪術高等専門学校ライセンス", fill=(150, 190, 220), font=sub_font)
            
            # ID Label (Top Right)
            draw.rounded_rectangle([790, 70, 970, 115], radius=5, outline=(0, 229, 255), width=2)
            draw.text((880, 92), "[SORCERER ID]", fill=(0, 229, 255), font=sub_font, anchor="mm")

            # 4. Main Data Fields (Left Side)
            y_start = 180
            line_h = 48
            x_label = 100
            x_val = 260
            
            # Load Icons
            icons_path = os.path.join(assets.IMAGE_DIR, "profile_icons.png")
            icons_img = self._get_image(icons_path)

            def get_icon(idx):
                if not icons_img: return None
                cache_key = f"icon_crop_{idx}"
                if cache_key in self.asset_cache:
                    return self.asset_cache[cache_key]
                w, h = icons_img.size
                cw, ch = w // 3, h // 3
                row, col = idx // 3, idx % 3
                icon = icons_img.crop((col * cw, row * ch, (col + 1) * cw, (row + 1) * ch))
                icon_resized = icon.resize((45, 45), Image.LANCZOS)
                self.asset_cache[cache_key] = icon_resized
                return icon_resized

            fields = [
                (0, "Student ID:", str(user_data.get('telegramId', '000000'))),
                (3, "Name:", str(user_data.get('username', 'Unknown')).upper()),
                (1, "Rank:", str(user_data.get('rank', 'Iron')).upper()),
                (4, "Grade:", str(user_data.get('grade', '4')).replace("Grade ", "")),
                (2, "Energy:", f"{user_data.get('playerLevel', 1) % 100}%"),
                (5, "Technique:", f"{min(99, 50 + user_data.get('playerLevel', 1))}%"),
                (7, "Issued:", time.strftime("%Y-%m-%d")),
                (8, "Authority:", school_name)
            ]

            for i, (icon_idx, lbl, val) in enumerate(fields):
                yy = y_start + (i * line_h)
                
                # Field Box
                draw.rounded_rectangle([45, yy - 12, 470, yy + 32], radius=5, fill=(0, 25, 50, 180), outline=(0, 229, 255, 50), width=1)
                
                # Icon placement
                icon_img = get_icon(icon_idx)
                if icon_img:
                    canvas.paste(icon_img, (48, yy - 13), icon_img)
                else:
                    draw.ellipse([50, yy - 8, 85, yy + 28], outline=(0, 229, 255, 120), width=2)
                
                # Text Labels
                draw.text((x_label, yy + 10), lbl, fill=(160, 210, 255), font=label_font_small, anchor="lm")
                
                # Values
                if "Energy" in lbl or "Technique" in lbl:
                    pct = int(val.replace("%", ""))
                    draw.text((x_val, yy + 10), val, fill=(255, 255, 255), font=val_font_small, anchor="lm")
                    # Progress Bar
                    bar_x = x_val + 50
                    draw.rectangle([bar_x, yy + 5, bar_x + 150, yy + 15], fill=(0, 40, 80), outline=(0, 229, 255, 80))
                    draw.rectangle([bar_x, yy + 5, bar_x + (150 * pct / 100), yy + 15], fill=(0, 229, 255))
                elif "Grade" in lbl:
                    draw.text((x_val, yy + 10), val, fill=(255, 255, 255), font=val_font_small, anchor="lm")
                    # Grade blocks
                    bar_x = x_val + 50
                    val_num = int(val) if val.isdigit() else 1
                    for step in range(6):
                        color = (0, 229, 255) if step < val_num else (0, 40, 80)
                        draw.rectangle([bar_x + (step * 25), yy + 5, bar_x + (step * 25) + 18, yy + 15], fill=color)
                else:
                    draw.text((x_val, yy + 10), val, fill=(255, 255, 255), font=val_font_small, anchor="lm")

            # 5. Player Photo & Grade Frame (Right Side)
            draw.rectangle([600, 180, 970, 530], outline=(0, 229, 255, 100), width=2)
            draw.line([600, 180, 660, 180], fill=(0, 229, 255), width=6)
            draw.line([600, 180, 600, 240], fill=(0, 229, 255), width=6)
            draw.line([970, 530, 910, 530], fill=(0, 229, 255), width=6)
            draw.line([970, 530, 970, 470], fill=(0, 229, 255), width=6)

            if not player_photo_bytes:
                default_pfp_path = os.path.join(assets.IMAGE_DIR, "PRO.webp")
                if not os.path.exists(default_pfp_path):
                    default_pfp_path = os.path.join(assets.IMAGE_DIR, "PRO.png")
                
                pfp_key = "default_pfp_processed_350_340"
                if pfp_key in self.asset_cache:
                    p_img_cropped = self.asset_cache[pfp_key]
                    canvas.paste(p_img_cropped, (610, 185), p_img_cropped)
                elif os.path.exists(default_pfp_path):
                    try:
                        p_img = Image.open(default_pfp_path).convert("RGBA")
                        target_w, target_h = 350, 340
                        ratio = max(target_w/p_img.width, target_h/p_img.height)
                        p_img = p_img.resize((int(p_img.width*ratio), int(p_img.height*ratio)), Image.LANCZOS)
                        left = (p_img.width - target_w) / 2
                        top = (p_img.height - target_h) / 2
                        p_img_cropped = p_img.crop((left, top, left + target_w, top + target_h))
                        self.asset_cache[pfp_key] = p_img_cropped
                        canvas.paste(p_img_cropped, (610, 185), p_img_cropped)
                    except Exception as e:
                        print(f"DEBUG: Photo paste error: {e}")
            else:
                try:
                    p_img = Image.open(io.BytesIO(player_photo_bytes)).convert("RGBA")
                    target_w, target_h = 350, 340
                    ratio = max(target_w/p_img.width, target_h/p_img.height)
                    p_img = p_img.resize((int(p_img.width*ratio), int(p_img.height*ratio)), Image.LANCZOS)
                    left = (p_img.width - target_w) / 2
                    top = (p_img.height - target_h) / 2
                    p_img = p_img.crop((left, top, left + target_w, top + target_h))
                    canvas.paste(p_img, (610, 185), p_img)
                except Exception as e:
                    print(f"DEBUG: Photo paste error: {e}")

            # Grade Badge
            grade_raw = str(user_data.get('grade', '4')).replace("Grade ", "")
            draw.ellipse([570, 150, 670, 250], fill=(10, 20, 40), outline=(0, 229, 255), width=4)
            draw.text((620, 180), "Grade", fill=(160, 210, 255), font=sub_font, anchor="mm")
            draw.text((620, 215), grade_raw, fill=(255, 255, 255), font=header_font, anchor="mm")

            # 6. Barcode & Footer
            bx = 45
            by = 555
            draw.rectangle([bx, by, bx + 430, by + 35], fill=(255, 255, 255))
            for _ in range(45):
                w = random.choice([2, 4, 6, 8])
                draw.rectangle([bx, by, bx + w, by + 35], fill="black")
                bx += w + random.choice([1, 3])
            
            footer_text = f"{school_name.upper()} - OFFICIAL IDENTITY VERIFICATION"
            draw.text((45, 595), footer_text, fill=(130, 160, 200, 130), font=sub_font, anchor="lb")

            # Final Save
            img_byte_arr = io.BytesIO()
            canvas.convert("RGB").save(img_byte_arr, format='JPEG', quality=95)
            return img_byte_arr.getvalue()
        except Exception as e:
            print(f"License Card Error: {e}")
            import traceback; traceback.print_exc()
            return None

    async def generate_inspection_card(self, char_entry, base_char, full_stats):
        """Generate a premium character inspection card."""
        return await asyncio.to_thread(self._generate_inspection_card_sync, char_entry, base_char, full_stats)

    def _generate_inspection_card_sync(self, char_entry, base_char, full_stats):
        try:
            canvas_w, canvas_h = 1024, 500
            canvas = Image.new("RGB", (canvas_w, canvas_h), (15, 15, 25))
            draw = ImageDraw.Draw(canvas)

            # 1. Background
            bg_path = assets.REGISTRY.get("Team_BG")
            bg_key = f"Team_BG_composite_{canvas_w}_{canvas_h}_inspect"
            if bg_key in self.asset_cache:
                canvas.paste(self.asset_cache[bg_key], (0, 0))
            elif bg_path:
                bg = self._get_image(bg_path, (canvas_w, canvas_h))
                if bg:
                    overlay = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 180))
                    bg_composite = Image.alpha_composite(bg, overlay).convert("RGB")
                    self.asset_cache[bg_key] = bg_composite
                    canvas.paste(bg_composite, (0, 0))
            else:
                for i in range(canvas_h):
                    color = (15 + i//40, 15 + i//50, 25 + i//30)
                    draw.line([(0, i), (canvas_w, i)], fill=color)

            # Define Fonts
            title_font = self._get_font("arialbd.ttf", 48)
            subtitle_font = self._get_font("arial.ttf", 28)
            stat_font = self._get_font("cour.ttf", 24)

            rarity = base_char.get('rarity', 'Common')
            rarity_colors = {
                "Common": (180, 180, 180), 
                "Rare": (0, 180, 255), 
                "Epic": (200, 0, 255), 
                "Legendary": (255, 215, 0), 
                "Mythic": (255, 0, 50)
            }
            color = rarity_colors.get(rarity, (0, 229, 255))

            # 2. Character Portrait (Left)
            img_path = assets.get_asset_path(base_char)
            if img_path:
                cache_key = f"portrait_inspect_{img_path}"
                if cache_key in self.asset_cache:
                    portrait = self.asset_cache[cache_key]
                    box_w = 400
                    p_left = 40 + (box_w - portrait.width) // 2
                    canvas.paste(portrait, (p_left, 40), portrait)
                else:
                    portrait = self._get_image(img_path)
                    if portrait:
                        target_h = 420
                        ratio = target_h / portrait.height
                        portrait = portrait.resize((int(portrait.width * ratio), target_h), Image.LANCZOS)
                        self.asset_cache[cache_key] = portrait
                        
                        box_w = 400
                        p_left = 40 + (box_w - portrait.width) // 2
                        canvas.paste(portrait, (p_left, 40), portrait)
                
                # Frame
                draw.rectangle([40, 40, 440, 460], outline=color, width=4)
                # Bottom Name Plate
                draw.rectangle([40, 400, 440, 460], fill=(0, 0, 0, 200))
                draw.text((240, 430), base_char['name'].upper(), fill=color, font=subtitle_font, anchor="mm")

            # 3. Data panel (Right)
            start_x = 480
            
            # Header
            draw.text((start_x, 50), f"{base_char['name'].upper()}", fill="white", font=title_font)
            draw.text((start_x, 105), f"LVL {char_entry.get('level', 1)} | {rarity.upper()} | {full_stats.get('grade', 'Unrated').upper()}", fill=color, font=subtitle_font)
            
            draw.line([start_x, 145, canvas_w - 40, 145], fill=(255, 255, 255, 50), width=2)

            # Stats Grid
            y_stat = 160
            line_h = 40
            
            stats_list = [
                ("HP", full_stats.get('maxHp', 0), (255, 68, 68)),
                ("CE", full_stats.get('maxCe', 0), (0, 150, 255)),
                ("STR", full_stats.get('power', 0), (255, 100, 0)),
                ("SPD", full_stats.get('speed', 0), (0, 255, 136)),
                ("DUR", full_stats.get('stamina', 0), (255, 200, 0)),
                ("CEU", full_stats.get('ce_stat', 0), (180, 100, 255)), # CE Utilization/Stat
                ("TS", full_stats.get('technique', 0), (0, 229, 255))
            ]

            max_core = max([s[1] for s in stats_list[2:]] + [100])
            max_hpce = max([s[1] for s in stats_list[:2]] + [1000])

            for i, (lbl, val, bar_color) in enumerate(stats_list):
                draw.text((start_x, y_stat), lbl, fill="white", font=stat_font)
                draw.text((start_x + 80, y_stat), str(int(val)), fill=bar_color, font=stat_font)
                
                # Progress Bar
                bar_x = start_x + 160
                bar_w = 300
                m_val = max_hpce if i < 2 else max_core
                pct = min(1.0, val / m_val) if m_val > 0 else 0
                
                draw.rectangle([bar_x, y_stat + 5, bar_x + bar_w, y_stat + 20], fill=(30, 30, 40))
                draw.rectangle([bar_x, y_stat + 5, bar_x + (bar_w * pct), y_stat + 20], fill=bar_color)
                
                y_stat += line_h

            # Equipment / Special
            y_stat += 20
            held_item = char_entry.get('heldItem')
            item_name = "None Equipped"
            if held_item:
                from utils.data.items import ITEMS
                item_data = ITEMS.get(held_item)
                if item_data: item_name = item_data['name']
            
            draw.rounded_rectangle([start_x, y_stat, canvas_w - 40, y_stat + 60], radius=10, fill=(20, 20, 30), outline=(255, 255, 255, 50), width=1)
            draw.text((start_x + 20, y_stat + 15), f"CURSED TOOL:", fill=(150, 150, 150), font=stat_font)
            draw.text((start_x + 200, y_stat + 15), item_name, fill="white", font=stat_font)

            img_byte_arr = io.BytesIO()
            canvas.convert("RGB").save(img_byte_arr, format='JPEG', quality=90)
            return img_byte_arr.getvalue()
        except Exception as e:
            print(f"Inspection Card Error: {e}")
            import traceback; traceback.print_exc()
            return None


visual_engine = VisualEngine()
