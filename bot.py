# =========================================
# ZEDOX BOT - RENDER READY - FULL WORKING
# Complete Version with Keep-Alive
# =========================================

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
import os, time, random, string, threading, hashlib, hmac
from pymongo import MongoClient
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask
import requests

# =========================
# WEB SERVER FOR RENDER (KEEP ALIVE)
# =========================
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "🤖 ZEDOX BOT IS RUNNING! ✅"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host='0.0.0.0', port=port, debug=False)

# Start web server in background
threading.Thread(target=run_web, daemon=True).start()

# =========================
# BOT CONFIGURATION
# =========================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID"))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set!")

# =========================
# MONGODB SETUP
# =========================
MONGO_URI = os.environ.get("MONGO_URI")
if not MONGO_URI:
    raise ValueError("MONGO_URI environment variable not set!")

client = MongoClient(MONGO_URI, maxPoolSize=100, minPoolSize=20, connectTimeoutMS=3000, socketTimeoutMS=3000)
db = client["zedox_complete"]

# Collections
users_col = db["users"]
folders_col = db["folders"]
codes_col = db["codes"]
config_col = db["config"]
custom_buttons_col = db["custom_buttons"]
admins_col = db["admins"]
payments_col = db["payments"]

# Create indexes for speed
try:
    users_col.create_index("points")
    users_col.create_index("vip")
    users_col.create_index("referrals_count")
    folders_col.create_index([("cat", 1), ("parent", 1)])
    folders_col.create_index("number", unique=True, sparse=True)
except:
    pass

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")

# =========================
# KEEP ALIVE SYSTEM
# =========================
def keep_alive():
    render_url = os.environ.get("RENDER_URL", "")
    if not render_url:
        return
    while True:
        try:
            response = requests.get(f"{render_url}/", timeout=10)
            print(f"✅ Keep-alive ping sent: {response.status_code}")
        except Exception as e:
            print(f"❌ Keep-alive failed: {e}")
        time.sleep(240)

if os.environ.get("RENDER_URL"):
    threading.Thread(target=keep_alive, daemon=True).start()
    print("🔄 Keep-alive system ACTIVE")

# =========================
# CACHE SYSTEM
# =========================
_config_cache = None
_config_cache_time = 0
_user_cache = {}
_user_cache_time = {}
_folder_cache = {}
_folder_cache_time = {}
CACHE_TTL = 60

def get_cached_config():
    global _config_cache, _config_cache_time
    now = time.time()
    if _config_cache and (now - _config_cache_time) < CACHE_TTL:
        return _config_cache
    _config_cache = get_config()
    _config_cache_time = now
    return _config_cache

# =========================
# SECURITY
# =========================
def validate_request(message):
    if not message or not message.from_user:
        return False
    if len(message.text or "") > 4096:
        return False
    return True

def hash_user_data(uid):
    secret = os.environ.get("BOT_TOKEN", "secret_key")
    return hmac.new(secret.encode(), str(uid).encode(), hashlib.sha256).hexdigest()[:16]

# =========================
# CONFIG SYSTEM
# =========================
def get_config():
    cfg = config_col.find_one({"_id": "config"})
    if not cfg:
        cfg = {
            "_id": "config",
            "force_channels": [],
            "custom_buttons": [],
            "vip_msg": "💎 Buy VIP to unlock this!",
            "welcome": "🔥 Welcome to ZEDOX BOT",
            "ref_reward": 5,
            "notify": True,
            "purchase_msg": "💰 Purchase VIP to access premium features!",
            "next_folder_number": 1,
            "points_per_dollar": 100,
            "contact_username": None,
            "contact_link": None,
            "vip_contact": None,
            "vip_price": 50,
            "vip_points_price": 5000,
            "payment_methods": ["💳 Binance", "💵 USDT (TRC20)", "💰 Bank Transfer", "🪙 Bitcoin"],
            "referral_vip_count": 50,
            "referral_purchase_count": 10,
            "vip_duration_days": 30,
            "binance_coin": "USDT",
            "binance_network": "TRC20",
            "binance_address": "",
            "binance_memo": "",
            "require_screenshot": True
        }
        config_col.insert_one(cfg)
    return cfg

def set_config(key, value):
    global _config_cache
    _config_cache = None
    config_col.update_one({"_id": "config"}, {"$set": {key: value}}, upsert=True)

# =========================
# ADMINS SYSTEM
# =========================
def init_admins():
    if not admins_col.find_one({"_id": ADMIN_ID}):
        admins_col.insert_one({
            "_id": ADMIN_ID,
            "username": None,
            "added_by": "system",
            "added_at": time.time(),
            "is_owner": True
        })

init_admins()

def is_admin(uid):
    uid = int(uid) if isinstance(uid, str) else uid
    if uid == ADMIN_ID:
        return True
    return admins_col.find_one({"_id": uid}) is not None

def add_admin(uid, username=None, added_by=None):
    uid = int(uid) if isinstance(uid, str) else uid
    if admins_col.find_one({"_id": uid}):
        return False
    admins_col.insert_one({
        "_id": uid,
        "username": username,
        "added_by": added_by,
        "added_at": time.time(),
        "is_owner": False
    })
    return True

def remove_admin(uid):
    uid = int(uid) if isinstance(uid, str) else uid
    if uid == ADMIN_ID:
        return False
    result = admins_col.delete_one({"_id": uid})
    return result.deleted_count > 0

def get_all_admins():
    return list(admins_col.find({}))

# =========================
# USER SYSTEM
# =========================
class User:
    def __init__(self, uid):
        self.uid = str(uid)
        
        now = time.time()
        if uid in _user_cache and (now - _user_cache_time.get(uid, 0)) < CACHE_TTL:
            self.data = _user_cache[uid]
            return
        
        data = users_col.find_one({"_id": self.uid})
        
        if not data:
            data = {
                "_id": self.uid,
                "points": 0,
                "vip": False,
                "vip_expiry": None,
                "ref": None,
                "refs": 0,
                "refs_who_bought_vip": 0,
                "purchased_methods": [],
                "used_codes": [],
                "username": None,
                "created_at": time.time(),
                "last_active": time.time(),
                "hash_id": hash_user_data(uid),
                "total_points_earned": 0,
                "total_points_spent": 0
            }
            users_col.insert_one(data)
        
        self.data = data
        _user_cache[uid] = data
        _user_cache_time[uid] = now
    
    def save(self):
        users_col.update_one({"_id": self.uid}, {"$set": self.data})
        _user_cache[self.uid] = self.data
        _user_cache_time[self.uid] = time.time()
    
    def is_vip(self):
        if self.data.get("vip", False):
            expiry = self.data.get("vip_expiry")
            if expiry and expiry < time.time():
                self.data["vip"] = False
                self.data["vip_expiry"] = None
                self.save()
                return False
            return True
        return False
    
    def points(self): 
        return self.data.get("points", 0)
    
    def purchased_methods(self): 
        return self.data.get("purchased_methods", [])
    
    def used_codes(self): 
        return self.data.get("used_codes", [])
    
    def username(self): 
        return self.data.get("username", None)
    
    def update_username(self, username):
        if username != self.data.get("username"):
            self.data["username"] = username
            self.save()
    
    def add_points(self, p):
        self.data["points"] += p
        self.data["total_points_earned"] = self.data.get("total_points_earned", 0) + p
        self.save()
    
    def spend_points(self, p):
        self.data["points"] -= p
        self.data["total_points_spent"] = self.data.get("total_points_spent", 0) + p
        self.save()
    
    def make_vip(self, duration_days=None):
        self.data["vip"] = True
        if duration_days and duration_days > 0:
            self.data["vip_expiry"] = time.time() + (duration_days * 86400)
        else:
            self.data["vip_expiry"] = None
        self.save()
    
    def remove_vip(self):
        self.data["vip"] = False
        self.data["vip_expiry"] = None
        self.save()
    
    def purchase_method(self, method_name, price):
        if self.points() >= price:
            self.spend_points(price)
            if method_name not in self.purchased_methods():
                self.data["purchased_methods"].append(method_name)
                self.save()
            return True
        return False
    
    def can_access_method(self, method_name):
        return self.is_vip() or method_name in self.purchased_methods()
    
    def add_used_code(self, code):
        if code not in self.used_codes():
            self.data["used_codes"].append(code)
            self.save()
            return True
        return False
    
    def has_used_code(self, code):
        return code in self.used_codes()
    
    def add_ref(self):
        self.data["refs"] = self.data.get("refs", 0) + 1
        self.save()
        config = get_cached_config()
        required_refs = config.get("referral_vip_count", 50)
        if self.data["refs"] >= required_refs and not self.is_vip():
            self.make_vip(config.get("vip_duration_days", 30))
            return True
        return False
    
    def add_ref_bought_vip(self):
        self.data["refs_who_bought_vip"] = self.data.get("refs_who_bought_vip", 0) + 1
        self.save()
        config = get_cached_config()
        required_purchases = config.get("referral_purchase_count", 10)
        if self.data["refs_who_bought_vip"] >= required_purchases and not self.is_vip():
            self.make_vip(config.get("vip_duration_days", 30))
            return True
        return False
    
    def get_refs_count(self):
        return self.data.get("refs", 0)
    
    def get_refs_bought_vip_count(self):
        return self.data.get("refs_who_bought_vip", 0)

# =========================
# FOLDER SYSTEM
# =========================
class FS:
    def _get_cache_key(self, cat, parent):
        return f"{cat}_{parent}"
    
    def add(self, cat, name, files, price, parent=None, number=None, text_content=None):
        if number is None:
            config = get_config()
            number = config.get("next_folder_number", 1)
            set_config("next_folder_number", number + 1)
        
        folder_data = {
            "cat": cat,
            "name": name,
            "files": files,
            "price": price,
            "parent": parent,
            "number": number,
            "created_at": time.time()
        }
        if text_content:
            folder_data["text_content"] = text_content
        folders_col.insert_one(folder_data)
        _folder_cache.pop(self._get_cache_key(cat, parent), None)
        return number
    
    def get(self, cat, parent=None):
        cache_key = self._get_cache_key(cat, parent)
        now = time.time()
        if cache_key in _folder_cache and (now - _folder_cache_time.get(cache_key, 0)) < CACHE_TTL:
            return _folder_cache[cache_key]
        
        query = {"cat": cat}
        if parent:
            query["parent"] = parent
        else:
            query["parent"] = None
        result = list(folders_col.find(query).sort("number", 1))
        _folder_cache[cache_key] = result
        _folder_cache_time[cache_key] = now
        return result
    
    def get_one(self, cat, name, parent=None):
        query = {"cat": cat, "name": name}
        if parent:
            query["parent"] = parent
        return folders_col.find_one(query)
    
    def get_by_number(self, number):
        return folders_col.find_one({"number": number})
    
    def update_numbers_after_delete(self, deleted_number):
        folders_col.update_many({"number": {"$gt": deleted_number}}, {"$inc": {"number": -1}})
        config = get_config()
        current_next = config.get("next_folder_number", 1)
        if current_next > deleted_number:
            set_config("next_folder_number", current_next - 1)
    
    def delete_all_subfolders(self, cat, parent_name):
        subfolders = list(folders_col.find({"cat": cat, "parent": parent_name}))
        for sub in subfolders:
            self.delete_all_subfolders(cat, sub["name"])
            folders_col.delete_one({"_id": sub["_id"]})
    
    def delete(self, cat, name, parent=None):
        query = {"cat": cat, "name": name}
        if parent:
            query["parent"] = parent
        else:
            query["parent"] = None
        folder = folders_col.find_one(query)
        if not folder:
            return False
        number = folder.get("number")
        self.delete_all_subfolders(cat, name)
        folders_col.delete_one(query)
        if number:
            self.update_numbers_after_delete(number)
        _folder_cache.pop(self._get_cache_key(cat, parent), None)
        return True
    
    def edit_price(self, cat, name, price, parent=None):
        query = {"cat": cat, "name": name}
        if parent:
            query["parent"] = parent
        folders_col.update_one(query, {"$set": {"price": price}})
        _folder_cache.pop(self._get_cache_key(cat, parent), None)
    
    def edit_name(self, cat, old, new, parent=None):
        query = {"cat": cat, "name": old}
        if parent:
            query["parent"] = parent
        folders_col.update_one(query, {"$set": {"name": new}})
        folders_col.update_many({"cat": cat, "parent": old}, {"$set": {"parent": new}})
        _folder_cache.clear()
    
    def move_folder(self, number, new_parent):
        folders_col.update_one({"number": number}, {"$set": {"parent": new_parent}})
        _folder_cache.clear()
    
    def edit_content(self, cat, name, content_type, content, parent=None):
        query = {"cat": cat, "name": name}
        if parent:
            query["parent"] = parent
        if content_type == "text":
            folders_col.update_one(query, {"$set": {"text_content": content}})
        elif content_type == "files":
            folders_col.update_one(query, {"$set": {"files": content}})
        _folder_cache.pop(self._get_cache_key(cat, parent), None)
        return True

fs = FS()

# =========================
# CODES SYSTEM
# =========================
class Codes:
    def generate(self, pts, count, multi_use=False, expiry_days=None):
        res = []
        expiry = time.time() + (expiry_days * 86400) if expiry_days else None
        for _ in range(count):
            code = "ZEDOX" + ''.join(random.choices(string.ascii_uppercase+string.digits, k=8))
            while codes_col.find_one({"_id": code}):
                code = "ZEDOX" + ''.join(random.choices(string.ascii_uppercase+string.digits, k=8))
            codes_col.insert_one({
                "_id": code,
                "points": pts,
                "used": False,
                "multi_use": multi_use,
                "used_count": 0,
                "max_uses": 0 if not multi_use else 10,
                "expiry": expiry,
                "created_at": time.time(),
                "used_by_users": []
            })
            res.append(code)
        return res
    
    def redeem(self, code, user):
        code_data = codes_col.find_one({"_id": code})
        if not code_data:
            return False, 0, "invalid"
        if code_data.get("expiry") and time.time() > code_data["expiry"]:
            return False, 0, "expired"
        if not code_data.get("multi_use", False) and code_data.get("used", False):
            return False, 0, "already_used"
        if user.uid in code_data.get("used_by_users", []):
            return False, 0, "already_used_by_user"
        if code_data.get("multi_use", False):
            used_count = code_data.get("used_count", 0)
            max_uses = code_data.get("max_uses", 10)
            if used_count >= max_uses:
                return False, 0, "max_uses_reached"
        pts = code_data["points"]
        user.add_points(pts)
        update_data = {"$push": {"used_by_users": user.uid}, "$inc": {"used_count": 1}}
        if not code_data.get("multi_use", False):
            update_data["$set"] = {"used": True}
        codes_col.update_one({"_id": code}, update_data)
        user.add_used_code(code)
        return True, pts, "success"
    
    def get_all_codes(self):
        return list(codes_col.find({}).sort("created_at", -1))
    
    def get_stats(self):
        total = codes_col.count_documents({})
        used = codes_col.count_documents({"used": True})
        unused = total - used
        multi_use = codes_col.count_documents({"multi_use": True})
        return total, used, unused, multi_use

codesys = Codes()

# =========================
# POINTS PACKAGES SYSTEM
# =========================
def get_points_packages():
    packages = config_col.find_one({"_id": "points_packages"})
    if not packages:
        default_packages = {
            "_id": "points_packages",
            "packages": [
                {"points": 100, "price": 5, "currency": "USD", "bonus": 0, "active": True},
                {"points": 250, "price": 10, "currency": "USD", "bonus": 25, "active": True},
                {"points": 550, "price": 20, "currency": "USD", "bonus": 100, "active": True},
                {"points": 1500, "price": 50, "currency": "USD", "bonus": 500, "active": True},
                {"points": 3500, "price": 100, "currency": "USD", "bonus": 1500, "active": True},
                {"points": 10000, "price": 250, "currency": "USD", "bonus": 5000, "active": True}
            ]
        }
        config_col.insert_one(default_packages)
        return default_packages["packages"]
    return packages["packages"]

def save_points_packages(packages):
    config_col.update_one({"_id": "points_packages"}, {"$set": {"packages": packages}}, upsert=True)

# =========================
# FORCE JOIN
# =========================
_force_cache = {}
FORCE_CACHE_TTL = 30

def force_block(uid):
    if is_admin(uid):
        return False
    cfg = get_cached_config()
    force_channels = cfg.get("force_channels", [])
    if not force_channels:
        return False
    for ch in force_channels:
        try:
            member = bot.get_chat_member(ch, uid)
            if member.status in ["left", "kicked"]:
                kb = InlineKeyboardMarkup()
                for channel in force_channels:
                    kb.add(InlineKeyboardButton(f"📢 Join {channel}", url=f"https://t.me/{channel.replace('@','')}"))
                kb.add(InlineKeyboardButton("✅ I Joined", callback_data="recheck"))
                bot.send_message(uid, "🚫 **Access Restricted!**\n\nPlease join the following channels:", reply_markup=kb, parse_mode="Markdown")
                return True
        except:
            kb = InlineKeyboardMarkup()
            for channel in force_channels:
                kb.add(InlineKeyboardButton(f"📢 Join {channel}", url=f"https://t.me/{channel.replace('@','')}"))
            kb.add(InlineKeyboardButton("✅ I Joined", callback_data="recheck"))
            bot.send_message(uid, f"🚫 **Please join required channels!**", reply_markup=kb, parse_mode="Markdown")
            return True
    return False

def force_join_handler(func):
    @wraps(func)
    def wrapper(message):
        if force_block(message.from_user.id):
            return
        return func(message)
    return wrapper

# =========================
# MAIN MENU
# =========================
def get_custom_buttons():
    cfg = get_cached_config()
    return cfg.get("custom_buttons", [])

def add_custom_button(button_text, button_type, button_data):
    cfg = get_config()
    buttons = cfg.get("custom_buttons", [])
    buttons.append({"text": button_text, "type": button_type, "data": button_data})
    set_config("custom_buttons", buttons)

def remove_custom_button(button_text):
    cfg = get_config()
    buttons = cfg.get("custom_buttons", [])
    buttons = [b for b in buttons if b["text"] != button_text]
    set_config("custom_buttons", buttons)

def main_menu(uid):
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("📂 FREE METHODS", "💎 VIP METHODS")
    kb.add("📦 PREMIUM APPS", "⚡ SERVICES")
    kb.add("💰 POINTS", "⭐ BUY VIP")
    custom_btns = get_custom_buttons()
    if custom_btns:
        row = []
        for btn in custom_btns:
            row.append(btn["text"])
            if len(row) == 2:
                kb.add(*row)
                row = []
        if row:
            kb.add(*row)
    kb.add("🎁 REFERRAL", "👤 ACCOUNT")
    kb.add("📚 MY METHODS", "💎 GET POINTS")
    kb.add("🆔 CHAT ID", "🏆 REDEEM")
    if is_admin(uid):
        kb.add("⚙️ ADMIN PANEL")
    return kb

def admin_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📦 Upload FREE", "💎 Upload VIP")
    kb.row("📱 Upload APPS", "⚡ Upload SERVICE")
    kb.row("📁 Create Subfolder", "🗑 Delete Folder")
    kb.row("✏️ Edit Price", "✏️ Edit Name")
    kb.row("📝 Edit Content", "🔀 Move Folder")
    kb.row("👑 Add VIP", "👑 Remove VIP")
    kb.row("💰 Give Points", "🎫 Generate Codes")
    kb.row("📊 View Codes", "📦 Points Packages")
    kb.row("👥 Admin Management", "📞 Set Contacts")
    kb.row("⚙️ VIP Settings", "💳 Payment Methods")
    kb.row("🏦 Binance Settings", "📸 Screenshot")
    kb.row("➕ Add Button", "➖ Remove Button")
    kb.row("➕ Add Channel", "➖ Remove Channel")
    kb.row("⚙️ Settings", "📊 Stats")
    kb.row("📢 Broadcast", "🔔 Notify")
    kb.row("📊 Leaderboard", "❌ Exit")
    return kb

def get_folders_kb(cat, parent=None, page=0, items_per_page=15):
    data = fs.get(cat, parent)
    start = page * items_per_page
    end = start + items_per_page
    page_items = data[start:end]
    kb = InlineKeyboardMarkup(row_width=2)
    for item in page_items:
        name = item["name"]
        price = item.get("price", 0)
        number = item.get("number", "?")
        subfolders = fs.get(cat, name)
        icon = "📁" if subfolders else "📄"
        text = f"{icon} [{number}] {name}"
        if price > 0:
            text += f" [{price} pts]"
        kb.add(InlineKeyboardButton(text, callback_data=f"open|{cat}|{name}|{parent or ''}"))
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"page|{cat}|{page-1}|{parent or ''}"))
    if end < len(data):
        nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"page|{cat}|{page+1}|{parent or ''}"))
    if nav_buttons:
        kb.row(*nav_buttons)
    if parent:
        kb.add(InlineKeyboardButton("🔙 Back", callback_data=f"back|{cat}|{parent}"))
    return kb

# =========================
# BOT HANDLERS
# =========================
@bot.message_handler(commands=["start"])
def start_cmd(m):
    if not validate_request(m):
        return
    uid = m.from_user.id
    args = m.text.split()
    user = User(uid)
    if m.from_user.username:
        user.update_username(m.from_user.username)
    if len(args) > 1:
        ref_id = args[1]
        if ref_id != str(uid) and ref_id.isdigit():
            ref_user_data = users_col.find_one({"_id": ref_id})
            if ref_user_data and not user.data.get("ref"):
                try:
                    ref_user = User(ref_id)
                    reward = get_cached_config().get("ref_reward", 5)
                    ref_user.add_points(reward)
                    got_vip = ref_user.add_ref()
                    user.data["ref"] = ref_id
                    user.save()
                    try:
                        vip_msg = ""
                        if got_vip:
                            vip_msg = f"\n\n🎉 **CONGRATULATIONS!** 🎉\nYou've reached {ref_user.get_refs_count()} referrals and got **FREE VIP ACCESS**!"
                        bot.send_message(int(ref_id), 
                            f"👤 **New Referral Alert!**\n\n"
                            f"✨ **@{user.username or user.uid}** just joined!\n\n"
                            f"💰 You earned **+{reward} points**!\n"
                            f"📊 Total Referrals: **{ref_user.get_refs_count()}**\n"
                            f"💎 Total Points: **{ref_user.points()}**{vip_msg}",
                            parse_mode="Markdown")
                    except:
                        pass
                except:
                    pass
    if force_block(uid):
        return
    cfg = get_cached_config()
    welcome_msg = cfg.get("welcome", "Welcome to ZEDOX BOT!")
    bot.send_message(uid, f"{welcome_msg}\n\n💰 Your points: **{user.points()}**", reply_markup=main_menu(uid))

@bot.message_handler(func=lambda m: m.text == "💰 POINTS")
@force_join_handler
def points_cmd(m):
    uid = m.from_user.id
    user = User(uid)
    purchased_count = len(user.purchased_methods())
    ref_count = user.get_refs_count()
    ref_bought_count = user.get_refs_bought_vip_count()
    points_msg = f"💰 **YOUR POINTS BALANCE** 💰\n\n"
    points_msg += f"┌ **Points:** `{user.points()}`\n"
    points_msg += f"├ **VIP Status:** {'✅ Active' if user.is_vip() else '❌ Not Active'}\n"
    points_msg += f"├ **Purchased Methods:** `{purchased_count}`\n"
    points_msg += f"├ **Total Referrals:** `{ref_count}`\n"
    points_msg += f"├ **Referrals who bought VIP:** `{ref_bought_count}`\n"
    points_msg += f"├ **Total Earned:** `{user.data.get('total_points_earned', 0)}`\n"
    points_msg += f"└ **Total Spent:** `{user.data.get('total_points_spent', 0)}`\n\n"
    points_msg += f"✨ **Ways to Earn Points:**\n"
    points_msg += f"• 🎁 **Referral System:** Share your link\n"
    points_msg += f"• 🏆 **Redeem Codes:** Use coupon codes\n"
    points_msg += f"• 💎 **Purchase:** Click 💎 GET POINTS button\n\n"
    points_msg += f"🎯 **Referral Rewards:**\n"
    cfg = get_cached_config()
    points_msg += f"• Invite {cfg.get('referral_vip_count', 50)} users → **FREE VIP**\n"
    points_msg += f"• {cfg.get('referral_purchase_count', 10)} referrals buy VIP → **FREE VIP**\n\n"
    points_msg += f"💡 **Use points to:**\n"
    points_msg += f"• Buy individual VIP methods\n"
    points_msg += f"• Access premium content\n"
    points_msg += f"• Redeem special offers"
    bot.send_message(uid, points_msg, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "💎 GET POINTS")
@force_join_handler
def get_points_button(m):
    uid = m.from_user.id
    user = User(uid)
    packages = get_points_packages()
    active_packages = [p for p in packages if p.get("active", True)]
    cfg = get_cached_config()
    contact_username = cfg.get("contact_username")
    contact_link = cfg.get("contact_link")
    binance_address = cfg.get("binance_address", "")
    binance_coin = cfg.get("binance_coin", "USDT")
    binance_network = cfg.get("binance_network", "TRC20")
    binance_memo = cfg.get("binance_memo", "")
    message = f"💰 **GET POINTS** 💰\n\n"
    message += f"✨ **Your Current Balance:** `{user.points()}` points\n\n"
    if active_packages:
        message += f"📦 **BUY POINTS PACKAGES:**\n\n"
        for i, pkg in enumerate(active_packages, 1):
            total_points = pkg["points"] + pkg.get("bonus", 0)
            price_display = f"${pkg['price']}"
            message += f"💎 **Package {i}:**\n"
            message += f"   • {pkg['points']} points for `{price_display}`\n"
            if pkg.get("bonus", 0) > 0:
                message += f"   • **BONUS:** +{pkg['bonus']} points FREE!\n"
                message += f"   • **Total:** `{total_points}` points\n"
            message += f"   • 💰 **Value:** {price_display}\n\n"
        if binance_address:
            message += f"💳 **Binance Payment Details:**\n"
            message += f"┌ **Coin:** {binance_coin}\n"
            message += f"├ **Network:** {binance_network}\n"
            message += f"├ **Address:** `{binance_address}`\n"
            if binance_memo:
                message += f"├ **Memo/Tag:** `{binance_memo}`\n"
            message += f"└ **Amount:** Equal to package price\n\n"
            if cfg.get("require_screenshot", True):
                message += f"📸 **IMPORTANT:** Send payment screenshot!\n\n"
        message += f"✨ **How to Purchase:**\n"
        message += f"1️⃣ Send payment to Binance address\n"
        message += f"2️⃣ Take a screenshot\n"
        message += f"3️⃣ Send screenshot here\n"
        message += f"4️⃣ Send User ID: `{uid}`\n"
        message += f"5️⃣ Mention package\n\n"
        message += f"💳 **Other Payment Methods:**\n"
        for method in cfg.get("payment_methods", ["💳 Binance", "💵 USDT"]):
            if "Binance" not in method:
                message += f"• {method}\n"
        message += f"\n"
        message += f"🎁 **Special Offers:**\n"
        message += f"• First purchase: **10% BONUS**\n"
        message += f"• Referral: Earn points\n\n"
        message += f"⚡ **Fast delivery!**\n\n"
    else:
        message += f"❌ No packages available.\n\n"
    message += f"🎁 **FREE WAYS TO EARN POINTS:**\n"
    message += f"• **Referral System:** Share your link\n"
    message += f"• **Redeem Codes:** Use coupon codes\n\n"
    message += f"💡 **Tip:** More points = More VIP methods!"
    kb = InlineKeyboardMarkup(row_width=2)
    if contact_link:
        kb.add(InlineKeyboardButton("📞 Contact Admin", url=contact_link))
    elif contact_username:
        kb.add(InlineKeyboardButton("📞 Contact Admin", url=f"https://t.me/{contact_username.replace('@', '')}"))
    else:
        try:
            admin_chat = bot.get_chat(ADMIN_ID)
            if admin_chat.username:
                kb.add(InlineKeyboardButton("📞 Contact Admin", url=f"https://t.me/{admin_chat.username}"))
        except:
            pass
    if active_packages:
        kb.add(InlineKeyboardButton("💰 Check Balance", callback_data="check_balance"))
    kb.add(InlineKeyboardButton("🎁 Referral Link", callback_data="get_referral"))
    kb.add(InlineKeyboardButton("⭐ VIP Info", callback_data="get_vip_info"))
    bot.send_message(uid, message, reply_markup=kb, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text in ["📂 FREE METHODS", "💎 VIP METHODS", "📦 PREMIUM APPS", "⚡ SERVICES"])
@force_join_handler
def show_category(m):
    uid = m.from_user.id
    mapping = {"📂 FREE METHODS": "free", "💎 VIP METHODS": "vip", "📦 PREMIUM APPS": "apps", "⚡ SERVICES": "services"}
    cat = mapping.get(m.text)
    if cat is None:
        bot.send_message(uid, "❌ Invalid category")
        return
    data = fs.get(cat)
    if not data:
        bot.send_message(uid, f"📂 {m.text}\n\nNo folders available!", parse_mode="Markdown")
        return
    bot.send_message(uid, f"📂 {m.text}\n\nSelect:", reply_markup=get_folders_kb(cat))

@bot.callback_query_handler(func=lambda c: c.data.startswith("open|"))
def open_folder(c):
    uid = c.from_user.id
    user = User(uid)
    parts = c.data.split("|")
    cat = parts[1]
    name = parts[2]
    parent = parts[3] if len(parts) > 3 and parts[3] else None
    folder = fs.get_one(cat, name, parent if parent else None)
    if not folder:
        bot.answer_callback_query(c.id, "❌ Folder not found")
        return
    subfolders = fs.get(cat, name)
    if subfolders and len(subfolders) > 0:
        kb = InlineKeyboardMarkup(row_width=1)
        for sub in subfolders:
            sub_name = sub["name"]
            sub_number = sub.get("number", "?")
            sub_price = sub.get("price", 0)
            deeper = fs.get(cat, sub_name)
            icon = "📁" if deeper else "📄"
            text = f"{icon} [{sub_number}] {sub_name}"
            if sub_price > 0:
                text += f" - {sub_price} pts"
            kb.add(InlineKeyboardButton(text, callback_data=f"open|{cat}|{sub_name}|{name}"))
        kb.add(InlineKeyboardButton("🔙 BACK", callback_data=f"back|{cat}|{name}"))
        bot.edit_message_text(f"📁 <b>{name}</b>", uid, c.message.message_id, reply_markup=kb, parse_mode="HTML")
        bot.answer_callback_query(c.id)
        return
    text_content = folder.get("text_content")
    if text_content and not folder.get("files"):
        price = folder.get("price", 0)
        if cat == "vip":
            if user.is_vip() or user.can_access_method(name):
                pass
            else:
                if price > 0:
                    buy_kb = InlineKeyboardMarkup(row_width=2)
                    buy_kb.add(InlineKeyboardButton(f"💰 Buy {price} pts", callback_data=f"buy|{cat}|{name}|{price}"), InlineKeyboardButton("⭐ VIP", callback_data="get_vip"), InlineKeyboardButton("💎 Points", callback_data="get_points"))
                    buy_kb.add(InlineKeyboardButton("❌ Cancel", callback_data="cancel_buy"))
                    bot.answer_callback_query(c.id, "🔒 VIP method")
                    bot.send_message(uid, f"🔒 **{name}**\n\nPrice: {price} pts\nYour points: {user.points()}", reply_markup=buy_kb, parse_mode="Markdown")
                else:
                    buy_kb = InlineKeyboardMarkup(row_width=2)
                    buy_kb.add(InlineKeyboardButton("⭐ VIP", callback_data="get_vip"), InlineKeyboardButton("💎 Points", callback_data="get_points"))
                    bot.answer_callback_query(c.id, "🔒 VIP only")
                    bot.send_message(uid, f"🔒 **{name}**\nVIP only!", reply_markup=buy_kb, parse_mode="Markdown")
                return
        if cat != "vip" and price > 0 and not user.is_vip():
            if user.points() < price:
                bot.answer_callback_query(c.id, f"❌ Need {price} pts! You have {user.points()}", True)
                return
            user.spend_points(price)
            bot.answer_callback_query(c.id, f"✅ -{price} pts")
        bot.send_message(uid, f"📄 **{name}**\n\n{text_content}", parse_mode="Markdown")
        if cat == "vip" and not user.is_vip():
            user.purchase_method(name, 0)
        return
    files = folder.get("files", [])
    price = folder.get("price", 0)
    if cat == "vip":
        if user.is_vip() or user.can_access_method(name):
            pass
        else:
            if price > 0:
                buy_kb = InlineKeyboardMarkup(row_width=2)
                buy_kb.add(InlineKeyboardButton(f"💰 Buy {price} pts", callback_data=f"buy|{cat}|{name}|{price}"), InlineKeyboardButton("⭐ VIP", callback_data="get_vip"), InlineKeyboardButton("💎 Points", callback_data="get_points"))
                buy_kb.add(InlineKeyboardButton("❌ Cancel", callback_data="cancel_buy"))
                bot.answer_callback_query(c.id, "🔒 VIP method")
                bot.send_message(uid, f"🔒 **{name}**\n\nPrice: {price} pts\nYour points: {user.points()}", reply_markup=buy_kb, parse_mode="Markdown")
            else:
                buy_kb = InlineKeyboardMarkup(row_width=2)
                buy_kb.add(InlineKeyboardButton("⭐ VIP", callback_data="get_vip"), InlineKeyboardButton("💎 Points", callback_data="get_points"))
                bot.answer_callback_query(c.id, "🔒 VIP only")
                bot.send_message(uid, f"🔒 **{name}**\nVIP only!", reply_markup=buy_kb, parse_mode="Markdown")
            return
    if cat != "vip" and price > 0 and not user.is_vip():
        if user.points() < price:
            bot.answer_callback_query(c.id, f"❌ Need {price} pts! You have {user.points()}", True)
            return
        user.spend_points(price)
        bot.answer_callback_query(c.id, f"✅ -{price} pts")
    if files:
        bot.answer_callback_query(c.id, "📤 Sending...")
        count = 0
        for f in files:
            try:
                bot.copy_message(uid, f["chat"], f["msg"])
                count += 1
                time.sleep(0.05)
            except:
                continue
        if get_cached_config().get("notify", True):
            if count > 0:
                bot.send_message(uid, f"✅ {count} file(s) sent!")
            else:
                bot.send_message(uid, "❌ Failed to send.")
    else:
        bot.send_message(uid, "📁 No files.")
    if cat == "vip" and not user.is_vip():
        user.purchase_method(name, 0)

# =========================
# ADD MORE HANDLERS HERE (back, page, buy, etc.)
# =========================
@bot.callback_query_handler(func=lambda c: c.data.startswith("back|"))
def back_handler(c):
    _, cat, current_parent = c.data.split("|")
    parent_folder = fs.get_one(cat, current_parent)
    if parent_folder:
        grand_parent = parent_folder.get("parent")
        bot.edit_message_reply_markup(c.from_user.id, c.message.message_id, reply_markup=get_folders_kb(cat, grand_parent))
    else:
        bot.edit_message_reply_markup(c.from_user.id, c.message.message_id, reply_markup=get_folders_kb(cat))
    bot.answer_callback_query(c.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("page|"))
def page_handler(c):
    _, cat, page, parent = c.data.split("|")
    parent = parent if parent != "None" else None
    try:
        bot.edit_message_reply_markup(c.from_user.id, c.message.message_id, reply_markup=get_folders_kb(cat, parent, int(page)))
    except:
        pass
    bot.answer_callback_query(c.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("buy|"))
def buy_method(c):
    uid = c.from_user.id
    user = User(uid)
    try:
        _, cat, method_name, price = c.data.split("|")
        price = int(price)
    except:
        bot.answer_callback_query(c.id, "Invalid")
        return
    if user.is_vip():
        bot.answer_callback_query(c.id, "✅ You are VIP!", True)
        open_folder(c)
        return
    if user.can_access_method(method_name):
        bot.answer_callback_query(c.id, "✅ You own this!", True)
        open_folder(c)
        return
    if user.points() < price:
        bot.answer_callback_query(c.id, f"❌ Need {price} pts! You have {user.points()}", True)
        return
    if user.purchase_method(method_name, price):
        bot.answer_callback_query(c.id, f"✅ Purchased! -{price} pts", True)
        bot.edit_message_text(f"✅ **Purchased!**\n\nYou now own: {method_name}\nRemaining: {user.points()} pts", uid, c.message.message_id, parse_mode="Markdown")
    else:
        bot.answer_callback_query(c.id, "❌ Failed!", True)

# =========================
# ADMIN PANEL HANDLER
# =========================
@bot.message_handler(func=lambda m: m.text == "⚙️ ADMIN PANEL" and is_admin(m.from_user.id))
def open_admin(m):
    bot.send_message(m.from_user.id, "⚙️ **Admin Panel**", reply_markup=admin_menu(), parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "❌ Exit" and is_admin(m.from_user.id))
def exit_admin(m):
    bot.send_message(m.from_user.id, "Exited", reply_markup=main_menu(m.from_user.id))

# =========================
# GIVE POINTS HANDLER
# =========================
@bot.message_handler(func=lambda m: m.text == "💰 Give Points" and is_admin(m.from_user.id))
def give_points_start(m):
    msg = bot.send_message(m.from_user.id, "💰 **Give Points**\n\nSend: `user_id points`\n\nExample: `7712834912 200`", parse_mode="Markdown")
    bot.register_next_step_handler(msg, give_points_process)

def give_points_process(m):
    try:
        parts = m.text.strip().split()
        if len(parts) != 2:
            bot.send_message(m.from_user.id, "❌ Use: user_id points")
            return
        user_id, points = int(parts[0]), int(parts[1])
        if points <= 0:
            bot.send_message(m.from_user.id, "❌ Points must be > 0")
            return
        user_data = users_col.find_one({"_id": str(user_id)})
        if not user_data:
            bot.send_message(m.from_user.id, f"❌ User {user_id} not found!")
            return
        user = User(user_id)
        old_points = user.points()
        user.add_points(points)
        bot.send_message(m.from_user.id, f"✅ Added {points} points to {user_id}\nOld: {old_points}\nNew: {user.points()}")
        try:
            bot.send_message(user_id, f"🎉 You received +{points} points!\n💰 New balance: {user.points()}")
        except:
            pass
    except:
        bot.send_message(m.from_user.id, "❌ Error! Use: user_id points")

# =========================
# RUN BOT
# =========================
def run_bot():
    while True:
        try:
            print("=" * 50)
            print("🚀 ZEDOX BOT - RENDER READY")
            print(f"✅ Bot: @{bot.get_me().username}")
            print(f"👑 Owner: {ADMIN_ID}")
            print(f"💾 MongoDB: Connected")
            print(f"🔄 Keep Alive: {'ACTIVE' if os.environ.get('RENDER_URL') else 'INACTIVE'}")
            print("=" * 50)
            bot.infinity_polling(timeout=30, long_polling_timeout=30)
        except Exception as e:
            print(f"❌ Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    run_bot()
