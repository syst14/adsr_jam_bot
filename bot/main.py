import telebot
import dateparser
import mysql.connector
import json
import time
import pytz
import re
import os
from datetime import datetime
from telebot.types import Poll, PollAnswer
from mysql.connector import Error
import threading
from types import SimpleNamespace

# Replace with your bot's token
API_TOKEN = os.getenv('API_TOKEN')

bot = telebot.TeleBot(API_TOKEN)

# Dictionary to track polls and who voted what
active_polls = {}  # poll_id: {"chat_id": ..., "message_id": ..., "options": [...], "votes": {user_id: option}}

TIMEZONE = "Europe/Kyiv"
tz = pytz.timezone(TIMEZONE)

MAX_RETRIES = 10
RETRY_DELAY = 3  # seconds

db = None
for attempt in range(MAX_RETRIES):
    try:
        db = mysql.connector.connect(
            host="mysql",
            user="root",
            password="rootpass",
            database="telegramdb"
        )
        print("✅ Connected to MySQL")
        break
    except Error as e:
        print(f"❌ MySQL connection failed (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
        time.sleep(RETRY_DELAY)

if db is None or not db.is_connected():
    raise RuntimeError("Failed to connect to MySQL after multiple retries.")

cursor = db.cursor(dictionary=True)

def load_active_polls():
    cursor.execute("SELECT poll_id, poll_data FROM jams")
    for row in cursor.fetchall():
        poll_id = row["poll_id"]
        poll_data = json.loads(row["poll_data"])
        active_polls[poll_id] = poll_data

load_active_polls()

def handle_jam_command(message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    if user_id != "scheduler":
        try:
            member = bot.get_chat_member(chat_id, user_id)
            if member.status not in ["administrator", "creator"]:
                bot.reply_to(message, "🚫 Only group admins can create a jam.")
                return
        except Exception as e:
            bot.reply_to(message, "⚠️ Failed to verify admin status.")
            print("Error checking admin status:", e)
            return

    args = message.text.strip().split()[1:]  # Everything after /jam

    if len(args) < 2:
        bot.reply_to(message, (
            "Usage: /jam <day/date> <time>\n"
            "Examples:\n"
            "/jam Friday 19:30\n"
            "/jam 2025-06-07 18:00\n"
            "/jam tomorrow 20:00"
        ))
        return

    day_part = args[0]
    time_part = args[1]

    # ✅ Time format validation: HH:mm, 24-hour
    if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", time_part):
        bot.reply_to(message, f"❌ Invalid time format: '{time_part}'. Use HH:mm (e.g., 18:30).")
        return

    date_string = f"{day_part} {time_part}"

    jam_datetime = dateparser.parse(
        date_string,
        settings={
            'TIMEZONE': TIMEZONE,
            'RETURN_AS_TIMEZONE_AWARE': True,
            'PREFER_DATES_FROM': 'future'
        }
    )

    if not jam_datetime:
        bot.reply_to(message, f"❌ Could not understand date/time: '{date_string}'")
        return

    # Convert to Kyiv TZ if not already
    if jam_datetime.tzinfo is None:
        jam_datetime = tz.localize(jam_datetime)
    else:
        jam_datetime = jam_datetime.astimezone(tz)

    # Reject if in the past
    now_kyiv = datetime.now(tz)
    if jam_datetime < now_kyiv:
        bot.reply_to(message, f"❌ '{jam_datetime.strftime('%A %H:%M')}' is in the past.")
        return

    # Poll question
    when_str = jam_datetime.strftime("%A at %H:%M")
    question = f"Who's in for the jam on {when_str}?"

    options = ['Drums', 'Bass', 'Leads','FX']

    msg = bot.send_poll(
        chat_id=message.chat.id,
        question=question,
        options=options,
        is_anonymous=False,
        allows_multiple_answers=False
    )
    poll_id = msg.poll.id
    chat_id = message.chat.id
    message_id = msg.message_id

    poll_data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "options": options,
        "votes": {},  # start empty
        "datetime": jam_datetime.isoformat()
    }

    cursor.execute("""
        INSERT INTO jams (poll_id, chat_id, message_id, jam_date, poll_data)
        VALUES (%s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            chat_id = VALUES(chat_id),
            message_id = VALUES(message_id),
            jam_date = VALUES(jam_date),
            poll_data = VALUES(poll_data)
    """, (
        poll_id,
        chat_id,
        message_id,
        jam_datetime,
        json.dumps(poll_data)
    ))
    db.commit()

    active_polls[poll_id] = poll_data


def send_jam_reminders(message):
    tz = pytz.timezone(TIMEZONE)
    today = datetime.now(tz).date()

    cursor.execute("SELECT * FROM jams WHERE DATE(jam_date) = %s", (today,))
    jams_today = cursor.fetchall()

    if not jams_today:
        bot.reply_to(message, "No jams scheduled for today 🎧")
        return

    for jam in jams_today:
        poll_id = jam['poll_id']
        chat_id = jam.get("chat_id")
        message_id = jam.get("message_id")
        mentions = []

        for role in ['drums', 'bass', 'leads', 'fx']:
            user = jam.get(role)
            if user:
                mentions.append(f"*{role.capitalize()}*: @{user}")

        if mentions:
            text = "🎶 *Нагадування про Джем сьогодні!* 🎶\n\n" + "\n".join(mentions)
        else:
            text = "Сьогодні немає участників на джем ❌"

        bot.send_message(
            chat_id,
            text,
            reply_to_message_id=message_id,
            parse_mode="Markdown"
        )


def fetch_empty_role_db(poll_id):
    cursor.execute("SELECT * FROM jams WHERE poll_id = %s", (poll_id,))
    jam_slots = cursor.fetchone()

    role_columns = ["drums", "bass", "leads", "fx"]
    empty_roles = [role.capitalize() for role in role_columns if jam_slots.get(role) is None]
    empty_roles_res = ", ".join(empty_roles)
    return empty_roles_res


@bot.message_handler(commands=['jam'])
def handle_jam(message):
    handle_jam_command(message)

@bot.message_handler(commands=['reminder'])
def handle_reminder(message):
    send_jam_reminders(message)

@bot.poll_answer_handler()
def handle_poll_answer(poll_answer: PollAnswer):
    poll_id = poll_answer.poll_id
    user = poll_answer.user
    user_id = user.id
    username = user.username or user.first_name
    mention = f"[{username}](tg://user?id={user_id})"

    print(active_polls)

    if poll_id not in active_polls:
        return

    poll_info = active_polls[poll_id]
    chat_id = poll_info["chat_id"]
    message_id = poll_info["message_id"]
    options = poll_info["options"]
    votes = poll_info["votes"]  # user_id -> option
    taken_options = {v: uid for uid, v in votes.items()}

    # Map readable option names to DB column names
    column_map = {
        "Drums": "drums",
        "Bass": "bass",
        "Leads": "leads",
        "FX": "fx"
    }

    # Vote was cancelled (empty option_ids)
    if not poll_answer.option_ids:
        old_vote = votes.pop(user_id, None)
        if old_vote:
            # Clear vote in MySQL
            column = column_map.get(old_vote)
            if column:
                cursor.execute(
                    f"UPDATE jams SET {column} = NULL WHERE poll_id = %s",
                    (poll_id,)
                )
                db.commit()

            empty_roles = fetch_empty_role_db(poll_id)
            bot.send_message(
                chat_id=chat_id,
                text=f"{mention} відмінив свою участь ❌ (був *{old_vote}*)\n 🎭 Вільні ролі: {empty_roles}",
                reply_to_message_id=message_id,
                parse_mode="Markdown"
            )
        return

    # New vote
    selected_index = poll_answer.option_ids[0]
    selected_option = options[selected_index]
    current_owner = taken_options.get(selected_option)

    # Option already taken
    if current_owner and current_owner != user_id:
        bot.send_message(
            chat_id=chat_id,
            text=f"{mention}, *{selected_option}* роль вже зайнята. Будь ласка, оберіть іншу 🎭",
            reply_to_message_id=message_id,
            parse_mode="Markdown"
        )
        return

    # If user changed their vote
    previous_vote = votes.get(user_id)
    if previous_vote != selected_option:
        # Remove old vote from DB if needed
        if previous_vote:
            old_column = column_map.get(previous_vote)
            if old_column:
                cursor.execute(
                    f"UPDATE jams SET {old_column} = NULL WHERE poll_id = %s",
                    (poll_id,)
                )

        # Update in-memory vote
        votes[user_id] = selected_option

        # Add new vote to DB
        new_column = column_map.get(selected_option)
        if new_column:
            cursor.execute(
                f"UPDATE jams SET {new_column} = %s WHERE poll_id = %s",
                (username, poll_id)
            )

        db.commit()

        empty_roles = fetch_empty_role_db(poll_id)
        bot.send_message(
            chat_id=chat_id,
            text=f"{mention} обрав *{selected_option}* 🎶\n 🎭 Вільні ролі: {empty_roles}",
            reply_to_message_id=message_id,
            parse_mode="Markdown"
        )


def jam_scheduler():
    has_run_today = False
    while True:
        now = datetime.now(tz)
        if now.weekday() == 1:
            if now.hour == 15 and now.minute == 25 and not has_run_today:
                chat_id = -4869311671  # your group chat ID
                user_id = 'scheduler'  # fake user/admin ID
                jam_input_time = "today 20:00"

                # ✅ Simulate a message object
                fake_message = SimpleNamespace(
                    chat=SimpleNamespace(id=chat_id),
                    from_user=SimpleNamespace(id=user_id, username="scheduler"),
                    text=f"/jam {jam_input_time}",
                    message_id=0
                )

                handle_jam_command(fake_message)
                has_run_today = True
        else:
            has_run_today = False

        time.sleep(3600)

def jam_reminder():
    has_run_today = False
    while True:
        now = datetime.now(tz)
        if now.weekday() == 1:
            if now.hour == 15 and now.minute == 32 and not has_run_today:
                chat_id = -4869311671  # your group chat ID
                user_id = 'scheduler'  # fake user/admin ID
                send_jam_reminders({})
                has_run_today = True
        else:
            has_run_today = False

        time.sleep(3600)

if __name__ == '__main__':
    print("Bot is running...")
    threading.Thread(target=jam_scheduler, daemon=True).start()
    threading.Thread(target=jam_reminder, daemon=True).start()
    print(active_polls)
    bot.polling(
        none_stop=True,
        interval=5,
        timeout=30,
        allowed_updates=["message", "poll", "poll_answer"]
    )
