import logging
import os
import pytz
import apscheduler.schedulers.base
from collections import OrderedDict
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from telegram.constants import ParseMode
from deep_translator import GoogleTranslator

# Patch dla Windowsa (bezpieczny na Linuxie)
def fixed_astimezone(obj): return pytz.utc
apscheduler.schedulers.base.astimezone = fixed_astimezone
os.environ['TZ'] = 'UTC'

# POBIERANIE TOKENA Z SYSTEMU (KOYEB SECRETS)
TOKEN = os.getenv('BOT_TOKEN') 
GROUP_ID = -1003537210812
TOPIC_POLSKI = None
TOPIC_INNY = 4925

BRIDGE = {
    TOPIC_POLSKI: {"target": TOPIC_INNY, "lang": "id"},
    TOPIC_INNY:   {"target": TOPIC_POLSKI, "lang": "pl"}
}

msg_map = OrderedDict()
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

async def handle_bridge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or update.message.from_user.is_bot: return
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id
    if chat_id != GROUP_ID or thread_id not in BRIDGE: return
    
    dest = BRIDGE[thread_id]
    user_name = update.message.from_user.first_name or "Użytkownik"
    text = update.message.text or update.message.caption
    if not text: return

    # Logika Reply (Odpowiedzi)
    reply_to_id = msg_map.get(update.message.reply_to_message.message_id) if update.message.reply_to_message else None

    try:
        translated = GoogleTranslator(source='auto', target=dest["lang"]).translate(text)
        final_msg = f"**{user_name}**: {translated}"
        
        if update.message.photo:
            sent_msg = await context.bot.send_photo(chat_id=GROUP_ID, message_thread_id=dest["target"],
                photo=update.message.photo[-1].file_id, caption=final_msg,
                parse_mode=ParseMode.MARKDOWN, reply_to_message_id=reply_to_id)
        else:
            sent_msg = await context.bot.send_message(chat_id=GROUP_ID, message_thread_id=dest["target"],
                text=final_msg, parse_mode=ParseMode.MARKDOWN, reply_to_message_id=reply_to_id)
        
        if sent_msg:
            msg_map[update.message.message_id] = sent_msg.message_id
            if len(msg_map) > 1000: msg_map.popitem(last=False)
    except Exception as e:
        logging.error(f"Błąd: {e}")

if __name__ == '__main__':
    if not TOKEN:
        print("BŁĄD: Nie znaleziono zmiennej BOT_TOKEN!")
    else:
        app = ApplicationBuilder().token(TOKEN).job_queue(None).build()
        app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & (~filters.COMMAND), handle_bridge))
        app.run_polling()
