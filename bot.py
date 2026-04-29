import os
import urllib.parse
import requests
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

TEXT_MODEL = "openai/gpt-oss-120b:free"

memory = {}

def get_memory(user_id):
    if user_id not in memory:
        memory[user_id] = [
            {"role": "system", "content": "Ты дружелюбный полезный ассистент."}
        ]
    return memory[user_id]

def ask_ai(user_id, text):
    url = "https://openrouter.ai/api/v1/chat/completions"
    messages = get_memory(user_id)
    messages.append({"role": "user", "content": text})
    memory[user_id] = messages[-12:]

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {"model": TEXT_MODEL, "messages": memory[user_id]}

    r = requests.post(url, headers=headers, json=data, timeout=30)
    if r.status_code != 200:
        print("AI error:", r.status_code, r.text[:300])
        return "⚠️ Ошибка ИИ"

    answer = r.json()["choices"][0]["message"]["content"]
    memory[user_id].append({"role": "assistant", "content": answer})
    return answer

def generate_image(prompt):
    encoded = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true"
    r = requests.get(url, timeout=120)
    if r.status_code != 200:
        print("IMG error:", r.status_code, r.text[:200])
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
    answer = ask_ai(user_id, text)
    await update.message.reply_text("🤖 " + answer)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет!\n\n"
        "Я бесплатный AI бот 🤖\n\n"
        "📌 Команды:\n"
        "/img <описание> — создать изображение\n\n"
        "💬 Просто напиши вопрос — я отвечу"
    )

app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("img", img))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

print("Бот запущен!")
app.run_polling()
