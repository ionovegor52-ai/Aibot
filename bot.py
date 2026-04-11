import asyncio
import aiohttp
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web

====== КОНФИГ ==========
BOT_T
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
