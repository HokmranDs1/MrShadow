import os
import telebot
import asyncio
import time
import smtplib
import logging
from datetime import datetime, timedelta
from email.message import EmailMessage
from urllib.parse import urlparse, parse_qs
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from telethon.sync import TelegramClient
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import (
    GetMessagesViewsRequest, ReportRequest, ReportSpamRequest, StartBotRequest
)
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon import functions
from telethon.errors import RPCError

logging.getLogger("telethon").setLevel(logging.CRITICAL)
logging.getLogger("telebot").setLevel(logging.CRITICAL)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")

# =============== CONFIG ===============
TOKEN = os.environ.get("BOT_TOKEN", "8831122238:AAGQfDxAGiu6cV__1_e9GAzfIMM3zjE1Ejc")
OWNER_ID = int(os.environ.get("OWNER_ID", "7722835349"))
PORT = int(os.environ.get("PORT", "10000"))

ACCOUNTS_FILE = 'accounts.txt'
ADMINS_FILE = 'admins.txt'
EMAILS_FILE = 'emails.txt'

REPORTS_PER_ACCOUNT = 10
REPORT_DELAY = 0.5
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

bot = telebot.TeleBot(TOKEN)
accounts = {}
admin_accounts = set()
emails = {}
command_history = {}

email_send_state = {}

RATE_LIMIT_COUNT = 2
RATE_LIMIT_WINDOW = 2

if os.path.exists(ACCOUNTS_FILE):
    with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                session_file, api_id, api_hash = line.strip().split(',')
                accounts[session_file] = {'api_id': api_id, 'api_hash': api_hash}

if os.path.exists(ADMINS_FILE):
    with open(ADMINS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                admin_accounts.add(int(line.strip()))

if os.path.exists(EMAILS_FILE):
    with open(EMAILS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                email, password = line.strip().split('|', 1)
                emails[email] = password


def save_admins():
    with open(ADMINS_FILE, 'w', encoding='utf-8') as f:
        for admin_id in admin_accounts:
            f.write(f"{admin_id}\n")


def save_emails():
    with open(EMAILS_FILE, 'w', encoding='utf-8') as f:
        for email, password in emails.items():
            f.write(f"{email}|{password}\n")


def is_rate_limited(user_id):
    if user_id == OWNER_ID:
        return False
    now = datetime.now()
    timestamps = command_history.get(user_id, [])
    timestamps = [t for t in timestamps if now - t < timedelta(seconds=RATE_LIMIT_WINDOW)]
    command_history[user_id] = timestamps
    if len(timestamps) >= RATE_LIMIT_COUNT:
        return True
    command_history[user_id].append(now)
    return False


def check_access(func):
    def wrapper(message):
        if message.from_user.id != OWNER_ID and message.from_user.id not in admin_accounts:
            bot.reply_to(message, "⚠️ You do not have access.")
            return
        if is_rate_limited(message.from_user.id):
            bot.reply_to(message, "🚫 Rate limit exceeded. Please wait.")
            return False
        return func(message)
    return wrapper



@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message,
        "🤖 Hello! I'm Shadow Reporter Bot.\n"
        "For subscription contact Support: @shikh3")


@bot.message_handler(commands=['help'])
@check_access
def help_command(message):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("➕ Add account", callback_data="add"),
        InlineKeyboardButton("➖ Remove account", callback_data="remove"),
        InlineKeyboardButton("📋 List accounts", callback_data="listaccount"),
        InlineKeyboardButton("➕ Add email", callback_data="addemail"),
        InlineKeyboardButton("➖ Remove email", callback_data="removeemail"),
        InlineKeyboardButton("📧 List emails", callback_data="listemail"),
        InlineKeyboardButton("📧 Send emails", callback_data="sendemail"),
        InlineKeyboardButton("🚩 Report", callback_data="report"),
        InlineKeyboardButton("👻 Spam report", callback_data="spamreport"),
        InlineKeyboardButton("👁 Boost views", callback_data="view_post"),
        InlineKeyboardButton("👽 Block user", callback_data="block"),
        InlineKeyboardButton("🔗 Join Gr/Ch", callback_data="join"),
        InlineKeyboardButton("🤖 Referral", callback_data="referral"),
        InlineKeyboardButton("💀 Methods", callback_data="methods")
    )
    bot.send_message(message.chat.id, "Please select an option:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    responses = {
        "add": "Send /add to add a new account (session + api_id + api_hash).",
        "remove": "Send /remove to delete an account.",
        "listaccount": "Send /listaccounts to see connected accounts.",
        "addemail": "Send /addemail and follow instructions.",
        "removeemail": "Send /removeemail to delete an email.",
        "listemail": "Send /listemails to see connected emails.",
        "sendemail": "Send /sendemail - bot will ask you step by step.",
        "report": "Send /report @username, post_id, option (e.g. 72 for scam)",
        "spamreport": "Send /spamreport @channel, post_id",
        "view_post": "Send /view_post @channel, post_id",
        "block": "Send /block @username",
        "join": "Send /join @username or /join https://t.me/+xxxxxx",
        "referral": "Send /referral and provide your referral link.",
        "methods": "Join for methods: https://t.me/+4I_jGUkgzB00Y2Q8"
    }
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, responses.get(call.data, "Unknown command."))




@bot.message_handler(commands=['addadmin'])
def add_admin(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "⚠️ Only owner can do this.")
        return
    bot.reply_to(message, "Send the numeric user ID to add as admin:")
    bot.register_next_step_handler(message, process_add_admin)


def process_add_admin(message):
    try:
        new_id = int(message.text.strip())
        admin_accounts.add(new_id)
        save_admins()
        bot.reply_to(message, f"✅ Admin {new_id} added.")
    except:
        bot.reply_to(message, "❌ Invalid ID.")


@bot.message_handler(commands=['removeadmin'])
def remove_admin(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "⚠️ Only owner can do this.")
        return
    bot.reply_to(message, f"Current admins:\n" + "\n".join(map(str, admin_accounts)) + "\nSend ID to remove:")
    bot.register_next_step_handler(message, process_remove_admin)


def process_remove_admin(message):
    try:
        rid = int(message.text.strip())
        admin_accounts.remove(rid)
        save_admins()
        bot.reply_to(message, f"✅ Admin {rid} removed.")
    except:
        bot.reply_to(message, "❌ Invalid or not found.")



@bot.message_handler(commands=['listaccounts'])
@check_access
def list_accounts(message):
    if not accounts:
        bot.reply_to(message, "No accounts connected.")
        return
    text = f"📋 Connected accounts ({len(accounts)}):\n" + "\n".join(accounts.keys())
    bot.reply_to(message, text)


@bot.message_handler(commands=['add'])
@check_access
def add_account(message):
    bot.reply_to(message, "Send the session file (as document):")
    bot.register_next_step_handler(message, get_session_file)


def get_session_file(message):
    if not message.document or not message.document.file_name.endswith('.session'):
        bot.reply_to(message, "Please send a valid .session file.")
        return
    file_name = message.document.file_name
    file_info = bot.get_file(message.document.file_id)
    downloaded = bot.download_file(file_info.file_path)
    with open(file_name, 'wb') as f:
        f.write(downloaded)
    bot.reply_to(message, "Send api_id:")
    bot.register_next_step_handler(message, get_api_id_step, file_name)


def get_api_id_step(message, file_name):
    if not message.text.isdigit():
        bot.reply_to(message, "api_id must be numeric.")
        return
    api_id = message.text.strip()
    bot.reply_to(message, "Send api_hash:")
    bot.register_next_step_handler(message, save_account, file_name, api_id)


def save_account(message, file_name, api_id):
    api_hash = message.text.strip()
    accounts[file_name] = {'api_id': api_id, 'api_hash': api_hash}
    with open(ACCOUNTS_FILE, 'a', encoding='utf-8') as f:
        f.write(f"{file_name},{api_id},{api_hash}\n")
    bot.reply_to(message, f"✅ Account {file_name} added successfully.")


@bot.message_handler(commands=['remove'])
def remove_account(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "Only owner can remove accounts.")
        return
    if not accounts:
        bot.reply_to(message, "No accounts.")
        return
    bot.reply_to(message, "Available accounts:\n" + "\n".join(accounts.keys()) + "\nSend session name to delete:")
    bot.register_next_step_handler(message, process_remove)


def process_remove(message):
    name = message.text.strip()
    if name not in accounts:
        bot.reply_to(message, "Not found.")
        return
    if os.path.exists(name):
        try:
            os.remove(name)
        except:
            pass
    accounts.pop(name)
    with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
        for k, v in accounts.items():
            f.write(f"{k},{v['api_id']},{v['api_hash']}\n")
    bot.reply_to(message, f"{name} removed.")



@bot.message_handler(commands=['listemails'])
@check_access
def list_emails(message):
    if not emails:
        bot.reply_to(message, "No emails connected.")
        return
    text = f"📧 Connected emails ({len(emails)}):\n" + "\n".join(emails.keys())
    bot.reply_to(message, text)


@bot.message_handler(commands=['addemail'])
@check_access
def add_email(message):
    msg = bot.send_message(message.chat.id, "📧 Send the email address (e.g. example@gmail.com):")
    bot.register_next_step_handler(msg, process_add_email_step1)


def process_add_email_step1(message):
    email = (message.text or "").strip()
    if '@' not in email or '.' not in email:
        bot.reply_to(message, "❌ Invalid email format.")
        return
    if email in emails:
        bot.reply_to(message, "❌ Email already exists.")
        return
    msg = bot.send_message(message.chat.id, "🔑 Send the app password (Google App Password):")
    bot.register_next_step_handler(msg, process_add_email_step2, email)


def process_add_email_step2(message, email):
    password = (message.text or "").strip()
    if len(password) < 4:
        bot.reply_to(message, "❌ Password too short.")
        return
    emails[email] = password
    save_emails()
    bot.reply_to(message, f"✅ Email {email} added successfully.")


@bot.message_handler(commands=['removeemail'])
def remove_email_cmd(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "Only owner can remove emails.")
        return
    if not emails:
        bot.reply_to(message, "No emails.")
        return
    bot.reply_to(message, "Available emails:\n" + "\n".join(emails.keys()) + "\nSend email to delete:")
    bot.register_next_step_handler(message, process_remove_email)


def process_remove_email(message):
    email = (message.text or "").strip()
    if email not in emails:
        bot.reply_to(message, "Not found.")
        return
    emails.pop(email)
    save_emails()
    bot.reply_to(message, f"✅ {email} removed.")



def send_email_blocking(email_from, password, target, subject, body):
    try:
        msg = EmailMessage()
        msg["From"] = email_from
        msg["To"] = target
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.login(email_from, password)
            server.send_message(msg)
        return True, None
    except Exception as e:
        return False, str(e)


@bot.message_handler(commands=['sendemail'])
@check_access
def send_email_cmd(message):
    if not emails:
        bot.reply_to(message, "❌ No emails available. Add some first with /addemail")
        return

    uid = message.from_user.id
    email_send_state[uid] = {"step": "waiting_target"}
    msg = bot.send_message(message.chat.id,
        "📧 *Send Bulk Email*\n\n"
        "Step 1/4: Send the *target email address* (e.g. victim@example.com):",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(msg, process_email_target)


def process_email_target(message):
    uid = message.from_user.id
    if uid not in email_send_state:
        return
    target = (message.text or "").strip()
    if '@' not in target or '.' not in target:
        bot.reply_to(message, "❌ Invalid email format. Send /sendemail to restart.")
        email_send_state.pop(uid, None)
        return

    email_send_state[uid]["target"] = target
    email_send_state[uid]["step"] = "waiting_subject"
    msg = bot.send_message(message.chat.id,
        f"✅ Target: {target}\n\n"
        "Step 2/4: Send the *email subject*:")
    bot.register_next_step_handler(msg, process_email_subject)


def process_email_subject(message):
    uid = message.from_user.id
    if uid not in email_send_state:
        return
    subject = (message.text or "").strip()
    if not subject:
        bot.reply_to(message, "❌ Subject cannot be empty. Send /sendemail to restart.")
        email_send_state.pop(uid, None)
        return

    email_send_state[uid]["subject"] = subject
    email_send_state[uid]["step"] = "waiting_body"
    msg = bot.send_message(message.chat.id,
        "✅ Subject saved.\n\n"
        "Step 3/4: Send the *email body*:\n")
    bot.register_next_step_handler(msg, process_email_body)


def process_email_body(message):
    uid = message.from_user.id
    if uid not in email_send_state:
        return
    body = message.text or ""
    if not body.strip():
        bot.reply_to(message, "❌ Body cannot be empty. Send /sendemail to restart.")
        email_send_state.pop(uid, None)
        return

    state = email_send_state[uid]
    target = state["target"]
    subject = state["subject"]
    body_length = len(body)

    msg = bot.send_message(message.chat.id,
        f"📋 *Confirm sending:*\n\n"
        f"📨 Target: {target}\n"
        f"📝 Subject: {subject}\n"
        f"📄 Body length: {body_length} characters\n"
        f"📧 Using {len(emails)} sender(s)\n\n"
        f"Step 4/4: Confirm? Send *'yes'* to send, *'no'* to cancel.")
    bot.register_next_step_handler(msg, process_email_confirm, body)


def process_email_confirm(message, body):
    uid = message.from_user.id
    if uid not in email_send_state:
        return
    ans = (message.text or "").strip().lower()
    if ans not in ("yes", "y"):
        bot.reply_to(message, "🚫 Cancelled.")
        email_send_state.pop(uid, None)
        return

    state = email_send_state[uid]
    target = state["target"]
    subject = state["subject"]
    email_send_state.pop(uid, None)

    status_msg = bot.send_message(message.chat.id, "📧 Starting email sending...")
    asyncio.run(send_bulk_emails(target, subject, body, status_msg))


async def send_bulk_emails(target, subject, body, status_msg):
    sent = 0
    failed = 0
    total = len(emails)
    results = []

    for idx, (email_from, password) in enumerate(emails.items(), start=1):
        try:
            bot.edit_message_text(
                f"📧 *Sending emails...*\n\n"
                f"📤 Sent: {sent}\n"
                f"❌ Failed: {failed}\n"
                f"🔄 Progress: {idx}/{total}\n"
                f"📨 Target: {target}",
                status_msg.chat.id,
                status_msg.message_id,
                parse_mode="Markdown"
            )
        except:
            pass

        loop = asyncio.get_event_loop()
        ok, error = await loop.run_in_executor(
            None, send_email_blocking, email_from, password, target, subject, body
        )

        if ok:
            sent += 1
            results.append(f"✅ {email_from}")
        else:
            failed += 1
            results.append(f"❌ {email_from}: {error[:60] if error else 'unknown'}")

        await asyncio.sleep(1)

    final_text = (
        f"✅ *Email sending completed!*\n\n"
        f"📤 Sent: {sent}\n"
        f"❌ Failed: {failed}\n"
        f"📨 Target: {target}\n"
        f"📝 Subject: {subject}\n\n"
    )
    if len(results) > 15:
        final_text += f"\n... and {len(results) - 15} more"

    try:
        bot.edit_message_text(
            final_text,
            status_msg.chat.id,
            status_msg.message_id,
            parse_mode="Markdown"
        )
    except:
        bot.send_message(status_msg.chat.id, final_text, parse_mode="Markdown")



async def block_on_all_accounts(username):
    results = []
    for session, info in accounts.items():
        client = None
        try:
            client = TelegramClient(session, int(info['api_id']), info['api_hash'])
            await client.start()
            user_entity = await client.get_entity(username)
            await client(functions.contacts.BlockRequest(user_entity))
            results.append(f"✅ Blocked {username}: {session}")
        except Exception as e:
            results.append(f"❌ {session}: {str(e)[:80]}")
        finally:
            if client:
                try:
                    await client.disconnect()
                except:
                    pass
    return results


@bot.message_handler(commands=['block'])
def block_command(message):
    if message.from_user.id not in admin_accounts and message.from_user.id != OWNER_ID:
        bot.reply_to(message, "⚠️ You do not have access.")
        return
    if not accounts:
        bot.reply_to(message, "There are no accounts available to block users.")
        return
    bot.reply_to(message, "Send the user target (format: @username):")
    bot.register_next_step_handler(message, process_block)


def process_block(message):
    target_username = message.text.strip()
    if not target_username.startswith('@'):
        bot.reply_to(message, "❌ Username must start with @.")
        return
    bot.reply_to(message, "⏳ Processing...")
    results = asyncio.run(block_on_all_accounts(target_username))
    bot.send_message(message.chat.id, "\n".join(results) or "No results.")


async def do_report(username, post_id, option, sender_id):
    results = []
    successful_reports = 0
    for session, info in accounts.items():
        client = None
        try:
            client = TelegramClient(session, int(info['api_id']), info['api_hash'])
            await client.start()
            for _ in range(REPORTS_PER_ACCOUNT):
                await client(ReportRequest(
                    peer=username,
                    id=[post_id],
                    option=option.encode(),
                    message="Violation report"
                ))
                successful_reports += 1
                await asyncio.sleep(REPORT_DELAY)
            results.append(f"✅ {session} ({REPORTS_PER_ACCOUNT} reports)")
        except Exception as e:
            results.append(f"❌ {session}: {str(e)[:80]}")
        finally:
            if client:
                try:
                    await client.disconnect()
                except:
                    pass

    report_text = (
        f"✅ Reports sent!\n"
        f"📊 Total: {successful_reports}\n"
        f"📤 Username: {username}\n"
        f"📄 Post: {post_id}\n\n"
        f"Details:\n" + "\n".join(results)
    )
    bot.send_message(sender_id, report_text)


@bot.message_handler(commands=['report'])
@check_access
def report_command(message):
    bot.reply_to(message, "Format: @channel, post_id, option\nExample: @testchannel, 10, 72 (72 = scam)")
    bot.register_next_step_handler(message, process_report)


def process_report(message):
    parts = [p.strip() for p in message.text.split(',')]
    if len(parts) != 3 or not parts[0].startswith('@'):
        bot.reply_to(message, "Invalid format.")
        return
    username, post_id_str, option = parts
    try:
        post_id = int(post_id_str)
    except:
        bot.reply_to(message, "Post ID must be a number.")
        return
    bot.reply_to(message, "⏳ Processing...")
    asyncio.run(do_report(username, post_id, option, message.from_user.id))


async def do_spamreport(username, post_id, sender_id):
    results = []
    for session, info in accounts.items():
        client = None
        try:
            client = TelegramClient(session, int(info['api_id']), info['api_hash'])
            await client.start()
            await client(ReportSpamRequest(peer=username))
            await client(GetMessagesViewsRequest(peer=username, id=[post_id], increment=True))
            results.append(f"✅ Spam + view: {session}")
        except Exception as e:
            results.append(f"❌ {session}: {str(e)[:80]}")
        finally:
            if client:
                try:
                    await client.disconnect()
                except:
                    pass
    bot.send_message(sender_id, "✅ Spam reports:\n" + "\n".join(results))


@bot.message_handler(commands=['spamreport'])
@check_access
def spamreport_command(message):
    bot.reply_to(message, "Send: @channel, post_id")
    bot.register_next_step_handler(message, process_spamreport)


def process_spamreport(message):
    parts = [p.strip() for p in message.text.split(',')]
    if len(parts) != 2 or not parts[0].startswith('@'):
        bot.reply_to(message, "Invalid format.")
        return
    username, post_id_str = parts
    try:
        post_id = int(post_id_str)
    except:
        bot.reply_to(message, "Invalid post ID.")
        return
    bot.reply_to(message, "⏳ Processing...")
    asyncio.run(do_spamreport(username, post_id, message.from_user.id))


async def do_view_post(username, post_id, sender_id):
    results = []
    successful_views = 0
    for session, info in accounts.items():
        client = None
        try:
            client = TelegramClient(session, int(info['api_id']), info['api_hash'])
            await client.start()
            await client(GetMessagesViewsRequest(peer=username, id=[post_id], increment=True))
            successful_views += 1
            results.append(f"✅ View: {session}")
            await asyncio.sleep(1)
        except Exception as e:
            results.append(f"❌ {session}: {str(e)[:80]}")
        finally:
            if client:
                try:
                    await client.disconnect()
                except:
                    pass
    bot.send_message(sender_id, f"✅ Views boosted: +{successful_views}\n\n" + "\n".join(results))


@bot.message_handler(commands=['view_post'])
@check_access
def view_post_command(message):
    bot.reply_to(message, "Send: @channel, post_id")
    bot.register_next_step_handler(message, process_view_post)


def process_view_post(message):
    parts = [p.strip() for p in message.text.split(',')]
    if len(parts) != 2 or not parts[0].startswith('@'):
        bot.reply_to(message, "Invalid format.")
        return
    username, post_id_str = parts
    try:
        post_id = int(post_id_str)
    except:
        bot.reply_to(message, "Invalid post ID.")
        return
    bot.reply_to(message, "⏳ Processing...")
    asyncio.run(do_view_post(username, post_id, message.from_user.id))


async def do_join_normal(username, sender_id):
    results = []
    for session, info in accounts.items():
        client = None
        try:
            client = TelegramClient(session, int(info['api_id']), info['api_hash'])
            await client.start()
            await client(JoinChannelRequest(channel=username))
            results.append(f"✅ Joined: {session}")
        except Exception as e:
            results.append(f"❌ {session}: {str(e)[:80]}")
        finally:
            if client:
                try:
                    await client.disconnect()
                except:
                    pass
    bot.send_message(sender_id, "✅ Join:\n" + "\n".join(results))


async def do_join_fake(hash_part, sender_id):
    results = []
    for session, info in accounts.items():
        client = None
        try:
            client = TelegramClient(session, int(info['api_id']), info['api_hash'])
            await client.start()
            await client(ImportChatInviteRequest(hash_part))
            results.append(f"✅ Fake join: {session}")
        except Exception as e:
            results.append(f"❌ {session}: {str(e)[:80]}")
        finally:
            if client:
                try:
                    await client.disconnect()
                except:
                    pass
    bot.send_message(sender_id, "✅ Fake join:\n" + "\n".join(results))


@bot.message_handler(commands=['join'])
@check_access
def join_command(message):
    bot.reply_to(message, "Send username (@username) or private invite link (https://t.me/+xxxx):")
    bot.register_next_step_handler(message, process_join)


def process_join(message):
    target = message.text.strip()
    if target.startswith('https://t.me/+'):
        hash_part = target.split('/')[-1]
        bot.reply_to(message, "⏳ Processing...")
        asyncio.run(do_join_fake(hash_part, message.from_user.id))
    elif target.startswith('@') or (not target.startswith('http') and target):
        username = target.lstrip('@')
        bot.reply_to(message, "⏳ Processing...")
        asyncio.run(do_join_normal(username, message.from_user.id))
    else:
        bot.reply_to(message, "❌ Invalid format!")



async def do_referral(bot_username, start_param, sender_id):
    results = []
    successful = 0
    total = len(accounts)

    for session, info in accounts.items():
        client = None
        try:
            client = TelegramClient(session, int(info['api_id']), info['api_hash'])
            await client.start()
            bot_entity = await client.get_entity(bot_username)
            await client(StartBotRequest(
                bot=bot_entity,
                peer=bot_entity,
                start_param=start_param
            ))
            successful += 1
            results.append(f"✅ Started: {session}")
            await asyncio.sleep(1)
        except Exception as e:
            results.append(f"❌ {session}: {str(e)[:80]}")
        finally:
            if client:
                try:
                    await client.disconnect()
                except:
                    pass

    bot.send_message(
        sender_id,
        f"✅ Referral completed!\n"
        f"🤖 Bot: @{bot_username}\n"
        f"🔑 Param: {start_param}\n"
        f"✅ Success: {successful}/{total}\n\n"
        + "\n".join(results)
    )


@bot.message_handler(commands=['referral'])
@check_access
def referral_command(message):
    if not accounts:
        bot.reply_to(message, "❌ No accounts available. Add accounts first with /add")
        return
    bot.reply_to(message,
    "🎯 *Referral Bot Starter*\n\n"
    "Send your referral link:\n"
    "Example: `https://t.me/usernamebot?start=ref_5883954452`",
    parse_mode="Markdown"
)
    bot.register_next_step_handler(message, process_referral)


def process_referral(message):
    link = (message.text or "").strip()
    parsed = urlparse(link)

    if parsed.netloc not in ('t.me', 'telegram.me'):
        bot.reply_to(message, "❌ Invalid link. Must be: https://t.me/botname?start=xxx")
        return

    bot_username = parsed.path.strip('/')
    if not bot_username:
        bot.reply_to(message, "❌ Could not extract bot username from link.")
        return

    params = parse_qs(parsed.query)
    start_param = params.get('start', [''])[0]

    if not start_param:
        bot.reply_to(message, "❌ No start parameter found. Link must contain ?start=xxx")
        return

    bot.reply_to(
        message,
        f"⏳ Starting @{bot_username} with {start_param} on all {len(accounts)} account(s)..."
    )
    asyncio.run(do_referral(bot_username, start_param, message.from_user.id))


from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is running!")

    def log_message(self, *args):
        pass


def start_http():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    logging.info(f"HTTP server on port {PORT}")
    server.serve_forever()


# =============== RUN ===============
if __name__ == "__main__":
    Thread(target=start_http, daemon=True).start()
    logging.info("Bot started.")
    try:
        bot.polling(none_stop=True, interval=0, timeout=60)
    except Exception as e:
        logging.error(f"Polling error: {e}")
        time.sleep(5)
        bot.polling(none_stop=True)
