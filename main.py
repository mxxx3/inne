import asyncio
import logging
import sqlite3
import html
import os
import random
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter

# =================================================================
# SEKCJA KONFIGURACJI
# =================================================================

MAIN_GROUP_ID = -1003676480681

TOPIC_GENERAL = 0
TOPIC_SPANISH = 27893
TOPIC_ENGLISH = 37572
TOPIC_RUSSIAN = 37576
TOPIC_UKRAINIAN = 37575

BOT_TOKEN = '8567902133:AAGBgYX0b4hdzbt0KOowa-gHDAqGwblboVE'

GEMINI_KEYS = {
    "es": os.getenv("Spain", ""),
    "en": os.getenv("English", ""),
    "ru": os.getenv("Russia", ""),
    "uk": os.getenv("Ukraine", ""),
    "pl": os.getenv("Spain", "")
}

MODEL_NAME = "gemini-2.5-flash"

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
        logger.error(f"Błąd SQLite Save: {e}")

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
        logger.error(f"Błąd SQLite Get: {e}")
        return None

async def translate_single_lang(session, text, lang_config, original_message, source_label, user_display):
    """Tłumaczenie i wysyłka z obsługą multimediów i odpowiedzi."""
    target_chat, target_topic, lang = lang_config
    api_key = GEMINI_KEYS.get(lang)
    
    if not api_key:
        return

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={api_key}"
    payload = {
        "contents": [{
            "parts": [{
                "text": f"Translate to {lang}. Only output translation. No preamble. Preserve formatting:\n\n{text}"
            }]
        }]
    }

    raw_translation = None
    for attempt in range(4):
        try:
            async with session.post(url, json=payload, timeout=12) as response:
                if response.status == 200:
                    data = await response.json()
                    raw_translation = data['candidates'][0]['content']['parts'][0]['text'].strip()
                    break
                elif response.status == 429:
                    await asyncio.sleep(1.5 ** attempt)
                else:
                    break
        except Exception:
            await asyncio.sleep(0.5)

    if not raw_translation:
        raw_translation = "<i>(Błąd tłumaczenia AI)</i>"

    content = html.escape(raw_translation)
    final_html = f"<b>{source_label}</b>\n👤 {user_display}\n⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n{content}"
    
    # Pobieranie ID wiadomości do której jest to odpowiedź w temacie docelowym
    reply_id = None
    if original_message.reply_to_message:
        reply_id = get_mapping(target_chat, original_message.reply_to_message.message_id)

    kwargs = {
        "chat_id": target_chat,
        "message_thread_id": target_topic if target_topic != 0 else None,
        "reply_to_message_id": reply_id,
        "parse_mode": ParseMode.HTML,
        "disable_web_page_preview": True
    }

    # Milisekundowe opóźnienie przed wysyłką (staggering)
    await asyncio.sleep(random.uniform(0.1, 0.6))

    for retry in range(5):
        try:
            # Sprawdzanie czy wiadomość zawiera jakiekolwiek media
            has_media = any([
                original_message.photo, original_message.video, 
                original_message.animation, original_message.document, 
                original_message.audio, original_message.voice
            ])

            if has_media:
                # Kopiowanie mediów z nowym podpisem (caption)
                sent = await original_message.copy_to(caption=final_html, **kwargs)
            else:
                # Wysyłka zwykłej wiadomości tekstowej
                sent = await bot.send_message(text=final_html, **kwargs)
            
            if sent:
                save_mapping(original_message.chat.id, original_message.message_id, target_chat, sent.message_id)
            break

        except TelegramRetryAfter as e:
            logger.warning(f"Telegram Flood! Czekam {e.retry_after}s dla {lang}")
            await asyncio.sleep(e.retry_after + 0.1)
        except Exception as e:
            logger.error(f"Błąd wysyłki dla {lang}: {e}")
            break

async def translation_worker(worker_id):
    logger.info(f"Worker {worker_id} ({MODEL_NAME}) aktywny.")
    async with aiohttp.ClientSession() as session:
        while True:
            task = await translation_queue.get()
            try:
                message, target_configs, source_label = task
                
                # Tekst może być w .text (wiadomość) lub .caption (media)
                original_text = message.text or message.caption or ""
                
                if not original_text.strip() and not any([message.photo, message.video, message.animation]):
                    translation_queue.task_done()
                    continue

                user = message.from_user
                safe_name = html.escape(user.full_name) if user else "Użytkownik"
                user_display = f'<b><a href="https://t.me/{user.username}">{safe_name}</a></b>' if user and user.username else f'<b>{safe_name}</b>'
                
                tasks = [
                    translate_single_lang(session, original_text, cfg, message, source_label, user_display)
                    for cfg in target_configs
                ]
                await asyncio.gather(*tasks)

            except Exception as e:
                logger.error(f"Błąd krytyczny workera {worker_id}: {e}")
            
            translation_queue.task_done()

@dp.message(Command("id"))
async def get_ids(message: types.Message):
    t_id = message.message_thread_id or 0
    await message.reply(f"📊 Chat: <code>{message.chat.id}</code> | Topic: <code>{t_id}</code>", parse_mode=ParseMode.HTML)

@dp.message()
async def bridge_handler(message: types.Message):
    if (message.from_user and message.from_user.is_bot) or (message.text and message.text.startswith("/")):
        return

    curr_chat, curr_topic = message.chat.id, message.message_thread_id or 0
    if curr_chat != MAIN_GROUP_ID: return

    target_configs, source_label = [], ""

    if curr_topic == TOPIC_GENERAL:
        target_configs = [
            (MAIN_GROUP_ID, TOPIC_SPANISH, 'es'), 
            (MAIN_GROUP_ID, TOPIC_ENGLISH, 'en'), 
            (MAIN_GROUP_ID, TOPIC_RUSSIAN, 'ru'), 
            (MAIN_GROUP_ID, TOPIC_UKRAINIAN, 'uk')
        ]
        source_label = "GENERAL"
    elif curr_topic == TOPIC_SPANISH:
        target_configs, source_label = [(MAIN_GROUP_ID, TOPIC_GENERAL, 'pl')], "SPANISH"
    elif curr_topic == TOPIC_ENGLISH:
        target_configs, source_label = [(MAIN_GROUP_ID, TOPIC_GENERAL, 'pl')], "ENGLISH"
    elif curr_topic == TOPIC_RUSSIAN:
        target_configs, source_label = [(MAIN_GROUP_ID, TOPIC_GENERAL, 'pl')], "RUSSIAN"
    elif curr_topic == TOPIC_UKRAINIAN:
        target_configs, source_label = [(MAIN_GROUP_ID, TOPIC_GENERAL, 'pl')], "UKRAINIAN"

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
