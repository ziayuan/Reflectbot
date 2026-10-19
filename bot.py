import logging
import json
import os
import asyncio
from urllib.parse import urlsplit, urlunsplit, unquote

import httpx
from datetime import datetime, time, timedelta, timezone

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest
from dotenv import load_dotenv

from diary_manager import DiaryManager
from reminder_schedule import ReminderSchedule

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
CHECK_INTERVAL = config.get('check_interval_minutes', 60)
REMINDER_ATTEMPTS = config.get('reminder_attempts', 5)
RETRY_SECONDS = config.get('reminder_retry_seconds', 60)
SLEEP_START = config.get('sleep_start_time', "23:30")
SLEEP_END = config.get('sleep_end_time', "09:30")
SUMMARY_TIME = config.get('daily_summary_time', "00:00")
PROMPT_TEMPLATE = config.get('prompt_message', "{name}，过去 {interval} 分钟你在干什么？有什么感想？")
ADMIN_NAME = config.get('admin_name', "zy")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID")
BARK_URL = os.getenv("BARK_URL", "").strip()
BARK_OPEN_URL = os.getenv("BARK_OPEN_URL", "").strip()

if ALLOWED_USER_ID:
    ALLOWED_USER_ID = int(ALLOWED_USER_ID)

# Timezone handling
# Explicitly use Beijing Time (UTC+8) to avoid server timezone issues
BEIJING_TZ = timedelta(hours=8)

def get_now():
    """Get current time in Beijing Time."""
    # Use timezone-aware datetime
    return datetime.now(timezone(BEIJING_TZ))


# Global state
schedule = None
diary = DiaryManager()

def is_sleeping_time():
    """Check if current time is within sleep range."""
    # Use Beijing Time
    now = get_now().time()
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

async def send_bark(title, body):
    """Send a Bark notification without exposing the device key in logs."""
    if not BARK_URL:
        return
    parsed = urlsplit(BARK_URL)
    prefix, _, device_key = parsed.path.rstrip("/").rpartition("/")
    if parsed.scheme != "https" or not parsed.netloc or not device_key:
        logger.error("BARK_URL must be an HTTPS URL ending with the device key")
        return
    endpoint = urlunsplit((parsed.scheme, parsed.netloc, prefix + "/push", "", ""))
    payload = {
        "device_key": unquote(device_key),
        "title": title, "body": body, "group": "Reflectbot",
    }
    if BARK_OPEN_URL:
        payload["url"] = BARK_OPEN_URL
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(endpoint, json=payload)
            response.raise_for_status()
            if response.json().get("code") != 200:
                logger.error("Bark rejected notification")
    except Exception as exc:
        # HTTP client exceptions can contain the secret URL. Log only the type.
        logger.error("Bark notification failed (%s)", type(exc).__name__)


async def send_notification(bot, title, body):
    """Deliver independently so either channel can succeed if the other fails."""
    tasks = [send_bark(title, body)]
    if ALLOWED_USER_ID:
        tasks.append(send_long_message(bot, ALLOWED_USER_ID, body))
    await asyncio.gather(*tasks)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a welcome message."""
    user = update.effective_user
    if ALLOWED_USER_ID and user.id != ALLOWED_USER_ID:
        await update.message.reply_text("Sorry, I am a private bot.")
        return
    
    await update.message.reply_text(
        f"Hi {user.first_name}! I'm Reflect-30.\n"
        f"回复后 {CHECK_INTERVAL} 分钟提醒；未回复则每 {RETRY_SECONDS // 60} 分钟提醒，共 {REMINDER_ATTEMPTS} 次。\n"
        f"之后再等 {CHECK_INTERVAL} 分钟开始下一轮。\n"
        f"Sleep time is {SLEEP_START} to {SLEEP_END}.\n"
        f"Daily summary at {SUMMARY_TIME}.\n"
        "Commands: /pause, /continue, /stop"
    )

async def pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ALLOWED_USER_ID and update.effective_user.id != ALLOWED_USER_ID:
        return
    schedule.pause()
    await update.message.reply_text("Paused. I won't message you until you /continue.")

async def resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ALLOWED_USER_ID and update.effective_user.id != ALLOWED_USER_ID:
        return
    schedule.resume(get_now())
    await update.message.reply_text("Resumed. Monitoring started.")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ALLOWED_USER_ID and update.effective_user.id != ALLOWED_USER_ID:
        return
    schedule.pause()
    await update.message.reply_text("Stopped. (Same as paused). Use /continue to restart.")

async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually trigger a summary. Usage: /summary [YYYYMMDD]"""
    user = update.effective_user
    if ALLOWED_USER_ID and user.id != ALLOWED_USER_ID:
        return

    target_date = get_now()
    
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
            try:
                ts = datetime.fromisoformat(entry['timestamp'])
                # If timestamp is naive, assume it's Beijing Time (legacy data or previously captured)
                # If accurate, adjust display
                time_str = ts.strftime("%H:%M")
            except:
                 time_str = "??"
            summary_text += f"⏰ {time_str}: {entry['content']}\n"
    
    await send_long_message(context.bot, update.effective_chat.id, summary_text)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if ALLOWED_USER_ID and user.id != ALLOWED_USER_ID:
        return

    text = update.message.text
    if text:
        diary.add_entry(text)
        replied_at = update.message.date or get_now()
        schedule.replied(replied_at)
        next_time = schedule.next_due.astimezone(timezone(BEIJING_TZ)).strftime('%H:%M')
        await update.message.reply_text(
            f"已记录。下次提醒：{next_time}（北京时间，免打扰时段内顺延）。"
        )

async def periodic_check(context: ContextTypes.DEFAULT_TYPE):
    """Check the persisted deadline; both channels share one reply timer."""
    if not schedule.take_due(get_now(), sleeping=is_sleeping_time()):
        return
    message = PROMPT_TEMPLATE.format(name=ADMIN_NAME, interval=CHECK_INTERVAL)
    await send_notification(context.bot, "每小时反思提醒", message)

async def send_daily_summary(context: ContextTypes.DEFAULT_TYPE):
    """Send daily summary."""
    if not ALLOWED_USER_ID:
        return
    
    # Determine which day to summarize
    # If running at 00:00 (Check scheduled time logic), summarize yesterday
    # Assuming job runs at SUMMARY_TIME Beijing Time
    
    now = get_now()
    # Logic: if now is close to 00:00, we want previous day summary
    # Or strict check: if hour < 12, assume it's early morning summary of previous day
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
            try:
                # Parse timestamp
                ts = datetime.fromisoformat(entry['timestamp'])
                time_str = ts.strftime("%H:%M")
            except:
                time_str = "??"
            summary_text += f"⏰ {time_str}: {entry['content']}\n"

    await send_notification(context.bot, "每日反思总结", summary_text)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log errors caused by Updates."""
    logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)

async def post_init(application: Application):
    """Restore reminder state and register reminder/summary jobs."""
    global schedule
    schedule = ReminderSchedule(
        "reminder_state.json", get_now(), CHECK_INTERVAL,
        REMINDER_ATTEMPTS, RETRY_SECONDS,
    )
    await send_notification(
        application.bot, "Reflectbot 已启动",
        f"Reflectbot 已启动：回复后 {CHECK_INTERVAL} 分钟提醒；未回复则每 "
        f"{RETRY_SECONDS // 60} 分钟提醒，共 {REMINDER_ATTEMPTS} 次，随后再等 "
        f"{CHECK_INTERVAL} 分钟开始下一轮。北京时间 {SLEEP_START}–{SLEEP_END} 免打扰。",
    )
    application.job_queue.run_repeating(
        periodic_check, interval=5, first=1,
    )

    # Add daily summary job
    try:
        sh, sm = map(int, SUMMARY_TIME.split(':'))
        target_time = time(hour=sh, minute=sm, tzinfo=timezone(BEIJING_TZ))
    except ValueError:
        logger.error("Invalid DAILY_SUMMARY_TIME format. Using default 00:00")
        target_time = time(hour=0, minute=0, tzinfo=timezone(BEIJING_TZ))
    
    application.job_queue.run_daily(
        send_daily_summary,
        time=target_time,
    )
    logger.info("Jobs scheduled: reply-based %smin, %s attempts every %ss, next due %s, daily summary at %s",
                CHECK_INTERVAL, REMINDER_ATTEMPTS, RETRY_SECONDS, schedule.next_due.isoformat(), target_time)

def main():
    if not TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not found in environment variables.")
        return

    # Configure request with timeouts
    request = HTTPXRequest(
        connection_pool_size=8,
        read_timeout=30,
        write_timeout=30,
        connect_timeout=20,
        pool_timeout=10,
        http_version="1.1",
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

    # Global error handler — makes all polling/network errors visible in logs
    application.add_error_handler(error_handler)

    # Run bot
    logger.info("Bot starting...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
        timeout=30,
        poll_interval=2.0,
    )

if __name__ == '__main__':
    main()
