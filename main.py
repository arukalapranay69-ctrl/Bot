import logging
import requests
import json
import os
import asyncio
import nest_asyncio
import re
import html
from threading import Thread
from flask import Flask
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters
)
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
from urllib.parse import quote

# ================== ASYNC FIX ==================
nest_asyncio.apply()

# ================== CONFIG ==================
TOKEN = "PASTE_TELEGRAM_TOKEN"
SCRAPER_API_KEY = "PASTE_SCRAPERAPI_KEY"

AMAZON_TAG = "yourtag-21"
DB_FILE = "tracker.json"
CHECK_INTERVAL = 21600  # 6 hours

# Gmail
GMAIL_USER = "yourgmail@gmail.com"
GMAIL_APP_PASSWORD = "gmail_app_password"

# ================== LOGGING ==================
logging.basicConfig(level=logging.INFO)

# ================== KEEP-ALIVE SERVER ==================
app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Bot Alive"

def run_web():
    app_web.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

# ================== DATABASE ==================
def load_db():
    if not os.path.exists(DB_FILE):
        return {}
    with open(DB_FILE, "r") as f:
        return json.load(f)

def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f)

# ================== HELPERS ==================
def is_valid_email(email):
    return re.match(r"[^@]+@[^@]+\.[^@]+", email)

def should_ask_email(user):
    last = user.get("last_email_ask")
    if not last:
        return True
    return datetime.now() - datetime.fromisoformat(last) > timedelta(days=30)

def affiliate_link(url):
    m = re.search(r"/dp/([A-Z0-9]{10})", url)
    if m:
        return f"https://www.amazon.in/dp/{m.group(1)}?tag={AMAZON_TAG}"
    return url.split("?")[0] + f"?tag={AMAZON_TAG}"

def whatsapp_share(title, price, link):
    text = f"🔥 Price Drop!\n{title}\nNow ₹{price}\n{link}"
    return f"https://wa.me/?text={quote(text)}"

def send_email(to_email, title, old_price, new_price, link):
    body = f"""
Price Drop Alert!

{title}

Old Price: ₹{old_price}
New Price: ₹{new_price}

Buy Now:
{link}
"""
    msg = MIMEText(body)
    msg["Subject"] = "Amazon Price Drop Alert"
    msg["From"] = GMAIL_USER
    msg["To"] = to_email

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.send_message(msg)

# ================== SCRAPER ==================
def get_product_details(url):
    payload = {
        "api_key": SCRAPER_API_KEY,
        "url": url,
        "country_code": "in",
        "render": "true"
    }
    try:
        r = requests.get("http://api.scraperapi.com", params=payload, timeout=60)
        soup = BeautifulSoup(r.content, "html.parser")

        title_tag = soup.find(id="productTitle")
        price_tag = soup.find("span", class_="a-offscreen")

        if not price_tag:
            return None, None

        title = title_tag.get_text(strip=True) if title_tag else "Amazon Product"
        price = float(price_tag.text.replace("₹", "").replace(",", ""))

        return price, title
    except:
        return None, None

# ================== PRICE CHECK ==================
async def check_prices(bot):
    db = load_db()

    for user_id, user in db.items():
        email = user.get("email")

        for item in user["items"]:
            if item["status"] != "active":
                continue

            new_price, _ = get_product_details(item["url"])
            if not new_price:
                continue

            old_price = item["price"]
            if new_price < old_price:
                item["price"] = new_price
                save_db(db)

                wa = whatsapp_share(item["title"], new_price, item["url"])
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📤 Share on WhatsApp", url=wa)]
                ])

                msg = (
                    f"📉 <b>Price Dropped!</b>\n\n"
                    f"{html.escape(item['title'])}\n"
                    f"Old: ₹{old_price}\n"
                    f"New: ₹{new_price}\n\n"
                    f"<a href='{item['url']}'>Buy Now</a>"
                )

                await bot.send_message(
                    chat_id=user_id,
                    text=msg,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )

                if email:
                    send_email(email, item["title"], old_price, new_price, item["url"])

# ================== AUTO LOOP ==================
async def auto_loop(app):
    await asyncio.sleep(10)
    while True:
        await check_prices(app.bot)
        await asyncio.sleep(CHECK_INTERVAL)

# ================== TELEGRAM ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send Amazon product link to start tracking."
    )

# ---------- EMAIL CAPTURE ----------
async def capture_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "pending_url" not in context.user_data:
        return

    email = update.message.text.strip()
    if not is_valid_email(email):
        await update.message.reply_text("❌ Invalid email. Try again.")
        return

    user_id = str(update.effective_user.id)
    db = load_db()
    db[user_id]["email"] = email
    save_db(db)

    url = context.user_data.pop("pending_url")
    await add_item(user_id, url, update)

# ---------- ADD ITEM ----------
async def add_item(user_id, url, update):
    price, title = get_product_details(url)
    if not price:
        await update.message.reply_text("❌ Failed to fetch product.")
        return

    db = load_db()
    db[user_id]["items"].append({
        "title": title,
        "url": affiliate_link(url),
        "price": price,
        "status": "active"
    })
    save_db(db)

    await update.message.reply_text(
        f"✅ Tracking started:\n{title}\n₹{price}"
    )

# ---------- PROCESS LINK ----------
async def process_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if "amazon" not in url.lower():
        return

    user_id = str(update.effective_user.id)
    db = load_db()

    if user_id not in db:
        db[user_id] = {
            "email": None,
            "last_email_ask": None,
            "items": []
        }

    user = db[user_id]

    if should_ask_email(user):
        user["last_email_ask"] = datetime.now().isoformat()
        save_db(db)
        context.user_data["pending_url"] = url
        await update.message.reply_text("📧 Send your email for price-drop alerts.")
        return

    await add_item(user_id, url, update)

# ================== MAIN ==================
if __name__ == "__main__":
    Thread(target=run_web, daemon=True).start()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("@"), capture_email))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), process_link))

    asyncio.get_event_loop().create_task(auto_loop(app))

    print("✅ Amazon Tracker Bot Running")
    app.run_polling()
