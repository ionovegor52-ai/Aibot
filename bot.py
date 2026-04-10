import asyncio
import aiohttp
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web

# ========== КОНФИГ ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
RENDER_URL = os.environ.get("RENDER_URL", "https://aibot-f7s6.onrender.com")

# Простое хранилище
user_requests = {}

# Инициализация
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ========== КЛАВИАТУРА ==========
def main_menu():
    buttons = [
        [InlineKeyboardButton(text="💬 Спросить ИИ", callback_data="ask")],
        [InlineKeyboardButton(text="💰 Баланс", callback_data="balance")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ========== ОБРАБОТЧИКИ ==========
@dp.message(Command("start"))
async def start(message: Message):
    user_id = message.from_user.id
    if user_id not in user_requests:
        user_requests[user_id] = 5
    
    await message.answer(
        "🤖 *Простой ИИ-бот*\n\n"
        f"У вас осталось *{user_requests[user_id]}* запросов\n"
        "Просто напишите вопрос, я отвечу через GPT-4o\n\n"
        "👇 Выберите действие:",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "ask")
async def ask_start(callback: types.CallbackQuery):
    await callback.message.answer("✏️ Напишите ваш вопрос:")
    await callback.answer()

@dp.callback_query(F.data == "balance")
async def show_balance(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    left = user_requests.get(user_id, 5)
    await callback.message.answer(f"💰 Осталось запросов: {left}")
    await callback.answer()

@dp.message()
async def chat(message: Message):
    user_id = message.from_user.id
    
    if user_id not in user_requests:
        user_requests[user_id] = 5
    
    if user_requests[user_id] <= 0:
        await message.answer("❌ У вас закончились запросы!")
        return
    
    await message.bot.send_chat_action(message.chat.id, "typing")
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "openai/gpt-4o",
        "messages": [{"role": "user", "content": message.text}],
        "max_tokens": 500
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://openrouter.ai/api/v1/chat/completions",
                                   headers=headers, json=payload, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    answer = data["choices"][0]["message"]["content"]
                    user_requests[user_id] -= 1
                    left = user_requests[user_id]
                    await message.answer(f"{answer}\n\n📊 Осталось запросов: {left}")
                else:
                    await message.answer(f"❌ Ошибка API: {resp.status}")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)[:100]}")

# ========== ВЕБ-СЕРВЕР И ПИНГ ==========
async def health(request):
    return web.Response(text="✅ Бот работает")

async def ping():
    while True:
        await asyncio.sleep(600)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(RENDER_URL) as resp:
                    print(f"[SELF-PING] {resp.status}")
        except Exception as e:
            print(f"[SELF-PING] Ошибка: {e}")

async def start_web():
    app = web.Application()
    app.router.add_get('/', health)
    port = int(os.environ.get('PORT', 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def main():
    await start_web()
    asyncio.create_task(ping())
    print("✅ Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
