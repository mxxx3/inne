import asyncio
import logging
import re
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
from deep_translator import GoogleTranslator

# --- KONFIGURACJA ---
# Podmień te wartości po użyciu komendy /id
BOT_TOKEN = '8567902133:AAGBgYX0b4hdzbt0KOowa-gHDAqGwblboVE'

GROUP_A_ID = -1003676480681  # Grom
GROUP_B_ID = -1003676480681  # translator

TOPIC_A_ID = 0           # Temat w Grom
TOPIC_B_ID = 27893            # Temat w Aka Grom

# Słownik do mapowania odpowiedzi
msg_mapping = {}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def translate_message(text):
    """Automatycznie wykrywa język i tłumaczy PL->EN lub EN->PL"""
    try:
        detector = GoogleTranslator(source='auto', target='en')
        # Wykrywamy język źródłowy
        detected_lang = detector.detect_language(text)
        
        if detected_lang == 'pl':
            return GoogleTranslator(source='pl', target='en').translate(text)
        else:
            return GoogleTranslator(source='en', target='pl').translate(text)
    except Exception as e:
        logger.error(f"Błąd tłumaczenia: {e}")
        return text

# --- KOMENDA DO SPRAWDZANIA ID ---
@dp.message(Command("id"))
async def get_ids(message: types.Message):
    info = (
        f"📊 **Dane tego czatu:**\n"
        f"--- --- --- --- ---\n"
        f"🆔 **Chat ID:** `{message.chat.id}`\n"
        f"🧵 **Topic ID:** `{message.message_thread_id or 'Główny (0)'}`\n"
        f"--- --- --- --- ---\n"
        f"Skopiuj te dane do sekcji KONFIGURACJA w kodzie."
    )
    await message.reply(info, parse_mode=ParseMode.MARKDOWN)

# --- GŁÓWNA LOGIKA MOSTU ---
@dp.message()
async def bridge_handler(message: types.Message):
    # Ignoruj komendy i boty
    if message.text and message.text.startswith("/") or message.from_user.is_bot:
        return

    try:
        # Określenie kierunku
        if message.chat.id == GROUP_A_ID and message.message_thread_id == TOPIC_A_ID:
            target_chat = GROUP_B_ID
            target_topic = TOPIC_B_ID
            source_label = "Grom"
        elif message.chat.id == GROUP_B_ID and message.message_thread_id == TOPIC_B_ID:
            target_chat = GROUP_A_ID
            target_topic = TOPIC_A_ID
            source_label = "Aka Grom"
        else:
            return

        # Logika odpowiedzi (Reply)
        reply_to_id = None
        reply_info = ""
        if message.reply_to_message and message.reply_to_message.message_id != message.message_thread_id:
            reply_to_id = msg_mapping.get(message.reply_to_message.message_id)
            replied_to_name = message.reply_to_message.from_user.full_name
            reply_info = f"↩️ Odpowiedź dla **{replied_to_name}**\n"

        # Tłumaczenie treści
        original_text = message.text or message.caption or ""
        translated = translate_message(original_text) if original_text else ""
        
        sender_name = message.from_user.full_name
        final_caption = f"{reply_info}👤 **{sender_name}** ({source_label}):\n\n{translated}"

        # Przesyłanie
        if any([message.photo, message.video, message.document, message.audio]):
            sent_msg = await message.copy_to(
                chat_id=target_chat,
                message_thread_id=target_topic,
                reply_to_message_id=reply_to_id,
                caption=final_caption,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            sent_msg = await bot.send_message(
                chat_id=target_chat,
                text=final_caption,
                message_thread_id=target_topic,
                reply_to_message_id=reply_to_id,
                parse_mode=ParseMode.MARKDOWN
            )

        # Zapisywanie mapowania ID
        if sent_msg:
            msg_mapping[message.message_id] = sent_msg.message_id
            msg_mapping[sent_msg.message_id] = message.message_id

    except Exception as e:
        logger.error(f"Błąd mostu: {e}")

async def main():
    logger.info("Bot uruchomiony. Użyj /id w grupie, aby sprawdzić parametry.")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())

