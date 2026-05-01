import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
import os, time
from pymongo import MongoClient
from flask import Flask
import threading
import requests

# Flask web server
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Bot is running!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host='0.0.0.0', port=port)

threading.Thread(target=run_web, daemon=True).start()

# Bot setup
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID"))
MONGO_URI = os.environ.get("MONGO_URI")

bot = telebot.TeleBot(BOT_TOKEN)

# MongoDB
client = MongoClient(MONGO_URI)
db = client["zedox_complete"]
users_col = db["users"]

# Keep alive
def keep_alive():
    url = os.environ.get("RENDER_URL", "")
    while url:
        try:
            requests.get(url)
        except:
            pass
        time.sleep(240)

threading.Thread(target=keep_alive, daemon=True).start()

# Simple start command
@bot.message_handler(commands=['start'])
def start(m):
    uid = str(m.from_user.id)
    user = users_col.find_one({"_id": uid})
    if not user:
        user = {"_id": uid, "points": 0}
        users_col.insert_one(user)
    bot.send_message(m.chat.id, f"Welcome! Points: {user['points']}")

# Run bot
def run():
    print("Bot started!")
    bot.infinity_polling()

if __name__ == "__main__":
    run()
