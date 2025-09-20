import telebot
from telebot import types
import sqlite3
import os
import threading
import time
import html
import yt_dlp

# ==============================================================
#           1. معلومات البوت الأساسية والإعدادات
# ==============================================================
# قراءة المتغيرات من بيئة التشغيل (Railway)
BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID_STR = os.environ.get('ADMIN_ID')

# التحقق من وجود المتغيرات
if not BOT_TOKEN or not ADMIN_ID_STR:
    print("CRITICAL ERROR: BOT_TOKEN or ADMIN_ID environment variables not set.")
    exit()

try:
    ADMIN_ID = int(ADMIN_ID_STR)
except ValueError:
    print("CRITICAL ERROR: ADMIN_ID is not a valid integer.")
    exit()

# قاعدة البيانات ستكون في مسار مخصص ودائم في Railway
DB_FILE = '/data/bot_database.db'

admin_states = {}

# ==============================================================
#           2. إعداد قاعدة البيانات
# ==============================================================
def get_db_connection():
    # التأكد من وجود مجلد /data قبل إنشاء الاتصال
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def setup_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    cursor.execute('CREATE TABLE IF NOT EXISTS force_subscribe (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT NOT NULL UNIQUE)')
    cursor.execute('CREATE TABLE IF NOT EXISTS broadcast_messages (original_message_id INTEGER, user_id INTEGER, sent_message_id INTEGER, PRIMARY KEY (original_message_id, user_id))')
    cursor.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", ('welcome_message', "👋 <b>أهلاً بك في بوت تحميل الفيديوهات فائق السرعة.</b>\n\nأرسل لي رابط أي فيديو من يوتيوب، تيك توك، انستغرام، وغيرها وسأقوم بتحميله لك فوراً."))
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", ('subscribe_message', "🚫 <b>عذراً، عليك الاشتراك في القنوات التالية أولاً لاستخدام البوت:</b>"))
    conn.commit()
    conn.close()

bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')

# ==============================================================
#           3. الدوال المساعدة (Helpers)
# ==============================================================
def is_admin(user_id):
    return user_id == ADMIN_ID

def get_setting(key):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    result = cursor.fetchone()
    conn.close()
    return result['value'] if result else None

def update_setting(key, value):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE settings SET value = ? WHERE key = ?", (value, key))
    conn.commit()
    conn.close()

def add_user_to_db(user):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)", (user.id, user.username, user.first_name))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB Error] Error adding user: {e}")

def get_force_subscribe_channels():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id FROM force_subscribe")
    channels = [row['channel_id'] for row in cursor.fetchall()]
    conn.close()
    return channels

def check_subscription(user_id):
    channels = get_force_subscribe_channels()
    if not channels:
        return True
    for channel in channels:
        try:
            member = bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                return False
        except Exception:
            return False
    return True

# ==============================================================
#           4. لوحة التحكم الاحترافية للأدمن (كاملة)
# ==============================================================
def get_main_admin_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📢 قسم البث", callback_data="admin_broadcast_menu"),
        types.InlineKeyboardButton("📢 قسم الاشتراك", callback_data="admin_subscribe_menu"),
        types.InlineKeyboardButton("⚙️ قسم الإعدادات", callback_data="admin_settings_menu"),
        types.InlineKeyboardButton("📊 الإحصائيات", callback_data="admin_stats")
    )
    return markup

def get_broadcast_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("📝 بث عادي", callback_data="admin_broadcast_simple"),
        types.InlineKeyboardButton("🔗 بث مع أزرار", callback_data="admin_broadcast_buttons"),
        types.InlineKeyboardButton("🔙 رجوع", callback_data="admin_main_menu")
    )
    return markup

def get_subscribe_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    channels = get_force_subscribe_channels()
    for channel in channels:
        markup.add(types.InlineKeyboardButton(f"❌ حذف {channel}", callback_data=f"delete_{channel}"))
    markup.add(
        types.InlineKeyboardButton("➕ إضافة قناة جديدة", callback_data="admin_add_channel"),
        types.InlineKeyboardButton("🔙 رجوع", callback_data="admin_main_menu")
    )
    return markup

def get_settings_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("✏️ تعديل رسالة الترحيب", callback_data="admin_edit_welcome"),
        types.InlineKeyboardButton("✏️ تعديل رسالة الاشتراك", callback_data="admin_edit_subscribe"),
        types.InlineKeyboardButton("🔙 رجوع", callback_data="admin_main_menu")
    )
    return markup

@bot.message_handler(commands=['admin'], func=is_admin)
def admin_panel(message):
    bot.send_message(message.chat.id, "<b>⚙️ لوحة تحكم الأدمن الرئيسية</b>\n\nاختر القسم الذي تريد إدارته.", reply_markup=get_main_admin_keyboard())

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_') and is_admin(call.from_user.id))
def admin_menu_handler(call):
    bot.answer_callback_query(call.id)
    actions = {
        "admin_main_menu": ("<b>⚙️ لوحة تحكم الأدمن الرئيسية</b>\n\nاختر القسم الذي تريد إدارته.", get_main_admin_keyboard),
        "admin_broadcast_menu": ("<b>📢 قسم البث</b>\n\nاختر نوع الرسالة الجماعية.", get_broadcast_keyboard),
        "admin_subscribe_menu": ("<b>📢 قسم الاشتراك الإجباري</b>\n\nإدارة قنوات الاشتراك.", get_subscribe_keyboard),
        "admin_settings_menu": ("<b>⚙️ قسم الإعدادات</b>\n\nتحكم في رسائل البوت.", get_settings_keyboard)
    }
    if call.data in actions:
        text, keyboard_func = actions[call.data]
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=keyboard_func())
    elif call.data == "admin_stats":
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM users WHERE join_date >= datetime('now', '-24 hours')")
        new_users = cursor.fetchone()[0]
        conn.close()
        text = f"📊 <b>إحصائيات البوت:</b>\n\n-  <b>إجمالي المستخدمين:</b> {total_users}\n-  <b>المستخدمون الجدد (آخر 24 ساعة):</b> {new_users}"
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 رجوع", callback_data="admin_main_menu")))
    elif call.data in ["admin_add_channel", "admin_edit_welcome", "admin_edit_subscribe", "admin_broadcast_simple", "admin_broadcast_buttons"]:
        state_prompts = {
            "admin_add_channel": ("adding_channel", "أرسل الآن معرف القناة (مثال: @YourChannel) أو قم بتوجيه رسالة منها."),
            "admin_edit_welcome": ("editing_welcome", "أرسل الآن رسالة الترحيب الجديدة. يمكنك استخدام تنسيق HTML."),
            "admin_edit_subscribe": ("editing_subscribe", "أرسل الآن رسالة الاشتراك الإجباري الجديدة. يمكنك استخدام تنسيق HTML."),
            "admin_broadcast_simple": ("broadcasting_simple", "أرسل الآن الرسالة التي تود بثها (نص، صورة، إلخ)."),
            "admin_broadcast_buttons": ("broadcasting_buttons", "أرسل الرسالة أولاً، ثم سأطلب منك الأزرار.")
        }
        state, prompt = state_prompts[call.data]
        admin_states[call.from_user.id] = state
        bot.send_message(call.message.chat.id, prompt)

@bot.message_handler(func=lambda message: admin_states.get(message.from_user.id) and is_admin(message.from_user.id), content_types=['text', 'photo', 'video', 'document'])
def handle_admin_state_messages(message):
    state = admin_states.pop(message.from_user.id, None)
    if not state: return
    if state == "adding_channel":
        channel_id = f"@{message.forward_from_chat.username}" if message.forward_from_chat else message.text
        if not channel_id or not channel_id.startswith('@'):
            bot.send_message(message.chat.id, "المعرف غير صالح. حاول مرة أخرى.")
            return
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO force_subscribe (channel_id) VALUES (?)", (channel_id,))
            conn.commit()
            conn.close()
            bot.send_message(message.chat.id, f"✅ تم إضافة القناة <b>{channel_id}</b> بنجاح.")
        except sqlite3.IntegrityError: bot.send_message(message.chat.id, "⚠️ هذه القناة مضافة بالفعل.")
        except Exception as e: bot.send_message(message.chat.id, f"حدث خطأ: {e}")
    elif state == "editing_welcome":
        update_setting('welcome_message', message.text)
        bot.send_message(message.chat.id, "✅ تم تحديث رسالة الترحيب بنجاح.")
    elif state == "editing_subscribe":
        update_setting('subscribe_message', message.text)
        bot.send_message(message.chat.id, "✅ تم تحديث رسالة الاشتراك الإجباري بنجاح.")
    elif state == "broadcasting_simple":
        broadcast_message_handler(message)
    elif state == "broadcasting_buttons":
        admin_states[message.from_user.id] = {"state": "waiting_for_buttons", "message": message}
        bot.send_message(message.chat.id, "الآن أرسل الأزرار بهذا التنسيق:\n\nاسم الزر 1 - رابط الزر 1\nاسم الزر 2 - رابط الزر 2")
    elif isinstance(state, dict) and state.get("state") == "waiting_for_buttons":
        original_message = state["message"]
        markup = types.InlineKeyboardMarkup()
        try:
            for line in message.text.split('\n'):
                parts = line.split(' - ')
                if len(parts) == 2: markup.add(types.InlineKeyboardButton(parts[0].strip(), url=parts[1].strip()))
            broadcast_message_handler(original_message, markup)
        except Exception as e: bot.send_message(message.chat.id, f"❌ تنسيق الأزرار غير صالح. حاول مرة أخرى. الخطأ: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('delete_'))
def delete_channel_callback(call):
    if not is_admin(call.from_user.id): return
    channel_to_delete = call.data.split("_", 1)[1]
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM force_subscribe WHERE channel_id = ?", (channel_to_delete,))
    conn.commit()
    conn.close()
    bot.answer_callback_query(call.id, f"تم حذف القناة {channel_to_delete} بنجاح.")
    bot.edit_message_text("<b>📢 قسم الاشتراك الإجباري</b>\n\nتم حذف القناة. هذه هي القائمة المحدثة.", call.message.chat.id, call.message.message_id, reply_markup=get_subscribe_keyboard())

def broadcast_message_handler(message, reply_markup=None):
    bot.send_message(message.chat.id, "⏳ جارٍ بدء عملية البث...")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    cursor.execute("DELETE FROM broadcast_messages")
    conn.commit()
    success, fail = 0, 0
    for user in users:
        try:
            sent_msg = bot.copy_message(user['user_id'], message.chat.id, message.message_id, reply_markup=reply_markup)
            cursor.execute("INSERT INTO broadcast_messages VALUES (?, ?, ?)", (message.message_id, user['user_id'], sent_msg.message_id))
            conn.commit()
            success += 1
        except: fail += 1
        time.sleep(0.05)
    conn.close()
    summary_msg = f"✅ <b>اكتمل البث!</b>\n\n-  <b>تم الإرسال إلى:</b> {success}\n-  <b>فشل الإرسال إلى:</b> {fail}"
    markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🗑️ حذف هذه الرسالة من عند الجميع", callback_data=f"del_broadcast_{message.message_id}"))
    bot.send_message(message.chat.id, summary_msg, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('del_broadcast_'))
def delete_broadcast_handler(call):
    if not is_admin(call.from_user.id): return
    original_message_id = int(call.data.split('_')[-1])
    bot.edit_message_text("⏳ جارٍ حذف الرسالة...", call.message.chat.id, call.message.message_id, reply_markup=None)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, sent_message_id FROM broadcast_messages WHERE original_message_id = ?", (original_message_id,))
    messages_to_delete = cursor.fetchall()
    deleted_count = 0
    for item in messages_to_delete:
        try:
            bot.delete_message(item['user_id'], item['sent_message_id'])
            deleted_count += 1
        except: pass
        time.sleep(0.05)
    bot.edit_message_text(f"✅ تم حذف الرسالة من عند {deleted_count} مستخدم.", call.message.chat.id, call.message.message_id)
    cursor.execute("DELETE FROM broadcast_messages WHERE original_message_id = ?", (original_message_id,))
    conn.commit()
    conn.close()

# ==============================================================
#           5. أوامر وتفاعلات المستخدمين
# ==============================================================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    add_user_to_db(message.from_user)
    bot.send_message(message.chat.id, get_setting('welcome_message'))

@bot.message_handler(func=lambda message: True, content_types=['text'])
def handle_message(message):
    add_user_to_db(message.from_user)
    if not check_subscription(message.from_user.id):
        channels = get_force_subscribe_channels()
        if not channels:
            bot.reply_to(message, "حدث خطأ إداري. لا توجد قنوات اشتراك محددة حالياً.")
            return
        markup = types.InlineKeyboardMarkup(row_width=1)
        for channel in channels:
            try:
                chat_info = bot.get_chat(channel)
                invite_link = chat_info.invite_link or bot.export_chat_invite_link(channel)
                markup.add(types.InlineKeyboardButton(f"📢 {chat_info.title}", url=invite_link))
            except: markup.add(types.InlineKeyboardButton(f"🔗 {channel}", url=f"https://t.me/{channel.replace('@','')}"))
        markup.add(types.InlineKeyboardButton("✅ لقد اشتركت، تحقق الآن", callback_data="check_join"))
        bot.send_message(message.chat.id, get_setting('subscribe_message'), reply_markup=markup)
        return
    if message.text.startswith('http://') or message.text.startswith('https://'):
        process_video_download(message)
    else:
        bot.reply_to(message, "الرجاء إرسال رابط فيديو صالح للتحميل.")

@bot.callback_query_handler(func=lambda call: call.data == 'check_join')
def check_join_callback(call):
    if check_subscription(call.from_user.id):
        bot.answer_callback_query(call.id, "✅ شكراً لك! يمكنك الآن استخدام البوت.")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, "رائع! أرسل الآن رابط الفيديو الذي تريد تحميله.")
    else:
        bot.answer_callback_query(call.id, "⚠️ يبدو أنك لم تشترك في جميع القنوات بعد. حاول مرة أخرى.", show_alert=True)

# ==============================================================
#           6. نظام التحميل النقي والقوي (yt-dlp بدون بروكسي)
# ==============================================================
def process_video_download(message):
    url = message.text
    msg = bot.reply_to(message, "📥 جارٍ التحميل، يرجى الانتظار...")

    def download_thread():
        video_path = None
        try:
            # استخدام مسار مؤقت للتحميلات
            download_folder = '/tmp/downloads'
            os.makedirs(download_folder, exist_ok=True)

            ydl_opts = {
                'format': 'best[ext=mp4][height<=720]/best[ext=mp4]/best',
                'outtmpl': os.path.join(download_folder, f'{message.from_user.id}_{int(time.time())}.%(ext)s'),
                'noplaylist': True,
                'quiet': True,
                'noprogress': True,
                'socket_timeout': 30,
                # لا يوجد بروكسي! اتصال مباشر ونظيف.
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                video_path = ydl.prepare_filename(info)

            bot.edit_message_text("⬆️ جارٍ الرفع...", chat_id=msg.chat.id, message_id=msg.message_id)
            with open(video_path, 'rb') as video_file:
                bot.send_video(message.chat.id, video_file, caption="✅ <b>تم التحميل بنجاح!</b>", reply_to_message_id=message.message_id)
            bot.delete_message(msg.chat.id, msg.message_id)

        except Exception as e:
            print(f"[Download Error] {e}")
            error_text = "❌ <b>عذراً، فشل التحميل.</b>\n\nقد يكون الرابط غير صحيح، أو أن هذا الموقع غير مدعوم حالياً."
            bot.edit_message_text(error_text, chat_id=msg.chat.id, message_id=msg.message_id)
        
        finally:
            if video_path and os.path.exists(video_path):
                os.remove(video_path)

    threading.Thread(target=download_thread).start()

# ==============================================================
#           7. تشغيل البوت
# ==============================================================
if __name__ == '__main__':
    print("Bot is running... (Version 15.0 - Railway Ready)")
    setup_database()
    bot.polling(none_stop=True)
