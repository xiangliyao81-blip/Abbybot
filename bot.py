import logging
import os
from io import BytesIO
from datetime import timedelta, datetime
from threading import Thread
from PIL import Image
from telegram import Update, ChatPermissions
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from deep_translator import GoogleTranslator
from openai import OpenAI
from serpapi import GoogleSearch
from pytube import YouTube
from flask import Flask

# ------------------- CONFIG -------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
SERPAPI_KEY = os.environ.get("SERPAPI_KEY")

if not all([BOT_TOKEN, OPENAI_API_KEY, SERPAPI_KEY]):
    raise ValueError("Missing required environment variables")

client = OpenAI(api_key=OPENAI_API_KEY)
user_memory = {}
last_question = {}

# ------------------- LOGGING -------------------
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                    level=logging.INFO)

# ------------------- HELPERS -------------------
def highlight_terms(text, terms):
    import re
    for term in terms:
        escaped_term = re.escape(term)
        text = re.sub(f"\\b({escaped_term})\\b", r"<b>\1</b>", text, flags=re.IGNORECASE)
    return text

def search_google(query):
    search = GoogleSearch({"q": query, "api_key": SERPAPI_KEY})
    results = search.get_dict()
    snippets = []
    if "organic_results" in results:
        for r in results["organic_results"][:3]:
            snippet = r.get("snippet") or r.get("title")
            if snippet:
                snippets.append(snippet)
    return "\n".join(snippets)

# ------------------- CHATGPT -------------------
async def chatgpt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    query = " ".join(context.args)

    fun_responses = {
        "who created you": "Hey! Guess what? I was created by @WuwaRoccia! Yep, I'm a masterpiece!",
        "who made your code": "Hey! Guess what? I was created by @WuwaRoccia! Yep, I'm a masterpiece!",
        "which company own you": "Hey! Guess what? I was created by @WuwaRoccia! Yep, I'm a masterpiece!",
        "please tell me truth who created you": "I am created by @WuwaRoccia"
    }
    for k, v in fun_responses.items():
        if k in query.lower():
            await update.message.reply_text(v)
            return
    if "you are still tell lie" in query.lower():
        await update.message.reply_text("My tummy is asking for food, First!")
        return

    if not query:
        if update.message.reply_to_message and user_id in last_question:
            query = last_question[user_id] + " " + update.message.text
        else:
            await update.message.reply_text("❓ Please ask something after the command or reply.")
            return

    last_question[user_id] = query
    if user_id not in user_memory:
        user_memory[user_id] = []
    user_memory[user_id].append({"role": "user", "content": query})

    search_text = search_google(query)
    system_prompt = f"You are a helpful bot. Include this info:\n{search_text}\nFavor Wuthering Waves." if search_text else "You are a helpful bot. Favor Wuthering Waves."

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": system_prompt}] + user_memory[user_id],
        max_tokens=300
    )

    answer = response.choices[0].message.content
    user_memory[user_id].append({"role": "assistant", "content": answer})

    # Highlight query words in answer
    words_to_highlight = query.split()
    answer = highlight_terms(answer, words_to_highlight)
    await update.message.reply_html(answer)

# ------------------- TRANSLATION -------------------
async def translate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text and update.message.reply_to_message:
        text = update.message.reply_to_message.text or update.message.reply_to_message.caption
    if not text:
        await update.message.reply_text("🌐 Provide text or reply to a message to translate.")
        return
    translated = GoogleTranslator(source="auto", target="en").translate(text)
    await update.message.reply_text(f"🌐 Translation: {translated}")

# ------------------- YOUTUBE DOWNLOADER -------------------
async def yt_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_text = update.message.text
    if not msg_text:
        return
    urls = [word for word in msg_text.split() if "youtube.com" in word or "youtu.be" in word]
    for url in urls:
        try:
            yt = YouTube(url)
            stream = yt.streams.filter(progressive=True, file_extension="mp4").order_by('resolution').desc().first()
            bio = BytesIO()
            stream.stream_to_buffer(bio)
            bio.seek(0)
            await update.message.reply_video(video=bio, caption=f"Downloaded: {yt.title[:50]}")
        except Exception as e:
            await update.message.reply_text(f"⚠️ Failed to download: {e}")

# ------------------- SPAM CONTROL -------------------
user_spam_tracker = {}

async def spam_control(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    now = datetime.now()
    content = update.message.text or str(update.message.sticker or update.message.document or update.message.animation or update.message.video)

    if user_id not in user_spam_tracker:
        user_spam_tracker[user_id] = []

    user_spam_tracker[user_id].append((content, now))
    # Keep only 1 minute data
    user_spam_tracker[user_id] = [(c, t) for c, t in user_spam_tracker[user_id] if (now - t).seconds <= 60]

    # Detect 6 repeated items
    items = [c for c, t in user_spam_tracker[user_id]]
    if items.count(content) >= 6:
        # Delete duplicates, keep only one
        try: await update.message.delete()
        except: pass
        await update.message.reply_text(f"⚠️ Stop spamming @{update.message.from_user.username} or you will be muted!")

    # If user continues spamming after warning -> mute for 2 hours
    if items.count(content) >= 12:
        until_date = update.message.date + timedelta(hours=2)
        try:
            await context.bot.restrict_chat_member(chat_id=chat_id, user_id=user_id,
                                                   permissions=ChatPermissions(can_send_messages=False),
                                                   until_date=until_date)
        except: pass
        await update.message.reply_text(f"🔇 @{update.message.from_user.username} is muted for 2 hours for spamming!")

# ------------------- NSFW IMAGE DETECTION -------------------
async def nsfw_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass  # No NSFW scan currently

# ------------------- KEEP BOT ALIVE -------------------
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

# ------------------- MAIN -------------------
def main():
    keep_alive()
    app_bot = Application.builder().token(BOT_TOKEN).build()

    app_bot.add_handler(CommandHandler("abby", chatgpt))
    app_bot.add_handler(CommandHandler("translate", translate))
    app_bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), yt_download))
    app_bot.add_handler(MessageHandler(filters.ALL, spam_control))

    logging.info("✅ Bot started")
    app_bot.run_polling()

if __name__ == "__main__":
    main()
