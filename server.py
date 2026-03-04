from flask import Flask, request, jsonify
from flask_cors import CORS
import google.generativeai as genai

app = Flask(__name__)
# CORS разрешает вашему React-приложению общаться с этим сервером
CORS(app) 

# ВАЖНО: Вставьте сюда ваш реальный ключ API от Gemini
genai.configure(api_key="AIzaSyBM2bf-H9x2wCUFbLbstuE0OInMvzd3540")

@app.route('/ask', methods=['POST'])
def ask_ai():
    data = request.json
    user_query = data.get('query', '')
    
    # Инструкция для ИИ (адаптирована для показа внутри приложения)
    sys_instruct = """Ты — наставник Math Studio. Руководитель: Жунус Абаевич.
    Объясняй решения по шагам. 
    Используй HTML теги: <b>жирный</b>, <br> для переноса строки.
    Все формулы оборачивай в тег <code>...</code>.
    Не используй Markdown (звездочки **)."""
    
    try:
        model = genai.GenerativeModel(
            model_name='gemini-3-flash-preview', # Или 'gemini-3-flash-preview', если используете его
            system_instruction=sys_instruct
        )
        response = model.generate_content(user_query)
        
        # Легкая очистка текста от звездочек, если ИИ ошибется
        text = response.text.replace('**', '<b>').replace('**', '</b>')
        
        return jsonify({'status': 'success', 'answer': text})
    except Exception as e:
        return jsonify({'status': 'error', 'answer': str(e)})

if __name__ == '__main__':
    # host='0.0.0.0' заставляет сервер слушать все входящие адреса
    app.run(host='0.0.0.0', port=5000, debug=True)