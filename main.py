import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
from deep_translator import GoogleTranslator

# --- KONFIGURACJA ---
# Wprowadź swój token bota
BOT_TOKEN = '8567902133:AAGBgYX0b4hdzbt0KOowa-gHDAqGwblboVE'

# ID grupy głównej (z Twoich screenów wynika, że obie podgrupy są w tej samej grupie)
GROUP_A_ID = -1003676480681  
GROUP_B_ID = -1003676480681  

# ID tematów (podgrup)
TOPIC_A_ID = 27893   # Translator
TOPIC_B_ID = 0       # General (Główny) - w kodzie obsłużymy go jako 0 lub None

# Słownik do mapowania ID wiadomości (aby działały odpowiedzi/replies)
# W wersji produkcyjnej warto użyć bazy danych, tutaj pamięć RAM (limit 2000 wiadomości)
msg_mapping = {}

# Konfiguracja logowania
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Inicjalizacja bota i dispatchera
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def smart_translate(text):
    """
    Automatycznie wykrywa język i tłumaczy:
    Polski -> Angielski
    Inny (Angielski) -> Polski
    """
    try:
        # Używamy GoogleTranslator do detekcji i tłumaczenia
        translator = GoogleTranslator(source='auto', target='en')
        detected_lang = translator.detect_language(text)
        
        if detected_lang == 'pl':
            return GoogleTranslator(source='pl', target='en').translate(text)
        else:
            return GoogleTranslator(source='en', target='pl').translate(text)
    except Exception as e:
        logger.error(f"Błąd podczas tłumaczenia: {e}")
        return text

# --- KOMENDA DIAGNOSTYCZNA /id ---
@dp.message(Command("id"))
async def get_ids(message: types.Message):
    """Wyświetla ID czatu i wątku, aby ułatwić konfigurację"""
    t_id = message.message_thread_id if message.message_thread_id is not None else 0
    info = (
        f"📊 **Dane diagnostyczne:**\n"
        f"--- --- --- --- ---\n"
        f"🆔 **Chat ID:** `{message.chat.id}`\n"
        f"🧵 **Topic ID:** `{t_id}`\n"
        f"--- --- --- --- ---\n"
        f"Upewnij się, że te dane zgadzają się z sekcją KONFIGURACJA w kodzie."
    )
    await message.reply(info, parse_mode=ParseMode.MARKDOWN)

# --- OBSŁUGA MOSTU I TŁUMACZENIA ---
@dp.message()
async def bridge_handler(message: types.Message):
    # Ignoruj boty i komendy systemowe
    if message.from_user.is_bot or (message.text and message.text.startswith("/")):
        return

    try:
        # Normalizacja ID wątku (None -> 0 dla tematu głównego)
        current_topic = message.message_thread_id if message.message_thread_id is not None else 0

        # Wykrywanie kierunku przesyłu
        target_chat = None
        target_topic = None
        source_name = ""

        # Kierunek: Z Translator do General
        if message.chat.id == GROUP_A_ID and current_topic == TOPIC_A_ID:
            target_chat = GROUP_B_ID
            target_topic = TOPIC_B_ID
            source_name = "Translator"
        
        # Kierunek: Z General do Translator
        elif message.chat.id == GROUP_B_ID and current_topic == TOPIC_B_ID:
            target_chat = GROUP_A_ID
            target_topic = TOPIC_A_ID
            source_name = "General"

        # Jeśli wiadomość nie pochodzi z obserwowanych wątków, wyjdź
        if target_chat is None:
            return

        # Logika odpowiedzi (Reply)
        reply_to_id = None
        reply_prefix = ""
        
        if message.reply_to_message and message.reply_to_message.message_id != message.message_thread_id:
            # Szukamy czy wiadomość, na którą odpowiadamy, ma swój odpowiednik w drugiej grupie
            reply_to_id = msg_mapping.get(message.reply_to_message.message_id)
            replied_user = message.reply_to_message.from_user.full_name
            reply_prefix = f"↩️ Odpowiedź dla **{replied_user}**\n"

        # Tłumaczenie treści (tekst lub podpis pod zdjęciem)
        original_content = message.text or message.caption or ""
        translated_text = smart_translate(original_content) if original_content else ""

        # Składanie finalnej wiadomości
        sender = message.from_user.full_name
        final_text = f"{reply_prefix}👤 **{sender}** ({source_name}):\n\n{translated_text}"

        # Przygotowanie parametrów wysyłki
        # Jeśli target_topic to 0, wysyłamy jako None (standard Telegrama dla General)
        thread_id_to_send = target_topic if target_topic != 0 else None

        sent_msg = None
        # Przesyłanie mediów lub tekstu
        if any([message.photo, message.video, message.document, message.audio, message.voice]):
            sent_msg = await message.copy_to(
                chat_id=target_chat,
                message_thread_id=thread_id_to_send,
                reply_to_message_id=reply_to_id,
                caption=final_text,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            sent_msg = await bot.send_message(
                chat_id=target_chat,
                text=final_text,
                message_thread_id=thread_id_to_send,
                reply_to_message_id=reply_to_id,
                parse_mode=ParseMode.MARKDOWN
            )

        # Mapowanie ID w obie strony dla przyszłych odpowiedzi
        if sent_msg:
            msg_mapping[message.message_id] = sent_msg.message_id
            msg_mapping[sent_msg.message_id] = message.message_id
            
            # Zapobieganie przepełnieniu pamięci (utrzymujemy ostatnie 2000 powiązań)
            if len(msg_mapping) > 4000: # 2000 par = 4000 wpisów
                # Usuwamy najstarsze wpisy
                keys = list(msg_mapping.keys())
                for i in range(200):
                    msg_mapping.pop(keys[i], None)

    except Exception as e:
        logger.error(f"Błąd podczas procesowania wiadomości: {e}")

async def main():
    logger.info("Bot uruchomiony. Most między Translator (27893) a General (0) jest aktywny.")
    # Czyścimy zaległe wiadomości przed startem
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot został wyłączony.")
