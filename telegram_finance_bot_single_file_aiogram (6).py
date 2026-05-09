import sqlite3
import random
import string
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
import asyncio

# =========================
# НАСТРОЙКИ
# =========================
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
BOT_USERNAME = os.getenv("BOT_USERNAME")
MIN_WITHDRAW = 1
MAX_WITHDRAW = 50
MIN_DEPOSIT = 0.1
CRYPTOBOT_TOKEN = os.getenv("CRYPTOBOT_TOKEN")

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())

# =========================
# БАЗА ДАННЫХ
# =========================
conn = sqlite3.connect("bot.db")
cur = conn.cursor()

cur.execute(
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        balance INTEGER DEFAULT 0,
        reg_date TEXT
    )
"""
)

cur.execute(
    """
    CREATE TABLE IF NOT EXISTS withdraws (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        crypto_link TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT
    )
"""
)

cur.execute(
    """
    CREATE TABLE IF NOT EXISTS checks (
        code TEXT PRIMARY KEY,
        amount INTEGER,
        activations INTEGER,
        used_by TEXT DEFAULT ''
    )
"""
)

conn.commit()

# =========================
# СОСТОЯНИЯ
# =========================
class WithdrawState(StatesGroup):
    amount = State()
    link = State()


class AddBalanceState(StatesGroup):
    user_id = State()
    amount = State()


class CreateCheckState(StatesGroup):
    amount = State()
    activations = State()


class BroadcastState(StatesGroup):
    text = State()


class RemoveBalanceState(StatesGroup):
    user_id = State()
    amount = State()


class RouletteState(StatesGroup):
    bet = State()
    number = State()


class DepositState(StatesGroup):
    amount = State()


# =========================
# ФУНКЦИИ
# =========================
def register_user(user_id, username):
    cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = cur.fetchone()

    if not user:
        cur.execute(
            "INSERT INTO users VALUES (?, ?, ?, ?)",
            (
                user_id,
                username,
                0,
                datetime.now().strftime("%d.%m.%Y %H:%M"),
            ),
        )
        conn.commit()


def get_balance(user_id):
    cur.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    result = cur.fetchone()
    return result[0] if result else 0


def set_balance(user_id, amount):
    cur.execute(
        "UPDATE users SET balance = balance + ? WHERE user_id=?",
        (amount, user_id),
    )
    conn.commit()


def profile_text(user_id, username):
    balance = get_balance(user_id)

    return f"""
<b>👤 ПРОФИЛЬ</b>

🆔 ID: <code>{user_id}</code>
👤 Username: @{username if username else 'нет'}
💰 Баланс: <b>{balance} $</b>

🎰 Казино • Выплаты • Чеки • Рулетка
"""


def main_menu():
    kb = InlineKeyboardBuilder()

    kb.row(
        InlineKeyboardButton(text="👤 Профиль", callback_data="profile")
    )

    kb.row(
        InlineKeyboardButton(text="🎰 Рулетка", callback_data="roulette")
    )

    return kb.as_markup()


def admin_menu():
    kb = InlineKeyboardBuilder()

    kb.row(
        InlineKeyboardButton(text="💰 Зачислить баланс", callback_data="admin_add_balance")
    )

    kb.row(
        InlineKeyboardButton(text="💸 Снять баланс", callback_data="admin_remove_balance")
    )

    kb.row(
        InlineKeyboardButton(text="🎁 Создать чек", callback_data="admin_create_check")
    )

    kb.row(
        InlineKeyboardButton(text="📨 Выводы", callback_data="admin_withdraws")
    )

    kb.row(
        InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")
    )

    return kb.as_markup()


# =========================
# START
# =========================
@dp.message(CommandStart())
async def start(message: Message):
    args = message.text.split()

    register_user(message.from_user.id, message.from_user.username)

    # АКТИВАЦИЯ ЧЕКА
    if len(args) > 1:
        code = args[1]

        if code.startswith("check_"):
            check_code = code.replace("check_", "")

            cur.execute("SELECT * FROM checks WHERE code=?", (check_code,))
            check = cur.fetchone()

            if not check:
                await message.answer("❌ Чек не найден")
                return

            code_db, amount, activations, used_by = check

            used_users = used_by.split(",") if used_by else []

            if str(message.from_user.id) in used_users:
                await message.answer("❌ Ты уже активировал этот чек")
                return

            if len(used_users) >= activations:
                await message.answer("❌ Лимит активаций исчерпан")
                return

            used_users.append(str(message.from_user.id))

            cur.execute(
                "UPDATE checks SET used_by=? WHERE code=?",
                (",".join(used_users), check_code),
            )

            set_balance(message.from_user.id, amount)

            conn.commit()

            await message.answer(
                f"🎉 Чек активирован!\n\n💰 Получено: <b>{amount} $</b>"
            )

    await message.answer(
        "🔥 Добро пожаловать в бота",
        reply_markup=main_menu(),
    )


# =========================
# ПРОФИЛЬ
# =========================
@dp.callback_query(F.data == "profile")
async def profile(call: CallbackQuery):
    text = profile_text(call.from_user.id, call.from_user.username)

    profile_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💳 Пополнить",
                    callback_data="deposit"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💸 Вывести",
                    callback_data="withdraw"
                )
            ]
        ]
    )

    await call.message.edit_text(text, reply_markup=profile_kb)


# =========================
# ПОПОЛНЕНИЕ
# =========================
@dp.callback_query(F.data == "deposit")
async def deposit(call: CallbackQuery, state: FSMContext):
    text = f"""
💳 <b>ПОПОЛНЕНИЕ БАЛАНСА</b>

💵 Минимум: <b>{MIN_DEPOSIT} $</b>

✍️ Введи сумму пополнения:
"""

    await state.set_state(DepositState.amount)

    await call.message.edit_text(text)


@dp.message(DepositState.amount)
async def deposit_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
    except:
        return

    if amount < MIN_DEPOSIT:
        return await message.answer("❌ Минимальное пополнение 0.1 $")

    invoice_url = f"https://t.me/CryptoBot?start=IV{random.randint(100000,999999)}"

    text = f"""
💳 <b>СЧЕТ СОЗДАН</b>

💵 Сумма: <b>{amount} $</b>

🔗 Оплати счет:
{invoice_url}

⚠️ После оплаты администратор может выдать баланс автоматически или вручную.
"""

    await message.answer(text, reply_markup=main_menu())

    await bot.send_message(
    ADMIN_ID,
    f"""💳 Новый запрос на пополнение

👤 ID: <code>{message.from_user.id}</code>
💵 Сумма: <b>{amount} $</b>
"""
)

    await state.clear()


# =========================
# РУЛЕТКА
# =========================
@dp.callback_query(F.data == "roulette")
async def roulette(call: CallbackQuery, state: FSMContext):
    text = """
🎰 <b>РУЛЕТКА</b>

💵 Минимальная ставка: <b>0.25 $</b>

🎯 Можно ставить:
• На число от 1 до 32
• 1-12
• 13-25
• 26-32

🏆 Выигрыш: <b>x3</b>

✍️ Введи сумму ставки:
"""

    await state.set_state(RouletteState.bet)
    await call.message.edit_text(text)


@dp.message(RouletteState.bet)
async def roulette_bet(message: Message, state: FSMContext):
    try:
        bet = float(message.text)
    except:
        return

    if bet < 0.25:
        return await message.answer("❌ Минимальная ставка 0.25 $")

    balance = get_balance(message.from_user.id)

    if bet > balance:
        return await message.answer("❌ Недостаточно средств")

    await state.update_data(bet=bet)
    await state.set_state(RouletteState.number)

    await message.answer(
        "🎯 Введи число или диапазон:

1-12
13-25
26-32
или число 1-32"
    )


@dp.message(RouletteState.number)
async def roulette_number(message: Message, state: FSMContext):
    choice = message.text.strip()

    valid_ranges = ["1-12", "13-25", "26-32"]

    number_choice = None

    if choice in valid_ranges:
        number_choice = choice
    else:
        try:
            num = int(choice)
            if num < 1 or num > 32:
                return
            number_choice = num
        except:
            return

    data = await state.get_data()

    bet = float(data["bet"])

    roll = random.randint(1, 32)

    win = False

    if isinstance(number_choice, int):
        if roll == number_choice:
            win = True
    else:
        if number_choice == "1-12" and 1 <= roll <= 12:
            win = True
        elif number_choice == "13-25" and 13 <= roll <= 25:
            win = True
        elif number_choice == "26-32" and 26 <= roll <= 32:
            win = True

    if win:
        prize = round(bet * 3, 2)

        cur.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id=?",
            (prize, message.from_user.id),
        )

        conn.commit()

        await message.answer(
            f"🎉 Выпало число: <b>{roll}</b>

🏆 Ты выиграл <b>{prize} $</b>",
            reply_markup=main_menu(),
        )
    else:
        cur.execute(
            "UPDATE users SET balance = balance - ? WHERE user_id=?",
            (bet, message.from_user.id),
        )

        conn.commit()

        await message.answer(
            f"❌ Выпало число: <b>{roll}</b>

💸 Ты проиграл <b>{bet} $</b>",
            reply_markup=main_menu(),
        )

    await state.clear()


# =========================
# ВЫВОД
# =========================
@dp.callback_query(F.data == "withdraw")
async def withdraw(call: CallbackQuery, state: FSMContext):
    balance = get_balance(call.from_user.id)

    text = f"""
💸 <b>ВЫВОД СРЕДСТВ</b>

💰 Твой баланс: <b>{balance} $</b>

📉 Минимум: <b>{MIN_WITHDRAW} $</b>
📈 Максимум: <b>{MAX_WITHDRAW} $</b>

✍️ Введи сумму вывода:
"""

    await state.set_state(WithdrawState.amount)
    await call.message.edit_text(text)


@dp.message(WithdrawState.amount)
async def withdraw_amount(message: Message, state: FSMContext):
    try:
        int(message.text)
    except:
        return

    amount = int(message.text)
    balance = get_balance(message.from_user.id)

    if amount < MIN_WITHDRAW:
        return await message.answer("❌ Слишком маленькая сумма")

    if amount > MAX_WITHDRAW:
        return await message.answer("❌ Превышен максимум")

    if amount > balance:
        return await message.answer("❌ Недостаточно средств")

    await state.update_data(amount=amount)
    await state.set_state(WithdrawState.link)

    await message.answer(
        "🔗 Пришли ссылку на пополнение CryptoBot"
    )


@dp.message(WithdrawState.link)
async def withdraw_link(message: Message, state: FSMContext):
    data = await state.get_data()

    amount = data["amount"]
    link = message.text

    cur.execute(
        "INSERT INTO withdraws (user_id, amount, crypto_link, created_at) VALUES (?, ?, ?, ?)",
        (
            message.from_user.id,
            amount,
            link,
            datetime.now().strftime("%d.%m.%Y %H:%M"),
        ),
    )

    conn.commit()

    withdraw_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=f"accept_withdraw_{message.from_user.id}_{amount}"
                ),
                InlineKeyboardButton(
                    text="❌ Отменить",
                    callback_data=f"cancel_withdraw_{message.from_user.id}_{amount}"
                ),
            ]
        ]
    )

    await bot.send_message(
        ADMIN_ID,
        f"""
📨 <b>НОВАЯ ЗАЯВКА НА ВЫВОД</b>

👤 Юзер: @{message.from_user.username if message.from_user.username else 'нет'}
🆔 ID: <code>{message.from_user.id}</code>

💰 Сумма: <b>{amount} $</b>
🔗 Ссылка: {link}
""",
        reply_markup=withdraw_kb,
    )

    await message.answer(
        "✅ Заявка отправлена администрации",
        reply_markup=main_menu(),
    )

    await state.clear()


# =========================
# ПОДТВЕРЖДЕНИЕ / ОТМЕНА ВЫВОДА
# =========================
@dp.callback_query(F.data.startswith("accept_withdraw_"))
async def accept_withdraw(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return

    try:
        _, _, user_id, amount = call.data.split("_")

        user_id = int(user_id)
        amount = int(amount)

        cur.execute(
            "UPDATE users SET balance = balance - ? WHERE user_id=?",
            (amount, user_id),
        )

        conn.commit()

        try:
            await bot.send_message(
                user_id,
                f"✅ Твой вывод на сумму <b>{amount} $</b> подтвержден"
            )
        except:
            pass

        await call.message.edit_reply_markup(reply_markup=None)
        await call.answer("Вывод подтвержден")

    except Exception as e:
        await call.answer(str(e), show_alert=True)


@dp.callback_query(F.data.startswith("cancel_withdraw_"))
async def cancel_withdraw(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return

    try:
        _, _, user_id, amount = call.data.split("_")

        user_id = int(user_id)
        amount = int(amount)

        try:
            await bot.send_message(
                user_id,
                f"❌ Вывод на сумму <b>{amount} $</b> отменен"
            )
        except:
            pass

        await call.message.edit_reply_markup(reply_markup=None)
        await call.answer("Вывод отменен")

    except Exception as e:
        await call.answer(str(e), show_alert=True)


# =========================
# АДМИНКА
# =========================
@dp.message(F.text == "/admin")
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    await message.answer(
        "⚙️ <b>АДМИН ПАНЕЛЬ</b>

💎 Управление балансом
🎁 Управление чеками
📨 Заявки и рассылка",
        reply_markup=admin_menu(),
    )


# =========================
# ЗАЧИСЛЕНИЕ БАЛАНСА
# =========================
@dp.callback_query(F.data == "admin_add_balance")
async def admin_add_balance(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return

    await state.set_state(AddBalanceState.user_id)

    await call.message.answer("🆔 Введи ID пользователя")


@dp.message(AddBalanceState.user_id)
async def add_balance_user(message: Message, state: FSMContext):
    try:
        int(message.text)
    except:
        return

    await state.update_data(user_id=int(message.text))
    await state.set_state(AddBalanceState.amount)

    await message.answer("💰 Введи сумму")


@dp.message(AddBalanceState.amount)
async def add_balance_amount(message: Message, state: FSMContext):
    try:
        int(message.text)
    except:
        return

    data = await state.get_data()

    user_id = data["user_id"]
    amount = int(message.text)

    set_balance(user_id, amount)

    try:
        await bot.send_message(
            user_id,
            f"🎉 Тебе зачислено <b>{amount} $</b>",
        )
    except:
        pass

    await message.answer("✅ Баланс зачислен")

    await state.clear()


# =========================
# СНЯТИЕ БАЛАНСА
# =========================
@dp.callback_query(F.data == "admin_remove_balance")
async def remove_balance(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return

    await state.set_state(RemoveBalanceState.user_id)

    await call.message.answer("🆔 Введи ID пользователя")


@dp.message(RemoveBalanceState.user_id)
async def remove_balance_user(message: Message, state: FSMContext):
    try:
        int(message.text)
    except:
        return

    await state.update_data(user_id=int(message.text))
    await state.set_state(RemoveBalanceState.amount)

    await message.answer("💸 Введи сумму снятия")


@dp.message(RemoveBalanceState.amount)
async def remove_balance_amount(message: Message, state: FSMContext):
    try:
        int(message.text)
    except:
        return

    data = await state.get_data()

    user_id = data["user_id"]
    amount = int(message.text)

    cur.execute(
        "UPDATE users SET balance = balance - ? WHERE user_id=?",
        (amount, user_id),
    )

    conn.commit()

    try:
        await bot.send_message(
            user_id,
            f"💸 С твоего баланса снято <b>{amount} $</b>"
        )
    except:
        pass

    await message.answer("✅ Баланс снят")

    await state.clear()


# =========================
# СОЗДАНИЕ ЧЕКА
# =========================
@dp.callback_query(F.data == "admin_create_check")
async def create_check(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return

    await state.set_state(CreateCheckState.amount)

    await call.message.answer("💰 Введи сумму чека")


@dp.message(CreateCheckState.amount)
async def check_amount(message: Message, state: FSMContext):
    try:
        int(message.text)
    except:
        return

    await state.update_data(amount=int(message.text))
    await state.set_state(CreateCheckState.activations)

    await message.answer("👥 Введи количество активаций")


@dp.message(CreateCheckState.activations)
async def check_activations(message: Message, state: FSMContext):
    try:
        int(message.text)
    except:
        return

    data = await state.get_data()

    amount = data["amount"]
    activations = int(message.text)

    code = "".join(random.choices(string.digits, k=6))

    cur.execute(
        "INSERT INTO checks VALUES (?, ?, ?, ?)",
        (code, amount, activations, ""),
    )

    conn.commit()

    link = f"https://t.me/{BOT_USERNAME}?start=check_{code}"

    used_info = "Пока никто не активировал"

    await message.answer(
        f"""
🎁 <b>ЧЕК СОЗДАН</b>

💰 Сумма: <b>{amount} $</b>
👥 Активаций: <b>{activations}</b>

🔗 Ссылка:
{link}
"""
    )

    await state.clear()


# =========================
# ВЫВОДЫ
# =========================
@dp.callback_query(F.data == "admin_withdraws")
async def admin_withdraws(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return

    cur.execute(
        "SELECT user_id, amount, crypto_link, created_at FROM withdraws ORDER BY id DESC LIMIT 20"
    )

    rows = cur.fetchall()

    if not rows:
        return await call.message.answer("❌ Заявок нет")

    text = "📨 <b>СПИСОК ВЫВОДОВ</b>\n\n"

    for row in rows:
        user_id, amount, link, created = row

        text += (
            f"👤 ID: <code>{user_id}</code>\n"
            f"💰 Сумма: <b>{amount} $</b>\n"
            f"🔗 {link}\n"
            f"🕒 {created}\n\n"
        )

    await call.message.answer(text)


# =========================
# РАССЫЛКА
# =========================
@dp.callback_query(F.data == "admin_broadcast")
async def broadcast(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return

    await state.set_state(BroadcastState.text)

    await call.message.answer("📢 Отправь текст для рассылки")


@dp.message(BroadcastState.text)
async def broadcast_text(message: Message, state: FSMContext):
    cur.execute("SELECT user_id FROM users")
    users = cur.fetchall()

    sent = 0

    for user in users:
        try:
            await bot.send_message(user[0], message.text)
            sent += 1
            await asyncio.sleep(0.05)
        except:
            pass

    await message.answer(f"✅ Рассылка завершена\n\n📨 Отправлено: {sent}")

    await state.clear()





# =========================
# ЗАПУСК
# =========================
async def main():
    print("BOT STARTED")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
