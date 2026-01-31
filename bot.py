import logging
import json
import os
import asyncio
from datetime import datetime, time, timedelta

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from telegram.request import HTTPXRequest
from dotenv import load_dotenv

from diary_manager import DiaryManager

# Load environment variables
load_dotenv()

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
# Make httpx logging more visible to catch network errors
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Config loading
CONFIG_FILE = 'config.json'

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

config = load_config()

# Constants from config
CHECK_INTERVAL = config.get('check_interval_minutes', 30)
SLEEP_START = config.get('sleep_start_time', "23:30")
SLEEP_END = config.get('sleep_end_time', "09:30")
SUMMARY_TIME = config.get('daily_summary_time', "00:00")
PROMPT_TEMPLATE = config.get('prompt_message', "{name}，过去 {interval} 分钟你在干什么？有什么感想？")
ADMIN_NAME = config.get('admin_name', "zy")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID")

if ALLOWED_USER_ID:
    ALLOWED_USER_ID = int(ALLOWED_USER_ID)

# Global state
is_paused = False
diary = DiaryManager()
scheduler = AsyncIOScheduler()

def is_sleeping_time():
    """Check if current time is within sleep range."""
    now = datetime.now().time()
    try:
        start_t = datetime.strptime(SLEEP_START, "%H:%M").time()
        end_t = datetime.strptime(SLEEP_END, "%H:%M").time()
    except ValueError:
        logger.error("Invalid time format in config")
        return False

    if start_t > end_t:
        return now >= start_t or now <= end_t
    else:
        return start_t <= now <= end_t

async def send_long_message(bot, chat_id, text):
    """Send text, splitting it if it exceeds Telegram's limit."""
    MAX_LENGTH = 4096
    if len(text) <= MAX_LENGTH:
        try:
            await bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
        return

    # Split by lines to avoid breaking words if possible
    lines = text.split('\n')
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) + 1 > MAX_LENGTH:
            try:
                await bot.send_message(chat_id=chat_id, text=chunk)
            except Exception as e:
                logger.error(f"Failed to send chunk: {e}")
            chunk = line + "\n"
        else:
            chunk += line + "\n"
    
    if chunk:
        try:
            await bot.send_message(chat_id=chat_id, text=chunk)
        except Exception as e:
            logger.error(f"Failed to send final chunk: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a welcome message."""
    user = update.effective_user
    if ALLOWED_USER_ID and user.id != ALLOWED_USER_ID:
        await update.message.reply_text("Sorry, I am a private bot.")
        return
    
    await update.message.reply_text(
        f"Hi {user.first_name}! I'm Reflect-30.\n"
        f"I will ask you what you are doing every {CHECK_INTERVAL} minutes.\n"
        f"Sleep time is {SLEEP_START} to {SLEEP_END}.\n"
        f"Daily summary at {SUMMARY_TIME}.\n"
        "Commands: /pause, /continue, /stop"
    )

async def pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_paused
    is_paused = True
    await update.message.reply_text("Paused. I won't message you until you /continue.")

async def resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_paused
    is_paused = False
    await update.message.reply_text("Resumed. Monitoring started.")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_paused
    is_paused = True
    await update.message.reply_text("Stopped. (Same as paused). Use /continue to restart.")

async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually trigger a summary. Usage: /summary [YYYYMMDD]"""
    user = update.effective_user
    if ALLOWED_USER_ID and user.id != ALLOWED_USER_ID:
        return

    target_date = datetime.now()
    
    # Check for arguments
    if context.args:
        date_input = context.args[0]
        try:
            # Parse YYYYMMDD
            target_date = datetime.strptime(date_input, "%Y%m%d")
        except ValueError:
            await update.message.reply_text("❌ Invalid date format. Please use YYYYMMDD, e.g., /summary 20260120")
            return

    date_str = target_date.strftime("%Y-%m-%d")
    entries = diary.get_entries_for_day(date_str)

    if not entries:
        summary_text = f"📅 Summary for {date_str}:\nNo entries found."
    else:
        summary_text = f"📅 Summary for {date_str}:\n\n"
        for entry in entries:
            ts = datetime.fromisoformat(entry['timestamp'])
            time_str = ts.strftime("%H:%M")
            summary_text += f"⏰ {time_str}: {entry['content']}\n"
    
    await send_long_message(context.bot, update.effective_chat.id, summary_text)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if ALLOWED_USER_ID and user.id != ALLOWED_USER_ID:
        return

    text = update.message.text
    if text:
        diary.add_entry(text)
        await update.message.reply_text(f"Recorded at {datetime.now().strftime('%H:%M')}.")

async def periodic_check(application: Application):
    """Task to check if we should send a reminder."""
    global is_paused
    if is_paused:
        return
    
    if is_sleeping_time():
        return

    if not ALLOWED_USER_ID:
        return

    message = PROMPT_TEMPLATE.format(name=ADMIN_NAME, interval=CHECK_INTERVAL)
    try:
        await application.bot.send_message(chat_id=ALLOWED_USER_ID, text=message)
    except Exception as e:
        logger.error(f"Failed to send periodic message: {e}")

async def send_daily_summary(application: Application):
    """Send daily summary."""
    if not ALLOWED_USER_ID:
        return
    
    # Determine which day to summarize
    # If running at 00:00, summarize yesterday
    # If running late in the day, summarize today
    now = datetime.now()
    if now.hour < 12:
        target_date = now - timedelta(days=1)
    else:
        target_date = now
    
    date_str = target_date.strftime("%Y-%m-%d")
    entries = diary.get_entries_for_day(date_str)
    
    if not entries:
        summary_text = f"📅 Summary for {date_str}:\nNo entries found."
    else:
        summary_text = f"📅 Summary for {date_str}:\n\n"
        for entry in entries:
            # Parse timestamp to show only time
            ts = datetime.fromisoformat(entry['timestamp'])
            time_str = ts.strftime("%H:%M")
            summary_text += f"⏰ {time_str}: {entry['content']}\n"

    await send_long_message(application.bot, ALLOWED_USER_ID, summary_text)

async def post_init(application: Application):
    """Send a startup message to the admin."""
    if ALLOWED_USER_ID:
        try:
            await application.bot.send_message(chat_id=ALLOWED_USER_ID, text="Reflect-30 Bot 启动成功！🚀")
        except Exception as e:
            logger.error(f"Failed to send startup message: {e}")

    # Add periodic job
    scheduler.add_job(
        periodic_check, 
        IntervalTrigger(minutes=CHECK_INTERVAL), 
        kwargs={"application": application}
    )
    
    # Add daily summary job
    # Parse HH:MM from config for cron trigger
    try:
        sh, sm = map(int, SUMMARY_TIME.split(':'))
        scheduler.add_job(
            send_daily_summary,
            CronTrigger(hour=sh, minute=sm),
            kwargs={"application": application}
        )
    except ValueError:
        logger.error("Invalid DAILY_SUMMARY_TIME format. Using default 00:00")
        scheduler.add_job(
            send_daily_summary,
            CronTrigger(hour=0, minute=0),
            kwargs={"application": application}
        )
    
    scheduler.start()

def main():
    if not TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not found in environment variables.")
        return

    # Configure request with timeouts
    request = HTTPXRequest(
        connection_pool_size=8,
        read_timeout=60,
        write_timeout=60,
        connect_timeout=30,
        pool_timeout=None
    )

    # Build application
    application = Application.builder().token(TOKEN).request(request).post_init(post_init).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("pause", pause))
    application.add_handler(CommandHandler("continue", resume))
    application.add_handler(CommandHandler("resume", resume)) # Alias
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("summary", summary))
    
    
    # Text handler (exclude commands)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Run bot
    print("Bot started...")
    print("Bot started...")
    # More robust polling parameters
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        timeout=30,  # Polling timeout
        poll_interval=1.0 # Check for updates every 1 second
    )

if __name__ == '__main__':
    main()
