import os
import re
import time
import base64
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
HF_TOKEN = os.environ.get("HF_TOKEN", "")

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
    text = re.sub(r'`{1,3}([^`]*)`{1,3}', r'\1', text)
    text = re.sub(r'^\s*\|.*\|.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*[-|]+[-|+\s]*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def jina_read(url):
    try:
        r = requests.get(
            "https://r.jina.ai/" + url,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "text/plain"}
        )
        if r.status_code == 200 and len(r.text) > 200:
            lines = r.text.split('\n')
            clean_lines = [l for l in lines if l.strip()
                           and not l.startswith('!')
                           and not l.startswith('[Image')
                           and not l.startswith('URL Source')
                           and not l.startswith('Title:')]
            return '\n'.join(clean_lines[:60])[:3000]
    except Exception as e:
        print("Jina read error: " + str(e))
    return ""

def parse_ddg_urls(text):
    urls = re.findall(r'uddg=(https?[^&\s\)]+)', text)
    return [urllib.parse.unquote(u) for u in urls[:3]]

def web_search(query):
    snippets = []
    page_urls = []

    try:
        enc = urllib.parse.quote(query)
        r = requests.get(
            "https://r.jina.ai/https://lite.duckduckgo.com/lite/?q=" + enc,
            timeout=18,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "text/plain"}
        )
        if r.status_code == 200 and len(r.text) > 300:
            lines = r.text.split('\n')
            for line in lines:
                line = line.strip()
                if len(line) > 60 and not line.startswith('*') and not line.startswith('[') and 'duckduckgo.com' not in line:
                    snippets.append(line[:300])
                if len(snippets) >= 5:
                    break
            page_urls = parse_ddg_urls(r.text)
            print("DDG lite: " + str(len(snippets)) + " snippets, " + str(len(page_urls)) + " URLs")
    except Exception as e:
        print("DDG lite error: " + str(e))

    page_content = ""
    for url in page_urls:
        if url and url.startswith("http") and "duckduckgo.com" not in url:
            content = jina_read(url)
            if content and len(content) > 200:
                page_content = content
                print("Read page: " + url[:60])
                break

    if not snippets:
        try:
            enc = urllib.parse.quote(query)
            r = requests.get(
                "https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=" + enc + "&format=json&srlimit=2&srprop=snippet",
                timeout=10
            )
            wiki = r.json()
            for item in wiki.get("query", {}).get("search", []):
                s = re.sub(r'<[^>]+>', '', item.get("snippet", ""))
                if s:
                    snippets.append(s)
                title = item.get("title", "").replace(" ", "_")
                if title and not page_content:
                    c = jina_read("https://en.wikipedia.org/wiki/" + title)
                    if c:
                        page_content = c
                        break
        except Exception as e:
            print("Wikipedia error: " + str(e))

    parts = []
    if page_content:
        parts.append(page_content)
    if snippets:
        parts.append("Результаты поиска:\n" + "\n".join(snippets))

    result = "\n\n".join(parts)
    if result:
        print("Search total: " + str(len(result)) + " chars")
    return result[:4000]

def translate_to_english(prompt):
    try:
        headers = {
            "Authorization": "Bearer " + OPENROUTER_API_KEY,
            "Content-Type": "application/json"
        }
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json={
                "model": "google/gemma-4-26b-a4b-it:free",
                "messages": [{
                    "role": "user",
                    "content": "Translate this image description to English and expand it with vivid details. Reply with ONLY the English description, nothing else: " + prompt
                }]
            },
            timeout=20
        )
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print("Translate error: " + str(e))
    return prompt

def generate_image(prompt):
    en_prompt = translate_to_english(prompt)
    full_prompt = en_prompt + ", masterpiece, highly detailed, sharp focus, high quality"
    print("Generating: " + full_prompt[:80])
    # HuggingFace Inference API - models without license gates
    models = [
        "stabilityai/stable-diffusion-2-1",
        "Lykon/dreamshaper-8",
        "prompthero/openjourney-v4",
        "CompVis/stable-diffusion-v1-4",
    ]
    for model in models:
        try:
            print("Trying HF model: " + model)
            r = requests.post(
                "https://api-inference.huggingface.co/models/" + model,
                headers={"Authorization": "Bearer " + HF_TOKEN, "Content-Type": "application/json"},
                json={"inputs": full_prompt, "options": {"wait_for_model": True}},
                timeout=90
            )
            ct = r.headers.get("content-type", "")
            print("HF " + model.split("/")[1] + ": status=" + str(r.status_code) + " ct=" + ct[:20])
            if r.status_code == 200 and ct.startswith("image"):
                print("HF success: " + str(len(r.content)) + " bytes")
                return r.content
            else:
                print("HF error body: " + r.text[:200])
        except Exception as e:
            print("HF exception " + model + ": " + str(e))
    return None

def ask_ai(user_id, text):
    today = datetime.now().strftime("%d %B %Y")
    search_results = web_search(text)

    if search_results:
        system = (
            "Ты дружелюбный и точный ассистент. Сегодняшняя дата: " + today + ".\n"
            "Ниже — актуальные данные из интернета. Используй их как главный источник.\n"
            "ВАЖНО: пиши простым текстом без markdown — без звёздочек, решёток, подчёркиваний, таблиц. Только обычный текст.\n\n"
            "Данные из интернета:\n" + search_results
        )
    else:
        system = (
            "Ты дружелюбный и точный ассистент. Сегодняшняя дата: " + today + ".\n"
            "Отвечай точно и по делу. Если не уверен в актуальности — предупреди кратко.\n"
            "ВАЖНО: пиши простым текстом без markdown — без звёздочек, решёток, подчёркиваний, таблиц. Только обычный текст."
        )

    messages = get_memory(user_id)
    messages.append({"role": "user", "content": text})
    memory[user_id] = messages[-12:]

    full_messages = [{"role": "system", "content": system}] + memory[user_id]
    headers = {
        "Authorization": "Bearer " + OPENROUTER_API_KEY,
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
            print("Model " + model + " failed: " + str(r.status_code))
        except Exception as e:
            print("Model " + model + " error: " + str(e))

    return "Все модели недоступны, попробуй позже"

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

print("Бот запущен! Дата: " + datetime.now().strftime('%d.%m.%Y'))
app.run_polling()
