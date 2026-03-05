import asyncio
import logging
import sqlite3
import html
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
from deep_translator import GoogleTranslator

# =================================================================
# SEKCJA KONFIGURACJI - WSZYSTKIE JĘZYKI W JEDNEJ GRUPIE
# =================================================================

# ID GRUPY GŁÓWNEJ (Dla wszystkich wątków)
MAIN_GROUP_ID = -1003676480681

# ID TEMATÓW (TOPIC IDs)
TOPIC_GENERAL = 0
TOPIC_SPANISH = 27893
TOPIC_ENGLISH = 37572
TOPIC_RUSSIAN = 37576
TOPIC_UKRAINIAN = 37575

# TOKEN BOTA
BOT_TOKEN = '8567902133:AAGBgYX0b4hdzbt0KOowa-gHDAqGwblboVE'

# =================================================================
# KONIEC KONFIGURACJI
# =================================================================

MAX_WORKERS = 5
DB_PATH = "translator_cache.db"
translation_queue = asyncio.Queue()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS message_map (
            orig_chat_id INTEGER,
            orig_msg_id INTEGER,
            trans_chat_id INTEGER,
            trans_msg_id INTEGER,
            PRIMARY KEY (orig_chat_id, orig_msg_id, trans_chat_id)
        )
    ''')
    conn.commit()
    conn.close()

def save_mapping(o_chat, o_msg, t_chat, t_msg):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO message_map VALUES (?, ?, ?, ?)", (o_chat, o_msg, t_chat, t_msg))
        cursor.execute("INSERT OR REPLACE INTO message_map VALUES (?, ?, ?, ?)", (t_chat, t_msg, o_chat, o_msg))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"SQLite Save Error: {e}")

def get_mapping(target_chat_id, reply_to_msg_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT trans_msg_id FROM message_map WHERE orig_msg_id = ? AND trans_chat_id = ?", 
            (reply_to_msg_id, target_chat_id)
        )
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    except Exception as e:
        logger.error(f"SQLite Get Error: {e}")
        return None

async def perform_translation(text, target_lang):
    try:
        translator = GoogleTranslator(source='auto', target=target_lang)
        return await asyncio.to_thread(translator.translate, text)
    except Exception as e:
        logger.error(f"Translation Error ({target_lang}): {e}")
        return None

async def translation_worker(worker_id):
    logger.info(f"Worker {worker_id} gotowy.")
    while True:
        task = await translation_queue.get()
        try:
            message, target_configs, source_label = task
            original_text = message.text or message.caption or ""
            translated_cache = {}
            
            user = message.from_user
            if user:
                safe_name = html.escape(user.full_name)
                # Link t.me (nie pinguje) zamiast tg://user (pinguje)
                if user.username:
                    user_display = f'<b><a href="https://t.me/{user.username}">{safe_name}</a></b>'
                else:
                    user_display = f'<b>{safe_name}</b>'
            else:
                user_display = "<b>Użytkownik</b>"
            
            for target_chat, target_topic, lang in target_configs:
                if lang not in translated_cache:
                    if original_text.strip():
                        res = await perform_translation(original_text, lang)
                        translated_cache[lang] = html.escape(res) if res else "<i>Błąd tłumaczenia</i>"
                    else:
                        translated_cache[lang] = ""

                content = translated_cache[lang]
                header = f"<b>{source_label}</b>\n👤 {user_display}\n"
                separator = "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯"
                final_html = f"{header}{separator}\n{content}"
                
                reply_id = None
                if message.reply_to_message:
                    reply_id = get_mapping(target_chat, message.reply_to_message.message_id)

                send_thread = target_topic if target_topic != 0 else None
                sent = None
                
                media_check = [message.photo, message.video, message.animation, message.document, message.audio, message.voice]
                
                if any(media_check):
                    sent = await message.copy_to(
                        chat_id=target_chat,
                        message_thread_id=send_thread,
                        reply_to_message_id=reply_id,
                        caption=final_html,
                        parse_mode=ParseMode.HTML
                    )
                else:
                    sent = await bot.send_message(
                        chat_id=target_chat,
                        text=final_html,
                        message_thread_id=send_thread,
                        reply_to_message_id=reply_id,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True
                    )

                if sent:
                    save_mapping(message.chat.id, message.message_id, target_chat, sent.message_id)

        except Exception as e:
            logger.error(f"Błąd w workerze {worker_id}: {e}")
        
        translation_queue.task_done()

@dp.message(Command("id"))
async def get_ids(message: types.Message):
    t_id = message.message_thread_id if message.message_thread_id is not None else 0
    await message.reply(
        f"📊 Chat ID: <code>{message.chat.id}</code>\n🧵 Topic ID: <code>{t_id}</code>", 
        parse_mode=ParseMode.HTML
    )

@dp.message()
async def bridge_handler(message: types.Message):
    if message.from_user and message.from_user.is_bot:
        return
    if message.text and message.text.startswith("/"):
        return

    curr_chat = message.chat.id
    curr_topic = message.message_thread_id if message.message_thread_id is not None else 0
    
    # Tylko wiadomości z naszej głównej grupy nas interesują
    if curr_chat != MAIN_GROUP_ID:
        return

    target_configs = []
    source_label = ""

    # 1. Z General -> Wysyłka do wszystkich 4 języków
    if curr_topic == TOPIC_GENERAL:
        target_configs = [
            (MAIN_GROUP_ID, TOPIC_SPANISH, 'es'),
            (MAIN_GROUP_ID, TOPIC_ENGLISH, 'en'),
            (MAIN_GROUP_ID, TOPIC_RUSSIAN, 'ru'),
            (MAIN_GROUP_ID, TOPIC_UKRAINIAN, 'uk')
        ]
        source_label = "GENERAL"

    # 2. Ze Spanish -> General (PL)
    elif curr_topic == TOPIC_SPANISH:
        target_configs = [(MAIN_GROUP_ID, TOPIC_GENERAL, 'pl')]
        source_label = "SPANISH"

    # 3. Z English -> General (PL)
    elif curr_topic == TOPIC_ENGLISH:
        target_configs = [(MAIN_GROUP_ID, TOPIC_GENERAL, 'pl')]
        source_label = "ENGLISH"

    # 4. Z Russian -> General (PL)
    elif curr_topic == TOPIC_RUSSIAN:
        target_configs = [(MAIN_GROUP_ID, TOPIC_GENERAL, 'pl')]
        source_label = "RUSSIAN"

    # 5. Z Ukrainian -> General (PL)
    elif curr_topic == TOPIC_UKRAINIAN:
        target_configs = [(MAIN_GROUP_ID, TOPIC_GENERAL, 'pl')]
        source_label = "UKRAINIAN"

    if target_configs:
        await translation_queue.put((message, target_configs, source_label))

async def main():
    init_db()
    for i in range(MAX_WORKERS):
        asyncio.create_task(translation_worker(i + 1))
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
