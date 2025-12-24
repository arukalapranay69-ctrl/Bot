import logging
import requests
import json
import os
import asyncio
import nest_asyncio
import re
import html
import time
import random
from threading import Thread          # <--- Added for Render Fix
from flask import Flask               # <--- Added for Render Fix
from datetime import datetime
from telegram import Update, constants, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from bs4 import BeautifulSoup

# 👇 FIX ASYNC ISSUES
nest_asyncio.apply()

# --- ⚙️ CONFIGURATION ---
# ✅ SCRAPER API KEY (DO NOT CHANGE)
SCRAPER_API_KEY = "848a68ab7a4bbef78ad6a246b7aad98a"

# ✅ YOUR NEW TOKEN
TOKEN = "8515989457:AAFCbRnILjdX2u2ekfbsGURSzQim1DNja0w"
AMAZON_TAG = "pranay0d82-21"
DB_FILE = "tracker.json"
MY_DEALS_CHANNEL = "https://t.me/Grabthelootsandoffers" 

# --- 📝 LOGGING ---
logging.basicConfig(format='%(asctime)s - %(message)s', level=logging.INFO)

# --- 🌐 BACKGROUND WEB SERVER (FIXES RENDER PORT ERROR) ---
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "✅ Bot is Online via ScraperAPI!"

def run_web_server():
    # Render assigns a random PORT. We must listen on it.
    port = int(os.environ.get("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)

# --- 💾 DATABASE MANAGER ---
def load_db():
    if not os.path.exists(DB_FILE): return {}
    try:
        with open(DB_FILE, 'r') as f: 
            data = json.load(f)
            # AUTO-REPAIR: Ensure all items have a status
            dirty = False
            for user_id in data:
                for item in data[user_id]:
                    if 'status' not in item:
                        item['status'] = 'active'
                        dirty = True
            if dirty:
                save_db(data)
            return data
    except: 
        return {}

def save_db(data):
    with open(DB_FILE, 'w') as f: json.dump(data, f)

# --- 🔗 AFFILIATE LINK GENERATOR ---
def create_affiliate_link(url):
    try:
        match = re.search(r'/dp/([A-Z0-9]+)', url)
        if match:
            asin = match.group(1)
            return f"https://www.amazon.in/dp/{asin}?tag={AMAZON_TAG}"
        else:
            clean = url.split("?")[0] if "?" in url else url
            return f"{clean}?tag={AMAZON_TAG}"
    except:
        return f"{url}?tag={AMAZON_TAG}"

# --- 🕵️‍♂️ SCRAPER (WITH SCRAPER API INTEGRATION) ---
def get_product_details(url):
    # This sends the request through the Proxy Key so Amazon thinks you are a real person
    payload = {
        'api_key': SCRAPER_API_KEY, 
        'url': url, 
        'country_code': 'in',   # Forces Indian Amazon
        'device_type': 'desktop',
        'autoparse': 'false'    # We will parse it ourselves using your logic
    }

    try:
        # Request via ScraperAPI (Bypasses Amazon Blocks)
        response = requests.get('http://api.scraperapi.com', params=payload, timeout=60)
        
        soup = BeautifulSoup(response.content, "html.parser")
        
        # Get Title
        title = "Amazon Product"
        possible_titles = [soup.find(id="productTitle"), soup.find("h1"), soup.find("meta", {"name": "title"})]
        for t in possible_titles:
            if t:
                title = t.get("content").strip() if t.name == "meta" else t.get_text(strip=True)
                break
        if len(title) > 50: title = title[:50] + "..."

        # Get Price (Your Logic)
        price = None
        price_whole = soup.find(class_="a-price-whole")
        offscreen = soup.find("span", {"class": "a-offscreen"})
        
        if price_whole:
            raw = price_whole.get_text(strip=True).replace('.', '').replace(',', '')
            try: price = float(raw)
            except: pass
        elif offscreen:
            raw = offscreen.get_text(strip=True).replace('₹', '').replace('$', '').replace(',', '')
            try: price = float(raw)
            except: pass

        if price is None and "Currently unavailable" in response.text:
             print("Product is Out of Stock.")

        return price, title
    except Exception as e:
        print(f"Scraping Error: {e}")
        return None, None

# --- 🤖 TELEGRAM HANDLERS ---

# 1. START COMMAND
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_text = (
        "🎉 Great to see you! Welcome!\n\n"
        "=>I am a Price Tracker & Alert Bot. I can track the price of the products and Out of Stock products.\n\n"
        "=> Just send me the product's URL, then I will notify you when the price is increased or decreased.\n\n"
        "=>Supported Links : Amazon Links Only\n\n"
        "Save Time! Save Money!!\n\n"
        "Click /help to get more help."
    )
    keyboard = [[InlineKeyboardButton("Today's Deals", url=MY_DEALS_CHANNEL)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(msg_text, reply_markup=reply_markup)

# 2. HELP COMMAND
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_text = (
        "Add / Track Product \n\n"
        "- Just send the product url to start tracking the product.\n\n"
        "Stop Tracking \n\n"
        "- click /stop for stop tracking products.\n"
        "- click /stop_{Specific_PID} to stop tracking the specific product.\n\n"
        "Tracking List \n\n"
        "- click /list to get the tracking list as a text message.\n\n"
        "Untracked List \n\n"
        "- click /untracked_list to get the untracked products as a text message.\n\n"
        "       Thanks For Using This Bot"
    )
    await update.message.reply_text(msg_text)

# 3. ADD / TRACK PRODUCT (Process Link)
async def process_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    user_id = str(update.effective_user.id)

    if "amazon" not in url.lower() and "amzn" not in url.lower():
        await update.message.reply_text("⚠️ Supported Links : Amazon Links Only")
        return

    status_msg = await update.message.reply_text("🔎 Tracking price via secure proxy...")
    
    # Run scraping
    price, title = get_product_details(url)
    affiliate_link = create_affiliate_link(url)

    if price:
        db = load_db()
        if user_id not in db: db[user_id] = []
        
        # Check if already exists to prevent duplicates
        # Simple check based on title or URL could be added here
        
        db[user_id].append({
            "title": title, 
            "url": affiliate_link, 
            "price": price, 
            "status": "active"
        })
        save_db(db)

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        safe_title = html.escape(title)
        
        final_msg = (
            "The product has Started Tracking!\n\n\n"
            f"🔥 <a href='{affiliate_link}'>{safe_title}</a>\n\n\n"
            f"Current price : ₹{price}\n\n\n"
            f"<a href='{affiliate_link}'>Click here to open in Amazon</a>\n\n\n"
            f"({current_time})\n\n"
            "😉 I've started tracking this product. Now, you can sit back and relax! "
            "I will send you an alert When the price of this product drops!!\n\n"
            "Click /list to see all the products I am tracking for you 😁"
        )
        
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=status_msg.message_id,
            text=final_msg,
            parse_mode=constants.ParseMode.HTML, 
            disable_web_page_preview=True
        )
    else:
        # If price is None, it might be blocking or invalid link
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=status_msg.message_id,
            text="❌ Could not track. \n\nPossibilities:\n1. Link is invalid.\n2. Product is Out of Stock.\n3. Amazon blocked the bot request."
        )

# 4. TRACKING LIST (/list)
async def view_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = str(update.effective_user.id)
        db = load_db()
        
        if user_id not in db or not db[user_id]:
            await update.message.reply_text("📭 Your list is empty.")
            return
        
        msg = "📋 <b>Tracking List:</b>\n\n"
        count = 0
        for idx, item in enumerate(db[user_id]):
            if item.get('status', 'active') == 'active':
                count += 1
                safe_title = html.escape(item.get('title', 'Unknown Item'))
                price = item.get('price', 'N/A')
                link = item.get('url', '#')
                
                msg += (
                    f"<b>{idx+1}.</b> {safe_title}\n"
                    f"   💰 Price: ₹{price}\n"
                    f"   🔗 <a href='{link}'>Link</a>\n\n"
                )
        
        if count == 0:
            msg = "📭 You are not tracking any products currently."
            
        await update.message.reply_text(msg, parse_mode=constants.ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        print(f"Error in list: {e}")
        await update.message.reply_text("⚠️ An error occurred while fetching your list.")

# 5. STOP MENU (/stop)
async def stop_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = str(update.effective_user.id)
        db = load_db()
        
        msg = "🛑 <b>Select a product to Stop Tracking:</b>\n\n"
        count = 0
        
        if user_id in db:
            for idx, item in enumerate(db[user_id]):
                if item.get('status', 'active') == 'active':
                    count += 1
                    safe_title = html.escape(item.get('title', 'Item'))
                    msg += f"<b>{idx+1}.</b> {safe_title} \n   ❌ Stop: /stop_{idx+1}\n\n"

        if count == 0:
            msg = "🤷‍♂️ You are not tracking anything right now."

        await update.message.reply_text(msg, parse_mode=constants.ParseMode.HTML)
    except Exception as e:
        print(f"Error in stop menu: {e}")
        await update.message.reply_text("⚠️ Error loading stop menu.")

# 6. UNTRACKED LIST (/untracked_list)
async def view_untracked_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = str(update.effective_user.id)
        db = load_db()
        
        if user_id not in db:
            await update.message.reply_text("📭 No data found.")
            return

        msg = "🛑 <b>Untracked List:</b>\n\n"
        count = 0
        for idx, item in enumerate(db[user_id]):
            if item.get('status') == 'untracked':
                count += 1
                safe_title = html.escape(item.get('title', 'Item'))
                msg += (
                    f"<b>{idx+1}.</b> {safe_title}\n"
                    f"   🔙 Click to Retrack: /retrack_{idx+1}\n\n"
                )
        
        if count == 0:
            msg = "✅ You don't have any untracked products."

        await update.message.reply_text(msg, parse_mode=constants.ParseMode.HTML)
    except Exception as e:
        print(f"Error in untracked list: {e}")
        await update.message.reply_text("⚠️ Error loading untracked list.")

# 7. SPECIFIC STOP HANDLER (/stop_ID)
async def stop_specific(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    query = update.message.text 
    
    try:
        idx = int(query.split("_")[1]) - 1
        db = load_db()
        
        if user_id in db and 0 <= idx < len(db[user_id]):
            db[user_id][idx]['status'] = 'untracked'
            save_db(db)
            
            product_name = html.escape(db[user_id][idx]['title'])
            await update.message.reply_text(f"🛑 Stopped tracking: <b>{product_name}</b>\n\nView in /untracked_list", parse_mode=constants.ParseMode.HTML)
        else:
            await update.message.reply_text("❌ Product not found.")
    except Exception as e:
        await update.message.reply_text("❌ Error processing request.")

# 8. RETRACK HANDLER (/retrack_ID)
async def retrack_specific(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    query = update.message.text
    
    try:
        idx = int(query.split("_")[1]) - 1
        db = load_db()
        
        if user_id in db and 0 <= idx < len(db[user_id]):
            db[user_id][idx]['status'] = 'active'
            save_db(db)
            
            product_name = html.escape(db[user_id][idx]['title'])
            await update.message.reply_text(f"✅ tracking resumed for: <b>{product_name}</b>", parse_mode=constants.ParseMode.HTML)
        else:
            await update.message.reply_text("❌ Product not found.")
    except Exception as e:
        await update.message.reply_text("❌ Error processing request.")


# --- 🚀 MAIN ---
if __name__ == '__main__':
    print("Bot is starting...")
    
    # ✅ 1. START BACKGROUND SERVER (CRITICAL FOR RENDER)
    t = Thread(target=run_web_server)
    t.daemon = True
    t.start()
    
    # ✅ 2. START TELEGRAM BOT
    app = ApplicationBuilder().token(TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("list", view_list))
    app.add_handler(CommandHandler("untracked_list", view_untracked_list))
    app.add_handler(CommandHandler("stop", stop_menu))
    
    # Dynamic handlers 
    app.add_handler(MessageHandler(filters.Regex(r"^/stop_\d+$"), stop_specific))
    app.add_handler(MessageHandler(filters.Regex(r"^/retrack_\d+$"), retrack_specific))
    
    # Message Handler for Links (Must be last)
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), process_link))

    print("✅ System Ready: Bot + Web Server are running.")
    app.run_polling()
