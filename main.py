import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from deep_translator import GoogleTranslator

# --- KONFIGURACJA ---
# Token bota z BotFather
BOT_TOKEN = '8567902133:AAGBgYX0b4hdzbt0KOowa-gHDAqGwblboVE'

# ID Twoich grup
GROUP_A_ID = -1003676480681  # Grom
GROUP_B_ID = -1003537210812  # Aka Grom

# ID konkretnych Tematów (Topics)
TOPIC_A_ID = 11957           # Temat w Grom
TOPIC_B_ID = 7367            # Temat w Aka Grom

# Konfiguracja logowania
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Inicjalizacja bota
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(F.chat.id.in_({GROUP_A_ID, GROUP_B_ID}))
async def bridge_handler(message: types.Message):
    """Przesyłanie wiadomości między wybranymi tematami"""
    try:
        # Zabezpieczenie przed botami i pętlą
        if message.from_user.is_bot:
            return

        # Filtracja tematów i kierunek przesyłu
        if message.chat.id == GROUP_A_ID:
            if message.message_thread_id != TOPIC_A_ID:
                return
            target_chat = GROUP_B_ID
            target_topic = TOPIC_B_ID
            source_label = "Grom"
        elif message.chat.id == GROUP_B_ID:
            if message.message_thread_id != TOPIC_B_ID:
                return
            target_chat = GROUP_A_ID
            target_topic = TOPIC_A_ID
            source_label = "Aka Grom"
        else:
            return

        # Pobranie tekstu i tłumaczenie
        sender_name = message.from_user.full_name
        original_text = message.text or message.caption or ""
        
        translated = original_text
        if original_text:
            try:
                translated = GoogleTranslator(source='auto', target='pl').translate(original_text)
            except:
                translated = original_text

        caption = f"👤 **{sender_name}** ({source_label}):\n\n{translated}"

        # Przesyłanie (zdjęcia/filmy lub sam tekst)
        if message.photo or message.video or message.document:
            await message.copy_to(
                chat_id=target_chat,
                message_thread_id=target_topic,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await bot.send_message(
                chat_id=target_chat,
                text=caption,
                message_thread_id=target_topic,
                parse_mode=ParseMode.MARKDOWN
            )
        logger.info(f"Przesłano wiadomość od {sender_name}")

    except Exception as e:
        logger.error(f"Błąd: {e}")

async def main():
    logger.info("Bot startuje...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot wyłączony.")
