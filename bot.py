import logging
import json
import uuid
import re
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest
import os ### MODIFIED ###

# --- Configuration ---
### MODIFIED: Read from Environment Variables for security ###
TELEGRAM_BOT_TOKEN = os.getenv("7281684199:AAGXXsvFtG8ATWwbddZKPDixj0eGZ36OBvE")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", 5815604554)) # Default is for local testing

### MODIFIED: Define a persistent data directory for Railway Volumes ###
# On Railway, this will be the path to the volume, e.g., '/data'
# For local testing, it will just be a 'data' subfolder.
DATA_DIR = os.getenv("DATA_DIR", "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

USER_DATA_FILE = os.path.join(DATA_DIR, "user_data.json")
TASKS_FILE = os.path.join(DATA_DIR, "tasks.json")
WITHDRAWALS_FILE = os.path.join(DATA_DIR, "withdrawals.json")


# --- Force Subscribe Channels ---
REQUIRED_CHANNELS = [
    "@Tecno_Tips",
    # "@YourOtherChannel",
]

# --- TON Currency Settings ---
MINIMUM_WITHDRAWAL = 2.0
REFERRAL_BONUS = 0.01
DAILY_BONUS_AMOUNT = 0.05

# --- Conversation Handler States ---
ADD_TASK_TYPE, ADD_TASK_NAME, ADD_TASK_REWARD, ADD_CHANNEL_USERNAME = range(4)
CHOOSE_NETWORK, GET_ADDRESS, GET_AMOUNT = range(4, 7)

# --- Logging Setup ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Helper Functions for Escaping ---
def escape_markdown(text: str) -> str:
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

def format_ton(amount: float) -> str:
    return escape_markdown(f"{amount:.4f}")

# --- Keyboard Layouts ---
def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Balance", callback_data="balance"), InlineKeyboardButton("🔗 Referral", callback_data="referral")],
        [InlineKeyboardButton("🎁 Daily Bonus", callback_data="daily_bonus")],
        [InlineKeyboardButton("📋 Tasks", callback_data="tasks"), InlineKeyboardButton("💸 Withdraw", callback_data="withdraw_start")],
    ])

def back_to_main_menu_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="back_to_menu")]])

def admin_panel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Task", callback_data="admin_add_task")],
        [InlineKeyboardButton("➖ Delete Task", callback_data="admin_delete_task")],
        [InlineKeyboardButton("🔔 Withdrawal Requests", callback_data="admin_withdrawals")],
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="back_to_menu")],
    ])

# --- Data Handling ---
def load_data(filename):
    try:
        with open(filename, "r") as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return {}

def save_data(filename, data):
    with open(filename, "w") as f: json.dump(data, f, indent=4)

# --- Force Subscribe Feature ---
async def check_channel_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    for channel in REQUIRED_CHANNELS:
        try:
            member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                return False
        except BadRequest:
            logger.error(f"Could not check membership for channel {channel}. Is the bot an admin?")
            return False
        except Exception as e:
            logger.error(f"An unexpected error occurred checking channel {channel}: {e}")
            return False
    return True

async def force_subscribe_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    
    if await check_channel_membership(update, context):
        await query.edit_message_text("✅ Thank you for joining\\!\n\nWelcome\\! Here are your options:", reply_markup=main_menu_keyboard(), parse_mode=ParseMode.MARKDOWN_V2)
    else:
        text = "❌ You must join all required channels to use this bot\\.\n\nPlease join the channels below and then click '✅ I\\'ve Joined'\\."
        keyboard_buttons = []
        for channel in REQUIRED_CHANNELS:
            keyboard_buttons.append([InlineKeyboardButton(f"➡️ Join {channel}", url=f"https://t.me/{channel.replace('@', '')}")])
        keyboard_buttons.append([InlineKeyboardButton("✅ I've Joined", callback_data="verify_subscription")])
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard_buttons), parse_mode=ParseMode.MARKDOWN_V2)
        await query.answer("You have not joined all the required channels yet.", show_alert=True)

# --- Core Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    
    if not await check_channel_membership(update, context):
        text = "❌ You must join all required channels to use this bot\\.\n\nPlease join the channels below and then click '✅ I\\'ve Joined'\\."
        keyboard_buttons = []
        for channel in REQUIRED_CHANNELS:
            keyboard_buttons.append([InlineKeyboardButton(f"➡️ Join {channel}", url=f"https://t.me/{channel.replace('@', '')}")])
        keyboard_buttons.append([InlineKeyboardButton("✅ I've Joined", callback_data="verify_subscription")])
        
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard_buttons), parse_mode=ParseMode.MARKDOWN_V2)
        return

    user_id_str = str(user.id)
    user_data = load_data(USER_DATA_FILE)
    if user_id_str not in user_data:
        user_data[user_id_str] = {"balance": 0.0, "completed_tasks": [], "last_bonus_claim": None}
        logger.info(f"New user {user.username} (ID: {user.id}) started the bot.")
        if context.args and len(context.args) > 0:
            referrer_id = context.args[0]
            if referrer_id in user_data:
                user_data[referrer_id]["balance"] += REFERRAL_BONUS
                save_data(USER_DATA_FILE, user_data)
                text = f"🎉 A new user has joined using your referral link\\! You've received *{format_ton(REFERRAL_BONUS)} TON*\\."
                await context.bot.send_message(chat_id=referrer_id, text=text, parse_mode=ParseMode.MARKDOWN_V2)
    save_data(USER_DATA_FILE, user_data)
    await update.message.reply_text("Welcome\\! Here are your options:", reply_markup=main_menu_keyboard(), parse_mode=ParseMode.MARKDOWN_V2)

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("You are not authorized\\.", parse_mode=ParseMode.MARKDOWN_V2); return
    await update.message.reply_text("Welcome to the Admin Panel:", reply_markup=admin_panel_keyboard())

# --- Callback Query Handler (Router) ---
async def main_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    
    if query.data == "verify_subscription":
        await query.answer()
        await force_subscribe_handler(update, context)
        return

    if not await check_channel_membership(update, context):
        await query.answer()
        await force_subscribe_handler(update, context)
        return

    await query.answer()

    data = query.data
    routes = {
        "back_to_menu": lambda q, c: q.edit_message_text("Main Menu:", reply_markup=main_menu_keyboard()),
        "balance": show_balance, "referral": show_referral, "daily_bonus": claim_daily_bonus, "tasks": show_tasks,
        "admin_panel": lambda q, c: q.edit_message_text("Admin Panel:", reply_markup=admin_panel_keyboard()),
        "admin_delete_task": show_tasks_for_deletion, "admin_withdrawals": show_pending_withdrawals,
    }
    if data in routes: await routes[data](query, context)
    elif data.startswith("complete_task_"): await complete_simple_task(query, context, data.split("_")[2])
    elif data.startswith("join_channel_"): await prompt_channel_join(query, context, data.split("_")[2])
    elif data.startswith("verify_join_"): await verify_channel_join(query, context, data.split("_")[2])
    elif data.startswith("delete_task_"): await delete_task(query, context, data.split("_")[2])
    elif data.startswith("view_withdrawal_"): await view_withdrawal_details(query, context, data.split("_")[2])
    elif data.startswith("approve_withdrawal_"): await approve_withdrawal(query, context, data.split("_")[2])
    elif data.startswith("reject_withdrawal_"): await reject_withdrawal(query, context, data.split("_")[2])


# --- The rest of your functions (show_balance, show_referral, etc.) go here... ---
# --- They don't need to be changed. I am omitting them for brevity. ---
# --- Just make sure they are included in your final `main.py` file. ---


async def approve_withdrawal(query: Update.callback_query, context: ContextTypes.DEFAULT_TYPE, w_id: str):
    withdrawals = load_data(WITHDRAWALS_FILE)
    w = withdrawals.get(w_id)
    if not w or w.get('status') != 'pending':
        await query.answer("Request already processed or not found.", show_alert=True); return
    await context.bot.send_message(chat_id=w['user_id'], text=f"✅ Your withdrawal request for *{format_ton(w['amount'])} TON* has been approved\\!", parse_mode=ParseMode.MARKDOWN_V2)
    del withdrawals[w_id]; save_data(WITHDRAWALS_FILE, withdrawals)
    await query.answer("Request approved and removed from history.", show_alert=True)
    await show_pending_withdrawals(query, context)

async def reject_withdrawal(query: Update.callback_query, context: ContextTypes.DEFAULT_TYPE, w_id: str):
    withdrawals = load_data(WITHDRAWALS_FILE)
    w = withdrawals.get(w_id)
    if not w or w.get('status') != 'pending':
        await query.answer("Request already processed or not found.", show_alert=True); return
    user_data = load_data(USER_DATA_FILE)
    user_id_str = str(w['user_id'])
    if user_id_str in user_data:
        user_data[user_id_str]['balance'] += float(w['amount'])
        save_data(USER_DATA_FILE, user_data)
    await context.bot.send_message(chat_id=w['user_id'], text=f"❌ Your withdrawal request for *{format_ton(w['amount'])} TON* has been rejected\\. The TON has been returned to your balance\\.", parse_mode=ParseMode.MARKDOWN_V2)
    del withdrawals[w_id]; save_data(WITHDRAWALS_FILE, withdrawals)
    await query.answer("Request rejected, TON refunded, and history removed.", show_alert=True)
    await show_pending_withdrawals(query, context)

# ... (All your other functions like withdraw_start, add_task, etc. go here)

# --- Main Application Setup ---
def main() -> None:
    """Run the bot."""
    # Check if tokens are set
    if not TELEGRAM_BOT_TOKEN or not ADMIN_USER_ID:
        logger.error("FATAL: Environment variables TELEGRAM_BOT_TOKEN and ADMIN_USER_ID must be set.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # ... (Your ConversationHandlers go here)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin))
    application.add_handler(CallbackQueryHandler(main_callback_handler))

    logger.info("Bot is starting...")
    application.run_polling()

if __name__ == "__main__":
    main()