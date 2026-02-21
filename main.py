import asyncio
import logging
import sqlite3
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
from deep_translator import GoogleTranslator

# --- KONFIGURACJA ---
BOT_TOKEN = '8567902133:AAGBgYX0b4hdzbt0KOowa-gHDAqGwblboVE'

# ID grupy głównej
GROUP_ID = -1003676480681  

# ID tematów (podgrup)
TOPIC_GENERAL_ID = 0      
TOPIC_TRANSLATOR_ID = 27893 

# Ustawienia wydajności
MAX_WORKERS = 4  
DB_PATH = "translator_cache.db"

# Kolejka zadań
translation_queue = asyncio.Queue()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- OBSŁUGA BAZY DANYCH (SQLite) ---
def init_db():
    """Inicjalizacja bazy danych SQLite dla mapowania wiadomości"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS message_map (
            orig_id INTEGER PRIMARY KEY,
            trans_id INTEGER
        )
    ''')
    conn.commit()
    conn.close()

def save_mapping(orig_id, trans_id):
    """Zapisuje powiązanie ID wiadomości w bazie"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO message_map (orig_id, trans_id) VALUES (?, ?)", (orig_id, trans_id))
        cursor.execute("INSERT OR REPLACE INTO message_map (orig_id, trans_id) VALUES (?, ?)", (trans_id, orig_id))
        conn.commit()
        
        # Ograniczenie wielkości bazy do ostatnich 20k rekordów
        cursor.execute("SELECT COUNT(*) FROM message_map")
        if cursor.fetchone()[0] > 20000:
            cursor.execute("DELETE FROM message_map WHERE orig_id IN (SELECT orig_id FROM message_map LIMIT 1000)")
            conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Błąd SQLite (zapis): {e}")

def get_mapping(orig_id):
    """Pobiera zmapowane ID dla odpowiedzi (reply)"""
    if not orig_id: return None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT trans_id FROM message_map WHERE orig_id = ?", (orig_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    except Exception as e:
        logger.error(f"Błąd SQLite (odczyt): {e}")
        return None

# --- LOGIKA TŁUMACZENIA ---
async def perform_translation(text, target_lang):
    """Tłumaczenie tekstu w osobnym wątku"""
    try:
        translator = GoogleTranslator(source='auto', target=target_lang)
        return await asyncio.to_thread(translator.translate, text)
    except Exception as e:
        logger.error(f"Błąd Google Translate: {e}")
        return None

async def translation_worker(worker_id):
    """Pracownik przetwarzający kolejkę w tle"""
    logger.info(f"Worker {worker_id} wystartował.")
    while True:
        task = await translation_queue.get()
        try:
            message, target_topic, target_lang, source_label = task
            original_text = message.text or message.caption or ""
            
            # Tłumacz tylko jeśli jest tekst
            translated = await perform_translation(original_text, target_lang) if original_text.strip() else ""
            
            if original_text.strip() and not translated:
                translated = f"[Błąd tłumaczenia] {original_text}"

            # Pobranie ID wiadomości do której jest to odpowiedź
            reply_to_id = None
            if message.reply_to_message:
                reply_to_id = get_mapping(message.reply_to_message.message_id)
            
            sender = message.from_user.full_name
            final_text = f"👤 **{sender}** ({source_label}):\n\n{translated}"
            send_to_thread = target_topic if target_topic != 0 else None

            sent = None
            # Rozszerzona lista mediów (dodano message.animation dla GIFów)
            media_check = [
                message.photo, message.video, message.animation, 
                message.document, message.audio, message.voice
            ]
            
            if any(media_check):
                sent = await message.copy_to(
                    chat_id=GROUP_ID,
                    message_thread_id=send_to_thread,
                    reply_to_message_id=reply_to_id,
                    caption=final_text,
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                sent = await bot.send_message(
                    chat_id=GROUP_ID,
                    text=final_text,
                    message_thread_id=send_to_thread,
                    reply_to_message_id=reply_to_id,
                    parse_mode=ParseMode.MARKDOWN
                )

            if sent:
                save_mapping(message.message_id, sent.message_id)

        except Exception as e:
            logger.error(f"Błąd w workerze {worker_id}: {e}")
        
        translation_queue.task_done()

# --- KOMENDA /id ---
@dp.message(Command("id"))
async def get_ids(message: types.Message):
    t_id = message.message_thread_id if message.message_thread_id is not None else 0
    await message.reply(f"📊 Chat ID: `{message.chat.id}` | Topic ID: `{t_id}`")

# --- PRZYJMOWANIE WIADOMOŚCI ---
@dp.message()
async def bridge_handler(message: types.Message):
    # Ignoruj boty i komendy
    if message.from_user.is_bot or (message.text and message.text.startswith("/")):
        return

    current_topic = message.message_thread_id if message.message_thread_id is not None else 0
    
    target_topic = None
    target_lang = None
    source_label = ""

    # General -> Translator (PL do EN)
    if message.chat.id == GROUP_ID and current_topic == TOPIC_GENERAL_ID:
        target_topic = TOPIC_TRANSLATOR_ID
        target_lang = 'en'
        source_label = "General"
    # Translator -> General (EN do PL)
    elif message.chat.id == GROUP_ID and current_topic == TOPIC_TRANSLATOR_ID:
        target_topic = TOPIC_GENERAL_ID
        target_lang = 'pl'
        source_label = "Translator"

    if target_topic is not None:
        await translation_queue.put((message, target_topic, target_lang, source_label))

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
