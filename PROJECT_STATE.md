# PROJECT_STATE.md — SELF RIVAL

> Handoff document for a new Claude conversation. Snapshot date: **2026-11-15** (v2: diamond economy; sections 0b and 15 describe what changed — older sections 1-14 are partly superseded).
> Built by static inspection of the repository (zip `Myself--main`, later modified in the previous conversation). **Nothing was executed against Telegram** and **no Git history exists in the zip** (no `.git`), so "recent changes" below come from the previous conversation, not from commits.
> Legend: ✅ verified in code · ⚠️ implemented but untested in production · ❓ unknown / needs investigation.
> No secrets are recorded here (names of environment variables only).

---

---

## 0b. v2 changes (conversation 3) — READ FIRST
Everything below is ✅ compiled and unit-tested offline (`tests/test_economy.py`, `tests/test_rival_core.py`, stubbed Pyrogram) but ⚠️ **never run against Telegram**.

| Area | What it is now |
|---|---|
| New modules | `rival_core.py` (manager-bot UI + economy handlers + loops, installed via `rival_core.install(globals())` in bot.py), `rival_cards.py` (Pillow cards), `self_tools/economy.py` (SQLite ledger), `self_tools/rival_user.py` (`.موجودی`, `.برترین‌ها` from the self) |
| Reply keyboard | rows 1 / 2 / 1 / 3: ⚙️ مدیریت سلف · 👤 حساب کاربری + ❓ سلف چیست · 🛒 خرید الماس · 📨 پشتیبانی و راهنما + 💎 الماس رایگان + ☑️ مینی اپ. Old button texts still map (legacy keyboards). Old `rival_*` handlers removed from bot.py. |
| Economy | 1 diamond = 10 toman (500 💎 = 5,000 ت). 5,000 💎 = 30 days. One balance, ledger rows for every change (`UNIQUE(uid,reason,ref)` = idempotent). DB: `economy.db` next to `DATA_FILE` (override `ECONOMY_DB`). Included in the admin backup (sent as a 2nd document); restore by sending `economy*.db` to the bot as ROOT_ADMIN. |
| Subscription | trial days (default 5, `/settrial`) at first login; existing users got 7 grace days once (`migrated_v1`). Expiry loop stops the self (no log_out); renewal restarts it. Admins exempt. Hooks: `finalize_login` → `rival_core.on_login`; `_start_bot_instance_now_impl` and `start_bot_instance` check `rival_core.sub_ok`. |
| Shop | presets + custom amount ≥500 → invoice (30 min) → user sends receipt photo → forwarded to all admins with ✅/❌ → credit. Payment text set with `/setcard` or admin panel. Receipt `file_unique_id` is UNIQUE. |
| Referral | `/start ref_<uid>`; reward only when the **global forced join** (admin menu «عضویت اجباری سراسری») is ON and satisfied: +200 inviter, +100 invitee; +500 inviter after invitee's self stayed active 3 days (phone hash dedupe, 20/day cap). Callback `chk_manager_join_*` (previously unhandled) is now handled in rival_core. |
| Games | only in the chat registered with `/setofficial` (run inside the group; bot must be admin so it sees plain text). `بازی 500` / `/bet 500`: 2 players, CSPRNG winner, stake escrowed, 10% tax on profit, min 10 / max 100,000. `دوز 1000` / `/dooz 1000`: 3×3 inline board, creator = ❌ starts, 120 s move timeout = forfeit, draw = refund. Open games expire after 10 min (refund). |
| Commands | `موجودی` / `/balance` and `برترین‌ها` / `/top` in bot PV and groups (balance card photo; top-10 + your rank). Admin: `/addgems id n`, `/adddays id n`, `/settrial n`, `/setcard text`, `/setofficial`, `/unsetofficial`, `/economy`; keyboard buttons «💎 اقتصاد» / «🔙 منوی کاربری». |
| Login | code entry is an inline keypad (`kp:*` callbacks, 3 per row, ⌫ حذف کد, ✖️ انصراف, ✅ تأیید) → calls the existing `text_handler` with a `_MenuMsg`; typing the code still works as fallback. |
| Removed | `nsfw_controller` + help section, `اسپم`/`فلود` commands + help lines. Enemy/friend/crush lists untouched. |
| Style | new text language `‹ ʀɪᴠᴀʟ ›` headers, `◈ key ⟢ value` rows, no box/line art; help sections, panel (emoji toggles 🟢/⚫, tabs), notices rewritten. Command words themselves unchanged. The marker check for own messages now also accepts `ʀɪᴠᴀʟ`. |
| Cards | `self_tools/assets/`: `card_player.jpg` (Name/ID/Username/Rank, @selfrival_bot baked in), `card_balance.jpg`, banners for bet/dooz/referral. Persian shaping via arabic_reshaper+bidi (fallback raqm). Optional fonts in `miniapp/dashboard/fonts/` (Vazirmatn-Bold is picked up by the cards). |
| Mini app | glass theme (`#rival-theme`), Lalezar + Vazirmatn (`/fonts/*` route; drop the TTFs in `miniapp/dashboard/fonts/`, else Google Fonts/system fallback), tab «الماس» → `gemsView` (balance, days, rank, renew 30 days, referral, top-10) backed by `POST /miniapp/eco`. Embedded help text restyled. |

## 15. Open items after v2
1. Live test everything (checklist in `RIVAL_UPDATE_FA.md`). Biggest unknowns: styled `style` buttons on reply keyboards, `text_handler` reuse from the keypad (`_MenuMsg` must satisfy `finalize_login`), group visibility of plain-text commands (privacy mode), inline-sent `.پنل` photo + caption edits.
2. Add the font files; confirm mini app renders (JS syntax was checked with `node --check`, not executed in a browser).
3. Decide payment methods beyond manual card-to-card.
4. Gambling with purchased diamonds was chosen by the owner (single balance); legal/ban risk acknowledged.
5. Unchanged old risks from §11 (custom encryption, hot-deploy path, unpinned deps).

## 0. How to use this file in a new conversation

1. Give Claude this file plus the repo (or the files you are changing).
2. Tell Claude to follow section 12 (Development Rules) and start from section 13 (Next Task).
3. Source code in `bot.py` has unusual spacing (`foo (x ,y )`, `. attr`), because of how it was produced. It compiles fine, but **exact-string edits must copy the original spacing**. Line numbers below were correct on the snapshot date and will drift after edits — search by function name.

---

## 1. Identity and design

| Item | Value |
|---|---|
| Project name | **SELF RIVAL** (display brand string in code: `RIVALSELF`) |
| Type | Telegram **userbot (self-bot) hosting platform**, not just a bot |
| Manager bot username | `@selfrival_bot` (stated by the owner; the code reads it at runtime into `BOT_USERNAME`, ✅ `_legacy_main`) |
| Support contact | `@sadzr` → `https://t.me/sadzr` (`RIVAL_SUPPORT_URL` in `bot.py`) |
| Language of UI | Persian (Farsi), RTL |
| Tagline used on banner | `𝐒𝐄𝐋𝐅 𝐑𝐈𝐕𝐀𝐋 \| 𝘽𝙪𝙞𝙡𝙩 𝘽𝙚𝙮𝙤𝙣𝙙 𝙇𝙞𝙢𝙞𝙩𝙨` |

### Implemented design (✅ in files)
- **Theme:** dark / near-black with deep electric-blue glow and silver (crown, "SR" monogram). Modern, "technological" look.
- **Welcome banner:** `self_tools/rival_banner.jpg` (1672×941, JPEG converted from the owner's PNG). Wolf with crown, SR logo, "SELF RIVAL / ربات سلف ریوال", four feature tiles.
- **Profile card template:** `self_tools/card_template.jpg` (1672×941): `SELF RIVAL` logo at left, crowned circular ring (photo slot) in the center, `ID:` pill at right, `@` username bar at the bottom.
- **Text header style used in self tools:** `✦ 𝗥𝗜𝗩𝗔𝗟𝗦𝗘𝗟𝗙 ✦  ·  {title}` + `━━━━━━━━━━━━━━━━━━` (`self_tools/common.py: HEAD`).
- **Brand fonts in strings:** Unicode math-bold (`𝗥𝗜𝗩𝗔𝗟𝗦𝗘𝗟𝗙`) and small-caps (`ʀɪᴠᴀʟsᴇʟꜰ`). Plain `RIVALSELF` where the original was plain.
- **Colored Telegram buttons:** uses Bot API button `style` values `success` (green), `primary` (blue), `danger` (red).

### Not matching the identity (✅ observed, not yet unified)
- `miniapp/dashboard/index.html` (the page actually served) uses Telegram theme variables with dark-blue defaults (`--bg #0e1621`, accent `#4ea1f0`, green/red status colors) — close to the theme but **not** a dedicated SELF RIVAL design system.
- `miniapp/index.html` uses a neon cyan/violet/pink palette (`--a1 #38e1ff`, `--a2 #8b6cff`, `--a3 #ff5fa2`) and is **not served** by `miniapp_api.py` (it serves `miniapp/dashboard/index.html`). Probably a legacy GitHub-Pages version ❓.

### Planned design (❓ no evidence in repo)
No design roadmap or design-system document exists. Treat any new visuals as "follow banner + card template".

---

## 2. Quick facts

| Topic | Fact |
|---|---|
| Language | Python 3 (exact version ❓ not pinned; no `runtime.txt`) |
| Telegram library | **Pyrogram** (`requirements.txt` is **unpinned**; installed version ❓). Code monkey-patches Pyrogram internals (`patch_pyrogram_filter_performance`, `patch_peer_id_validation`, `patch_pyrogram_runtime_noise`, `ResilientClient`), so it is version-sensitive. `tgcrypto` for speed. |
| Entry point | `python bot.py` (`Procfile`: `worker: python bot.py`) |
| Hosting | Railway (service named `worker`; trial plan at the time) |
| Main file | `bot.py` ≈ 17.7k lines; plus `miniapp_api.py`, `downloader.py`, `self_tools/` (≈40 plugin modules) |
| Storage | JSON file `bot_data.json` (+ `.bak`), Pyrogram session files in `sessions/`, admin logs `.voldyself_logs/*.jsonl` |
| Git history | ❓ none available |
| README | none |
| Tests | `test_ttt.py`, `tests/*.py` — require Pyrogram; **not executed** in this snapshot ❓ |

---

## 3. Repository map

```
bot.py                      main app: manager bot + userbot runtime + DB + handlers (17.7k lines)
miniapp_api.py              aiohttp server for the Telegram Mini App (API + static dashboard + health + card images)
downloader.py               yt-dlp based link downloader (used by link_downloader_controller)
Procfile                    worker: python bot.py
requirements.txt            unpinned deps
.gitignore                  __pycache__, *.pyc, sessions/, *.session, bot_data.json
selfloop_autodelete.patch   leftover diff adding /self_del help lines (✅ already reflected? ❓ not verified)
test_ttt.py, tests/         tests for tic-tac-toe, selfloop and self_tools filters (need pyrogram)
miniapp/dashboard/index.html   served dashboard (6.3k lines, vanilla JS/CSS)
miniapp/index.html             alternate page, not served by miniapp_api.py ❓ legacy
self_tools/__init__.py      plugin loader: MODULES list + register_all()
self_tools/common.py        Env wrapper over bot globals, HEAD, md_to_html, chunk helpers
self_tools/help_sections.py extra help sections (ai, aiplus, tools, tools2, farm, ttt, imgmeta)
self_tools/profilecard.py   profile-card generator + /card command (added in previous conversation)
self_tools/card_template.jpg, rival_banner.jpg, DejaVuSans-Bold.ttf   assets (font bundled because Railway lacks fonts)
self_tools/*.py             one module per tool (see §7.2)
PROJECT_STATE.md            this file
```

---

## 4. Runtime architecture

### 4.1 Two layers
1. **Manager bot** — `manager_bot = Client("manager_bot", bot_token=BOT_TOKEN, ...)` (`bot.py` ~line 2197). Talks to everyone who opens `@selfrival_bot`: onboarding/login, buttons, admin menu, inline panel/help, callbacks, mini app menu button.
2. **Self instances (userbots)** — one `ResilientClient` per activated user, created in `_start_bot_instance_now_impl` with `session_string`, `workdir="sessions"`, `in_memory=False`, `no_updates=False`. Stored in the global `ACTIVE_BOTS[uid] = (client, [tasks])`.

The userbot has **no UI of its own**: the user types commands in any chat from their own account; for rich panels it asks the manager bot via **inline mode** (`get_inline_bot_results(BOT_USERNAME, "panel")` → `send_inline_bot_result`), so the manager bot must have **Inline Mode enabled in BotFather** ✅.

### 4.2 Startup flow (✅ `main` → `_legacy_main`)
`main()` → if sharding disabled → `_legacy_main()`:
1. `startup_disk_safety_cleanup()`
2. `manager_bot.start()`, read `BOT_USERNAME`
3. `_start_miniapp_server()` (aiohttp, see §9) and `notify_admins(...)`
4. background tasks: `memory_cleaner`, `data_manager.auto_save_loop`, `hourly_database_backup_task`, `database_external_reload_watcher`, `cpu_stats_sampler`
5. load all sessions from DB and start each with `start_bot_instance(...)` under a semaphore (`STARTUP_CONCURRENCY`), then `_pemoji_premium_autostart()` and `idle()`.

### 4.3 Sharding (opt-in, ❓ not studied in depth)
`_sharding_enabled_for(cpu_limit)` is true only if `VOLDYSELF_SHARD=1`, CPU limit > 1 (from DB `server_limits`), `VOLDYSELF_NO_SHARD!=1`, and the process is not itself a worker. Then `_master_sharded_main` supervises worker processes (`_ShardSupervisor`, `_worker_main`, `_shard_assigns_to_me`, IPC via `_shard_init_ipc`, `_commit_and_broadcast_shards`). Default is single-process legacy mode. The mini app server start in sharded mode: ❓.

### 4.4 Instance startup details (✅ `start_bot_instance`, `_start_bot_instance_now_impl`)
- Per-user `asyncio.Lock` (`SESSION_START_LOCKS`), `_activation_wait_left(uid)` delays fresh logins (`_fresh_login_start_delay`) — anti-ban measure ❓ rationale inferred.
- Skips start if banned, invalid session, global switch off, or RAM cap hit.
- `client.start()` with 30 s timeout; on success starts 7 background tasks: `update_profile_clock`, `anti_login_task`, `status_action_task`, `tabchi_controller_loop`, `tabchi_repeater_loop`, `private_channel_save_jobs_loop`, `avatar_loop`.
- Failure handling: `AuthKeyUnregistered/UserDeactivated/SessionRevoked/AuthKeyInvalid` → `data_manager.delete_session(phone)`; corrupted string → `mark_invalid_session` + delete; `FloodWait` → retry up to 3 times with sleep; always cleans the client in `finally`.

### 4.5 Reconnection / recovery
- `ResilientClient` (subclass of Pyrogram `Client`) overrides `invoke`, `fetch_peers`, `handle_updates`, `get_messages` and schedules cleanup of invalid sessions (`_schedule_invalid_session_cleanup`). Internals ❓ (not read line-by-line).
- `memory_cleaner`, `_prune_client_runtime`, `_drop_idle_caches` trim memory.
- Sessions auto-start again on process restart because they are read from DB.

---

## 5. Authentication and sessions

### 5.1 Login flow (✅ code verified)
1. User opens the bot → `/start` → banner + coloured reply keyboard (§6.1).
2. User taps **✅ فعالسازی** → `rival_activate_btn` → calls `start_handler` with a fake text `"فعال‌سازی سلف"` via `_MenuMsg`.
3. `start_handler` (`bot.py` ~16389) checks ban/global status/slot limit (`data_manager.self_slot_available`), existing session, else asks the user to share their phone with a contact button.
4. `contact_handler` (~16566): rate-limit (`LOGIN_RATE_LIMIT/WINDOW/MAX`), creates a **temporary in-memory** `Client("login_<uid>", in_memory=True, no_updates=True, **fingerprint)`, `connect()`, `send_code(phone)`; stores `LOGIN_STATES[uid] = {"step":"code","phone","client","hash","started_at"}`.
5. `text_handler` (~16655; only for chats present in `LOGIN_STATES`): extracts digits from the code message (`re.sub(r"\D+","",text)`) and calls `sign_in(phone, hash, code)`. On `SessionPasswordNeeded` it handles 2FA: tries a saved encrypted password (`settings.twofa_password`), else asks the user, `check_password`, then stores the password encrypted (`_db_encrypt`).
6. `finalize_login` (~16873): `export_session_string()`, `get_me()`, ban/slot checks, then `data_manager.update_user_data(...)` / `save_session`, sets `activation_ready_at`, `activation_id`, `activation_notice_chat`, and schedules `start_bot_instance`.
7. `_notify_activation_result` informs the user when the self is live.

`_get_client_fingerprint(uid)` generates per-user device parameters (`**login_fp`, `**client_fp`) ❓ details not read.

### 5.2 Session storage
- Source of truth: `bot_data.json` → `users[uid].session_string` and `sessions[phone]` (encrypted with `_db_encrypt`, see §5.3). `DataManager.get_decrypted_session_string`, `get_all_sessions`.
- Pyrogram also writes session files under `sessions/` (`workdir="sessions"`, in `.gitignore`). On Railway these are lost on redeploy unless a Volume is mounted; the session string in the DB lets the client recreate them.
- Invalid sessions are tracked in `data["invalid_sessions"]`.

### 5.3 Encryption (✅ `_db_derive_key`, `_db_encrypt`, `_db_decrypt`)
- Key = `sha256(DB_ENCRYPTION_KEY)` if set, otherwise `sha256("API_HASH|BOT_TOKEN|darkself_db_key")`.
- **Custom** scheme: zlib compress → XOR with an HMAC-SHA256 counter keystream (random salt+nonce) → truncated HMAC tag; prefix `_DB_ENC_PREFIX`. Not a standard AEAD (ChaCha20-Poly1305/AES-GCM) — see §11 risks.
- **Do not change `DB_ENCRYPTION_KEY` after users have logged in**, otherwise stored sessions cannot be decrypted. Do not rename the literal `darkself_db_key`.
- File permissions are tightened by `_secure_file_permissions`. Admin tools: "رمزگشایی سشن‌ها" (decrypt sessions), `session_export_controller` (the owner's own `.سشن` command exports their session string).

### 5.4 Deactivation (new, ⚠️ untested)
`rival_deactivate_btn` → inline confirm (`rv:dyes` / `rv:dno`) → `rival_callbacks` → `_deactivate_self(uid)`: strips clock chars from the profile name, cancels tasks, `client.log_out()` (terminates the session on Telegram), `stop_user_bot`, `data_manager.delete_session(phone)`, clears `session_string`, `_load_target_reply_texts(uid, restore_defaults=True)`, `_commit_and_broadcast_shards`.
An older equivalent exists: `reset_session_handler` (button text "ورود مجدد (ریست)", no longer on the keyboard).

---

## 6. Manager bot (user-facing)

### 6.1 `/start` experience (✅ implemented in previous conversation, ⚠️ untested live)
`send_main_menu(chat_id)` sends the banner photo with the welcome HTML caption (`RIVAL_WELCOME_HTML`, ~831 UTF-16 units < 1024) and a **reply keyboard** with placeholder `انتخاب کن - RIVAL`:

| Button | Style | Handler | Behavior |
|---|---|---|---|
| `✅ فعالسازی` (becomes `⛔ غیرفعال‌سازی` when `uid in ACTIVE_BOTS`) | success / danger | `rival_activate_btn` / `rival_deactivate_btn` | login flow / confirm-then-logout |
| `👤 حساب کاربری` | primary | `rival_account_btn` | sends the profile card (§8) with name, id, username, masked phone, self status |
| `📨 راهنما و پشتیبانی` | danger | `rival_help_btn` | inline buttons: `📖 راهنما` (`switch_inline_query_current_chat="help"` → opens the full help center via inline mode) and `💬 پشتیبانی` (URL `https://t.me/sadzr`) |

Helpers: `_main_kb_json(uid, styled)`, `_main_kb_pyro(uid)`, `_send_with_main_kb`, `_reply_main`, `_md_to_html`. Falls back from styled → unstyled → Pyrogram keyboard if Telegram rejects `style` ❓ (whether Telegram accepts `style` on reply-keyboard buttons is unverified).
All rival_* handlers use `group=-13` and `stop_propagation()`.
Admins: after the banner, `start_handler` additionally sends the admin menu (`get_admin_menu_keyboard`), which **replaces** the coloured keyboard (admins do not see the RIVAL buttons) — design decision ❓ pending.
`send_main_menu` also sets the chat menu button to the mini app when a public URL exists (`_set_menu_button`).

### 6.2 Other manager-bot handlers (✅ list from decorators)
`/start` + "فعال‌سازی سلف" (`start_handler`), `/panel|/help|/menu` and Persian words (`menu_cmd_handler`), `contact_handler`, `text_handler`, `reset_session_handler`, `main_menu_callback` (old `mm:*` inline menu, now unused by `/start`), `callback_panel_handler` (all inline panel callbacks), `inline_panel_handler` (inline queries), `/miniapp` (admin only, `miniapp_status_handler`), guard handlers (`manager_banned_user_guard`, `manager_global_fjoin_check`, `manager_root_ban_reply_handler`).

### 6.3 Admin menu (✅ `get_admin_menu_keyboard`)
ROOT_ADMIN buttons: فعال‌سازی سلف, تنظیم لیمیت, مدیریت ادمین‌ها, مدیریت کاربران, پیام همگانی, وضعیت سرور, وضعیت سراسری سلف‌ها, عضویت اجباری سراسری, بکاپ دیتابیس, بازیابی دیتابیس, رمزگشایی سشن‌ها, حذف کامل دیتابیس, لاگ, سایر. Other admins: فعال‌سازی سلف (+ لاگ).
Also: `admin_source_handler` ("سورس"), `admin_log_menu_handler` ("لاگ"), `self_limit_menu_handler` ("تنظیم لیمیت").
**Hot deploy (✅ `admin_deploy_handler`, ROOT_ADMIN only):** sending a `.py` document with a caption in `DEPLOY_WORDS` (e.g. "آپدیت") compiles it with `subprocess.run([python,"-m","py_compile",...])`, backs up and **overwrites the live `bot.py`**, then launches a guard shell script (`setsid bash`) that references `/root/run_bot.sh` — a VPS-style path that most likely **does not exist on Railway** ❓ (deploy-by-upload is probably not reliable there; Railway redeploys come from GitHub).

---

## 7. Userbot commands and event handling

### 7.1 Command detection (important)
- `me_cmd(pattern, flags)` (`bot.py` ~2576) builds a filter for **outgoing** messages (`filters.me`) whose text matches the pattern; `get_cmd(uid, text)` (~2618) strips the optional dot prefix and returns the bare command.
- **Dot prefix:** per-user flag `settings.dot_commands` → `DOT_COMMANDS_STATUS[uid]`. In dot mode commands must be written as `.پنل`. **The default was changed to `True`** in the previous conversation (new users get dot mode; existing users keep their stored value; toggle exists in the panel as "نقطه‌ای"). Places changed: default user dict (~2046), `load` of states (~3023), several `.get(uid, True)` call sites.
- `self_tools` commands accept **both `/` and `.`** prefixes independent of that flag.
- Handler groups (negative = early): `-1000` activation guard, `-100` chat tracker, `-90…-3` anti-delete/anti-edit/seen/lock/forced-join/self toggle/modifiers, `0` command controllers, `1…4` watchers (first comment, target reply, secretary, tag alert, tabchi link watcher), `5–6` premium-emoji watchers. `self_tools` register at group `-6` via `_Registrar`, which silences them when the self is off (`SELF_ACTIVE_STATUS`), banned, or still in activation wait.

### 7.2 Commands defined in `bot.py` (✅ registered in `_start_bot_instance_now_impl`; prefix rule above; "details ❓" = behavior not read in depth)

| Command (Persian / English) | Function | Purpose |
|---|---|---|
| `راهنما` | `help_cmd_handler` | opens help center through inline mode |
| `پنل` / `panel` | `panel_command_controller` | sends the control panel via inline bot result (**now a photo card**, §8) |
| `تنظیم منشی` | `set_secretary_message_controller` | set secretary auto-reply text |
| `رمز` / `رمزگشایی` | `crypto_text_controller` | custom text encrypt/decrypt (`dark_encrypt_text`) |
| `ارسال`, `پاک شونده` | `timed_tools_controller` | timed / self-destruct sends |
| `کامنت`, `تنظیم متن کامنت اول`… | `first_comment_controller` | first-comment on channel posts |
| `اکشن` | `action_panel_controller` | action panel |
| `تنظیم/لیست/حذف فیلتر کلمات` | `filter_words_controller` | word filter |
| `بنر پیوی کل`, `وضعیت تبچی`, `تنظیم بنر/تایمر`, `ارسال خودکار`, `تبچی هوشمند`… | `tabchi_commands_controller` | "tabchi" bulk banner/advert sending |
| `حذف تمام گروه/کانال/ربات ها`, `توقف پاکسازی` | `bulk_cleanup_controller` | account cleanup |
| `عضو` | `membership_join_controller` | join prompts |
| `ترک`, `ترک گروه/پیوی`, `حذف پیام های امروز/هفته` | `clean_exit_controller` | clean exit / delete own messages |
| `سیو کانال خصوصی` | `private_channel_save_controller` | copy protected channel posts to Saved |
| ایموجی commands | `pemoji_controller` (+ watchers) | premium emoji mapping (uses `PREMIUM_BOT_TOKEN`) |
| `لوگو <text>` / `logo` | `logo_controller` | procedural logo images (`_lg_*` Pillow functions) |
| `آهنگ/موزیک <q>` / `song` | `music_controller` | music search/delivery |
| `هوش` / `ai` / `گپت` | `ai_controller` | AI chat (g4f-based) |
| `سورس` / `source` | `source_controller` | source/info |
| `نرخ`, `ارز`, `قیمت دلار/طلا/سکه…` | `rate_controller` | FX/gold prices |
| `آواتار` / `avatar` | `avatar_controller` + `avatar_loop` | dynamic profile avatar |
| `تنظیم/حذف/لیست/پاکسازی لیست` + `دشمن/دوست/کراش` | `list_management_controller` | target lists |
| `ماتریکس`, `لاو` | `extra_fun_controller` | fun |
| `تاس`, `دارت`, `فوتبال`, `بولینگ`, `بسکتبال` | `game_cheat_controller` | dice-game helpers |
| `fun`, `فان`, `heart`, `قلب` | `fun_controller` | fun |
| `آیدی` / `id` | `id_command_handler` | show ids |
| `سشن` | `session_export_controller` | export the owner's session string (sensitive) |
| `لیست ریاکت`, `ریاکت پاکسازی` | auto-reaction handlers | reactions |
| reply-based: `دانلود, بن, پین, ذخیره, تکرار, بلاک, سکوت, ریاکشن …` | `reply_based_controller` | actions on replied message |
| `سرچ <q>` | `search_topic_controller` | web snippet search |
| `عکس <q>` | `image_search_controller` | image search |
| `تگ`, `tagall`, `آن پین`, `اسپم`, `فلود`, `حذف…` | `tools_controller` | group tools |
| `کپی روشن/خاموش` | `copy_profile_controller` | copy a profile |
| `بکاپ` / `backup` | `backup_controller` | chat backup to HTML |
| `ساعت/تاریخ/time/date` | `datetime_info_controller` | Jalali/Gregorian/Hijri info |
| `ping` | `ping_controller` | latency |
| download/video/mp3 `+ URL` | `link_downloader_controller` | yt-dlp downloads (`downloader.py`) |
| `ترجمه` | `translate_controller` | translate reply |
| `گیف` / `gif` | `gif_converter_controller` | gif conversion |
| `استیکر` / `sticker` | `sticker_creator_controller` | quote stickers (needs `ffmpeg`) |
| `تنظیم نام اکانت…`, `حذف عکس پروفایل…` | `manage_account_controller` | profile management |
| `ساخت/حذف گروه/کانال` | `create_delete_controller` | create/delete chats |
| `تنظیم/حذف/لیست عضویت اجباری` | `forced_join_cmds_controller` | forced join |
| `boob`, `butt`, `lewd`, `hentai` | `nsfw_controller` | adult image APIs (oboobs/obutts/purrbot) — flagged to owner, left in place |

Toggles (clock, bio clock/date, anti-delete/edit, secretary, auto-seen, pv-lock, typing/playing/record/upload/gif status, tabchi modes, fonts, etc.) live in the panel and in `settings` (see §10.2); `_PANEL_FLAGS` lists the in-memory dicts.
Status per command: all ✅ present; production correctness ❓ (not tested here).

### 7.3 Commands from `self_tools/` (✅ `MODULES` list; prefix `/` or `.`)
calc, uuid, count, age, qr, tr, date, bmi, hash, json, b64e, b64d, stats, remind (+stop), passgen, pray, tz, tzlist, short, unit(s), imgmeta, ip, weather, crypto, price, wiki, ai (+ `aiplus`), image, voice, ocr, removebg (needs `REMOVEBG_API_KEY`), userinfo, groupinfo, channelinfo, checkuser, font, ascii, sum, fix, prompt, fwd, self_on / self_off / self_status / self_del (module `selfloop`, multi-slot looped sending with optional auto-delete), purge (`purge` and Persian `حذف N پیام`), ttt (tic-tac-toe vs self with learning: `ttt_controller`, `ttt_core`, `ttt_learn`), **`card` / `pcard` / `کارت`** (`profilecard`, new).
Each module exposes `register(reg)` and optional `resume(client, g)`; one failing module does not stop the others (`register_all`).
Help text for these is in `self_tools/help_sections.py` and in `HELP_SECTIONS` in `bot.py` (keys include toolsmath, toolshash, toolstime, toolsinfo, toolsmedia, toolsai, downloader, selfloop, meowgame, main, wallet, backup, datetime, panel, group, reply, react, profile, create, lists, wordfilter, secretary, fjoin, privatechan, media, cheat, fun, security, crypto, timed, firstcomment, nsfw, cleanexit, tabchi, pemoji, logo, rate, ai, music, avatar).

### 7.4 Passive features (event listeners, ✅ registered)
anti-delete / anti-edit / TTL ("view once") media capture (`anti_delete_raw_update_handler`, `ttl_media_raw_hint_handler`, `auto_save_view_once_handler`), timeline cache, auto-seen, PV media lock, forced-join check, secretary auto-reply, first-comment watcher, tag alert, target-reply (enemy/friend/crush lists), "god mode", outgoing text modifiers (bold/spoiler/code/underline/gradual-edit/translate/fonts via `outgoing_message_modifier`), self-destruct media, auto reaction, wallet (`wallet_controller`), chat tracker.

---

## 8. Profile cards and generated images (new work)

### 8.1 `self_tools/profilecard.py` (✅ rendered and visually checked with synthetic input)
- `build_card(photo_bytes, user_id, username, name) -> BytesIO(JPEG)` using Pillow on `card_template.jpg`.
- Geometry constants (measured from the template): `CIRCLE_CENTER=(836,408)`, `CIRCLE_RADIUS=206`, `ID_BOX=(1148,436,1578,509)`, `USER_BOX=(745,674,1125,766)`. Font `DejaVuSans-Bold.ttf` auto-fit. No photo → first letter on a dark-blue disc. No name slot exists on the template, so `name` is only used for the placeholder letter.
- `/card`, `/card @user|id`, or reply + `/card` (prefixes `/` or `.`; aliases `pcard`, `کارت`): `handler()` resolves the user, downloads the photo (`_get_photo`), renders in a thread, `send_photo`, then deletes the command message.

### 8.2 Account button card
`rival_account_btn` → `_card_for_user(uid, [manager_bot, active_self_client])` (`bot.py`): `get_users`, downloads profile photo, `build_card`; 120 s per-user cache `_CARD_BYTES`. The manager bot can only fetch photos of users who interacted with it and allow it; otherwise the placeholder is used.

### 8.3 `.پنل` as a photo card (⚠️ untested)
- `inline_panel_handler` answers the inline query with an **article** result by default (`answerInlineQuery` through `bot_api_request`). If `_card_url_for_panel(uid)` returns a URL, it answers with a **photo** result instead (`photo_url`/`thumbnail_url`, caption = panel text, Markdown, same inline keyboard `generate_panel_markup_json`).
- `_card_url_for_panel` requires: `PANEL_CARD` not off, mini app server running (`_MINIAPP_STATE["running"]`), a public origin (`_card_origin()`), and a successful `GET /healthz` self-check (cached 120 s). It stores the JPEG in `CARD_CACHE[token]` (15 min TTL) and returns `https://<origin>/cardimg/<token>.jpg`, served by `miniapp_api.cardimg`.
- Because the panel message becomes a **photo**, `bot_api_request` now wraps `_bot_api_request_raw` and converts a failed `editMessageText` ("no text in the message to edit") into `editMessageCaption` (strips `disable_web_page_preview`/`entities`, caption ≤ 1024). Pyrogram fallbacks `edit_inline_text` were **not** adapted ❓.
- If the public URL is missing or unreachable the panel stays text-only (previous behavior).

---

## 9. Mini app (✅ server code, ✅ log line seen by owner)

- `miniapp_api.start(globals())` runs an **aiohttp** server inside the bot process (port `MINIAPP_PORT` or `PORT`, default 8080, bound to `0.0.0.0`).
- Routes: `/` and `/app` → `miniapp/dashboard/index.html`; `/healthz`; `/cardimg/{tok}`; `/miniapp/state`, `/miniapp/set`, `/miniapp/admin`, `/miniapp/clientlog`.
- **Auth:** every API call validates Telegram `initData` (HMAC with `BOT_TOKEN` or `PREMIUM_BOT_TOKEN`) in `_auth`. CORS origin from `MINIAPP_ORIGIN` (default `*`).
- Public URL: `_miniapp_public_url()` = `MINIAPP_URL` if https and not `github.io`, else `https://$RAILWAY_PUBLIC_DOMAIN/`. The chat **menu button** "⚡ پنل سلف" is set through `setChatMenuButton` (`_set_menu_button`) at startup and on `/start`.
- Admin command `/miniapp` shows server state/port/URL/menu button.
- Owner confirmed the log line `[miniapp] server listening on 0.0.0.0:8080 | public url: https://…up.railway.app/` ✅. Opening the mini app from Telegram, and the explicit "🚀 مینی‌اپ" button on the old menu (`_menu_buttons`) are not part of the new `/start` keyboard.
- Keyboard-button Web Apps do not provide signed `initData`, hence the app is opened from the **menu button** (or an inline `web_app` button, not yet added; offered to the owner).

---

## 10. Data, config, infrastructure

### 10.1 Environment variables (names only)

| Variable | Used for |
|---|---|
| `API_ID`, `API_HASH` | Telegram app credentials (required; process exits if missing) |
| `BOT_TOKEN` | manager bot token (BotFather) |
| `ROOT_ADMIN` | numeric Telegram id of the owner |
| `DB_ENCRYPTION_KEY` | key for session/2FA encryption (set it; never change later) |
| `DATA_FILE` | path of the JSON DB (added in previous conversation; default `bot_data.json`; intended `/data/bot_data.json` with a Railway Volume) |
| `MINIAPP_ENABLED`, `MINIAPP_PORT`, `PORT`, `MINIAPP_URL`, `MINIAPP_PUBLIC_URL`, `MINIAPP_ORIGIN`, `RAILWAY_PUBLIC_DOMAIN` | mini app server and URLs |
| `PANEL_CARD` | `0/false/off` disables the photo panel card |
| `PREMIUM_BOT_TOKEN` | second bot for premium-emoji features |
| `CHANNEL_URL`, `SUPPORT_URL` | optional links in the old menu |
| `REMOVEBG_API_KEY` | `removebg` tool |
| `YTDLP_COOKIES`, `YTDLP_COOKIES_B64`, `DL_ALLOW_PRIVATE` | downloader |
| `VOLDYSELF_SHARD`, `VOLDYSELF_NO_SHARD`, `VOLDYSELF_SHARD_COUNT`, `VOLDYSELF_SHARD_ID`, `VOLDYSELF_SHARDING_ACTIVE`, `VOLDYSELF_STARTUP_CONCURRENCY`, `VOLDYSELF_STARTUP_BATCH_PAUSE` | sharding/startup tuning (legacy internal names, intentionally not renamed) |

### 10.2 Database (✅ `DataManager`, `bot.py` ~1690)
`bot_data.json` top-level keys (`get_default_data`): `users`, `sessions`, `admins` (starts with `ROOT_ADMIN`), `banned_users`, `invalid_sessions`, `global_bot_status`, `global_fjoin_active`, `global_fjoin_chats`, `server_limits {cpu, ram_gb}`, `self_limit`, `admin_reply_targets`.
`users[<uid>]`: `user_id`, `phone`, `session_string` (encrypted), `first_name`, `username`, activation fields (`last_login_ts`, `activation_ready_at`, `activation_id`, `activation_notice_chat`, `activation_notice_pending`), and a large `settings` dict (font, clock, bold, secretary, auto_seen, pv_lock, anti_login, anti_report, typing/playing/record_voice/upload_photo/watch_gif, copy_mode, translate, spoiler/code/underline, tag_alert, enemy/friend/crash lists, auto_save, sec_text, anti_delete/edit, pv_* media locks, bio_clock/bio_date/bio_font, forced_join_active, **dot_commands (default now True)**, filter_words_active, gradual, self_destruct(+delay), first_comment(+text), avatar(+style/text), panel_color, help_color, self_active, `twofa_password` (encrypted) …).
Key methods: `load_data/save_data/force_save_sync/auto_save_loop` (atomic tmp-file write, `.bak` backup, reload watcher), `update_user_data`, `get_user_data`, `save_session`, `delete_session`, `delete_user_full`, `get_all_sessions`, `get_decrypted_session_string`, admin/ban helpers, `self_limit_status`, `self_slot_available`, `mark_invalid_session`. In-memory mirrors: `ACTIVE_BOTS`, `LOGIN_STATES`, `DOT_COMMANDS_STATUS`, `CLOCK_STATUS`, `SELF_ACTIVE_STATUS`, … (`_load_user_states`, `load_all_states`).
Hourly encrypted DB backup is sent to the admin (`hourly_database_backup_task`, `send_database_backup_to_admin`); restore via admin button (`restore_database_from_document` → `restart_process_after_restore` uses `os.execv`).

### 10.3 Dependencies (`requirements.txt`, all unpinned)
pyrogram, tgcrypto, aiohttp, Pillow, yt-dlp, jdatetime, arabic-reshaper, python-bidi, uvloop (non-Windows), psutil, requests, qrcode[pil], pyfiglet, gtts, pytesseract, deep-translator, tzdata. Notes: `pytesseract` needs the **system** package `tesseract` (not installed by requirements ❓ on Railway); `ffmpeg` is needed for sticker video frames (`subprocess.run([ffmpeg,...])`) and yt-dlp merging ❓ availability on Railway unknown; the `ai` features use g4f/web endpoints (`self_tools/ai*.py`, `bot.py` `_ai_*`) — library not in `requirements.txt` ❓ verify.
External services used (✅ domains seen): Telegram Bot API, Wikipedia, wttr.in, tgju / CoinGecko-style price APIs, Groq/other LLM endpoints, SoundCloud, yt-dlp sites, oboobs/obutts/purrbot (adult images).

### 10.4 Deployment (Railway)
- Service name `worker` (from `Procfile`), build by Railway's default builder (❓ Nixpacks/Railpack).
- Owner-set variables: `API_ID`, `API_HASH`, `BOT_TOKEN`, `ROOT_ADMIN`, `DB_ENCRYPTION_KEY`, `MINIAPP_ENABLED`, `MINIAPP_PORT=8080`, possibly `DATA_FILE=/data/bot_data.json`.
- **Volume:** the owner could not find the Volume UI on mobile. Whether `/data` exists is ❓. If `DATA_FILE` points to `/data/...` without a Volume the app may crash (this happened once: "Crashed", then fixed — exact fix ❓, probably variable change).
- Public domain generated, mini app server confirmed listening on 8080.
- Owner works **from a phone** (GitHub web UI + Railway mobile site), uploads files through the GitHub web UI.

### 10.5 Logging, errors, security mechanisms (✅)
- Logging via `logging` with noise filter (`VoldyselfNoiseFilter`), admin JSONL log handler (`VoldyselfAdminLogHandler`, dir `.voldyself_logs`, redaction `_redact_admin_log`), viewable from the admin "لاگ" menu.
- Global asyncio exception handler (`_voldyself_loop_exception_handler`), `friendly_telegram_error`, FloodWait handling, report-guard (`_report_guard_*`) limiting risky sends.
- Access control: `is_banned`, global bot switch, forced join (per user and global), self-slot limit, login rate-limit, `root_*` ban-reply controllers.
- Risks / notes: see §11.

---

## 11. Current status

### 11.1 Completely implemented (✅ in code; production-tested by owner ❓ unless stated)
Manager bot + login/2FA flow; session DB with encryption; userbot lifecycle; ~100 userbot commands and passive features; inline panel and help center; admin menu; DB backup/restore; mini app server; sharding framework; `self_tools` plugins.
Owner confirmed: bot online on Railway after setup; "کار کرد" (it worked); mini app server listening.

### 11.2 Implemented in the previous conversation, **not yet verified live** ⚠️
1. New `/start` (banner + welcome text + coloured reply keyboard) and the three buttons.
2. Deactivation flow with `log_out()`.
3. `.پنل` as a photo card via `/cardimg` (+ caption-edit fallback).
4. `/card` command and account-button card.
5. Dot commands default on.
6. Brand rename VOLDYSELF/DARKSELF → RIVALSELF in display strings (internal identifiers untouched).
7. `DATA_FILE` env override.
Delivered as `Myself-RIVAL-full.zip` (full repo). Whether the owner already deployed it and what happened is ❓.

### 11.3 Partially implemented / unfinished
- Explicit mini-app entry point in the user keyboard (only the menu button exists).
- Admin experience on `/start` (admin keyboard overrides the RIVAL keyboard).
- Pyrogram fallbacks for editing photo panels (`edit_inline_text` path).
- `miniapp/index.html` unused; dashboard branding not aligned with the banner design.
- Persistent storage on Railway (Volume) unconfirmed.
- Names `darkself_*` / `voldyself_*` still exist as internal identifiers and logs dir.

### 11.4 Known issues / risks (✅ observed in code unless marked)
- **Corrected statement:** an earlier summary said the code has no subprocess/exec; that was wrong. Real usages: `subprocess.run` (ffmpeg, line ~7483), the **ROOT_ADMIN hot-deploy** that overwrites `bot.py` and spawns a shell guard (`subprocess.Popen(["setsid","bash",guard])`, ~15734), and `os.execv` after DB restore (~15452). No `eval`/`exec`/`os.system` found.
- Hot deploy references `/root/run_bot.sh` (VPS path); likely non-functional on Railway ❓.
- Custom (non-standard) encryption scheme (§5.3). Fallback key derived from `API_HASH|BOT_TOKEN` if `DB_ENCRYPTION_KEY` is unset.
- Hosting other people's Telegram sessions is a serious responsibility; `.سشن` and admin "رمزگشایی سشن‌ها" expose session strings by design.
- Adult-content commands (`nsfw_controller`) can get accounts reported.
- Dependencies unpinned → upgrades (especially Pyrogram) can break monkey-patches.
- Railway filesystem is ephemeral without a Volume (DB loss on redeploy). Railway trial/credits are limited.
- `ffmpeg`/`tesseract` availability ❓.
- Colored `style` on reply-keyboard buttons and `switch_inline_query_current_chat` help flow: unverified.
- Tests not run here.

---

## 12. Development rules (keep)

1. Never rebuild an already implemented feature without a clear reason.
2. Never assume code exists or behaves a certain way — **open the related files first** (`grep` with tolerance for the odd spacing).
3. Preserve the architecture (manager bot + per-user Pyrogram clients + JSON DB + inline-mode panel).
4. Do not break existing commands; check `me_cmd` patterns, handler groups and `DOT_COMMANDS_STATUS` before adding/modifying commands.
5. New tools go in `self_tools/` as modules with `register(reg)` and be added to `MODULES`; prefer this over growing `bot.py`.
6. Never expose or overwrite secrets, sessions, tokens, `API_HASH`, `DB_ENCRYPTION_KEY`; never change the encryption key/derivation without a migration.
7. Keep internal identifiers (`darkself_db_key`, `VOLDYSELF_*` env names, `.voldyself_logs`) unless a migration is planned.
8. After every change: `python -m py_compile bot.py miniapp_api.py self_tools/*.py`, re-check imports/globals used by new code, and list regressions risked.
9. Owner works from a phone: deliver changes as complete files (or one zip) with exact GitHub upload locations; keep instructions short, in Persian.
10. Be honest about what was not tested; the environment has no Telegram access.

---

## 13. Roadmap and next task

### Next task (do this first when development resumes)
**Post-deploy verification of the RIVAL update** — ask the owner for Railway logs and run this checklist, fixing only what fails:
1. Logs show startup without exceptions (`self_tools: N tools registered`, `[miniapp] server listening … public url: https://…`).
2. `/start` shows banner + welcome text + 3 buttons, placeholder `انتخاب کن - RIVAL`, colors visible (if no colors → fallback path works; decide whether to accept).
3. `✅ فعالسازی` → login flow works end-to-end with a **secondary account**; button flips to `⛔ غیرفعال‌سازی`; confirm/cancel works; `log_out()` really removes the session from the account's device list.
4. `👤 حساب کاربری` sends the card; `/card` works in a chat.
5. `.پنل` returns a photo card with buttons; pressing panel buttons edits the caption without errors; if not, check `/miniapp` state, domain port (8080) and `PANEL_CARD`.
6. `📖 راهنما` opens the help center via inline mode; `💬 پشتیبانی` opens `@sadzr`.
7. Confirm Volume/`DATA_FILE`: redeploy and verify users survive.

### Prioritized roadmap
1. Fix anything found by the checklist above.
2. Make persistence reliable (Volume + backup-before-deploy habit; consider moving off JSON to a real DB later).
3. Add an inline `web_app` "🚀 مینی‌اپ" button (e.g. under the account card) — offered, not built.
4. Decide admin UX on `/start` (show RIVAL keyboard + admin entry).
5. Replace/neutralize the VPS hot-deploy for Railway, or disable it.
6. Replace the custom encryption with a standard AEAD with migration; pin dependency versions.
7. Unify mini-app visual identity with the banner (deep blue + silver), remove or repurpose `miniapp/index.html`.
8. Finish brand cleanup of internal names only if a migration is planned.
9. Run the existing tests in a Pyrogram-enabled environment; add tests for `profilecard` and the rival_* handlers.
10. Optional: name slot on the card template, more card variants.

---

## 14. Quick locator (function → purpose; search by name)

`bot.py`: `DataManager`, `ResilientClient`, `_ShardSupervisor`, `me_cmd`, `get_cmd`, `start_bot_instance`, `_start_bot_instance_now_impl`, `stop_user_bot`, `start_handler`, `contact_handler`, `text_handler`, `finalize_login`, `send_main_menu`, `rival_*`, `_deactivate_self`, `_card_for_user`, `_card_url_for_panel`, `inline_panel_handler`, `callback_panel_handler`, `generate_panel_markup_json`, `build_elite_panel_rows`, `PANEL_TABS` (prof, text, smart, shield, pres, tab, target, lang), `HELP_SECTIONS`, `get_admin_menu_keyboard`, `admin_deploy_handler`, `bot_api_request` / `_bot_api_request_raw`, `_start_miniapp_server`, `_miniapp_public_url`, `_set_menu_button`, `_legacy_main`, `main`.
`miniapp_api.py`: `_auth`, `start`, routes (`cardimg`, `page`, `health`, `/miniapp/*`).
`self_tools/__init__.py`: `MODULES`, `_Registrar`, `register_all`. `self_tools/profilecard.py`: `build_card`, `handler`, `register`.
