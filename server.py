import os
import time
import base64
import threading
import logging
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from dotenv import load_dotenv

# Загружаем переменные из .env при локальном запуске
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MathStudioBackend")

app = Flask(__name__)
CORS(app)

# ==============================================================================
# 1. КОНФИГУРАЦИЯ И ЗАЩИТА КЛЮЧЕЙ
# ==============================================================================

# Ключи читаются из переменных окружения Render (GEMINI_API_KEYS или GOOGLE_API_KEY)
RAW_KEYS = os.environ.get("GEMINI_API_KEYS", "").strip()
if not RAW_KEYS:
    RAW_KEYS = os.environ.get("GOOGLE_API_KEY", "").strip()

API_KEYS = [k.strip() for k in RAW_KEYS.split(",") if k.strip()]

MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite-preview"
]

SLOT_SPACING_SECONDS = 4.0        # Минимальный интервал между вызовами одного слота
COOLDOWN_ON_LIMIT_SECONDS = 60.0  # Кулдаун при 429 / 403 / 400
COOLDOWN_ON_ERROR_SECONDS = 15.0  # Кулдаун при 5xx


# ==============================================================================
# 2. МУЛЬТИПЛЕКСНЫЙ ПУЛ (MULTI-KEY & MULTI-MODEL POOL)
# ==============================================================================

@dataclass
class ChannelSlot:
    slot_id: str
    key: str
    model: str
    last_called_at: float = 0.0
    cooldown_until: float = 0.0
    total_calls: int = 0
    consecutive_errors: int = 0

    @property
    def is_available(self) -> bool:
        return time.time() >= self.cooldown_until

    @property
    def time_until_ready(self) -> float:
        now = time.time()
        spacing_wait = max(0.0, (self.last_called_at + SLOT_SPACING_SECONDS) - now)
        cooldown_wait = max(0.0, self.cooldown_until - now)
        return max(spacing_wait, cooldown_wait)


class GeminiMultiPool:
    def __init__(self, keys: List[str], models: List[str]):
        self.slots: List[ChannelSlot] = []
        self._pointer = 0
        self._lock = threading.Lock()
        self._models = models

        self.reconfigure(keys)

    def reconfigure(self, keys: List[str]):
        with self._lock:
            self.slots = []
            for k_idx, key in enumerate(keys, start=1):
                for model in self._models:
                    slot_id = f"K{k_idx:02d}_{model}"
                    self.slots.append(ChannelSlot(slot_id=slot_id, key=key, model=model))
            logger.info(f"Инициализирован пул ротации: {len(self.slots)} каналов.")

    def acquire_slot(self) -> ChannelSlot:
        with self._lock:
            if not self.slots:
                # Попытка перечитать ключи на лету
                latest_keys = [k.strip() for k in (os.environ.get("GEMINI_API_KEYS", "") or os.environ.get("GOOGLE_API_KEY", "")).split(",") if k.strip()]
                if latest_keys:
                    self.reconfigure(latest_keys)
                else:
                    raise RuntimeError("API-ключи не найдены в переменных окружения GEMINI_API_KEYS / GOOGLE_API_KEY.")

            n = len(self.slots)
            best_slot: Optional[ChannelSlot] = None
            min_wait = float("inf")

            for i in range(n):
                idx = (self._pointer + i) % n
                slot = self.slots[idx]

                if slot.is_available:
                    wait_time = max(0.0, (slot.last_called_at + SLOT_SPACING_SECONDS) - time.time())
                    if wait_time == 0:
                        self._pointer = (idx + 1) % n
                        slot.last_called_at = time.time()
                        slot.total_calls += 1
                        return slot

                    if wait_time < min_wait:
                        min_wait = wait_time
                        best_slot = slot

            if best_slot is None:
                best_slot = min(self.slots, key=lambda s: s.time_until_ready)
                min_wait = best_slot.time_until_ready

            if min_wait > 0:
                time.sleep(min_wait)

            best_slot.last_called_at = time.time()
            best_slot.total_calls += 1
            return best_slot

    def mark_error(self, slot: ChannelSlot, status_code: int):
        with self._lock:
            slot.consecutive_errors += 1
            if status_code in (400, 403, 429):
                slot.cooldown_until = time.time() + COOLDOWN_ON_LIMIT_SECONDS
                logger.warning(f"🚨 Ошибка/лимит [HTTP {status_code}] на слоте {slot.slot_id}. Кулдаун {COOLDOWN_ON_LIMIT_SECONDS}с.")
            else:
                slot.cooldown_until = time.time() + COOLDOWN_ON_ERROR_SECONDS
                logger.warning(f"⚠️ Ошибка сервера [HTTP {status_code}] на слоте {slot.slot_id}. Кулдаун {COOLDOWN_ON_ERROR_SECONDS}с.")

    def mark_success(self, slot: ChannelSlot):
        with self._lock:
            slot.consecutive_errors = 0


rotator_pool = GeminiMultiPool(keys=API_KEYS, models=MODELS)


# ==============================================================================
# 3. АКАДЕМИЧЕСКИЕ ПРОФИЛИ НАСТАВНИКОВ MATH STUDIO
# ==============================================================================

PROFILES = {
    "academic": """Ты — «Академик», выдающийся ИИ-тьютор, обладающий знаниями уровня PhD в области математики и Computer Science. Твоя миссия — не просто обучать, а трансформировать мышление студента, развивая у него интуитивное и логическое понимание предмета.
Методология (Сократовский метод):
Твоя стратегия базируется на методе майевтики. Ты веришь, что истина уже заложена в ученике, и твоя задача — помочь ей родиться.
Запрет на прямые ответы: Тебе категорически запрещено выдавать готовое решение, формулу или код в первом же сообщении, даже если пользователь прямо об этом просит.
Декомпозиция: Если задача сложная, разбей её на микро-шаги. Не переходи к следующему шагу, пока не убедишься, что студент освоил предыдущий.
Выявление пробелов: Если студент ошибается, не исправляй его сразу. Задай вопрос, который заставит его самого заметить логическое противоречие.
Апелляция к базе: Проси вспомнить определения, базовые свойства или аналогичные задачи, которые он решал ранее.
Алгоритм твоего ответа:
Шаг 1: Анализ. Кратко похвали за интерес к теме или признай сложность задачи.
Шаг 2: Наводка. Дай небольшую подсказку, метафору или вспомни аналогию из реального мира.
Шаг 3: Сократовский вопрос. Задай один (максимум два) четких вопроса, которые направят мысль студента к первому шагу решения.
Шаг 4: Проверка. Закончи фразу вопросом: «С чего мы начнем?» или «Какое свойство здесь кажется тебе ключевым?».
Тон и стиль:
Интеллектуальный, поддерживающий, но строгий в плане логики.
Используй профессиональную терминологию, но будь готов объяснить её «на пальцах».
Твои ответы должны быть лаконичными. Длинные лекции убивают диалог.
СТРОГОЕ ПРАВИЛО ДЛЯ ГРАФИКОВ (КРИТИЧЕСКИ ВАЖНО):
Если ты описываешь функцию или ученик просит построить график, ты ОБЯЗАН сгенерировать JSON-массив из 15-30 точек.
Ты ДОЛЖЕН обернуть этот массив в тройные обратные кавычки с языком "graph". НЕ пиши JSON обычным текстом!
Формат ОБЯЗАН быть таким:
```graph
[{"x": -5, "y": 25}, {"x": 0, "y": 0}, {"x": 5, "y": 25}]
```
ВАЖНО: Математику оборачивай в одинарные $...$ или двойные $$...$$ знаки доллара.""",

    "ent": """Ты — ведущий эксперт по подготовке к ЕНТ, НИШ и КТЛ (БИЛ) с 15-летним стажем. Твой стиль — «педагогический спецназ». Ты не просто учишь математике, ты учишь взламывать тесты. Твоя задача — довести результат ученика до максимума (140/140 на ЕНТ или проходной балл в НИШ).
Твои ключевые принципы:
Скорость превыше всего: Если задачу можно решить за 30 секунд методом исключения или подстановки — научи этому. Время на экзамене — твой главный враг.
Детектор ловушек: В каждом ответе ищи «дистракторы» (ложные ответы, которые кажутся правильными). Указывай, на чем обычно ловят учеников (ОДЗ, единицы измерения).
Казахстанский контекст: Все прикладные задачи связывай с реалиями Казахстана (Астана, Алматы, Шымкент; расчеты в тенге).
Алгоритм разбора любой задачи:
Этап 1: Суть. Краткое условие.
Этап 2: "Читерский" метод (Lifehack). Как решить задачу максимально быстро.
Этап 3: Классический метод. Кратко напомни теорию.
Этап 4: Минное поле. Укажи ловушку составителей.
СТРОГОЕ ПРАВИЛО ДЛЯ ГРАФИКОВ:
Если ты описываешь функцию или ученик просит построить график, сгенерируй JSON-массив в блоке:
```graph
[{"x": -5, "y": 25}, {"x": 0, "y": 0}, {"x": 5, "y": 25}]
```
ВАЖНО: Математику оборачивай в $...$ или $$...$$ знаки доллара.""",

    "focus": """Ты — Фокус-Тьютор. Добрый наставник для учеников, которым трудно долго концентрироваться.
ТВОИ СТРОГИЕ ПРАВИЛА (НАРУШАТЬ НЕЛЬЗЯ):
1. Пиши ОЧЕНЬ коротко. Не больше 2-3 предложений за один ответ!
2. Выдавай только ОДИН микро-шаг за раз.
3. Обязательно хвали ученика («Супер!», «Красава!», «Верно!»).
4. Если ученик прислал фото, похвали его за старание и разбери только ПЕРВУЮ строчку решения.
5. Заканчивай сообщение простым вопросом.
СТРОГОЕ ПРАВИЛО ДЛЯ ГРАФИКОВ:
Если нужен график, оберни JSON-массив в блок ```graph [...] ```.
ВАЖНО: Используй эмодзи и оборачивай математику в $...$ или $$...$$."""
}


# ==============================================================================
# 4. ВЫПОЛНЕНИЕ ЗАПРОСА С FAILOVER ПО 14 КАНАЛАМ
# ==============================================================================

def execute_with_failover(query: str, history: List[Dict], profile: str, image_b64: Optional[str]) -> str:
    system_instruction = PROFILES.get(profile, PROFILES["academic"])
    
    contents = []
    for h in history[-8:]:
        role = "user" if h.get("role") == "user" else "model"
        text = h.get("content", "")
        if text:
            contents.append({"role": role, "parts": [{"text": text}]})

    current_parts: List[Dict[str, Any]] = []
    if image_b64:
        clean_b64 = image_b64.split(",")[1] if "," in image_b64 else image_b64
        current_parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": clean_b64
            }
        })
    
    prompt_text = query if query else "Посмотри на это фото и помоги мне найти ошибку или решить задачу."
    current_parts.append({"text": prompt_text})
    contents.append({"role": "user", "parts": current_parts})

    payload = {
        "contents": contents,
        "system_instruction": {
            "parts": [{"text": system_instruction}]
        },
        "generationConfig": {
            "temperature": 0.35,
            "maxOutputTokens": 2048
        }
    }

    max_retries = max(1, len(rotator_pool.slots))
    last_error = None

    for attempt in range(max_retries):
        slot = rotator_pool.acquire_slot()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{slot.model}:generateContent?key={slot.key}"

        try:
            resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=30)
            
            if resp.status_code == 200:
                rotator_pool.mark_success(slot)
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates and "content" in candidates[0]:
                    parts = candidates[0]["content"].get("parts", [])
                    return "".join(p.get("text", "") for p in parts)
                return "Ответ не был сформирован моделью."

            rotator_pool.mark_error(slot, resp.status_code)
            last_error = f"HTTP {resp.status_code}: {resp.text[:120]}"
            logger.info(f"Failover с канала {slot.slot_id} на следующий (попытка {attempt + 1}/{max_retries})...")

        except Exception as e:
            rotator_pool.mark_error(slot, 500)
            last_error = str(e)
            logger.error(f"Сетевой сбой на слоте {slot.slot_id}: {e}")

    raise RuntimeError(f"Все каналы пула Gemini временно недоступны. Последняя ошибка: {last_error}")


# ==============================================================================
# 5. МАРШРУТЫ API
# ==============================================================================

@app.route('/', methods=['GET'])
def ping():
    return "Сервер Math Studio активен и готов к работе!", 200


@app.route('/health', methods=['GET'])
def health():
    available = sum(1 for s in rotator_pool.slots if s.is_available)
    return jsonify({
        'status': 'ok',
        'total_channels': len(rotator_pool.slots),
        'available_channels': available
    })


@app.route('/ask', methods=['POST'])
def ask():
    try:
        data = request.get_json() or {}
        user_query = data.get('query', '')
        history = data.get('history', [])
        profile = data.get('profile', 'academic')
        image_b64 = data.get('image', None)

        if not user_query and not image_b64:
            return jsonify({'status': 'error', 'answer': 'Запрос не может быть пустым.'}), 400

        answer = execute_with_failover(user_query, history, profile, image_b64)
        return jsonify({'status': 'success', 'answer': answer})

    except Exception as e:
        logger.error(f"Ошибка выполнения /ask: {e}")
        return jsonify({'status': 'error', 'answer': f"Сервер временно перегружен: {str(e)}"})


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
