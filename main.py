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
from threading import Thread
from flask import Flask
from datetime import datetime
from telegram import Update, constants, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from bs4 import BeautifulSoup

  FIX ASYNC ISSUES

nest_asyncio.apply()

--- ⚙️ CONFIGURATION ---

 KEYS

SCRAPER_API_KEY = "a56d97c8307687fb114fda295f7b7606"
TOKEN = "8515989457:AAHJw4jBl8W_IJezX_TEWPya7lp1GUatPFs"
ADMIN_ID = "7157243817"

AMAZON_TAG = "pranay0d82-21"
DB_FILE = "tracker.json"
MY_DEALS_CHANNEL = "https://t.me/Grabthelootsandoffers"

 CHECK INTERVAL (6 Hours)

CHECK_INTERVAL = 21600

--- LOGGING ---

logging.basicConfig(format='%(asctime)s - %(message)s', level=logging.INFO)

---  BACKGROUND WEB SERVER ---

app_web = Flask(name)

@app_web.route('/')
def home(): return " Bot is Online via ScraperAPI!"

def run_web_server():
port = int(os.environ.get("PORT", 10000))
app_web.run(host="0.0.0.0", port=port)

--- 💾 DATABASE MANAGER ---

def load_db():
if not os.path.exists(DB_FILE): return {}
try:
with open(DB_FILE, 'r') as f: return json.load(f)
except: return {}

def save_db(data):
with open(DB_FILE, 'w') as f: json.dump(data, f)

---  HELPERS ---

def create_affiliate_link(url):
try:
match = re.search(r'/dp/([A-Z0-9]+)', url)
if match:
return f"https://www.amazon.in/dp/{match.group(1)}?tag={AMAZON_TAG}"
clean = url.split("?")[0]
return f"{clean}?tag={AMAZON_TAG}"
except: return f"{url}?tag={AMAZON_TAG}"

def get_price_history_link(url):
match = re.search(r'/dp/([A-Z0-9]{10})', url)
if match: return f"https://pricehistory.app/p/{match.group(1)}"
return "https://pricehistory.app/"

---  SMART SCRAPER ---

def get_product_details(url):
payload = {
'api_key': SCRAPER_API_KEY,
'url': url,
'country_code': 'in',
'device_type': 'desktop',
'autoparse': 'false',
'render': 'true' #  Needed for Coupons
}

try:  
    response = requests.get('http://api.scraperapi.com', params=payload, timeout=60)  
    soup = BeautifulSoup(response.content, "html.parser")  
      
    # 1. Title  
    title = "Amazon Product"  
    possible_titles = [soup.find(id="productTitle"), soup.find("h1")]  
    for t in possible_titles:  
        if t:  
            title = t.get_text(strip=True)  
            break  
    if len(title) > 50: title = title[:50] + "..."  

    # 2. Main Price  
    price = None  
    price_whole = soup.find(class_="a-price-whole")  
    offscreen = soup.find("span", {"class": "a-offscreen"})  
      
    if price_whole:  
        raw = price_whole.get_text(strip=True).replace('.', '').replace(',', '')  
        price = float(raw)  
    elif offscreen:  
        raw = offscreen.get_text(strip=True).replace('₹', '').replace(',', '')  
        price = float(raw)  

    # 3. Coupon Hunter  
    coupon_discount = 0  
    try:  
        coupon_tags = soup.find_all("span", string=re.compile(r"Apply .* coupon"))  
        if not coupon_tags:  
            coupon_tags = soup.find_all("label", string=re.compile(r"Apply .* coupon"))  
          
        for tag in coupon_tags:  
            text = tag.get_text(strip=True)  
            amount_match = re.search(r'₹\s?([0-9,]+)', text)  
            if amount_match:  
                coupon_discount = float(amount_match.group(1).replace(',', ''))  
                break  
    except: pass  

    # 4. Final Calc  
    final_price = price  
    if price and coupon_discount > 0:  
        final_price = price - coupon_discount  

    return final_price, price, coupon_discount, title  

except Exception as e:  
    print(f"Scraping Error: {e}")  
    return None, None, 0, None

---  CHECKING LOGIC (Shared) ---

async def check_prices_logic(bot):
print("🔄 Running Price Check...")
db = load_db()

for user_id in db:  
    for idx, item in enumerate(db[user_id]):  
        if item.get('status') == 'active':  
            url = item['url']  
            target = float(item.get('target_price', 0))  
            old_price = float(item.get('price', 0))  
              
            print(f"🔎 Checking: {item['title']} (Target: {target})")  
              
            # Check New Price  
            new_final, new_orig, new_coupon, _ = get_product_details(url)  
              
            if new_final:  
                print(f"    Found Price: {new_final}")  
                  
                # UPDATE DB  
                db[user_id][idx]['price'] = new_final  
                save_db(db)  
                  
                # 🚨 1. TARGET HIT CHECK  
                # We check if target > 0 AND new price is LESS OR EQUAL to target  
                if target > 0 and new_final <= target:  
                    print("   🚀 TARGET HIT! Sending Alert.")  
                    msg = (  
                        f"🚨 **TARGET HIT! Price Drop Alert!** 🚨\n\n"  
                        f"📦 **{html.escape(item['title'])}**\n"  
                        f"🔻 Price dropped to: **₹{new_final}**\n"  
                        f"🎯 Your Target: ₹{target}\n\n"  
                        f"🛒 <a href='{url}'>BUY NOW</a>"  
                    )  
                    try:  
                        await bot.send_message(chat_id=user_id, text=msg, parse_mode='HTML')  
                        # Reset target so we don't spam  
                        db[user_id][idx]['target_price'] = 0   
                        save_db(db)  
                    except Exception as e: print(f"Msg Fail: {e}")  

                # 📉 2. GENERAL DROP CHECK (If price dropped but no target set)  
                elif new_final < old_price:  
                    msg = (  
                        f"📉 **Price Decreased!**\n\n"  
                        f"📦 {html.escape(item['title'])}\n"  
                        f"💰 Old: ₹{old_price}  ➡️  New: **₹{new_final}**\n\n"  
                        f"🛒 <a href='{url}'>Check Deal</a>"  
                    )  
                    try: await bot.send_message(chat_id=user_id, text=msg, parse_mode='HTML')  
                    except: pass  
            else:  
                print("   ❌ Failed to get price.")  
  
print("✅ Check Cycle Complete.")

--- 🔄 AUTOMATIC TRACKER LOOP ---

async def run_auto_tracker(app):
print("⏰ Auto-Tracker Started! I will check immediately first.")

# 1. Wait 10s then Check Immediately  
await asyncio.sleep(10)  
await check_prices_logic(app.bot)  
  
# 2. Loop forever  
while True:  
    try:  
        print(f"💤 Sleeping for {CHECK_INTERVAL} seconds...")  
        await asyncio.sleep(CHECK_INTERVAL)   
        await check_prices_logic(app.bot)  

    except Exception as e:  
        print(f"❌ Loop Error: {e}")  
        await asyncio.sleep(60)

--- 🤖 TELEGRAM HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
msg = (
"🎉 Welcome to the Price Tracker Bot!\n\n"
"1️⃣ Send an Amazon Link to start tracking.\n"
"2️⃣ Set a Target Price to get alerts.\n"
"3️⃣ Relax! I check prices automatically.\n\n"
"  Deals Channel:"
)
keyboard = [[InlineKeyboardButton("🔥 Today's Loot Deals", url=MY_DEALS_CHANNEL)]]
await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
msg = "📌 Track: Paste Link\n🎯 Target: /target_ID PRICE\n🔄 Force Check: /force_check\n📋 List: /list"
await update.message.reply_text(msg, parse_mode='Markdown')

📢 BROADCAST

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
user_id = str(update.effective_user.id)
if user_id != str(ADMIN_ID): return
message = " ".join(context.args)
if not message: return
db = load_db()
for uid in db:
try: await context.bot.send_message(chat_id=uid, text=f"📢 Loot Alert!\n\n{message}", parse_mode='Markdown')
except: pass
await update.message.reply_text("✅ Broadcast Sent.")

🔄 FORCE CHECK COMMAND (NEW)

async def force_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
user_id = str(update.effective_user.id)
if user_id != str(ADMIN_ID): return
await update.message.reply_text("🔄 Forcing Price Check Now...")
await check_prices_logic(context.bot)
await update.message.reply_text("✅ Check Complete.")

🔗 PROCESS LINK

async def process_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
url = update.message.text
user_id = str(update.effective_user.id)
if "amazon" not in url.lower() and "amzn" not in url.lower():
await update.message.reply_text("⚠️ Amazon Only!", parse_mode='Markdown')
return

status_msg = await update.message.reply_text("🔎 **Checking Price & Coupons...**", parse_mode='Markdown')  
final_price, original_price, coupon, title = get_product_details(url)  
affiliate_link = create_affiliate_link(url)  
history_link = get_price_history_link(url)  

if final_price:  
    db = load_db()  
    if user_id not in db: db[user_id] = []  
    new_item = {"title": title, "url": affiliate_link, "price": final_price, "target_price": 0, "status": "active"}  
    db[user_id].append(new_item)  
    save_db(db)  
    item_index = len(db[user_id])   

    keyboard = [  
        [InlineKeyboardButton("📉 Check History", url=history_link)],  
        [InlineKeyboardButton("🎯 Set Target Price", callback_data=f"ask_target_{item_index}")]  
    ]  
      
    # Smart Message  
    if coupon > 0:  
        msg = (  
            f"🎉 **HIDDEN COUPON FOUND!**\n\n"  
            f"📦 <b>{html.escape(title)}</b>\n"  
            f"❌ MRP: <strike>₹{original_price}</strike>\n"  
            f"🎁 **Coupon: -₹{coupon} OFF**\n"  
            f"✅ **YOUR PRICE: ₹{final_price}**"  
        )  
    else:  
        msg = f"✅ **Tracking Started!**\n📦 <b>{html.escape(title)}</b>\n💰 **₹{final_price}**"  

    await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text=msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))  
else:  
    await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text="❌ Failed. Out of Stock?", parse_mode='Markdown')

🔘 BUTTON HANDLER

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
query = update.callback_query
await query.answer()
if query.data.startswith("ask_target_"):
index = query.data.split("_")[2]
await query.message.reply_text(f" Set Target:\nCopy this: /target_{index} 0", parse_mode='Markdown')

🎯 SET TARGET

async def set_target_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
user_id = str(update.effective_user.id)
text = update.message.text
try:
parts = text.split()
command_part, target_amount = parts[0], float(parts[1])
item_idx = int(command_part.split("_")[1]) - 1
db = load_db()
if user_id in db and 0 <= item_idx < len(db[user_id]):
db[user_id][item_idx]['target_price'] = target_amount
save_db(db)
await update.message.reply_text(f"✅ Target Set: ₹{target_amount}\nI will alert you when price matches this!")
else: await update.message.reply_text("❌ Not found.")
except: await update.message.reply_text("❌ Error.")

async def view_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
user_id = str(update.effective_user.id)
db = load_db()
if user_id not in db or not db[user_id]:
await update.message.reply_text("📭 Empty.")
return
msg = "📋 List:\n\n"
for idx, item in enumerate(db[user_id]):
if item.get('status') == 'active':
msg += f"<b>{idx+1}.</b> {html.escape(item['title'][:30])}...\n   💰 ₹{item['price']} (Target: ₹{item.get('target_price', 0)})\n   ❌ /stop_{idx+1}\n\n"
await update.message.reply_text(msg, parse_mode='HTML')

async def stop_specific(update: Update, context: ContextTypes.DEFAULT_TYPE):
user_id = str(update.effective_user.id)
try:
idx = int(update.message.text.split("_")[1]) - 1
db = load_db()
if user_id in db and 0 <= idx < len(db[user_id]):
db[user_id][idx]['status'] = 'untracked'
save_db(db)
await update.message.reply_text("🛑 Stopped.")
except: pass

async def stop_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
await update.message.reply_text("ℹ️ Use /list and click the /stop command there.")

--- 🚀 MAIN EXECUTION ---

if name == 'main':
t = Thread(target=run_web_server)
t.daemon = True
t.start()

app = ApplicationBuilder().token(TOKEN).build()  

app.add_handler(CommandHandler("start", start))  
app.add_handler(CommandHandler("help", help_command))  
app.add_handler(CommandHandler("list", view_list))  
app.add_handler(CommandHandler("broadcast", broadcast))  
app.add_handler(CommandHandler("force_check", force_check)) # <--- NEW  
app.add_handler(CommandHandler("stop", stop_menu))  
  
app.add_handler(CallbackQueryHandler(button_click))   
app.add_handler(MessageHandler(filters.Regex(r"^/target_\d+"), set_target_price))  
app.add_handler(MessageHandler(filters.Regex(r"^/stop_\d+$"), stop_specific))  
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), process_link))  

loop = asyncio.get_event_loop()  
loop.create_task(run_auto_tracker(app))  

print("✅ Bot is Running with Coupon Hunter + Auto Tracker...")  
app.run_polling()
