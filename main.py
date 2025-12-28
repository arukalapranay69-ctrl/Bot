import os
import random
import asyncio
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from pymongo import MongoClient

# ===================== CONFIG =====================

TOKEN = os.getenv("8515989457:AAFGO1IYdB9hC7HSVfZyJNviWYN7Ao5df60")
MONGO_URI = os.getenv("MONGO_URI = mongodb+srv://admin:Pranay123@cluster0.tr5neeu.mongodb.net/pricebot?retryWrites=true&w=majority")

AMAZON_TAG = "pranay0d82-21"
CHECK_INTERVAL = 43200  # 12 hours

SCRAPER_KEYS = [
    "3d079c037f5e3b922c8324278e4f0544",
    "c17f6fb88e699a1f6986b1322e5e8a14",
    "aa4031b4e81f5d3cd7092926488242a0",
    "c81395d8fed816080bc3daee37249cbe",
    "68abca8be903485bc1a37f1588266763",
    "22439040fe5a99858087238649f210af",
    "52f794730dc2d2c23f8d9e71ff32f55d",
    "d615f37b1652ca551cf92e0148ab6112",
    "68afe9b4a872ab3199049b126f45039f",
    "97cc1948633953163f549939b9aed321",
    "a56d97c8307687fb114fda295f7b7606"
]

HEADERS = [
    {"User-Agent": "Mozilla/5.0"},
    {"User-Agent": "Chrome/120.0"},
    {"User-Agent": "Safari/537.36"}
]

# ===================== MONGODB =====================

client = MongoClient(MONGO_URI)
db = client["pricebot"]

users_col = db["users"]
trackers_col = db["trackers"]
referrals_col = db["referrals"]
meta_col = db["meta"]

if not meta_col.find_one({"_id": "scraper"}):
    meta_col.insert_one({"_id": "scraper", "index": 0})

# ===================== SCRAPER ROTATION =====================

def get_scraper_key():
    meta = meta_col.find_one({"_id": "scraper"})
    index = meta["index"]

    key = SCRAPER_KEYS[index]
    index = (index + 1) % len(SCRAPER_KEYS)

    meta_col.update_one(
        {"_id": "scraper"},
        {"$set": {"index": index}}
    )
    return key

def fetch_page(url):
    key = get_scraper_key()
    proxy_url = f"http://api.scraperapi.com?api_key={key}&url={url}"

    try:
        r = requests.get(
            proxy_url,
            headers=random.choice(HEADERS),
            timeout=20
        )
        if r.status_code == 200:
            return r.text
    except:
        pass
    return None

# ===================== PRICE PARSER =====================

def parse_amazon(html):
    soup = BeautifulSoup(html, "html.parser")
    price = soup.select_one(".a-price-whole")
    if price:
        return float(price.text.replace(",", "").strip())
    return None

# ===================== BOT COMMANDS =====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    user = users_col.find_one({"_id": uid})

    if not user:
        referred_by = None

        if context.args and context.args[0].startswith("ref"):
            ref = context.args[0].replace("ref", "")
            if ref != uid and users_col.find_one({"_id": ref}):
                referred_by = ref
                referrals_col.update_one(
                    {"_id": ref},
                    {"$addToSet": {"users": uid}},
                    upsert=True
                )

        users_col.insert_one({
            "_id": uid,
            "referred_by": referred_by
        })

    await update.message.reply_text(
        "✅ Bot is alive!\n\n"
        "/track <amazon_link>\n"
        "/list\n"
        "/untracked_list\n"
        "/stop <number>\n"
        "/help"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Price Tracker Bot Help*\n\n"
        "/start – Check bot status\n"
        "/track <link> – Track Amazon product\n"
        "/list – Active trackers\n"
        "/untracked_list – Disabled trackers\n"
        "/stop <id> – Stop tracking\n"
        "/help – Help message",
        parse_mode="Markdown"
    )

async def track(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("❌ Send product link.")

    url = context.args[0]
    if "amazon" not in url:
        return await update.message.reply_text("⚠️ Only Amazon supported (stable).")

    html = fetch_page(url)
    if not html:
        return await update.message.reply_text("❌ Failed to fetch product.")

    price = parse_amazon(html)
    if not price:
        return await update.message.reply_text("❌ Price not found.")

    trackers_col.insert_one({
        "user": update.effective_user.id,
        "url": url,
        "last_price": price,
        "active": True,
        "fail_count": 0
    })

    await update.message.reply_text(f"📉 Tracking started at ₹{price}")

async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    trackers = trackers_col.find({"user": uid, "active": True})

    msg = "📦 *Your Active Trackers*\n\n"
    found = False

    for i, t in enumerate(trackers, start=1):
        found = True
        msg += f"{i}. ₹{t['last_price']}\n{t['url']}\n\n"

    if not found:
        msg = "❌ No active trackers."

    await update.message.reply_text(msg, parse_mode="Markdown")

async def untracked_list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    trackers = trackers_col.find({"user": uid, "active": False})

    msg = "⚠️ *Untracked Products*\n\n"
    found = False

    for i, t in enumerate(trackers, start=1):
        found = True
        msg += f"{i}. Last price: ₹{t['last_price']}\n{t['url']}\n\n"

    if not found:
        msg = "✅ No untracked products."

    await update.message.reply_text(msg, parse_mode="Markdown")

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if not context.args:
        return await update.message.reply_text("❌ Usage: /stop <number>")

    try:
        index = int(context.args[0]) - 1
    except:
        return await update.message.reply_text("❌ Invalid number.")

    trackers = list(trackers_col.find({"user": uid, "active": True}))

    if index < 0 or index >= len(trackers):
        return await update.message.reply_text("❌ Tracker not found.")

    trackers_col.update_one(
        {"_id": trackers[index]["_id"]},
        {"$set": {"active": False}}
    )

    await update.message.reply_text("🛑 Tracking stopped.")

# ===================== PRICE CHECK LOOP =====================

async def price_checker(app):
    while True:
        for t in trackers_col.find({"active": True}):
            html = fetch_page(t["url"])

            if not html:
                trackers_col.update_one(
                    {"_id": t["_id"]},
                    {"$inc": {"fail_count": 1}}
                )
                if t["fail_count"] >= 3:
                    trackers_col.update_one(
                        {"_id": t["_id"]},
                        {"$set": {"active": False}}
                    )
                continue

            new_price = parse_amazon(html)
            if new_price and new_price < t["last_price"]:
                await app.bot.send_message(
                    chat_id=t["user"],
                    text=(
                        "🔥 *PRICE DROP ALERT*\n\n"
                        f"Old: ₹{t['last_price']}\n"
                        f"New: ₹{new_price}"
                    ),
                    parse_mode="Markdown"
                )
                trackers_col.update_one(
                    {"_id": t["_id"]},
                    {"$set": {"last_price": new_price, "fail_count": 0}}
                )

        await asyncio.sleep(CHECK_INTERVAL)

# ===================== MAIN =====================

async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("track", track))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("untracked_list", untracked_list_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))

    asyncio.create_task(price_checker(app))
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
