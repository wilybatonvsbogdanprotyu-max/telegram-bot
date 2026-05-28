import os
import urllib.parse
import requests
from datetime import datetime
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
        url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1&skip_disambig=1"
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        data = r.json()
        results = []
        if data.get("AbstractText"):
            results.append(data["AbstractText"][:500])
        for topic in data.get("RelatedTopics", [])[:4]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append(topic["Text"][:300])
        if results:
            return "\n".join(results)
    except Exception as e:
        print(f"DDG error: {e}")
    try:
        url = f"https://lite.duckduckgo.com/lite/?q={urllib.parse.quote(query)}"
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        from html.parser import HTMLParser
        class TextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.texts = []
            def handle_data(self, data):
                t = data.strip()
                if len(t) > 40:
                    self.texts.append(t)
        parser = TextExtractor()
        parser.feed(r.text)
        if parser.texts:
            return "\n".join(parser.texts[:3])
    except Exception as e:
        print(f"DDG lite error: {e}")
    return ""

def translate_to_english(prompt):
    """Translate prompt to English for better image generation."""
    try:
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json={
                "model": "google/gemma-4-26b-a4b-it:free",
                "messages": [
                    {
                        "role": "user",
                        "content": f"Translate this image description to English. Reply with ONLY the translation, nothing else: {prompt}"
                    }
                ]
            },
            timeout=20
        )
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"Translate error: {e}")
    return prompt  # fallback to original

def ask_ai(user_id, text):
    today = datetime.now().strftime("%d %B %Y")
    search_results = web_search(text)

    system = f"Ты дружелюбный полезный ассистент. Сегодняшняя дата: {today}. Отвечай точно и актуально."
    if search_results:
        system += f"\n\nАктуальные данные из интернета (используй их):\n{search_results}"

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
    en_prompt = translate_to_english(prompt)
    print(f"Image prompt: '{prompt}' -> '{en_prompt}'")
    encoded = urllib.parse.quote(en_prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&enhance=true"
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

print(f"Бот запущен! Дата: {datetime.now().strftime('%d.%m.%Y')}")
app.run_polling()
