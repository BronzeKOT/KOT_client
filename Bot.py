import os
import sqlite3
import asyncio
import random
import string
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web

BOT_TOKEN = os.environ["BOT_TOKEN"]
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# База данных
conn = sqlite3.connect('users.db')
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT UNIQUE,
        password TEXT,
        created_at TEXT,
        subscription TEXT DEFAULT 'free',
        sub_expire TEXT DEFAULT '',
        is_admin INTEGER DEFAULT 0
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS keys (
        key TEXT PRIMARY KEY,
        duration TEXT,
        days INTEGER,
        used INTEGER DEFAULT 0,
        used_by TEXT DEFAULT ''
    )
''')
conn.commit()

# Состояния для FSM
class RegStates(StatesGroup):
    waiting_login = State()
    waiting_password = State()

class AuthStates(StatesGroup):
    waiting_login = State()
    waiting_password = State()

class ChangeLogin(StatesGroup):
    waiting_new_login = State()

class ChangePassword(StatesGroup):
    waiting_new_password = State()

class AddKey(StatesGroup):
    waiting_key = State()

class RedeemKey(StatesGroup):
    waiting_key = State()

class AddAdmin(StatesGroup):
    waiting_username = State()

# Генерация ключа
def generate_key(duration, login):
    rand_letters = ''.join(random.choices(string.ascii_uppercase, k=5))
    rand_digits = ''.join(random.choices(string.digits, k=6))
    days = {'3d': 3, '1m': 30, '3m': 90, '6m': 180, 'forever': 99999}
    return f"PRO-{duration.upper()}-{rand_letters}-{login.upper()}-{rand_digits}", days[duration]

# Главное меню
def main_menu(is_admin=False):
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Мой профиль")],
        [KeyboardButton(text="Купить подписку"), KeyboardButton(text="Ввести ключ")]
    ], resize_keyboard=True)
    if is_admin:
        kb.keyboard.append([KeyboardButton(text="Добавить ключ"), KeyboardButton(text="Добавить админа")])
    return kb

# Старт
@dp.message(Command("start"))
async def start(msg: Message):
    user = cursor.execute("SELECT * FROM users WHERE user_id=?", (msg.from_user.id,)).fetchone()
    if user:
        await msg.answer(f"С возвращением, {user[1]}", reply_markup=main_menu(user[6]))
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Регистрация", callback_data="reg")],
            [InlineKeyboardButton(text="Войти", callback_data="auth")]
        ])
        await msg.answer("Добро пожаловать. Выберите действие:", reply_markup=kb)

@dp.callback_query(F.data == "reg")
async def reg_start(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Введите логин:")
    await state.set_state(RegStates.waiting_login)
    await call.answer()

@dp.message(RegStates.waiting_login)
async def reg_login(msg: Message, state: FSMContext):
    login = msg.text.strip()
    if len(login) < 3 or len(login) > 16:
        await msg.answer("Логин должен быть от 3 до 16 символов.")
        return
    exists = cursor.execute("SELECT * FROM users WHERE username=?", (login,)).fetchone()
    if exists:
        await msg.answer("Логин занят. Придумай другой.")
        return
    await state.update_data(login=login)
    await msg.answer("Логин одобрен. Теперь придумай пароль (от 6 до 12 символов):")
    await state.set_state(RegStates.waiting_password)

@dp.message(RegStates.waiting_password)
async def reg_password(msg: Message, state: FSMContext):
    pwd = msg.text.strip()
    if len(pwd) < 6 or len(pwd) > 12:
        await msg.answer("Пароль должен быть от 6 до 12 символов.")
        return
    data = await state.get_data()
    login = data['login']
    created = datetime.now().strftime("%d-%m-%Y")
    cursor.execute("INSERT INTO users (user_id, username, password, created_at) VALUES (?, ?, ?, ?)",
                   (msg.from_user.id, login, pwd, created))
    conn.commit()
    await msg.answer("Аккаунт создан", reply_markup=main_menu(False))
    await show_profile(msg)
    await state.clear()

@dp.callback_query(F.data == "auth")
async def auth_start(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Введите логин:")
    await state.set_state(AuthStates.waiting_login)
    await call.answer()

@dp.message(AuthStates.waiting_login)
async def auth_login(msg: Message, state: FSMContext):
    login = msg.text.strip()
    user = cursor.execute("SELECT * FROM users WHERE username=?", (login,)).fetchone()
    if not user:
        await msg.answer("Пользователь не найден.")
        return
    await state.update_data(auth_login=login)
    await msg.answer("Введите пароль:")
    await state.set_state(AuthStates.waiting_password)

@dp.message(AuthStates.waiting_password)
async def auth_password(msg: Message, state: FSMContext):
    pwd = msg.text.strip()
    data = await state.get_data()
    login = data['auth_login']
    user = cursor.execute("SELECT * FROM users WHERE username=? AND password=?", (login, pwd)).fetchone()
    if not user:
        await msg.answer("Неверный пароль.")
        return
    if user[0] != msg.from_user.id:
        cursor.execute("UPDATE users SET user_id=? WHERE username=?", (msg.from_user.id, login))
        conn.commit()
    await msg.answer("Вход выполнен", reply_markup=main_menu(user[6]))
    await show_profile(msg)
    await state.clear()

# Секретная команда для первого админа
@dp.message(Command("iamadmin"))
async def become_admin(msg: Message):
    admins = cursor.execute("SELECT * FROM users WHERE is_admin=1").fetchall()
    if admins:
        await msg.answer("Админ уже назначен.")
        return
    user = cursor.execute("SELECT * FROM users WHERE user_id=?", (msg.from_user.id,)).fetchone()
    if not user:
        await msg.answer("Сначала зарегистрируйся.")
        return
    cursor.execute("UPDATE users SET is_admin=1 WHERE user_id=?", (msg.from_user.id,))
    conn.commit()
    await msg.answer("Ты теперь админ", reply_markup=main_menu(True))

# Профиль
@dp.message(F.text == "Мой профиль")
async def show_profile(msg: Message):
    user = cursor.execute("SELECT * FROM users WHERE user_id=?", (msg.from_user.id,)).fetchone()
    if not user:
        await msg.answer("Ты не зарегистрирован. Жми /start")
        return
    sub_text = user[5] if user[4] == 'pro' else 'free'
    sub_display = f"PRO до {user[5]}" if user[4] == 'pro' and user[5] else "free"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сменить логин", callback_data="change_login"),
         InlineKeyboardButton(text="Сменить пароль", callback_data="change_password")],
        [InlineKeyboardButton(text="Купить подписку" if user[4] != 'pro' else "Продлить подписку", callback_data="buy_sub")]
    ])
    await msg.answer(
        f"Логин: {user[1]}\n"
        f"Пароль: {'*' * len(user[2])}\n"
        f"Дата создания: {user[3]}\n"
        f"Подписка: {sub_display}",
        reply_markup=kb
    )

# Смена логина
@dp.callback_query(F.data == "change_login")
async def change_login(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Введи новый логин:")
    await state.set_state(ChangeLogin.waiting_new_login)
    await call.answer()

@dp.message(ChangeLogin.waiting_new_login)
async def do_change_login(msg: Message, state: FSMContext):
    new_login = msg.text.strip()
    exists = cursor.execute("SELECT * FROM users WHERE username=?", (new_login,)).fetchone()
    if exists:
        await msg.answer("Логин занят.")
        return
    cursor.execute("UPDATE users SET username=? WHERE user_id=?", (new_login, msg.from_user.id))
    conn.commit()
    await msg.answer("Логин обновлён")
    await state.clear()
    await show_profile(msg)

# Смена пароля
@dp.callback_query(F.data == "change_password")
async def change_password(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Введи новый пароль (6-12 символов):")
    await state.set_state(ChangePassword.waiting_new_password)
    await call.answer()

@dp.message(ChangePassword.waiting_new_password)
async def do_change_password(msg: Message, state: FSMContext):
    pwd = msg.text.strip()
    if len(pwd) < 6 or len(pwd) > 12:
        await msg.answer("Пароль должен быть от 6 до 12 символов.")
        return
    cursor.execute("UPDATE users SET password=? WHERE user_id=?", (pwd, msg.from_user.id))
    conn.commit()
    await msg.answer("Пароль обновлён")
    await state.clear()
    await show_profile(msg)

# Подписка
@dp.callback_query(F.data == "buy_sub")
@dp.message(F.text == "Купить подписку")
async def buy_sub(msg_or_call, is_msg=False):
    text = (
        "Подписка PRO через ключ\n"
        "==============\n"
        "Входит в неё:\n"
        "(1) Доступ к софту\n"
        "(2) Все функции\n"
        "(3) Приоритетная поддержка\n"
        "(4) Эксклюзивные обновления\n"
        "==============\n"
        "А так же поддержка клиента"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="3 дня — 100 руб.", callback_data="buy_3d")],
        [InlineKeyboardButton(text="1 месяц — 200 руб.", callback_data="buy_1m")],
        [InlineKeyboardButton(text="3 месяца — 300 руб.", callback_data="buy_3m")],
        [InlineKeyboardButton(text="6 месяцев — 400 руб.", callback_data="buy_6m")],
        [InlineKeyboardButton(text="Навсегда — 700 руб.", callback_data="buy_forever")],
    ])
    if is_msg:
        await msg_or_call.answer(text, reply_markup=kb)
    else:
        await msg_or_call.message.answer(text, reply_markup=kb)
        await msg_or_call.answer()

# Обработка выбора тарифа
@dp.callback_query(F.data.startswith("buy_"))
async def process_buy(call: CallbackQuery):
    duration = call.data.split("_")[1]
    await call.message.answer(
        f"Переведите нужную сумму и после оплаты напишите @S1llyPUP, "
        f"укажите номер операции и сумму. Он выдаст вам ключ.\n"
        f"Когда получите ключ, введите его командой /redeem или кнопкой 'Ввести ключ'."
    )
    await call.answer()

# Ввод ключа
@dp.message(F.text == "Ввести ключ")
@dp.message(Command("redeem"))
async def redeem_key(msg: Message, state: FSMContext):
    await msg.answer("Введи ключ:")
    await state.set_state(RedeemKey.waiting_key)

@dp.message(RedeemKey.waiting_key)
async def process_redeem(msg: Message, state: FSMContext):
    key = msg.text.strip().upper()
    key_data = cursor.execute("SELECT * FROM keys WHERE key=? AND used=0", (key,)).fetchone()
    if not key_data:
        await msg.answer("Ключ недействителен или уже использован.")
        return
    days = key_data[2]
    expire_date = (datetime.now() + timedelta(days=days)).strftime("%d-%m-%Y") if days < 99999 else "навсегда"
    cursor.execute("UPDATE keys SET used=1, used_by=? WHERE key=?", (msg.from_user.id, key))
    cursor.execute("UPDATE users SET subscription='pro', sub_expire=? WHERE user_id=?", (expire_date, msg.from_user.id))
    conn.commit()
    await msg.answer(f"Ключ активирован. Подписка PRO до {expire_date}", reply_markup=main_menu(False))
    await state.clear()

# Админка: добавить ключ
@dp.message(F.text == "Добавить ключ")
async def add_key(msg: Message, state: FSMContext):
    user = cursor.execute("SELECT * FROM users WHERE user_id=? AND is_admin=1", (msg.from_user.id,)).fetchone()
    if not user:
        await msg.answer("Нет доступа.")
        return
    await msg.answer("Введи ключ в формате PRO-{срок}-{рандом}-{логин}-{цифры}:")
    await state.set_state(AddKey.waiting_key)

@dp.message(AddKey.waiting_key)
async def process_add_key(msg: Message, state: FSMContext):
    key = msg.text.strip().upper()
    parts = key.split('-')
    if len(parts) != 5 or parts[0] != 'PRO':
        await msg.answer("Неверный формат ключа.")
        return
    duration_str = parts[1]
    login = parts[3]
    user_exists = cursor.execute("SELECT * FROM users WHERE username=?", (login,)).fetchone()
    if not user_exists:
        await msg.answer("Пользователь с таким логином не найден.")
        return
    days_map = {'3D': 3, '1M': 30, '3M': 90, '6M': 180, 'FOREVER': 99999}
    if duration_str not in days_map:
        await msg.answer("Неверный срок в ключе.")
        return
    exists = cursor.execute("SELECT * FROM keys WHERE key=?", (key,)).fetchone()
    if exists:
        await msg.answer("Такой ключ уже существует.")
        return
    cursor.execute("INSERT INTO keys (key, duration, days) VALUES (?, ?, ?)", (key, duration_str, days_map[duration_str]))
    conn.commit()
    await msg.answer("Ключ добавлен в систему.")
    await state.clear()

# Админка: добавить админа
@dp.message(F.text == "Добавить админа")
async def add_admin(msg: Message, state: FSMContext):
    user = cursor.execute("SELECT * FROM users WHERE user_id=? AND is_admin=1", (msg.from_user.id,)).fetchone()
    if not user:
        await msg.answer("Нет доступа.")
        return
    await msg.answer("Введи логин пользователя:")
    await state.set_state(AddAdmin.waiting_username)

@dp.message(AddAdmin.waiting_username)
async def process_add_admin(msg: Message, state: FSMContext):
    login = msg.text.strip()
    target = cursor.execute("SELECT * FROM users WHERE username=?", (login,)).fetchone()
    if not target:
        await msg.answer("Пользователь не найден.")
        return
    cursor.execute("UPDATE users SET is_admin=1 WHERE username=?", (login,))
    conn.commit()
    await msg.answer(f"{login} теперь админ")
    await state.clear()

# Заглушка для Render
async def handle(request):
    return web.Response(text="Online")

async def main():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ['PORT']))
    await site.start()
    await dp.start_polling(bot)

asyncio.run(main())
