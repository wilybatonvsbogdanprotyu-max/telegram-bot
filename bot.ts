import TelegramBot from "node-telegram-bot-api";
import fetch from "node-fetch";

const TELEGRAM_TOKEN = process.env.BOT_TOKEN;
const OPENROUTER_API_KEY = process.env.OPENROUTER_API_KEY;

if (!TELEGRAM_TOKEN) throw new Error("BOT_TOKEN не задан");
if (!OPENROUTER_API_KEY) throw new Error("OPENROUTER_API_KEY не задан");

const bot = new TelegramBot(TELEGRAM_TOKEN, { polling: true });
console.log("🤖 Бот запущен и готов к работе!");

const FREE_MODELS = [
  "google/gemma-4-26b-a4b-it:free",
  "google/gemma-4-31b-it:free",
  "nvidia/nemotron-3-super-120b-a12b:free",
  "minimax/minimax-m2.5:free",
  "liquid/lfm-2.5-1.2b-instruct:free",
];

interface QueueItem {
  chatId: number;
  userText: string;
}

const requestQueue: QueueItem[] = [];
let processing = false;

function enqueue(chatId: number, userText: string) {
  requestQueue.push({ chatId, userText });
  processQueue();
}

async function processQueue() {
  if (processing || requestQueue.length === 0) return;
  processing = true;

  const { chatId, userText } = requestQueue.shift()!;

  try {
    if (userText.startsWith("/image ")) {
      const prompt = userText.slice(7).trim();
      if (!prompt) {
        await bot.sendMessage(chatId, "⚠️ Укажи описание после /image. Например: /image закат над морем");
      } else {
        await bot.sendMessage(chatId, "🎨 Генерирую изображение...");
        const imageUrl = `https://image.pollinations.ai/prompt/${encodeURIComponent(prompt)}?width=1024&height=1024&nologo=true&seed=${Date.now()}`;
        await bot.sendPhoto(chatId, imageUrl, { caption: `🖼 ${prompt}` });
      }
    } else {
      const response = await fetchWithRetry(userText);
      const chunks = response.match(/[\s\S]{1,4000}/g) || [];
      for (const chunk of chunks) {
        await bot.sendMessage(chatId, chunk);
      }
    }
  } catch (err: any) {
    console.error("Ошибка при обработке запроса:", err);
    await bot.sendMessage(
      chatId,
      "❌ Не удалось получить ответ. Попробуйте чуть позже.",
    );
  }

  await new Promise((r) => setTimeout(r, 500));
  processing = false;
  processQueue();
}

bot.on("message", (msg) => {
  const chatId = msg.chat.id;
  const userText = msg.text?.trim();

  if (!userText) {
    bot.sendMessage(chatId, "⚠️ Пустые сообщения не обрабатываются.");
    return;
  }

  enqueue(chatId, userText);
});

async function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

async function fetchWithRetry(userInput: string): Promise<string> {
  const MAX_RETRIES = 4;
  const RETRY_DELAY_MS = 8000;

  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    const model = FREE_MODELS[(attempt - 1) % FREE_MODELS.length];
    console.log(`Попытка ${attempt}/${MAX_RETRIES}, модель: ${model}`);

    try {
      return await fetchOpenRouter(userInput, model);
    } catch (err: any) {
      const is429 = err.message?.includes("429");
      const is404 = err.message?.includes("404");

      if ((is429 || is404) && attempt < MAX_RETRIES) {
        console.log(`Ошибка ${is429 ? "429" : "404"}, повтор через ${RETRY_DELAY_MS / 1000}с...`);
        await sleep(RETRY_DELAY_MS);
        continue;
      }
      throw err;
    }
  }

  throw new Error("Все попытки исчерпаны");
}

async function fetchOpenRouter(userInput: string, model: string): Promise<string> {
  const res = await fetch("https://openrouter.ai/api/v1/chat/completions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${OPENROUTER_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model,
      messages: [{ role: "user", content: userInput }],
    }),
  });

  const data = (await res.json()) as any;

  if (!res.ok) {
    throw new Error(
      `OpenRouter API ошибка: ${res.status} ${JSON.stringify(data)}`,
    );
  }

  if (!data.choices || !data.choices[0]?.message?.content) {
    throw new Error(
      `OpenRouter вернул неожиданный ответ: ${JSON.stringify(data)}`,
    );
  }

  return data.choices[0].message.content;
}