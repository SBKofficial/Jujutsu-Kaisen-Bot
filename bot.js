require('dotenv').config();
const { Telegraf, Scenes, session, Markup } = require('telegraf');
const db = require('./database');
const ui = require('./utils/ui');
const media = require('./utils/media');
const registrationScene = require('./utils/handlers/registration');
const trainingScene = require('./utils/handlers/train');
const pvp = require('./utils/handlers/pvp');
const gachaScene = require('./utils/handlers/gacha');
const shop = require('./utils/handlers/shop');
const clans = require('./utils/handlers/clans');
const competition = require('./utils/handlers/competition');
const social = require('./utils/handlers/social');
const inventory = require('./utils/handlers/inventory');
const quests = require('./utils/handlers/quests');
const upgrades = require('./utils/handlers/upgrades');
const clanService = require('./services/clanService');
const admin = require('./utils/handlers/admin');
const team = require('./utils/handlers/team');
const utility = require('./utils/handlers/utility');
const minigame = require('./utils/handlers/minigame');
const tournament = require('./utils/handlers/tournament');
const tournamentService = require('./services/tournamentService');
const domains = require('./utils/handlers/domains');
const socialService = require('./services/socialService');
const explore = require('./utils/handlers/explore');
const challenge = require('./utils/handlers/challenge');
const matchmaking = require('./services/matchmaking');
const adminService = require('./services/adminService');
const roster = require('./utils/handlers/roster');

const isUserBusy = (ctx, user) => {
    if (ctx.session && ctx.session.activeBattle && ctx.session.activeBattle.status === 'ongoing') return true;
    if (user && user.activeExplore && (user.activeExplore.status === 'found' || user.activeExplore.status === 'battling')) return true;
    return false;
};

const bot = new Telegraf(process.env.BOT_TOKEN);

// Ensure Indexes for Speed
(async () => {
    try {
        await db.connect();
        await db.users.ensureIndex({ fieldName: 'telegramId', unique: true });
        await db.users.ensureIndex({ fieldName: 'username', unique: false });
        await db.roster.ensureIndex({ fieldName: 'userId', unique: false });
        await db.clans.ensureIndex({ fieldName: 'name', unique: true });
        console.log('🚀 Performance Indexes Optimized');
    } catch (e) {
        console.error('❌ Index Init Error:', e.message);
    }
})();

bot.catch((err, ctx) => {
    console.error(`❌ [TELEGRAF ERROR] for update ${ctx.updateType}:`, err);
});

const ADMIN_IDS = process.env.ADMIN_IDS ? process.env.ADMIN_IDS.split(',').map(id => parseInt(id.trim())) : [];
const isAdmin = (ctx, next) => {
    if (ADMIN_IDS.includes(ctx.from.id)) return next();
    return ctx.reply("❌ Unauthorized. Admin access required.");
};

const stage = new Scenes.Stage([registrationScene, trainingScene, gachaScene, clans.clanScene]);

let maintenanceCache = { value: false, lastCheck: 0 };
const getMaintenance = async () => {
    const now = Date.now();
    if (now - maintenanceCache.lastCheck < 60000) return maintenanceCache.value;
    const setting = await db.settings.findOne({ key: 'maintenance' });
    maintenanceCache = { value: !!(setting && setting.value), lastCheck: now };
    return maintenanceCache.value;
};

bot.use(session());

// AUTO-REPLY MIDDLEWARE
bot.use((ctx, next) => {
    if (ctx.message && ctx.message.message_id) {
        
        const originalReply = ctx.reply.bind(ctx);
        const originalReplyWithHTML = ctx.replyWithHTML.bind(ctx);
        const originalReplyWithPhoto = ctx.replyWithPhoto.bind(ctx);

        const injectReplyQuote = (extra = {}) => {
            return {
                ...extra,
                reply_parameters: { message_id: ctx.message.message_id }
            };
        };

        ctx.reply = (text, extra) => originalReply(text, injectReplyQuote(extra));
        ctx.replyWithHTML = (html, extra) => originalReplyWithHTML(html, injectReplyQuote(extra));
        ctx.replyWithPhoto = (photo, extra) => originalReplyWithPhoto(photo, injectReplyQuote(extra));
    }
    return next();
});

bot.use((ctx, next) => {
    if (ctx.updateType === 'message' || ctx.updateType === 'callback_query') {
        const msg = ctx.message || ctx.callbackQuery.message;
        if (msg && msg.date) {
            const now = Math.floor(Date.now() / 1000);
            if (now - msg.date > 60) {
                console.log(`🕒 [OLD UPDATE] Ignoring message/callback from ${ctx.from.id} (${now - msg.date}s old)`);
                return;
            }
        }
    }
    return next();
});

bot.on('callback_query', async (ctx, next) => {
    const now = Date.now();
    if (!ctx.session) ctx.session = {};
    const lastClick = ctx.session.lastClick || 0;

    if (now - lastClick < 200) {
        return ctx.answerCbQuery().catch(() => null);
    }

    ctx.session.lastClick = now;

    return next();
});

bot.use(stage.middleware());

const USER_CACHE = new Map();
const CACHE_TTL = 30000;

bot.use(async (ctx, next) => {
    if (!ctx.from) return next();

    const now = Date.now();
    const cached = USER_CACHE.get(ctx.from.id);
    let user;

    if (cached && (now < cached.expiresAt)) {
        user = cached.data;
    } else {
        user = await db.users.findOne({ telegramId: ctx.from.id });
        if (user) {
            USER_CACHE.set(ctx.from.id, { data: user, expiresAt: now + CACHE_TTL });
        }
    }

    if (user && user.banned) {
        if (user.banUntil === -1 || now < user.banUntil) {
            return ctx.reply(`🚫 You are currently banned.\nReason: ${user.banReason || 'Unspecified'}`);
        } else {
            await db.users.update({ telegramId: ctx.from.id }, { $set: { banned: false } });
            user.banned = false;
            USER_CACHE.delete(ctx.from.id);
        }
    }

    const isMaintenance = await getMaintenance();
    if (isMaintenance && (!user || (user.adminRole || 0) < 2)) {
        if (!((ctx.message && ctx.message.text) && ctx.message.text.startsWith('/admin'))) {
            return ctx.reply("🚧 <b>SYSTEM MAINTENANCE</b>\nThe Higher-Ups are currently reinforcing the barriers. Most functions are unavailable. Check back later!", { parse_mode: 'HTML' });
        }
    }

    ctx.state.user = user;

    if (user && !ctx.callbackQuery) {
        const lastXp = user.lastProfileXpTime || 0;
        if (now - lastXp > 60000) { 
            db.users.update({ telegramId: user.telegramId }, {
                $inc: { playerXp: 5 },
                $set: { lastProfileXpTime: now }
            }).catch(() => null);
            
            user.playerXp = (user.playerXp || 0) + 5;
            user.lastProfileXpTime = now;
            
            const nextXp = (user.playerLevel || 1) * 50;
            if (user.playerXp >= nextXp) {
                user.playerLevel = (user.playerLevel || 1) + 1;
                user.playerXp = 0;
                db.users.update({ telegramId: user.telegramId }, {
                    $set: { playerLevel: user.playerLevel, playerXp: 0 },
                    $inc: { coins: 500 }
                }).catch(() => null);
                ctx.reply(`🎊 <b>LEVEL UP!</b>\nYou have reached Player Level <b>${user.playerLevel}</b>!`).catch(() => null);
            }
        }
    }

    return next();
});

bot.use(async (ctx, next) => {
    if (ctx.chat && (ctx.chat.type === 'group' || ctx.chat.type === 'supergroup')) {
        const text = (ctx.message && ctx.message.text) || "";
        const isStart = text.startsWith('/start');

        if (isStart) {
            const botUsername = ctx.botInfo.username;
            const msg = ui.formatHeader("HEADQUARTERS REQUIRED", "GENERAL") + "\n\n" +
                "👤 <b>PRIVATE MISSION</b>\n\n" +
                "The Higher-Ups have mandated that Registration and Exploration must be conducted in private to avoid cursed energy interference.\n\n" +
                "Click below to enter your private headquarters!";

            return ctx.replyWithHTML(msg, Markup.inlineKeyboard([
                [Markup.button.url('🚪 ENTER HQ', `https://t.me/${botUsername}?start=start`)]
            ]));
        }
    }
    return next();
});

const COOLDOWNS = new Map();
bot.use((ctx, next) => {
    if (!ctx.from || !ctx.message) return next();
    const userId = ctx.from.id;
    const now = Date.now();
    const lastAction = COOLDOWNS.get(userId) || 0;

    if (now - lastAction < 500) {
        return;
    }

    COOLDOWNS.set(userId, now);
    return next();
});

bot.start(async (ctx) => {
    if (!ctx.state.user) {
        return ctx.scene.enter('registration');
    }

    const startMsg = ui.formatHeader("JUJUTSU HIGH: CURSED CLASH") + "\n\n" +
        "Greetings, sorcerer. You have returned to the Tokyo Jujutsu High headquarters.\n\n" +
        "<i>\"The world is a stage, and cursed energy is the lighting.\"</i>\n\n" +
        "Verify your status or head out to the field below.";

    return media.sendBanner(ctx, "Academy", startMsg, Markup.inlineKeyboard([
        [Markup.button.callback('👤 My Profile', 'cmd_profile_init')],
        [Markup.button.callback('📜 Roster', 'cmd_roster'), Markup.button.callback('🎒 Inventory', 'cmd_inv')],
        [Markup.button.callback('🎯 Hunt', 'cmd_explore'), Markup.button.callback('📜 Commands', 'help_main')]
    ]));
});

bot.action('cmd_explore', async (ctx) => {
    if (isUserBusy(ctx, ctx.state.user)) return ctx.answerCbQuery("⚠️ You are already in a fight! Clear it first.", { show_alert: true });
    await ctx.answerCbQuery();
    return explore.handleExplore(ctx);
});

bot.action(/exp_init_(.+)/, async (ctx) => {
    return explore.startNewExplore(ctx, null, ctx.match[1]);
});

bot.action(/exp_catch_menu_(.+)/, async (ctx) => {
    return explore.handleCaptureMenu(ctx, ctx.match[1]);
});

bot.action('exp_next', async (ctx) => {
    return explore.handleNextStep(ctx);
});

bot.action('exp_resume', async (ctx) => {
    return explore.handleResume(ctx);
});

bot.action('exp_cancel_hunt', async (ctx) => {
    return explore.handleCancelHunt(ctx);
});

bot.action('back_to_hub', async (ctx) => {
    await ctx.answerCbQuery();
    try { await ctx.scene.leave(); } catch (e) { }
    return ctx.replyWithHTML(ui.formatHeader("JUJUTSU HIGH") + "\n\nWelcome back, sorcerer. Use /profile to view your license.");
});

const showProfile = async (ctx) => {
    const user = ctx.state.user;
    if (!user) return ctx.reply("Please use /start to register first.");

    const nextPlayerXp = (user.playerLevel || 1) * 50;
    const expBar = ui.createProgressBar(user.playerXp || 0, nextPlayerXp, 10);
    const winRate = user.battles > 0 ? Math.floor((user.battlesWon || 0) / user.battles * 100) : 0;

    let body = `👤 <b>Sorcerer:</b> @${user.username}\n` +
        `🎖 <b>Title:</b> ${user.title || "Wandering Soul"}\n` +
        `🌟 <b>Level:</b> ${user.playerLevel || 1} (${expBar})\n` +
        `🏆 <b>Rank:</b> ${user.rank} | <code>${user.elo}</code> ELO\n` +
        `🏫 <b>Academy:</b> ${user.school || "<i>Unassigned (/school)</i>"}`;

    let stats = `⚔️ <b>Total Battles:</b> ${user.battles || 0}\n` +
        `🎯 <b>Win Rate:</b> ${winRate}%\n` +
        `🗺 <b>Daily Hunts:</b> ${user.dailyExploreCount || 0}/1000`;

    let economy = `💰 <b>Coins:</b> ${user.coins} | ✨ <b>Dust:</b> ${user.dust || 0}\n` +
        `🔋 <b>Stamina:</b> ${user.stamina || 0}/100`;

    const fullMsg = ui.formatHeader("SORCERER LICENSE", "PROFILE") + "\n\n" +
        ui.panel(body) + "\n\n" +
        ui.panel(stats) + "\n" +
        ui.panel(economy) + "\n\n" +
        `<i>"The power of a sorcerer is limited only by their resolve."</i>`;

    let userPhoto = null;
    try {
        const photos = await ctx.telegram.getUserProfilePhotos(ctx.from.id);
        if (photos.total_count > 0) {
            const recentPhotoSet = photos.photos[0];
            userPhoto = recentPhotoSet[recentPhotoSet.length - 1].file_id;
        }
    } catch (e) { }

    const busy = isUserBusy(ctx, user);
    const kb = Markup.inlineKeyboard([
        [
            Markup.button.callback(busy ? '⚔️ BUSY' : '👥 Team', busy ? 'none' : 'cmd_team'),
            Markup.button.callback('🎒 Bag', 'cmd_inv')
        ],
        [
            Markup.button.callback(busy ? '⚔️ BUSY' : '🏮 Hunt', busy ? 'none' : 'cmd_explore'),
            Markup.button.callback('🛡 Clans', 'clan_home')
        ],
        [
            Markup.button.callback('🎟 Gacha', 'gacha_menu'),
            Markup.button.callback('🛍 Shop', 'shop_nav_daily')
        ],
        [
            Markup.button.callback('📜 Quests', 'cmd_quests'),
            Markup.button.callback('🏅 Achievements', 'cmd_achievements')
        ]
    ]);

    if (userPhoto) {
        if (ctx.callbackQuery) {
            return ctx.telegram.editMessageMedia(
                ctx.chat.id,
                ctx.callbackQuery.message.message_id,
                null,
                { type: 'photo', media: userPhoto, caption: fullMsg, parse_mode: 'HTML' },
                kb
            ).catch(() => ctx.replyWithPhoto(userPhoto, { caption: fullMsg, parse_mode: 'HTML', ...kb }));
        }
        return ctx.replyWithPhoto(userPhoto, { caption: fullMsg, parse_mode: 'HTML', ...kb });
    }

    const leadCharId = user.teamIds[0] || "Yuji Itadori";
    return media.sendPortrait(ctx, { name: leadCharId }, fullMsg, kb);
};

bot.command('profile', showProfile);

bot.action('cmd_profile_init', async (ctx) => {
    await ctx.answerCbQuery();
    return showProfile(ctx);
});

async function showSchoolSelection(ctx) {
    const user = ctx.state.user || await db.users.findOne({ telegramId: ctx.from.id });
    if (!user) return ctx.reply("Please /start first.");

    if ((user.playerLevel || 1) < 5) {
        const lockMsg = ui.formatHeader("ACADEMY LOCKED") + "\n\n" +
            "🔒 <b>Profile Level 5 Required</b>\n\n" +
            "The Academies only accept sorcerers who have proven their dedication. Stay active and explore to level up!";
        if (ctx.callbackQuery) return ctx.answerCbQuery("Profile Level 5 required!", { show_alert: true });
        return ctx.replyWithHTML(lockMsg, Markup.inlineKeyboard([[Markup.button.callback('⬅️ BACK', 'cmd_profile_init')]]));
    }

    if (user.school) {
        const link = user.school === 'Tokyo' ? "https://t.me/+u9BMzrdh5H44OTM1" : "https://t.me/+Ethjl7sH_KIxOTFl";
        const msg = `🏯 <b>LOYALTY CONFIRMED</b>\n\nYou are a student of <b>${user.school}</b> Academy. Find your exclusive Headquarters link below:\n\n🔗 <a href="${link}">${user.school} HQ Link</a>\n\n<i>"Your comrades are waiting at the front line."</i>`;

        if (ctx.callbackQuery) return media.smartEdit(ctx, msg, Markup.inlineKeyboard([[Markup.button.url('🏘 JOIN GC', link)], [Markup.button.callback('⬅️ BACK', 'cmd_profile_init')]]));
        return ctx.replyWithHTML(msg, Markup.inlineKeyboard([[Markup.button.url('🏘 JOIN GC', link)]]));
    }

    const msg = ui.formatHeader("ACADEMY ENTRANCE", "GENERAL") + "\n\n" +
        "Select your path. This choice will determine your kin and your clans.\n\n" +
        "🚫 <b>WARNING:</b> This choice is <b>PERMANENT</b>.";

    const kb = Markup.inlineKeyboard([
        [Markup.button.callback('🏮 TOKYO JUJUTSU HIGH', 'school_set_Tokyo')],
        [Markup.button.callback('⛩️ KYOTO JUJUTSU HIGH', 'school_set_Kyoto')],
        [Markup.button.callback('🏠 RETURN', 'back_to_hub')]
    ]);

    if (ctx.callbackQuery) return media.smartEdit(ctx, msg, kb);
    return ctx.replyWithHTML(msg, kb);
}

bot.command('school', showSchoolSelection);
bot.action('cmd_school', showSchoolSelection);

bot.action(/school_set_(.+)/, async (ctx) => {
    const academy = ctx.match[1];
    const user = await db.users.findOne({ telegramId: ctx.from.id });
    if (user.school) return ctx.answerCbQuery("❌ Choice already made.");

    await db.users.update({ telegramId: ctx.from.id }, { $set: { school: academy } });
    await ctx.answerCbQuery(`🏮 Welcome to ${academy} High!`, { show_alert: true });

    const link = academy === 'Tokyo' ? "https://t.me/+u9BMzrdh5H44OTM1" : "https://t.me/+Ethjl7sH_KIxOTFl";
    await ctx.replyWithHTML(`🎉 <b>CONGRATULATIONS SORCERER!</b>\n\nYou are now an official student of <b>${academy} Jujutsu High</b>. Join your Academy Headquarters using the link below:\n\n👇 <b>JOIN HERE:</b>\n${link}`, Markup.inlineKeyboard([[Markup.button.url('🚀 JOIN ACADEMY GC', link)]]));

    return showProfile(ctx);
});

matchmaking.onMatchFound = (p1, p2, mode) => pvp.startPvPBattle(p1, p2, mode, bot);
matchmaking.onMatchTimeout = (userId) => {
    bot.telegram.sendMessage(userId, "⚠️ <b>Matchmaking Timeout</b>\nNo opponent was found within 60 seconds. Please try again later.", { parse_mode: 'HTML' });
};

bot.command(['hunt', 'explore'], async (ctx) => {
    if (!ctx.state.user) return ctx.reply("Please /start first.");
    if (isUserBusy(ctx, ctx.state.user)) return ctx.reply("⚠️ <b>BUSY:</b> You are already in a fight! Clear the current encounter first.", { parse_mode: 'HTML' });

    const args = ctx.message.text.split(' ');
    if (args[1] === 'stats' || args[1] === 'status') return explore.showExploreStats(ctx);
    return explore.handleExplore(ctx);
});

bot.command('open', async (ctx) => {
    return explore.showAutoMenu(ctx);
});

bot.command('close', (ctx) => utility.handleClose(ctx));
bot.action('cmd_close', (ctx) => utility.handleClose(ctx));

bot.action('menu_auto_grind', (ctx) => explore.showAutoMenu(ctx));
bot.action(/exp_auto_(.+)/, (ctx) => explore.executeAutoGrind(ctx, ctx.match[1]));

bot.command('surrender', async (ctx) => {
    return ctx.reply("Use the 🏳️ Surrender button inside the battle UI to concede.");
});

bot.command('rematch', async (ctx) => {
    const now = Date.now();
    const lastRematch = ctx.session.lastRematch || 0;
    if (now - lastRematch < 5000) return ctx.reply("⏳ Rematch request on cooldown (5s).");
    ctx.session.lastRematch = now;

    return ctx.reply("♻️ Rematch request sent. Waiting 15s for response...");
});

bot.command('train', async (ctx) => {
    console.log(`[BOT] Received /train command from ${ctx.from.id}`);
    if (!ctx.state.user) return ctx.reply("Please /start first.");
    return ctx.scene.enter('training');
});

bot.command('shop', async (ctx) => {
    console.log(`[BOT] Received /shop command from ${ctx.from.id}`);
    if (!ctx.state.user) return ctx.reply("Please /start first.");
    return shop.showShop(ctx);
});

bot.action('cmd_explore', (ctx) => {
    if (isUserBusy(ctx, ctx.state.user)) return ctx.answerCbQuery("⚠️ You are busy!", { show_alert: true });
    return explore.handleExplore(ctx);
});
bot.action('cmd_inv', (ctx) => inventory.showInventory(ctx));
bot.action('gacha_menu', (ctx) => {
    ctx.answerCbQuery();
    return ctx.scene.enter('gacha_summon');
});
bot.action('shop_nav_daily', (ctx) => {
    ctx.answerCbQuery();
    return shop.showShop(ctx, 'daily');
});

bot.command('clan', async (ctx) => {
    console.log(`[BOT] Received /clan command from ${ctx.from.id}`);
    const user = ctx.state.user || await db.users.findOne({ telegramId: ctx.from.id });
    if (!user) return ctx.reply("Please /start first.");

    if ((user.playerLevel || 1) < 10) {
        return ctx.replyWithHTML(ui.formatHeader("SYNDICATE LOCKED") + "\n\n" +
            "🔒 <b>Profile Level 10 Required</b>\n\n" +
            "Clans are only for established sorcerers. Continue your training!");
    }

    return ctx.scene.enter('clan_scene');
});

bot.command('create_clan', async (ctx) => {
    const args = ctx.message.text.split(' ');
    if (args.length < 3) return ctx.reply("Usage: /create_clan NAME TAG");
    const name = args.slice(1, -1).join(' ');
    const tag = args[args.length - 1];

    const result = await clanService.createClan(ctx.from.id, name, tag);
    return ctx.reply(result.msg);
});

bot.command('test', isAdmin, async (ctx) => {
    await db.users.update({ telegramId: ctx.from.id }, {
        $set: {
            coins: 10000,
            dust: 100,
            stamina: 100,
            gachaTickets: 25,
            inventory: [
                { id: 'energy_drink', qty: 5 },
                { id: 'cursed_charm', qty: 5 },
                { id: 'exp_ticket', qty: 1 }
            ]
        }
    });
    return ctx.reply("🧪 ADMIN MODE: 10k Coins, Full Stamina, and Test Consumables added to your bag!");
});

bot.command('gacha', async (ctx) => {
    if (!ctx.state.user) return ctx.reply("Please /start first.");
    return ctx.scene.enter('gacha_summon');
});

// Removed /upload command (Admin/Dev only tool)

bot.command('quests', (ctx) => quests.handleQuests(ctx));
bot.command(['upgrade', 'upgrades'], upgrades.showUpgradeMenu);
bot.command(['inventory', 'inv'], inventory.showInventory);
bot.command('roster', (ctx) => roster.showRoster(ctx));
bot.command('view', (ctx) => roster.viewCommand(ctx));

bot.command('leaderboard', competition.showLeaderboard);
bot.command('rank', competition.showRank);
bot.command('tournament', tournament.handleTournament);

bot.command('daily', utility.handleDaily);
bot.command('streak', utility.showStreak);
bot.command('blackflash', minigame.startBlackFlash);
bot.command('domains', domains.showDomainList);
bot.command('help', (ctx) => utility.showHelp(ctx));

const handleItemTransfer = async (ctx) => {
    if (!ctx.state.user) return ctx.reply("Please /start first.");
    
    if (!ctx.message.reply_to_message) {
        return ctx.reply(
            "❌ <b>USAGE:</b>\n\n" +
            "Reply to a sorcerer with:\n" +
            "<code>/send [item] [amount]</code>\n\n" +
            "<b>Supported Items:</b>\n" +
            "• <code>coins</code> - 💰\n" +
            "• <code>dust</code> - ✨\n" +
            "• <code>shards</code> - ✨\n" +
            "• <code>potions</code> - 🧪\n\n" +
            "<b>Examples:</b>\n" +
            "<code>/send coins 500</code>\n" +
            "<code>/send dust 100</code>\n" +
            "<code>/send shards 50</code>\n" +
            "<code>/send potions 5</code>",
            { parse_mode: 'HTML' }
        );
    }

    const args = ctx.message.text.split(' ');
    if (args.length < 3) {
        return ctx.reply("❌ <b>Usage:</b> <code>/send [item_name] [amount]</code>", { parse_mode: 'HTML' });
    }

    const itemName = args[1].toLowerCase();
    const amount = parseInt(args[2]);

    if (isNaN(amount) || amount <= 0) {
        return ctx.reply("❌ Amount must be a positive number!");
    }

    const targetId = ctx.message.reply_to_message.from.id;
    const senderId = ctx.from.id;

    if (targetId === senderId) {
        return ctx.reply("❌ You cannot transfer items to yourself!");
    }

    // Get both users from DB
    const sender = ctx.state.user;
    const receiver = await db.users.findOne({ telegramId: targetId });

    if (!receiver) {
        return ctx.reply("❌ Target user not found or not registered!");
    }

    // Define item metadata
    const itemConfig = {
        coins: {
            dbField: 'coins',
            icon: '💰',
            label: 'Coins',
            type: 'currency'
        },
        dust: {
            dbField: 'dust',
            icon: '✨',
            label: 'Cosmic Dust',
            type: 'currency'
        },
        shards: {
            dbField: 'shardsCurrency',
            icon: '✨',
            label: 'Shards',
            type: 'currency'
        },
        shard: {
            dbField: 'shardsCurrency',
            icon: '✨',
            label: 'Shards',
            type: 'currency'
        },
        potions: {
            dbField: null,
            icon: '🧪',
            label: 'Potions',
            type: 'inventory'
        },
        potion: {
            dbField: null,
            icon: '🧪',
            label: 'Potions',
            type: 'inventory'
        }
    };

    // Validate item
    if (!itemConfig[itemName]) {
        const validItems = Object.keys(itemConfig)
            .filter((k, i, arr) => arr.indexOf(k) === i)
            .map(k => `• ${itemConfig[k].icon} ${itemConfig[k].label}`)
            .join('\n');
        
        return ctx.reply(
            `❌ Invalid item! Valid items are:\n\n${validItems}`,
            { parse_mode: 'HTML' }
        );
    }

    const config = itemConfig[itemName];

    try {
        // Handle currency transfers
        if (config.type === 'currency') {
            const senderBalance = sender[config.dbField] || 0;

            if (senderBalance < amount) {
                return ctx.reply(
                    `❌ Insufficient ${config.label}!\n` +
                    `You have: ${config.icon} ${senderBalance}`,
                    { parse_mode: 'HTML' }
                );
            }

            // Perform transfer
            await db.users.update(
                { telegramId: senderId },
                { $inc: { [config.dbField]: -amount } }
            );
            await db.users.update(
                { telegramId: targetId },
                { $inc: { [config.dbField]: amount } }
            );

            // Clear cache
            USER_CACHE.delete(senderId);
            USER_CACHE.delete(targetId);

            return ctx.replyWithHTML(
                `✅ <b>TRANSFER COMPLETE!</b>\n\n` +
                `${config.icon} <b>${config.label}</b> Transferred\n\n` +
                `<b>From:</b> @${ctx.from.username || senderId}\n` +
                `<b>To:</b> @${ctx.message.reply_to_message.from.username || targetId}\n` +
                `<b>Amount:</b> ${config.icon} ${amount}`,
                { parse_mode: 'HTML' }
            );
        }

        // Handle inventory (potions) transfers
        else if (config.type === 'inventory') {
            const senderInventory = sender.inventory || [];
            const receiverInventory = receiver.inventory || [];

            // Find potion in sender's inventory
            const potionIndex = senderInventory.findIndex(item => 
                item.id === 'energy_drink' || item.id === 'cursed_charm' || item.id === 'exp_ticket'
            );

            if (potionIndex === -1) {
                return ctx.reply("❌ You don't have any potions!");
            }

            const potion = senderInventory[potionIndex];

            if (potion.qty < amount) {
                return ctx.reply(
                    `❌ Insufficient ${config.label}!\n` +
                    `You have: ${config.icon} ${potion.qty}`,
                    { parse_mode: 'HTML' }
                );
            }

            // Deduct from sender
            if (potion.qty === amount) {
                senderInventory.splice(potionIndex, 1);
            } else {
                potion.qty -= amount;
            }

            // Add to receiver
            const receiverPotionIndex = receiverInventory.findIndex(item => item.id === potion.id);
            if (receiverPotionIndex === -1) {
                receiverInventory.push({ id: potion.id, qty: amount });
            } else {
                receiverInventory[receiverPotionIndex].qty += amount;
            }

            // Update both users
            await db.users.update(
                { telegramId: senderId },
                { $set: { inventory: senderInventory } }
            );
            await db.users.update(
                { telegramId: targetId },
                { $set: { inventory: receiverInventory } }
            );

            // Clear cache
            USER_CACHE.delete(senderId);
            USER_CACHE.delete(targetId);

            return ctx.replyWithHTML(
                `✅ <b>TRANSFER COMPLETE!</b>\n\n` +
                `${config.icon} <b>${potion.id.replace('_', ' ').toUpperCase()}</b> Transferred\n\n` +
                `<b>From:</b> @${ctx.from.username || senderId}\n` +
                `<b>To:</b> @${ctx.message.reply_to_message.from.username || targetId}\n` +
                `<b>Amount:</b> ${config.icon} x${amount}`,
                { parse_mode: 'HTML' }
            );
        }

    } catch (error) {
        console.error('Transfer error:', error);
        return ctx.reply("❌ Transfer failed! Please try again.");
    }
};

bot.command('addfriend', social.addFriend);
bot.command('friends', social.showFriends);
// --- UNIFIED ITEM SHARING COMMAND ---
bot.command('send', handleItemTransfer);
bot.command('team', (ctx) => {
    if (!ctx.state.user) return ctx.reply("Please /start first.");
    if (isUserBusy(ctx, ctx.state.user)) return ctx.reply("⚠️ <b>RESTRICTED:</b> You cannot manage your team while in a battle!", { parse_mode: 'HTML' });
    return team.showTeamMenu(ctx);
});

// Basic callback handlers for UI placeholders
// --- TEAM ACTIONS ---
bot.action('cmd_team', async (ctx) => {
    if (isUserBusy(ctx, ctx.state.user)) return ctx.answerCbQuery("⚠️ You cannot manage your team while in a battle!", { show_alert: true });
    await ctx.answerCbQuery();
    return team.showTeamMenu(ctx);
});
bot.action(/team_page_(\d+)/, (ctx) => team.showTeamMenu(ctx, parseInt(ctx.match[1])));
bot.action('team_swap_menu', (ctx) => team.showSwapMenu(ctx));
bot.action(/team_swap_slot_(\d+)/, (ctx) => team.showSwapBench(ctx, parseInt(ctx.match[1])));
bot.action(/team_swpage_(\d+)_(\d+)/, (ctx) => team.showSwapBench(ctx, parseInt(ctx.match[1]), parseInt(ctx.match[2])));
bot.action(/team_swap_confirm_(\d+)_(.+)/, (ctx) => team.confirmSwap(ctx, parseInt(ctx.match[1]), ctx.match[2]));
bot.action(/team_swap_exec_(\d+)_(.+)/, (ctx) => team.executeSwap(ctx, parseInt(ctx.match[1]), ctx.match[2]));
bot.action('team_reorder_menu', (ctx) => team.showReorderMenu(ctx));
bot.action(/team_move_(\d+)_(up|down)/, (ctx) => team.executeMove(ctx, parseInt(ctx.match[1]), ctx.match[2]));

bot.command('challenge', (ctx) => challenge.sendChallenge(ctx));
bot.command('duel', (ctx) => challenge.sendDuel(ctx));
bot.action(/chal_accept_(\d+)(_duel)?/, (ctx) => challenge.handleAccept(ctx, ctx.match[1], ctx.match[2] ? 'duel' : 'challenge'));
bot.action(/chal_decline_(\d+)(_duel)?/, (ctx) => challenge.handleDecline(ctx, ctx.match[1], ctx.match[2] ? 'duel' : 'challenge'));
bot.action(/chal_cancel_(.+)/, (ctx) => challenge.handleCancel(ctx, ctx.match[1]));

bot.command('admin', isAdmin, (ctx) => admin.handleAdminCommand(ctx));
bot.action(/^adm_nav_(.+)/, isAdmin, async (ctx) => {
    const action = ctx.match[1];
    await ctx.answerCbQuery();

    switch (action) {
        case 'stats': return admin.showDashboard(ctx);
        case 'battles': return admin.listBattles(ctx);
        case 'season':
            const res = await adminService.executeSeasonReset();
            return ctx.reply(res.msg);
        case 'broadcast':
            return ctx.reply("📣 <b>Broadcast Guide:</b>\nUse: <code>/admin broadcast [YOUR MESSAGE]</code>\nThis will send the message to all registered users.", { parse_mode: 'HTML' });
        case 'help':
            return ctx.reply("📚 <b>Admin Command Reference:</b>\n\n" +
                "👤 <b>User:</b> <code>/admin user [id]</code>\n" +
                "💰 <b>Coins:</b> <code>/admin add_coins [id] [qty]</code>\n" +
                "🚫 <b>Ban:</b> <code>/admin ban [id] [days] [reason]</code>\n" +
                "✨ <b>Gacha:</b> <code>/admin gacha_pity_reset [id]</code>\n" +
                "🛡 <b>Clan:</b> <code>/admin clan_delete [name]</code>", { parse_mode: 'HTML' });
    }
});


bot.action(/^adm_short_(.+)/, isAdmin, async (ctx) => {
    const short = ctx.match[1];
    await ctx.answerCbQuery();
    ctx.state.commandText = `/admin ${short}_msg`;
    return admin.handleAdminCommand(ctx);
});

bot.action(/^adm_(warn|ban|reset|user)_(.+)/, isAdmin, async (ctx) => {
    const [_, action, targetId] = ctx.match;
    await ctx.answerCbQuery();
    ctx.state.commandText = `/admin ${action} ${targetId}`;
    return admin.handleAdminCommand(ctx);
});

bot.command('broadcast_confirm', async (ctx) => {
    const adminRole = await adminService.getUserRole(ctx.from.id);
    if (adminRole < 2) return;
    const msg = ctx.session.pendingBroadcast;
    if (!msg) return ctx.reply("❌ No pending broadcast found.");

    const users = await db.users.find({});
    ctx.reply(`🚀 Broadcasting to ${users.length} users...`);
    let count = 0;
    for (const u of users) {
        try {
            await ctx.telegram.sendMessage(u.telegramId, `📢 <b>ANNOUNCEMENT</b>\n\n${msg}`, { parse_mode: 'HTML' });
            count++;
        } catch (e) { }
    }
    ctx.session.pendingBroadcast = null;
    return ctx.reply(`✅ Broadcast complete. Delivered to ${count} sorcerers.`);
});

bot.action('tourney_reg', async (ctx) => {
    // Note: handleRegistration already calls answerCbQuery
    return tournament.handleRegistration(ctx);
});

bot.action('bf_ready', (ctx) => minigame.handleBFReady(ctx));
bot.action(/bf_tap_(.+)/, (ctx) => minigame.handleBFTap(ctx, ctx.match[1]));

bot.action(/bf_zone_(\d+)_(\d+)/, (ctx) => {
    ctx.answerCbQuery();
    return minigame.handleBFChoice(ctx, ctx.match[1], ctx.match[2]);
});

bot.action('cmd_domains', (ctx) => {
    ctx.answerCbQuery();
    return domains.showDomainList(ctx);
});

bot.action(/view_domain_(.+)/, (ctx) => {
    ctx.answerCbQuery();
    return domains.renderDomainDetail(ctx, ctx.match[1]);
});

bot.action(/spec_(.+)/, async (ctx) => {
    const res = await socialService.addSpectator(ctx.match[1], ctx.from.id);
    await ctx.answerCbQuery(res.success ? "Successfully joined spectator channel!" : res.msg);
    if (res.success) return ctx.reply("You are now spectating...");
});

bot.action(/exp_f:(\d+):(.+)/, async (ctx) => {
    return explore.initiateWildBattle(ctx, ctx.match[2], false, ctx.match[1]);
});
bot.action(/exp_c:(\d+):(.+)/, async (ctx) => {
    return explore.initiateWildBattle(ctx, ctx.match[2], true, ctx.match[1]);
});
bot.action(/tool_cap_shackle_(.+)/, async (ctx) => {
    return explore.executeCapture(ctx, ctx.match[1], 'grade_1_shackle');
});

bot.action(/tool_cap_essence_(.+)/, async (ctx) => {
    return explore.executeCapture(ctx, ctx.match[1], 'domain_essence');
});

bot.action(/tool_cap_tag_(.+)/, async (ctx) => {
    return explore.executeCapture(ctx, ctx.match[1], 'cursed_seal_tag');
});

bot.action(/pvp_enter_(.+)/, async (ctx) => {
    return pvp.handleEnter(ctx, ctx.match[1]);
});

bot.action(/pvp_atk_(.+)_(.+)/, async (ctx) => {
    return pvp.handleMove(ctx, ctx.match[1], { type: 'attack', moveIdx: parseInt(ctx.match[2]) });
});

bot.action(/pvp_grd_(.+)/, async (ctx) => {
    return pvp.handleMove(ctx, ctx.match[1], { type: 'guard' });
});

bot.action(/pvp_swi_(.+)/, async (ctx) => {
    const battleId = ctx.match[1];
    const battle = await db.battles.findOne({ _id: battleId });
    const isP1 = ctx.from.id === battle.p1.id;
    const player = isP1 ? battle.p1 : battle.p2;

    const kb = player.team.map((c, i) => {
        if (i === player.activeIdx || c.hp <= 0) return null;
        return [Markup.button.callback(`🔄 ${c.name}`, `pvp_swiexec_${battleId}_${i}`)];
    }).filter(b => b !== null);

    kb.push([Markup.button.callback('⬅️ Back', `pvp_enter_${battleId}`)]);
    return ctx.editMessageReplyMarkup(Markup.inlineKeyboard(kb).reply_markup);
});

bot.action(/pvp_swiexec_(.+)_(.+)/, async (ctx) => {
    return pvp.handleMove(ctx, ctx.match[1], { type: 'switch', nextIdx: parseInt(ctx.match[2]) });
});

bot.action(/pvp_surr_(.+)/, async (ctx) => {
    // Basic surrender logic
    const battleId = ctx.match[1];
    const battle = await db.battles.findOne({ _id: battleId });
    if (!battle || battle.status === 'finished') return;

    const isP1 = ctx.from.id === battle.p1.id;
    battle.status = 'finished';
    battle.winner = isP1 ? battle.p2.username : battle.p1.username;
    battle.winnerId = isP1 ? battle.p2.id : battle.p1.id;
    battle.surrendered = true;
    battle.log.push(`🏳️ ${ctx.from.username} surrendered. No rewards granted.`);

    // Skip awardPvPRewards for surrenders
    await db.battles.update({ _id: battleId }, {
        $set: {
            status: battle.status,
            winner: battle.winner,
            winnerId: battle.winnerId,
            log: battle.log,
            surrendered: true
        }
    });
    return pvp.renderBattle(ctx, battle);
});

bot.action(/conf_cap_(.+)/, async (ctx) => {
    await ctx.answerCbQuery("Attempting capture...");
    return explore.executeCapture(ctx, ctx.match[1]);
});


// cmd_team action handled in the team section


bot.action('clan_home', async (ctx) => {
    await ctx.answerCbQuery();
    return clans.showHome(ctx);
});

bot.action(/upg_page_(\d+)/, (ctx) => upgrades.showUpgradeMenu(ctx, parseInt(ctx.match[1])));
bot.action(/upg_sel_char_(.+)/, (ctx) => upgrades.renderUpgradeOptions(ctx, ctx.match[1]));
bot.action(/upg_confirm_(.+)_(.+)/, (ctx) => upgrades.confirmUpgrade(ctx, ctx.match[1], ctx.match[2]));
bot.action(/upg_lvl_exec_(.+)/, (ctx) => upgrades.executeLevelUp(ctx, ctx.match[1]));
bot.action(/upg_grade_exec_(.+)/, (ctx) => upgrades.executeGradePromotion(ctx, ctx.match[1]));
bot.action('cmd_upgrades', (ctx) => upgrades.showUpgradeMenu(ctx));

bot.action(/upg_exec_(.+)_(.+)/, async (ctx) => {
    await ctx.answerCbQuery();
    return upgrades.handleUpgradeExecution(ctx, ctx.match[1], ctx.match[2]);
});
bot.action('cmd_inv', async (ctx) => {
    await ctx.answerCbQuery();
    return inventory.showInventory(ctx);
});

bot.action(/shop_nav_(.+)/, (ctx) => shop.showShop(ctx, ctx.match[1]));
bot.action(/shop_confirm_(.+)/, (ctx) => shop.showConfirm(ctx, ctx.match[1]));
bot.action(/shop_exec_(.+)/, (ctx) => shop.executePurchase(ctx, ctx.match[1]));
bot.action(/view_inv_(.+)/, async (ctx) => {
    await ctx.answerCbQuery();
    return inventory.viewItemDetails(ctx, ctx.match[1]);
});
bot.action(/use_inv_(.+)/, async (ctx) => {
    return inventory.useItem(ctx, ctx.match[1]);
});

bot.action('cmd_achievements', async (ctx) => {
    return utility.showAchievements(ctx);
});
bot.action('menu_titles', async (ctx) => {
    return utility.showTitlesMenu(ctx);
});
bot.action(/equip_title_(.+)/, async (ctx) => {
    return utility.equipTitle(ctx, ctx.match[1]);
});

// --- QUEST ACTIONS ---
bot.action('cmd_quests', (ctx) => quests.handleQuests(ctx));
bot.action(/q_claim_(\d+)/, (ctx) => quests.handleClaim(ctx, ctx.match[1]));
bot.action('q_claim_all', (ctx) => quests.handleClaimAll(ctx));

bot.action(/help_(.+)/, async (ctx) => {
    // Utility.showHelp handles answerCbQuery
    return utility.showHelp(ctx, ctx.match[1]);
});

bot.action('exp_let_go', (ctx) => explore.handleLetGo(ctx));
// Command and action listeners are consolidated above.


// --- ADVANCED TEAM ACTIONS ---
bot.action('team_nav_swap', (ctx) => {
    ctx.answerCbQuery();
    return team.showSwapMenu(ctx);
});
bot.action('team_nav_reorder', (ctx) => {
    ctx.answerCbQuery();
    return team.showReorderMenu(ctx);
});
bot.action(/team_swap_select_(.+)/, (ctx) => {
    ctx.answerCbQuery();
    return team.handleSwapSelect(ctx, ctx.match[1]);
});
bot.action(/team_swap_exec_(\d+)_(.+)/, (ctx) => {
    return team.executeSwap(ctx, parseInt(ctx.match[1]), ctx.match[2]);
});
bot.action(/team_reorder_(\d+)_(\d+)/, (ctx) => {
    return team.executeReorder(ctx, parseInt(ctx.match[1]), parseInt(ctx.match[2]));
});

bot.action(/roster_page_(\d+)/, (ctx) => {
    ctx.answerCbQuery();
    return roster.showRoster(ctx, parseInt(ctx.match[1]));
});
bot.action('roster_nav_details', async (ctx) => {
    ctx.answerCbQuery();
    return roster.handleDetailsNav(ctx);
});
bot.action(/roster_view_(.+)/, async (ctx) => {
    ctx.answerCbQuery();
    return roster.showCharacterDetails(ctx, ctx.match[1]);
});
bot.action('roster_nav_sell_menu', async (ctx) => {
    return roster.handleSellMenu(ctx);
});
bot.action('roster_nav_release', async (ctx) => {
    return roster.handleReleaseMenu(ctx, false);
});
bot.action('roster_nav_release_commons', async (ctx) => {
    return roster.handleReleaseMenu(ctx, true);
});
bot.action(/roster_nav_release_page_(\d+)/, (ctx) => {
    return roster.handleReleaseMenu(ctx, false, parseInt(ctx.match[1]));
});
bot.action(/roster_nav_release_commons_page_(\d+)/, (ctx) => {
    return roster.handleReleaseMenu(ctx, true, parseInt(ctx.match[1]));
});
bot.action('roster_mass_release_commons', async (ctx) => {
    return roster.handleMassReleaseCommons(ctx);
});
bot.action('roster_mass_release_exec', async (ctx) => {
    return roster.executeMassRelease(ctx);
});
bot.action('roster_mass_release_all', async (ctx) => {
    return roster.handleMassReleaseAll(ctx);
});
bot.action('roster_mass_release_all_exec', async (ctx) => {
    return roster.executeMassReleaseAll(ctx);
});
bot.action(/roster_release_toggle_(.+)/, async (ctx) => {
    return roster.toggleSelectForRelease(ctx, ctx.match[1]);
});
bot.action('roster_mass_release_selected', async (ctx) => {
    return roster.handleMassReleaseSelected(ctx);
});
bot.action('roster_release_selected_exec', async (ctx) => {
    return roster.executeSelectedRelease(ctx);
});
bot.action(/roster_release_conf_(.+)/, (ctx) => {
    return roster.handleReleaseConfirm(ctx, ctx.match[1]);
});
bot.action(/roster_release_exec_(.+)/, (ctx) => {
    return roster.executeRelease(ctx, ctx.match[1]);
});
bot.action(/roster_upg_lvl_(.+)/, (ctx) => {
    return roster.executeLevelUp(ctx, ctx.match[1]);
});
bot.action(/roster_upg_star_(.+)/, (ctx) => {
    return roster.executeAwaken(ctx, ctx.match[1]);
});
bot.action(/rost_dep_(.+)_(.+)/, async (ctx) => {
    return roster.executeDeployment(ctx, ctx.match[1], ctx.match[2]);
});

bot.action('cmd_roster', (ctx) => {
    ctx.answerCbQuery();
    return roster.showRoster(ctx);
});

bot.action(/^view_archive_(\d+)/, (ctx) => {
    return roster.showGlobalArchive(ctx, parseInt(ctx.match[1]));
});
bot.action(/^cmd_view_char_(.+)/, (ctx) => {
    return roster.viewCommand(ctx, ctx.match[1], true);
});

bot.command('achievements', (ctx) => utility.showAchievements(ctx));
// Removed placeholder /trade command

(async () => {
    try {
        await db.connect();
        console.log('✅ JUJUTSU HIGH BOT: STARTING...');
        bot.launch({ dropPendingUpdates: true });
        console.log('✅ JUJUTSU HIGH BOT: CURSED CLASH IS ONLINE');
    } catch (err) {
        console.error('❌ FATAL: Failed to connect to MongoDB:', err.message);
        process.exit(1);
    }

    try {
        // Auto-update command menu in Telegram - THE COMPLETE LIST
        await bot.telegram.setMyCommands([
            { command: 'start', description: 'Begin your sorcerer journey' },
            { command: 'profile', description: 'View your sorcerer license' },
            { command: 'hunt', description: 'Find & capture wild spirits' },
            { command: 'open', description: 'Initiate Automated Grinding (Blitz)' },
            { command: 'close', description: 'Tidy up chat (Close Menu)' },
            { command: 'roster', description: 'Manage squad & all owned sorcerers' },
            { command: 'view', description: 'Inspect full character cards' },
            { command: 'train', description: 'AI practice (Easy/Normal/Hard)' },
            { command: 'inv', description: 'Open your toolbag' },
            { command: 'gacha', description: 'Summon new souls' },
            { command: 'shop', description: 'Buy charms & drinks' },
            { command: 'daily', description: 'Claim daily login reward' },
            { command: 'streak', description: 'Check your current login streak' },
            { command: 'achievements', description: 'View progress & equip titles' },
            { command: 'school', description: 'Choose your Jujutsu Academy (Tokyo/Kyoto)' },
            { command: 'quests', description: 'View active missions' },
            { command: 'upgrades', description: 'Boost character stats' },
            { command: 'domains', description: 'Manage domain expansions' },
            { command: 'clan', description: 'Open Syndicate Hub' },
            { command: 'challenge', description: 'Challenge a sorcerer to a DM battle' },
            { command: 'duel', description: 'Request a live GC duel with preparation' },
            { command: 'create_clan', description: 'Start your own Clan (1k Coins)' },
            { command: 'friends', description: 'Manage ally list' },
            { command: 'send', description: 'Share items with sorcerers (coins/dust/shards/potions)' },
            { command: 'tournament', description: 'Enter the Zenin Tournament' },
            { command: 'leaderboard', description: 'View Special Grade rankings' },
            { command: 'rank', description: 'Check your global ELO position' },
            { command: 'blackflash', description: 'Play timing mini-game' },
            { command: 'help', description: 'Open the comprehensive guide' },
            { command: 'admin', description: 'Administrative oversight' }
        ]);
        console.log('📜 ALL COMMANDS Scheduled with Telegram.');
    } catch (e) {
        console.error('⚠️ [WARNING] Failed to set bot commands:', e.message);
    }

    // Inactivity Watchers (Every 30s) — PvP battles + Hunt sessions
    setInterval(() => {
        pvp.checkBattleTimeouts(bot);
        explore.checkExploreTimeouts(bot);
    }, 30000);
})();

// Enable graceful stop
process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
