# =============================
# TELEGRAM RAFFLE BOT
# Один файл
# aiogram 3 + CryptoBot AutoPay
# =============================

import asyncio
import random
import aiohttp
import aiosqlite
import os

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

# =============================
# LOAD ENV
# =============================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CRYPTO_TOKEN = os.getenv("CRYPTO_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

# =============================
# SETTINGS
# =============================

DB_NAME = "raffle.db"
TICKET_PRICE = 0.1

# =============================
# BOT
# =============================

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# =============================
# MEMORY
# =============================

waiting_ticket_amount = {}
current_raffle = None

# =============================
# DATABASE
# =============================

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:

        await db.execute("""
        CREATE TABLE IF NOT EXISTS raffle (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prize TEXT,
            active INTEGER DEFAULT 1
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            tickets INTEGER
        )
        """)

        await db.commit()

# =============================
# CRYPTOBOT
# =============================

async def create_invoice(amount):

    url = "https://pay.crypt.bot/api/createInvoice"

    headers = {
        "Crypto-Pay-API-Token": CRYPTO_TOKEN
    }

    payload = {
        "asset": "USDT",
        "amount": str(amount)
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json=payload,
            headers=headers
        ) as response:

            data = await response.json()
            return data["result"]

async def check_invoice(invoice_id):

    url = f"https://pay.crypt.bot/api/getInvoices?invoice_ids={invoice_id}"

    headers = {
        "Crypto-Pay-API-Token": CRYPTO_TOKEN
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(
            url,
            headers=headers
        ) as response:

            data = await response.json()

            return data["result"]["items"][0]["status"]

# =============================
# START
# =============================

@dp.message(Command("start"))
async def start(message: Message):

    await message.answer(
        "🎟 Добро пожаловать в бот розыгрышей!"
    )

# =============================
# CREATE RAFFLE
# /create 500$
# =============================

@dp.message(Command("create"))
async def create_raffle(message: Message):

    global current_raffle

    if message.from_user.id != ADMIN_ID:
        return

    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        await message.answer(
            "Использование:\n/create 500$"
        )
        return

    prize = args[1]

    current_raffle = prize

    async with aiosqlite.connect(DB_NAME) as db:

        await db.execute(
            "DELETE FROM tickets"
        )

        await db.execute(
            "DELETE FROM raffle"
        )

        await db.execute(
            "INSERT INTO raffle (prize) VALUES (?)",
            (prize,)
        )

        await db.commit()

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Купить билеты 🎟️",
                    callback_data="buy_ticket"
                )
            ]
        ]
    )

    await bot.send_message(
        CHANNEL_ID,
        f"""
🎉 РОЗЫГРЫШ НА {prize}

🎟 Цена билета: 0.1$
""",
        reply_markup=keyboard
    )

    admin_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎲 Завершить розыгрыш",
                    callback_data="finish_raffle"
                )
            ]
        ]
    )

    await message.answer(
        "✅ Розыгрыш создан",
        reply_markup=admin_keyboard
    )

# =============================
# BUY BUTTON
# =============================

@dp.callback_query(F.data == "buy_ticket")
async def buy_ticket(callback: CallbackQuery):

    waiting_ticket_amount[callback.from_user.id] = True

    await callback.message.answer(
        "🎟 Сколько билетов хотите купить?"
    )

    await callback.answer()

# =============================
# USER ENTERS TICKET COUNT
# =============================

@dp.message()
async def process_ticket_amount(message: Message):

    user_id = message.from_user.id

    if user_id not in waiting_ticket_amount:
        return

    if not message.text.isdigit():

        await message.answer(
            "❌ Введите число"
        )

        return

    tickets = int(message.text)

    total = round(tickets * TICKET_PRICE, 2)

    invoice = await create_invoice(total)

    invoice_id = invoice["invoice_id"]
    pay_url = invoice["pay_url"]

    keyboard_buttons = [
        [
            InlineKeyboardButton(
                text="💳 Оплатить",
                url=pay_url
            )
        ]
    ]

    if user_id == ADMIN_ID:

        keyboard_buttons.append([
            InlineKeyboardButton(
                text="⚡ НЕ ОПЛАЧИВАТЬ (ADMIN)",
                callback_data=f"fakepay:{tickets}"
            )
        ])

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=keyboard_buttons
    )

    await message.answer(
        f"""
🎟 Билетов: {tickets}
💰 К оплате: {total}$
""",
        reply_markup=keyboard
    )

    waiting_ticket_amount.pop(user_id)

    if user_id == ADMIN_ID:
        return

    paid = False

    for _ in range(120):

        status = await check_invoice(invoice_id)

        if status == "paid":
            paid = True
            break

        await asyncio.sleep(5)

    if not paid:

        await message.answer(
            "❌ Время оплаты вышло"
        )

        return

    username = message.from_user.username

    async with aiosqlite.connect(DB_NAME) as db:

        await db.execute(
            """
            INSERT INTO tickets
            (user_id, username, tickets)
            VALUES (?, ?, ?)
            """,
            (
                user_id,
                username,
                tickets
            )
        )

        await db.commit()

    await message.answer(
        "✅ Оплата прошла успешно!"
    )

    name = message.from_user.first_name

    await bot.send_message(
        CHANNEL_ID,
        f"""
🎟 Новая покупка билетов!

👤 {name}
🎫 Купил билетов: {tickets}
"""
    )

    await bot.send_message(
        ADMIN_ID,
        f"""
💰 Новая оплата

👤 @{username}
🎟 Билетов: {tickets}
"""
    )

# =============================
# ADMIN FAKE PAYMENT
# =============================

@dp.callback_query(F.data.startswith("fakepay:"))
async def fake_payment(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        return

    tickets = int(callback.data.split(":")[1])

    async with aiosqlite.connect(DB_NAME) as db:

        await db.execute(
            """
            INSERT INTO tickets
            (user_id, username, tickets)
            VALUES (?, ?, ?)
            """,
            (
                callback.from_user.id,
                callback.from_user.username,
                tickets
            )
        )

        await db.commit()

    await callback.message.answer(
        "✅ Билеты добавлены без оплаты"
    )

    await callback.answer()

# =============================
# FINISH RAFFLE
# =============================

@dp.callback_query(F.data == "finish_raffle")
async def finish_raffle(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        return

    users = []

    async with aiosqlite.connect(DB_NAME) as db:

        async with db.execute(
            "SELECT user_id, username, tickets FROM tickets"
        ) as cursor:

            rows = await cursor.fetchall()

    if not rows:

        await callback.message.answer(
            "❌ Нет участников"
        )

        return

    for row in rows:

        user_id = row[0]
        username = row[1]
        tickets = row[2]

        for _ in range(tickets):

            users.append(
                (user_id, username)
            )

    winner = random.choice(users)

    winner_username = winner[1]

    await bot.send_message(
        CHANNEL_ID,
        f"""
🎉 РОЗЫГРЫШ ЗАВЕРШЕН

🏆 Победитель:
@{winner_username}

🎲 Победитель выбран СЛУЧАЙНО!
"""
    )

    await callback.message.answer(
        "✅ Розыгрыш завершен"
    )

    await callback.answer()

# =============================
# MAIN
# =============================

async def main():

    await init_db()

    print("BOT STARTED")

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
