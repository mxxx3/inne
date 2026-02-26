import asyncio
import logging
import sqlite3
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
from deep_translator import GoogleTranslator

# --- KONFIGURACJA ---
BOT_TOKEN = '8567902133:AAGBgYX0b4hdzbt0KOowa-gHDAqGwblboVE'

# ID Grupy Głównej (General i Translator)
GROUP_MAIN_ID = -1003676480681  
# ID Nowej Grupy (Grom tłum)
GROUP_GROM_ID = -1003772687355  

# ID Tematów
TOPIC_GENERAL_ID = 0         
TOPIC_TRANSLATOR_ID = 27893  
TOPIC_GROM_ID = 0            

# Ustawienia wydajności
MAX_WORKERS = 5  
DB_PATH = "translator_cache.db"

# Kolejka zadań
translation_queue = asyncio.Queue()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- OBSŁUGA BAZY DANYCH (SQLite) ---
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
        logger.error(f"Błąd SQLite (zapis): {e}")

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
        logger.error(f"Błąd SQLite (odczyt): {e}")
        return None

# --- LOGIKA TŁUMACZENIA ---
async def perform_translation(text, target_lang):
    try:
        translator = GoogleTranslator(source='auto', target=target_lang)
        return await asyncio.to_thread(translator.translate, text)
    except Exception as e:
        logger.error(f"Błąd API Tłumacza ({target_lang}): {e}")
        return None

async def translation_worker(worker_id):
    logger.info(f"Worker {worker_id} gotowy.")
    while True:
        task = await translation_queue.get()
        try:
            message, target_configs, source_label = task
            original_text = message.text or message.caption or ""
            
            # Słownik do cache-owania tłumaczeń (żeby nie tłumaczyć dwa razy na ten sam język)
            translated_cache = {}

            sender = message.from_user.full_name
            
            for target_chat, target_topic, lang in target_configs:
                # Jeśli jeszcze nie mamy tłumaczenia na ten język, wykonujemy je
                if lang not in translated_cache:
                    if original_text.strip():
                        res = await perform_translation(original_text, lang)
                        translated_cache[lang] = res if res else f"[Błąd] {original_text}"
                    else:
                        translated_cache[lang] = ""

                content = translated_cache[lang]
                final_text = f"👤 **{sender}** ({source_label}):\n\n{content}"
                
                # Obsługa odpowiedzi
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
                        caption=final_text,
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    sent = await bot.send_message(
                        chat_id=target_chat,
                        text=final_text,
                        message_thread_id=send_thread,
                        reply_to_message_id=reply_id,
                        parse_mode=ParseMode.MARKDOWN
                    )

                if sent:
                    save_mapping(message.chat.id, message.message_id, target_chat, sent.message_id)

        except Exception as e:
            logger.error(f"Błąd w workerze {worker_id}: {e}")
        
        translation_queue.task_done()

# --- KOMENDA /id ---
@dp.message(Command("id"))
async def get_ids(message: types.Message):
    t_id = message.message_thread_id if message.message_thread_id is not None else 0
    await message.reply(f"📊 Chat: `{message.chat.id}` | Topic: `{t_id}`")

# --- PRZYJMOWANIE WIADOMOŚCI ---
@dp.message()
async def bridge_handler(message: types.Message):
    if message.from_user.is_bot or (message.text and message.text.startswith("/")):
        return

    curr_chat = message.chat.id
    curr_topic = message.message_thread_id if message.message_thread_id is not None else 0
    
    # target_configs to lista krotek: (chat_id, topic_id, target_lang)
    target_configs = []
    source_label = ""

    # 1. Z General -> Wysyłamy do obu grup, ale z RÓŻNYMI językami
    if curr_chat == GROUP_MAIN_ID and curr_topic == TOPIC_GENERAL_ID:
        target_configs = [
            (GROUP_MAIN_ID, TOPIC_TRANSLATOR_ID, 'es'), # Translator -> Hiszpański
            (GROUP_GROM_ID, TOPIC_GROM_ID, 'en')       # Grom -> Angielski
        ]
        source_label = "General"

    # 2. Z Translator -> Powrót na General | Tłumaczymy na Polski
    elif curr_chat == GROUP_MAIN_ID and curr_topic == TOPIC_TRANSLATOR_ID:
        target_configs = [(GROUP_MAIN_ID, TOPIC_GENERAL_ID, 'pl')]
        source_label = "Translator"

    # 3. Z Grom -> Powrót na General | Tłumaczymy na Polski
    elif curr_chat == GROUP_GROM_ID and curr_topic == TOPIC_GROM_ID:
        target_configs = [(GROUP_MAIN_ID, TOPIC_GENERAL_ID, 'pl')]
        source_label = "Grom"

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
