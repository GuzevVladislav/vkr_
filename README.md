# TaskFlow — Интеллектуальный планировщик задач

Flask-приложение по ВКР. Нейросетевые модули представлены заглушками.

## Запуск

```bash
pip install -r requirements.txt
python app.py
# → http://127.0.0.1:5000
```

## Структура

```
taskflow/
├── app.py                   # Flask-приложение, маршруты, AI-заглушки
├── requirements.txt
├── database.db              # создаётся автоматически при первом запуске
├── static/
│   ├── css/main.css
│   └── js/main.js
└── templates/
    ├── base.html            # базовый шаблон (Jinja2)
    ├── login.html
    ├── register.html
    ├── index.html           # дашборд
    ├── tasks.html           # список задач
    ├── task_form.html       # форма создания/редактирования
    ├── pomodoro.html        # таймер
    └── stats.html           # статистика + Chart.js
```

## AI-заглушки → замена на реальные модели

В `app.py` три функции-стабы. Каждая содержит docstring с точным контрактом.

### 1. `ai_classify_importance(title, description)` → квадрант Эйзенхауэра

```python
# Замените тело функции:
from ai_modules.bert_classifier import classify_importance
return classify_importance(title, description)

# Ожидаемый return:
# {"importance_score": float, "is_important": bool, "quadrant": "A"|"B"|"C"|"D"}
```

Модель: `DeepPavlov/rubert-base-cased` + классификатор поверх [CLS]-токена.

### 2. `ai_estimate_time(title, difficulty)` → минуты

```python
from ai_modules.time_predictor import predict_time
return predict_time(title, difficulty, user_id)   # int
```

Модель: XGBoost на признаках (BERT-вектор, категория, сложность, день недели, время).

### 3. `ai_deadline_risk(task_id, user_id)` → вероятность просрочки

```python
from ai_modules.risk_predictor import predict_risk
return predict_risk(task_id, user_id)

# Ожидаемый return:
# {"probability": float, "message": str}
```

Модель: логистическая регрессия (scikit-learn) на истории пользователя.

## Эндпоинты API (JSON)

| Метод | URL | Тело | Ответ |
|-------|-----|------|-------|
| POST | `/ai/estimate_time` | `{title, difficulty}` | `{minutes}` |
| POST | `/ai/risk` | `{task_id}` | `{probability, message}` |
| POST | `/ai/classify` | `{title, description}` | `{quadrant, importance_score}` |
| POST | `/pomodoro/session` | `{task_id, duration, completed}` | `{status}` |

## База данных (SQLite)

Схема создаётся при первом запуске (`init_db()`).  
Таблицы: `users`, `tasks`, `task_history`, `pomodoro_sessions`.
