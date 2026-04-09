import asyncio
import aiohttp
import sqlite3
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiohttp import web

# ========== КОНФИГ ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
RENDER_URL = os.environ.get("RENDER_URL", "https://aibot-f7s6.onrender.com")

# Только проверенные рабочие модели
MODELS = {
    "openai/gpt-4o": "GPT-4o 🌟 (самая умная)",
    "deepseek/deepseek-chat": "DeepSeek 🧠 (логика)"
}

# Максимум запросов на пользователя (БЕЗ ВОЗМОЖНОСТИ СБРОСА)
MAX_REQUESTS = 5

# База данных
conn = sqlite3.connect("ai.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    requests_used INTEGER DEFAULT 0,
    current_model TEXT DEFAULT 'openai/gpt-4o',
    temperature REAL DEFAULT 0.7,
    system_prompt TEXT DEFAULT 'Ты полезный ассистент. Отвечай на русском языке.',
    joined_date TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS chat_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    role TEXT,
    content TEXT,
    created_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
)
""")
conn.commit()

# Состояния
class SettingsState(StatesGroup):
    waiting_for_system_prompt = State()
    waiting_for_temperature = State()

class ChatState(StatesGroup):
    waiting_for_message = State()

# Инициализация
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ========== ФУНКЦИИ ==========
def register_user(user_id):
    cursor.execute("""
        INSERT OR IGNORE INTO users (user_id, joined_date, requests_used)
        VALUES (?, ?, 0)
    """, (user_id, datetime.now().isoformat()))
    conn.commit()

def get_user(user_id):
    cursor.execute("SELECT requests_used, current_model, temperature, system_prompt FROM users WHERE user_id = ?", (user_id,))
    return cursor.fetchone()

def increment_requests(user_id):
    cursor.execute("UPDATE users SET requests_used = requests_used + 1 WHERE user_id = ?", (user_id,))
    conn.commit()

def get_requests_left(user_id):
    cursor.execute("SELECT requests_used FROM users WHERE user_id = ?", (user_id,))
    used = cursor.fetchone()[0]
    return max(0, MAX_REQUESTS - used)

def can_use(user_id):
    return get_requests_left(user_id) > 0

def set_model(user_id, model):
    cursor.execute("UPDATE users SET current_model = ? WHERE user_id = ?", (model, user_id))
    conn.commit()

def set_temperature(user_id, temp):
    cursor.execute("UPDATE users SET temperature = ? WHERE user_id = ?", (temp, user_id))
    conn.commit()

def set_system_prompt(user_id, prompt):
    cursor.execute("UPDATE users SET system_prompt = ? WHERE user_id = ?", (prompt, user_id))
    conn.commit()

def add_to_history(user_id, role, content):
    cursor.execute("""
        INSERT INTO chat_history (user_id, role, content, created_at)
        VALUES (?, ?, ?, ?)
    """, (user_id, role, content, datetime.now().isoformat()))
    conn.commit()

def get_history(user_id, limit=10):
    cursor.execute("""
        SELECT role, content FROM chat_history 
        WHERE user_id = ? 
        ORDER BY id DESC LIMIT ?
    """, (user_id, limit))
    return cursor.fetchall()[::-1]

def clear_history(user_id):
    cursor.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
    conn.commit()

async def ask_ai(user_id, prompt):
    """Отправляет запрос к OpenRouter"""
    user_data = get_user(user_id)
    if not user_data or not can_use(user_id):
        return None, f"❌ Вы использовали все {MAX_REQUESTS} запросов. Бот доступен только для демонстрации."
    
    model = user_data[1]
    temperature = user_data[2]
    system_prompt = user_data[3]
    
    # Собираем историю
    history = get_history(user_id, 10)
    messages = [{"role": "system", "content": system_prompt}]
    for h in history:
        messages.append({"role": h[0], "content": h[1]})
    messages.append({"role": "user", "content": prompt})
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 1000
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://openrouter.ai/api/v1/chat/completions", 
                                   headers=headers, json=payload, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    response = data["choices"][0]["message"]["content"]
                    increment_requests(user_id)
                    add_to_history(user_id, "user", prompt)
                    add_to_history(user_id, "assistant", response)
                    return response, None
                else:
                    error_text = await resp.text()
                    return None, f"❌ Ошибка API: {resp.status}"
    except asyncio.TimeoutError:
        return None, "❌ Превышено время ожидания. Попробуйте ещё раз."
    except Exception as e:
        return None, f"❌ Ошибка: {str(e)[:100]}"

# ========== КЛАВИАТУРЫ ==========
def main_menu(user_id):
    user_data = get_user(user_id)
    requests_left = get_requests_left(user_id)
    
    buttons = [
        [InlineKeyboardButton(text="💬 Написать ИИ", callback_data="chat")],
        [InlineKeyboardButton(text="🤖 Выбрать модель", callback_data="models")],
        [InlineKeyboardButton(text="💰 Баланс", callback_data="balance")],
        [InlineKeyboardButton(text="📋 История", callback_data="history")],
        [InlineKeyboardButton(text="🔄 Сброс диалога", callback_data="clear")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="help")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def models_keyboard():
    buttons = []
    for model_id, model_name in MODELS.items():
        buttons.append([InlineKeyboardButton(text=model_name, callback_data=f"model_{model_id}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def settings_keyboard():
    buttons = [
        [InlineKeyboardButton(text="🎭 Системный промпт", callback_data="set_prompt")],
        [InlineKeyboardButton(text="🌡️ Температура", callback_data="set_temp")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ========== ОБРАБОТЧИКИ ==========
@dp.message(Command("start"))
async def start_command(message: Message):
    user_id = message.from_user.id
    register_user(user_id)
    requests_left = get_requests_left(user_id)
    
    await message.answer(
        "🤖 *ИИ-ассистент на OpenRouter*\n\n"
        "Я общаюсь с топовыми моделями ИИ:\n"
        "• GPT-4o — самый умный, универсальный\n"
        "• DeepSeek — отличная логика, математика\n\n"
        f"🎁 У вас есть *{requests_left} бесплатных запросов* из {MAX_REQUESTS}.\n"
        "После этого бот станет недоступен.\n\n"
        "👇 Выберите действие:",
        reply_markup=main_menu(user_id),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "back")
async def back_to_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    await callback.message.edit_text(
        "🤖 Главное меню:",
        reply_markup=main_menu(user_id)
    )
    await callback.answer()

@dp.callback_query(F.data == "chat")
async def start_chat(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    if not can_use(user_id):
        await callback.message.edit_text(
            f"❌ *Вы использовали все {MAX_REQUESTS} запросов!*\n\n"
            f"Бот доступен только для демонстрации.\n"
            f"Для тестирования обратитесь к разработчику.",
            parse_mode="Markdown",
            reply_markup=main_menu(user_id)
        )
        await callback.answer()
        return
    
    user_data = get_user(user_id)
    requests_left = get_requests_left(user_id)
    
    await state.set_state(ChatState.waiting_for_message)
    await callback.message.edit_text(
        f"💬 *Режим чата с ИИ*\n\n"
        f"📊 Осталось запросов: {requests_left} из {MAX_REQUESTS}\n"
        f"🤖 Модель: {MODELS.get(user_data[1], user_data[1])}\n"
        f"🌡️ Температура: {user_data[2]}\n\n"
        f"Просто напишите свой вопрос.\n"
        f"Для выхода нажмите «🔙 Выход»",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Выход", callback_data="back")]]),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.message(ChatState.waiting_for_message)
async def process_chat_message(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    if not can_use(user_id):
        await message.answer(
            f"❌ Вы использовали все {MAX_REQUESTS} запросов!\n"
            f"Бот доступен только для демонстрации."
        )
        await state.clear()
        return
    
    await message.bot.send_chat_action(message.chat.id, "typing")
    
    response, error = await ask_ai(user_id, message.text)
    
    if error:
        await message.answer(error)
        if "использовали все" in error:
            await state.clear()
    else:
        requests_left = get_requests_left(user_id)
        if len(response) > 4000:
            for i in range(0, len(response), 4000):
                await message.answer(response[i:i+4000])
            await message.answer(f"📊 Осталось запросов: {requests_left} из {MAX_REQUESTS}")
        else:
            await message.answer(
                f"{response}\n\n"
                f"📊 Осталось запросов: {requests_left} из {MAX_REQUESTS}",
                parse_mode="Markdown"
            )
        
        if requests_left == 0:
            await message.answer(
                f"⚠️ *Это был ваш последний запрос!*\n\n"
                f"Вы использовали все {MAX_REQUESTS} запросов.\n"
                f"Бот доступен только для демонстрации.\n\n"
                f"Спасибо за тестирование!",
                parse_mode="Markdown"
            )
            await state.clear()

@dp.callback_query(F.data == "models")
async def show_models(callback: CallbackQuery):
    await callback.message.edit_text(
        "🤖 *Выберите модель ИИ:*\n\n"
        "Каждая модель имеет свои особенности:\n"
        "• GPT-4o — универсальная, самая умная\n"
        "• DeepSeek — отличная логика, математика\n\n"
        "👇 Нажмите на модель для выбора:",
        reply_markup=models_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("model_"))
async def select_model(callback: CallbackQuery):
    user_id = callback.from_user.id
    model = callback.data.replace("model_", "")
    set_model(user_id, model)
    
    await callback.message.edit_text(
        f"✅ *Модель изменена!*\n\n"
        f"Теперь вы используете: {MODELS.get(model, model)}\n\n"
        f"Вернуться в меню — /start",
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "balance")
async def show_balance(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_data = get_user(user_id)
    requests_left = get_requests_left(user_id)
    requests_used = MAX_REQUESTS - requests_left
    
    text = f"💰 *Ваш баланс*\n\n"
    text += f"📊 Осталось запросов: {requests_left} из {MAX_REQUESTS}\n"
    text += f"📈 Использовано: {requests_used} из {MAX_REQUESTS}\n\n"
    text += f"🤖 Текущая модель: {MODELS.get(user_data[1], user_data[1])}\n"
    text += f"🌡️ Температура: {user_data[2]}\n"
    text += f"🎭 Системный промпт: {user_data[3][:50]}...\n\n"
    text += f"После использования всех запросов бот станет недоступен."
    
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=main_menu(user_id))
    await callback.answer()

@dp.callback_query(F.data == "history")
async def show_history(callback: CallbackQuery):
    user_id = callback.from_user.id
    history = get_history(user_id, 10)
    
    if not history:
        await callback.message.edit_text(
            "📋 *История пуста*\n\n"
            "Начните диалог с ИИ, чтобы здесь появились сообщения.",
            parse_mode="Markdown",
            reply_markup=main_menu(user_id)
        )
        await callback.answer()
        return
    
    text = "📋 *Последние сообщения:*\n\n"
    for i, (role, content) in enumerate(history[-6:], 1):
        icon = "👤" if role == "user" else "🤖"
        text += f"{icon} {content[:100]}"
        if len(content) > 100:
            text += "..."
        text += "\n\n"
    
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=main_menu(user_id))
    await callback.answer()

@dp.callback_query(F.data == "clear")
async def clear_chat(callback: CallbackQuery):
    user_id = callback.from_user.id
    clear_history(user_id)
    
    await callback.message.edit_text(
        "✅ *История диалога очищена!*\n\n"
        "Теперь ИИ будет отвечать без учёта предыдущих сообщений.",
        parse_mode="Markdown",
        reply_markup=main_menu(user_id)
    )
    await callback.answer()

@dp.callback_query(F.data == "settings")
async def show_settings(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_data = get_user(user_id)
    
    text = f"⚙️ *Настройки*\n\n"
    text += f"🎭 *Системный промпт:*\n`{user_data[3][:80]}{'...' if len(user_data[3]) > 80 else ''}`\n\n"
    text += f"🌡️ *Температура:* {user_data[2]} (0.1 — точный, 1.5 — креативный)\n\n"
    text += f"Выберите, что хотите изменить:"
    
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=settings_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "set_prompt")
async def set_prompt_start(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user_data = get_user(user_id)
    
    await state.set_state(SettingsState.waiting_for_system_prompt)
    await callback.message.edit_text(
        f"🎭 *Текущий системный промпт:*\n"
        f"`{user_data[3]}`\n\n"
        f"Введите новый системный промпт.\n\n"
        f"*Примеры:*\n"
        f"• «Ты эксперт по Python»\n"
        f"• «Ты дружелюбный помощник»\n\n"
        f"❌ Нажмите «Отмена» для выхода",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена", callback_data="settings")]])
    )
    await callback.answer()

@dp.message(SettingsState.waiting_for_system_prompt)
async def set_prompt(message: Message, state: FSMContext):
    user_id = message.from_user.id
    set_system_prompt(user_id, message.text)
    
    await message.answer(
        f"✅ *Системный промпт обновлён!*\n\n"
        f"Новый промпт: {message.text[:100]}{'...' if len(message.text) > 100 else ''}",
        parse_mode="Markdown",
        reply_markup=main_menu(user_id)
    )
    await state.clear()

@dp.callback_query(F.data == "set_temp")
async def set_temperature_start(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user_data = get_user(user_id)
    
    await state.set_state(SettingsState.waiting_for_temperature)
    await callback.message.edit_text(
        f"🌡️ *Текущая температура:* {user_data[2]}\n\n"
        f"Введите новое значение от 0.1 до 1.5:\n"
        f"• `0.1` — точные ответы\n"
        f"• `0.7` — баланс\n"
        f"• `1.5` — креативные ответы\n\n"
        f"*Пример:* `0.8`\n\n"
        f"❌ Нажмите «Отмена» для выхода",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена", callback_data="settings")]])
    )
    await callback.answer()

@dp.message(SettingsState.waiting_for_temperature)
async def set_temperature(message: Message, state: FSMContext):
    try:
        temp = float(message.text.replace(",", "."))
        if temp < 0.1 or temp > 1.5:
            raise ValueError
    except:
        await message.answer("❌ Введите число от 0.1 до 1.5, например: `0.8`", parse_mode="Markdown")
        return
    
    user_id = message.from_user.id
    set_temperature(user_id, temp)
    
    await message.answer(
        f"✅ *Температура обновлена!*\n\n"
        f"Новое значение: {temp}",
        parse_mode="Markdown",
        reply_markup=main_menu(user_id)
    )
    await state.clear()

@dp.callback_query(F.data == "help")
async def show_help(callback: CallbackQuery):
    text = (
        "ℹ️ *Помощь*\n\n"
        "📌 *Что умею:*\n"
        "• 💬 Общаться с топовыми ИИ-моделями\n"
        "• 🤖 Выбирать модель под задачу\n"
        "• 📋 Сохранять историю диалога\n"
        "• 🎭 Настраивать системный промпт\n"
        "• 🌡️ Регулировать креативность\n\n"
        f"🎁 У вас {MAX_REQUESTS} бесплатных запросов для демонстрации.\n"
        f"После этого бот станет недоступен.\n\n"
        "📌 *Доступные модели:*\n"
        "• GPT-4o — универсальная\n"
        "• DeepSeek — математика и логика\n\n"
        "👨‍💻 Создано для портфолио"
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=main_menu(callback.from_user.id))
    await callback.answer()

# ========== ВЕБ-СЕРВЕР И САМОПИНГ ==========
async def health_check(request):
    return web.Response(text="✅ Бот работает")

async def self_ping():
    while True:
        await asyncio.sleep(600)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(RENDER_URL, timeout=10) as resp:
                    print(f"[SELF-PING] {resp.status} - {datetime.now().strftime('%H:%M:%S')}")
        except:
            pass

async def start_web():
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    port = int(os.environ.get('PORT', 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"✅ Веб-сервер на порту {port}")

# ========== ЗАПУСК ==========
async def main():
    print("✅ ИИ-бот запущен!")
    print(f"📍 Адрес: {RENDER_URL}")
    print(f"🤖 Доступные модели: {', '.join(MODELS.keys())}")
    print(f"🎁 Максимум запросов на пользователя: {MAX_REQUESTS}")
    await start_web()
    asyncio.create_task(self_ping())
    print("🔄 Самопинг (каждые 10 минут) запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
