# UI for ai-docs-generate

Веб-приложение для запуска `ai-docs-generate` и просмотра логов генерации документации в реальном времени.

## Структура

- `backend`: FastAPI API + WebSocket для стриминга логов.
- `frontend`: SolidJS интерфейс (Vite).

## Требования

- Python 3.11+
- Node.js 18+
- Установленная утилита `ai-docs-generate` в окружении бэкенда

## Запуск backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install ai-docs-generate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Переменные окружения backend

- `DOCS_ALLOWED_ROOT` — корень песочницы для путей (по умолчанию `/workspace`).
- `DOCS_GENERATED_ROOT` — папка, которая раздается как статика (по умолчанию `/tmp/generated_docs`).

## Запуск frontend

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

Frontend проксирует `/api`, `/ws` и `/generated` на backend `localhost:8000`.

## API

### `POST /api/generate-docs`

Запускает задачу генерации.

```json
{ "source_path": "./my-project" }
```

Успешный ответ:

```json
{ "task_id": "<uuid>" }
```

### `GET /api/result/{task_id}`

Возвращает статус задачи и ссылку на результат.

### `WS /ws/logs/{task_id}`

Построчно возвращает логи.

Служебные сообщения:

- `__FINISHED__|<url>` — генерация успешна, `<url>` ведет на `index.html` документации.
- `__FAILED__` — генерация завершилась ошибкой.
