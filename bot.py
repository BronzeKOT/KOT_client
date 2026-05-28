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

BOT_TOKEN = "8878883808:AAGgJ9FS3P-rSy0t7z2fJ4wmk4dd6ILsaPY"
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

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

class Reg(StatesGroup):
    login = State()
    password = State()

class Auth(StatesGroup):
    login = State()
    password = State()

class ChangeLogin(StatesGroup):
    new = State()

class ChangePass(StatesGroup):
    new = State()

class AddKey(StatesGroup):
    key = State()

class RedeemKey(StatesGroup):
    key = State()

class AddAdmin(StatesGroup):
    username = State()

def main_menu(is_admin=False):
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Мой профиль")],
        [KeyboardButton(text="Купить подписку"), KeyboardButton(text="Ввести ключ")]
    ], resize_keyboard=True)
    if is_admin:
        kb.keyboard.append([KeyboardButton(text="Добавить ключ"), KeyboardButton(text="Добавить админа")])
    return kb

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
    await state.set_state(Reg.login)
    await call.answer()

@dp.message(Reg.login)
async def reg_login(msg: Message, state: FSMContext):
    login = msg.text.strip()
    if len(login) < 3 or len(login) > 16:
        await msg.answer("Логин от 3 до 16 символов.")
        return
    if cursor.execute("SELECT * FROM users WHERE username=?", (login,)).fetchone():
        await msg.answer("Логин занят.")
        return
    await state.update_data(login=login)
    await msg.answer("Введите пароль (6-12 символов):")
    await state.set_state(Reg.password)

@dp.message(Reg.password)
async def reg_password(msg: Message, state: FSMContext):
    pwd = msg.text.strip()
    if len(pwd) < 6 or len(pwd) > 12:
        await msg.answer("Пароль от 6 до 12 символов.")
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
    await state.set_state(Auth.login)
    await call.answer()

@dp.message(Auth.login)
async def auth_login(msg: Message, state: FSMContext):
    login = msg.text.strip()
    if not cursor.execute("SELECT * FROM users WHERE username=?", (login,)).fetchone():
        await msg.answer("Пользователь не найден.")
        return
    await state.update_data(login=login)
    await msg.answer("Введите пароль:")
    await state.set_state(Auth.password)

@dp.message(Auth.password)
async def auth_password(msg: Message, state: FSMContext):
    pwd = msg.text.strip()
    data = await state.get_data()
    login = data['login']
    user = cursor.execute("SELECT * FROM users WHERE username=? AND password=?", (login, pwd)).fetchone()
    if not user:
        await msg.answer("Неверный пароль.")
        return
    cursor.execute("UPDATE users SET user_id=? WHERE username=?", (msg.from_user.id, login))
    conn.commit()
    await msg.answer("Вход выполнен", reply_markup=main_menu(user[6]))
    await show_profile(msg)
    await state.clear()

@dp.message(Command("iamadmin"))
async def become_admin(msg: Message):
    if cursor.execute("SELECT * FROM users WHERE is_admin=1").fetchone():
        await msg.answer("Админ уже есть.")
        return
    user = cursor.execute("SELECT * FROM users WHERE user_id=?", (msg.from_user.id,)).fetchone()
    if not user:
        await msg.answer("Сначала зарегистрируйся.")
        return
    cursor.execute("UPDATE users SET is_admin=1 WHERE user_id=?", (msg.from_user.id,))
    conn.commit()
    await msg.answer("Ты теперь админ", reply_markup=main_menu(True))

@dp.message(F.text == "Мой профиль")
async def show_profile(msg: Message):
    user = cursor.execute("SELECT * FROM users WHERE user_id=?", (msg.from_user.id,)).fetchone()
    if not user:
        await msg.answer("Ты не зарегистрирован. /start")
        return
    sub_display = f"PRO до {user[5]}" if user[4] == 'pro' and user[5] else "free"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сменить логин", callback_data="ch_login"),
         InlineKeyboardButton(text="Сменить пароль", callback_data="ch_pass")],
        [InlineKeyboardButton(text="Купить подписку" if user[4] != 'pro' else "Продлить подписку", callback_data="buy_sub")]
    ])
    await msg.answer(
        f"Логин: {user[1]}\n"
        f"Пароль: {'*' * len(user[2])}\n"
        f"Дата создания: {user[3]}\n"
        f"Подписка: {sub_display}",
        reply_markup=kb
    )

@dp.callback_query(F.data == "ch_login")
async def ch_login(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Введи новый логин:")
    await state.set_state(ChangeLogin.new)
    await call.answer()

@dp.message(ChangeLogin.new)
async def do_ch_login(msg: Message, state: FSMContext):
    new = msg.text.strip()
    if cursor.execute("SELECT * FROM users WHERE username=?", (new,)).fetchone():
        await msg.answer("Занят.")
        return
    cursor.execute("UPDATE users SET username=? WHERE user_id=?", (new, msg.from_user.id))
    conn.commit()
    await msg.answer("Готово")
    await state.clear()

@dp.callback_query(F.data == "ch_pass")
async def ch_pass(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Введи новый пароль (6-12):")
    await state.set_state(ChangePass.new)
    await call.answer()

@dp.message(ChangePass.new)
async def do_ch_pass(msg: Message, state: FSMContext):
    pwd = msg.text.strip()
    if len(pwd) < 6 or len(pwd) > 12:
        await msg.answer("6-12 символов.")
        return
    cursor.execute("UPDATE users SET password=? WHERE user_id=?", (pwd, msg.from_user.id))
    conn.commit()
    await msg.answer("Готово")
    await state.clear()

@dp.callback_query(F.data == "buy_sub")
@dp.message(F.text == "Купить подписку")
async def buy_sub(event, is_msg=False):
    text = (
        "Подписка PRO\n"
        "==============\n"
        "Входит:\n"
        "(1) Доступ к софту\n"
        "(2) Все функции\n"
        "(3) Поддержка\n"
        "=============="
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="3 дня — 100 руб.", callback_data="buy_3d")],
        [InlineKeyboardButton(text="1 месяц — 200 руб.", callback_data="buy_1m")],
        [InlineKeyboardButton(text="3 месяца — 300 руб.", callback_data="buy_3m")],
        [InlineKeyboardButton(text="6 месяцев — 400 руб.", callback_data="buy_6m")],
        [InlineKeyboardButton(text="Навсегда — 700 руб.", callback_data="buy_forever")],
    ])
    if is_msg:
        await event.answer(text, reply_markup=kb)
    else:
        await event.message.answer(text, reply_markup=kb)
        await event.answer()

@dp.callback_query(F.data.startswith("buy_"))
async def process_buy(call: CallbackQuery):
    await call.message.answer(
        "Переведите сумму и напишите @S1llyPUP с номером операции. Он выдаст ключ.\n"
        "Как получите — введите через кнопку 'Ввести ключ'."
    )
    await call.answer()

@dp.message(F.text == "Ввести ключ")
async def redeem(msg: Message, state: FSMContext):
    await msg.answer("Введите ключ:")
    await state.set_state(RedeemKey.key)

@dp.message(RedeemKey.key)
async def do_redeem(msg: Message, state: FSMContext):
    key = msg.text.strip().upper()
    k = cursor.execute("SELECT * FROM keys WHERE key=? AND used=0", (key,)).fetchone()
    if not k:
        await msg.answer("Ключ недействителен.")
        return
    days = k[2]
    expire = (datetime.now() + timedelta(days=days)).strftime("%d-%m-%Y") if days < 99999 else "навсегда"
    cursor.execute("UPDATE keys SET used=1, used_by=? WHERE key=?", (msg.from_user.id, key))
    cursor.execute("UPDATE users SET subscription='pro', sub_expire=? WHERE user_id=?", (expire, msg.from_user.id))
    conn.commit()
    await msg.answer(f"PRO активирована до {expire}")
    await state.clear()

@dp.message(F.text == "Добавить ключ")
async def add_key(msg: Message, state: FSMContext):
    if not cursor.execute("SELECT * FROM users WHERE user_id=? AND is_admin=1", (msg.from_user.id,)).fetchone():
        await msg.answer("Нет доступа.")
        return
    await msg.answer("Введи ключ:")
    await state.set_state(AddKey.key)

@dp.message(AddKey.key)
async def do_add_key(msg: Message, state: FSMContext):
    key = msg.text.strip().upper()
    parts = key.split('-')
    if len(parts) != 5 or parts[0] != 'PRO':
        await msg.answer("Неверный формат.")
        return
    days_map = {'3D': 3, '1M': 30, '3M': 90, '6M': 180, 'FOREVER': 99999}
    if parts[1] not in days_map:
        await msg.answer("Неверный срок.")
        return
    if cursor.execute("SELECT * FROM keys WHERE key=?", (key,)).fetchone():
        await msg.answer("Уже существует.")
        return
    cursor.execute("INSERT INTO keys (key, duration, days) VALUES (?, ?, ?)", (key, parts[1], days_map[parts[1]]))
    conn.commit()
    await msg.answer("Ключ добавлен.")
    await state.clear()

@dp.message(F.text == "Добавить админа")
async def add_admin(msg: Message, state: FSMContext):
    if not cursor.execute("SELECT * FROM users WHERE user_id=? AND is_admin=1", (msg.from_user.id,)).fetchone():
        await msg.answer("Нет доступа.")
        return
    await msg.answer("Введи логин:")
    await state.set_state(AddAdmin.username)

@dp.message(AddAdmin.username)
async def do_add_admin(msg: Message, state: FSMContext):
    login = msg.text.strip()
    if not cursor.execute("SELECT * FROM users WHERE username=?", (login,)).fetchone():
        await msg.answer("Не найден.")
        return
    cursor.execute("UPDATE users SET is_admin=1 WHERE username=?", (login,))
    conn.commit()
    await msg.answer(f"{login} теперь админ.")
    await state.clear()

async def main():
    await dp.start_polling(bot)

asyncio.run(main())
