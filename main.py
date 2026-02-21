import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
from deep_translator import GoogleTranslator

# --- KONFIGURACJA ---
BOT_TOKEN = '8567902133:AAGBgYX0b4hdzbt0KOowa-gHDAqGwblboVE'

# ID grupy głównej
GROUP_ID = -1003676480681  

# ID tematów
TOPIC_GENERAL_ID = 0      # General (Główny)
TOPIC_TRANSLATOR_ID = 27893 # Translator

# Słownik do mapowania ID wiadomości dla odpowiedzi (replies)
msg_mapping = {}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def translate_content(text, target_lang):
    """Tłumaczy tekst na wskazany język docelowy"""
    try:
        return GoogleTranslator(source='auto', target=target_lang).translate(text)
    except Exception as e:
        logger.error(f"Błąd tłumaczenia: {e}")
        return text

# --- KOMENDA /id ---
@dp.message(Command("id"))
async def get_ids(message: types.Message):
    t_id = message.message_thread_id if message.message_thread_id is not None else 0
    await message.reply(
        f"📊 **Dane diagnostyczne:**\n"
        f"🆔 Chat ID: `{message.chat.id}`\n"
        f"🧵 Topic ID: `{t_id}`",
        parse_mode=ParseMode.MARKDOWN
    )

# --- OBSŁUGA MOSTU ---
@dp.message()
async def bridge_handler(message: types.Message):
    if message.from_user.is_bot or (message.text and message.text.startswith("/")):
        return

    try:
        current_topic = message.message_thread_id if message.message_thread_id is not None else 0
        
        target_topic = None
        target_lang = None
        source_label = ""

        # LOGIKA KIERUNKOWA:
        # 1. Z General (0) -> Translator (27893) | Tłumacz na Angielski
        if message.chat.id == GROUP_ID and current_topic == TOPIC_GENERAL_ID:
            target_topic = TOPIC_TRANSLATOR_ID
            target_lang = 'en'
            source_label = "General"

        # 2. Z Translator (27893) -> General (0) | Tłumacz na Polski
        elif message.chat.id == GROUP_ID and current_topic == TOPIC_TRANSLATOR_ID:
            target_topic = TOPIC_GENERAL_ID
            target_lang = 'pl'
            source_label = "Translator"

        if target_topic is None:
            return

        # Obsługa odpowiedzi (Reply)
        reply_to_id = msg_mapping.get(message.reply_to_message.message_id) if message.reply_to_message else None
        # Ignoruj reply jeśli to tylko przypięta wiadomość lub start wątku
        if message.reply_to_message and message.reply_to_message.message_id == message.message_thread_id:
            reply_to_id = None

        # Tłumaczenie
        original_text = message.text or message.caption or ""
        translated = translate_content(original_text, target_lang) if original_text else ""
        
        sender = message.from_user.full_name
        final_caption = f"👤 **{sender}** ({source_label}):\n\n{translated}"

        # Ustalenie ID wątku dla Telegrama (0 musi być wysłane jako None)
        send_to_thread = target_topic if target_topic != 0 else None

        # Wysyłka
        if any([message.photo, message.video, message.document, message.audio, message.voice]):
            sent = await message.copy_to(
                chat_id=GROUP_ID,
                message_thread_id=send_to_thread,
                reply_to_message_id=reply_to_id,
                caption=final_caption,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            sent = await bot.send_message(
                chat_id=GROUP_ID,
                text=final_caption,
                message_thread_id=send_to_thread,
                reply_to_message_id=reply_to_id,
                parse_mode=ParseMode.MARKDOWN
            )

        # Zapisanie powiązania wiadomości
        if sent:
            msg_mapping[message.message_id] = sent.message_id
            msg_mapping[sent.message_id] = message.message_id
            
            # Czyszczenie pamięci
            if len(msg_mapping) > 4000:
                for _ in range(100):
                    msg_mapping.pop(next(iter(msg_mapping)), None)

    except Exception as e:
        logger.error(f"Błąd mostu: {e}")

async def main():
    logger.info("Bot translator uruchomiony...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
