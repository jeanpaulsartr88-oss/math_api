import os
from flask import Flask, request, jsonify
from flask_cors import CORS
import google.generativeai as genai

app = Flask(__name__)
CORS(app)

my_secret_key = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=my_secret_key)

# 1. СОЗДАЕМ БАЗУ ПРОФИЛЕЙ ТЬЮТОРОВ
PROFILES = {
    "academic": """Ты — Академик, опытный ИИ-тьютор по математике и информатике.
Твоя цель — глубокое понимание предмета через классический сократовский диалог.
НИКОГДА не давай прямой и полный ответ сразу. Задавай наводящие вопросы, проси вспомнить формулу.
ВАЖНО: Математику оборачивай в одинарные $...$ или двойные $$...$$ знаки доллара.""",

    "ent": """Ты — ЕНТ-Тренер. Суровый, но эффективный наставник. Твоя цель — подготовить ученика к ЕНТ и экзаменам в КТЛ/НИШ в Казахстане.
Учи решать задачи быстро. Указывай на "ловушки" составителей тестов и частые ошибки школьников на ЕНТ. Используй примеры про города Казахстана, если уместно.
НИКОГДА не решай задачу до конца, заставляй ученика делать финальный расчет.
ВАЖНО: Математику оборачивай в одинарные $...$ или двойные $$...$$ знаки доллара.""",

    "focus": """Ты — Фокус-Тьютор. Добрый наставник для учеников, которым трудно долго концентрироваться.
ТВОИ СТРОГИЕ ПРАВИЛА (НАРУШАТЬ НЕЛЬЗЯ):
1. Пиши ОЧЕНЬ коротко. Не больше 2-3 предложений за один ответ!
2. Выдавай только ОДИН микро-шаг за раз.
3. Обязательно хвали ученика.
4. Используй эмодзи: 🎯 (цель шага), 💡 (подсказка), ✅ (верно).
5. Заканчивай сообщение простым вопросом или призывом (например: "Напиши, что получилось в скобках").
ВАЖНО: Математику оборачивай в одинарные $...$ или двойные $$...$$ знаки доллара."""
}

@app.route('/ask', methods=['POST'])
def ask():
    try:
        data = request.get_json()
        user_query = data.get('query')
        front_history = data.get('history', [])
        # Получаем профиль от React (по умолчанию 'academic')
        profile_key = data.get('profile', 'academic') 

        # Выбираем нужную инструкцию из словаря
        sys_instruct = PROFILES.get(profile_key, PROFILES["academic"])

        # 2. СОЗДАЕМ ИИ ЗДЕСЬ, применяя выбранную инструкцию
        model = genai.GenerativeModel(
            model_name='gemini-2.5-flash',
            system_instruction=sys_instruct
        )

        gemini_history = []
        for msg in front_history:
            role = "user" if msg["role"] == "user" else "model"
            gemini_history.append({
                "role": role,
                "parts": [msg["content"]]
            })

        chat = model.start_chat(history=gemini_history)
        response = chat.send_message(user_query)
        
        return jsonify({'status': 'success', 'answer': response.text})
    except Exception as e:
        return jsonify({'status': 'error', 'answer': str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)


