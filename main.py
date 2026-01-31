import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from deep_translator import GoogleTranslator

# --- KONFIGURACJA ---
BOT_TOKEN = '8567902133:AAGBgYX0b4hdzbt0KOowa-gHDAqGwblboVE'

# ID Twoich grup
GROUP_A_ID = -1003676480681  # Grom
GROUP_B_ID = -1003537210812  # Aka Grom

# ID konkretnych Tematów (Topics)
TOPIC_A_ID = 11957           # Temat w Grom
TOPIC_B_ID = 7367            # Temat w Aka Grom

# Słownik do przechowywania powiązań między wiadomościami (ID mapowanie)
# Pozwala na poprawne działanie odpowiedzi (replies) między grupami
msg_mapping = {}

# Konfiguracja logowania
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Inicjalizacja bota
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(F.chat.id.in_({GROUP_A_ID, GROUP_B_ID}))
async def bridge_handler(message: types.Message):
    """Przesyłanie wiadomości z obsługą odpowiedzi (replies)"""
    try:
        # Ignoruj boty
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

        # Sprawdzenie czy wiadomość jest odpowiedzią
        reply_to_id = None
        reply_info = ""
        if message.reply_to_message:
            # Szukamy czy mamy w pamięci ID wiadomości, na którą ktoś odpowiada
            orig_reply_id = message.reply_to_message.message_id
            reply_to_id = msg_mapping.get(orig_reply_id)
            
            # Dodatkowy tekst informujący na kogo odpowiadamy (wizualny)
            replied_to_name = message.reply_to_message.from_user.full_name
            reply_info = f"↩️ Odpowiedź dla **{replied_to_name}**\n"

        # Tłumaczenie
        sender_name = message.from_user.full_name
        original_text = message.text or message.caption or ""
        
        translated = original_text
        if original_text:
            try:
                translated = GoogleTranslator(source='auto', target='pl').translate(original_text)
            except:
                translated = original_text

        caption = f"{reply_info}👤 **{sender_name}** ({source_label}):\n\n{translated}"

        sent_msg = None
        # Przesyłanie mediów lub tekstu
        if message.photo or message.video or message.document or message.audio:
            sent_msg = await message.copy_to(
                chat_id=target_chat,
                message_thread_id=target_topic,
                reply_to_message_id=reply_to_id, # Tutaj bot podpina odpowiedź
                caption=caption,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            sent_msg = await bot.send_message(
                chat_id=target_chat,
                text=caption,
                message_thread_id=target_topic,
                reply_to_message_id=reply_to_id, # Tutaj bot podpina odpowiedź
                parse_mode=ParseMode.MARKDOWN
            )

        # Zapisujemy powiązanie ID wiadomości w pamięci
        if sent_msg:
            msg_mapping[message.message_id] = sent_msg.message_id
            # Czyścimy stare wpisy jeśli słownik jest zbyt duży (limit 1000 wiadomości)
            if len(msg_mapping) > 1000:
                first_key = next(iter(msg_mapping))
                del msg_mapping[first_key]

        logger.info(f"Przesłano wiadomość od {sender_name} (Odpowiedź: {'Tak' if reply_to_id else 'Nie'})")

    except Exception as e:
        logger.error(f"Błąd: {e}")

async def main():
    logger.info("Bot startuje z obsługą odpowiedzi (replies)...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot wyłączony.")
