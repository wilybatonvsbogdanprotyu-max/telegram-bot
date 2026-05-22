import os
import urllib.parse
import requests
from duckduckgo_search import DDGS
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

TELEGRAM_TOKEN = os.environ["BOT_TOKEN"]
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]

MODELS = [
    "google/gemma-4-26b-a4b-it:free",
    "openai/gpt-oss-20b:free",
    "z-ai/glm-4.5-air:free",
]

memory = {}

def get_memory(user_id):
    if user_id not in memory:
        memory[user_id] = []
    return memory[user_id]

def web_search(query):
    try:
        results = DDGS().text(query, max_results=3)
        if not results:
            return ""
        parts = []
        for r in results:
            parts.append(f"- {r['title']}: {r['body'][:300]}")
        return "\n".join(parts)
    except Exception as e:
        print(f"Search error: {e}")
        return ""

def ask_ai(user_id, text):
    search_results = web_search(text)

    system = "Ты дружелюбный полезный ассистент. Отвечай точно и актуально."
    if search_results:
        system += f"\n\nАктуальные данные из интернета:\n{search_results}\n\nИспользуй эти данные в ответе."

    messages = get_memory(user_id)
    messages.append({"role": "user", "content": text})
    memory[user_id] = messages[-12:]

    full_messages = [{"role": "system", "content": system}] + memory[user_id]

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

    for model in MODELS:
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json={"model": model, "messages": full_messages},
                timeout=60
            )
            if r.status_code == 200:
                answer = r.json()["choices"][0]["message"]["content"]
                memory[user_id].append({"role": "assistant", "content": answer})
                return answer
            print(f"Model {model} failed: {r.status_code} {r.text[:200]}")
        except Exception as e:
            print(f"Model {model} error: {e}")

    return "⚠️ Все модели недоступны, попробуй позже"

def generate_image(prompt):
    encoded = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true"
    r = requests.get(url, timeout=120)
    if r.status_code != 200:
        return None
    return r.content

async def img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("Напиши: /img кот в космосе")
        return
    msg = await update.message.reply_text("🎨 создаю изображение...")
    image = generate_image(prompt)
    if image:
        await update.message.reply_photo(photo=image)
    else:
        await update.message.reply_text("❌ ошибка генерации")
    try:
        await msg.delete()
    except Exception:
        pass

async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    answer = ask_ai(user_id, text)
    await update.message.reply_text("🤖 " + answer)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет!\n\n"
        "Я AI бот с поиском в интернете 🤖🌐\n\n"
        "📌 Команды:\n"
        "/img <описание> — создать изображение\n\n"
        "💬 Просто напиши вопрос — найду актуальный ответ"
    )

app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("img", img))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

print("Бот запущен с поиском!")
app.run_polling()
