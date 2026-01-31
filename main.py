import asyncio
import logging
import re
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
    """Przesyłanie wiadomości z poprawną obsługą odpowiedzi (replies)"""
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

        # --- LOGIKA ODPOWIEDZI (REPLY) ---
        reply_to_id = None
        reply_info = ""
        
        if message.reply_to_message:
            orig_reply_id = message.reply_to_message.message_id
            # Szukamy ID wiadomości w grupie docelowej
            reply_to_id = msg_mapping.get(orig_reply_id)
            
            # Pobieranie imienia osoby, której odpowiadamy
            replied_msg = message.reply_to_message
            bot_info = await bot.get_me()
            
            # Jeśli odpowiadamy na wiadomość bota, wyciągamy imię z treści (między gwiazdkami)
            if replied_msg.from_user.id == bot_info.id:
                content = replied_msg.text or replied_msg.caption or ""
                match = re.search(r"\*\*([^\*]+)\*\*", content)
                replied_to_name = match.group(1) if match else "Użytkownik"
            else:
                replied_to_name = replied_msg.from_user.full_name
                
            reply_info = f"↩️ Odpowiedź dla **{replied_to_name}**\n"

        # --- TŁUMACZENIE I TREŚĆ ---
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
                reply_to_message_id=reply_to_id,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            sent_msg = await bot.send_message(
                chat_id=target_chat,
                text=caption,
                message_thread_id=target_topic,
                reply_to_message_id=reply_to_id,
                parse_mode=ParseMode.MARKDOWN
            )

        # --- ZAPISYWANIE POWIĄZANIA (OBIE STRONY) ---
        if sent_msg:
            # Kluczowe: mapujemy ID w obie strony, żeby odpowiedzi działały płynnie
            msg_mapping[message.message_id] = sent_msg.message_id
            msg_mapping[sent_msg.message_id] = message.message_id
            
            # Czyszczenie pamięci (limit 2000 wpisów, bo mapujemy podwójnie)
            if len(msg_mapping) > 2000:
                for _ in range(10):
                    first_key = next(iter(msg_mapping))
                    del msg_mapping[first_key]

        logger.info(f"Przesłano od {sender_name}. Powiązanie: {message.message_id} <-> {sent_msg.message_id if sent_msg else 'None'}")

    except Exception as e:
        logger.error(f"Błąd: {e}")

async def main():
    logger.info("Bot startuje z poprawioną obsługą odpowiedzi...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot wyłączony.")
