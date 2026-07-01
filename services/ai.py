import logging

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """Ты — редактор Telegram-канала о технологиях и AI. Тебе дают список последних постов из разных Telegram-каналов.

Выбери 3–5 самых важных и интересных новостей. Для каждой оформи блок по шаблону:

[эмодзи] Заголовок

Краткое описание (1–2 предложения).

• Важный факт
• Важный факт
• Важный факт

Почему это важно:
[Объяснение значимости для читателя]

Источник: @channel

---

Правила эмодзи — ставь ТОЛЬКО если новость подходит по смыслу:
🤖 — AI, нейросети, языковые модели
🚀 — запуск продукта, релиз, новая фича
💰 — деньги, инвестиции, финансы, сделки
🛡️ — безопасность, взлом, уязвимости
🔬 — исследование, наука, эксперимент
⚡ — обновление модели, ускорение, оптимизация

Если подходящего эмодзи нет — не используй. Максимум 3–5 эмодзи на весь пост.
Разделяй блоки строкой из трёх дефисов (---).
Не включай рекламные и малозначимые посты.
Пиши на русском языке."""


async def generate_digest(posts: list[dict]) -> str:
    from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL

    if not OPENAI_API_KEY:
        raise RuntimeError(
            "OpenAI не настроен. Укажи OPENAI_API_KEY в .env"
        )

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

    posts_text = ""
    for i, post in enumerate(posts, 1):
        date = post.get("date", "")[:16]
        source = post.get("source", "")
        text = (post.get("text") or "")[:800]
        posts_text += f"\n[{i}] Канал: {source} | {date}\n{text}\n"

    user_msg = (
        f"Вот последние посты из Telegram-каналов ({len(posts)} шт.):\n"
        f"{posts_text}\n\nСделай выжимку самых важных новостей."
    )

    logger.info("Отправляю %d постов в AI (модель: %s)", len(posts), OPENAI_MODEL)

    response = await client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=2500,
        temperature=0.7,
    )

    result = response.choices[0].message.content.strip()
    logger.info("AI сгенерировал выжимку (%d символов)", len(result))
    return result
