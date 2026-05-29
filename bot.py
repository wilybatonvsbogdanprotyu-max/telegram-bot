import os
import re
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

def clean_markdown(text):
    text = re.sub(r'#{1,6}\s*', '', text)
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,2}([^_]+)_{1,2}', r'\1', text)
    text = re.sub(r'`{1,3}[^`]*`{1,3}', lambda m: m.group().strip('`'), text)
    text = re.sub(r'^\s*\|.*\|.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*[-|]+[-|+\s]*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

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
                "messages": [{
                    "role": "user",
                    "content": (
                        f"Translate this image description to English and expand it with details "
                        f"to make it vivid and complete. Reply with ONLY the English description, nothing else: {prompt}"
                    )
                }]
            },
            timeout=20
        )
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"Translate error: {e}")
    return prompt

def ask_ai(user_id, text):
    today = datetime.now().strftime("%d %B %Y")
    search_results = web_search(text)

    system = (
        f"Ты дружелюбный полезный ассистент. Сегодняшняя дата: {today}. "
        f"Отвечай точно и актуально. "
        f"ВАЖНО: пиши простым текстом без markdown-форматирования — "
        f"без звёздочек, решёток, подчёркиваний, таблиц и других специальных символов."
    )
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
                answer = clean_markdown(answer)
                memory[user_id].append({"role": "assistant", "content": answer})
                return answer
            print(f"Model {model} failed: {r.status_code} {r.text[:200]}")
        except Exception as e:
            print(f"Model {model} error: {e}")

    return "Все модели недоступны, попробуй позже"

def generate_image(prompt):
    en_prompt = translate_to_english(prompt)
    quality = "masterpiece, highly detailed, perfect anatomy, complete, sharp focus, high quality, 8k"
    full_prompt = f"{en_prompt}, {quality}"
    print(f"Image: '{prompt}' -> '{full_prompt[:80]}...'")
    encoded = urllib.parse.quote(full_prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded}?model=flux&width=1024&height=1024&nologo=true&enhance=true"
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
        await update.message.reply_text("Ошибка генерации, попробуй снова")
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
        "Привет!\n\n"
        "Я AI бот с поиском в интернете\n\n"
        "Команды:\n"
        "/img описание — создать изображение\n\n"
        "Просто напиши вопрос — найду актуальный ответ"
    )

app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("img", img))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

print(f"Бот запущен! Дата: {datetime.now().strftime('%d.%m.%Y')}")
app.run_polling()
