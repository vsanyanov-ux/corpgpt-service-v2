# CorpGPT External Knowledge Service

## 📝 Описание

FastAPI-сервис для интеграции Confluence с CorpGPT через External Knowledge API. Позволяет CorpGPT получать доступ к документам из Confluence для использования в качестве контекста при ответах.

## 🚀 Возможности

- Поиск документов в Confluence по текстовому запросу
- Извлечение полного содержимого страниц (не только excerpts)
- Очистка HTML-разметки и форматирование текста
- Соответствие формату CorpGPT External Knowledge API
- Автоматический деплой на Render при push в GitHub

## 🔧 Технологии

- **FastAPI** - веб-фреймворк
- **httpx** - асинхронный HTTP-клиент для запросов к Confluence
- **Pydantic** - валидация данных
- **Uvicorn** - ASGI сервер
- **Render** - хостинг и автоматический деплой

## 📦 Установка и запуск

### Переменные окружения

```bash
CONFLUENCE_BASE_URL=https://your-domain.atlassian.net/wiki
CONFLUENCE_USERNAME=your-email@example.com
CONFLUENCE_API_TOKEN=your-api-token
```

### Локальный запуск

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

## 🔌 API Endpoints

### GET `/`
Проверка статуса сервиса

**Response:**
```json
{
  "status": "online",
  "service": "Confluence Search API",
  "confluence_configured": true
}
```

### GET `/health`
Health check endpoint

**Response:**
```json
{
  "status": "healthy"
}
```

### POST `/retrieval`
Поиск документов в Confluence (CorpGPT External Knowledge API)

**Request:**
```json
{
  "knowledge_id": "your-knowledge-id",
  "query": "текст запроса",
  "retrieval_setting": {
    "top_k": 10,
    "score_threshold": 0.5
  }
}
```

**Response:**
```json
{
  "records": [
    {
      "metadata": {
        "path": "/spaces/SPACE/pages/123456",
        "description": "Название страницы"
      },
      "score": 1.0,
      "title": "Название страницы",
      "content": "Полный текст документа..."
    }
  ]
}
```

## 🎯 Интеграция с CorpGPT

1. Создайте External KB в CorpGPT
2. Укажите URL вашего сервиса: `https://your-service.onrender.com/retrieval`
3. Настройте параметры извлечения (top_k, score_threshold)
4. Протестируйте подключение через Hit Testing

## 📊 Мониторинг

- **Logs**: доступны в Render Dashboard
- **API Docs**: `/docs` - Swagger UI
- **Health Check**: `/health`

## 🐛 Решение проблем

### 422 Unprocessable Content
- Проверьте формат запроса - должен быть JSON body, не query parameters
- Убедитесь, что все обязательные поля присутствуют

### IndentationError
- Используйте 4 пробела для отступов, не табы
- Проверьте консистентность отступов во всём файле

### NameError: 'records' is not defined
- Убедитесь, что переменная инициализирована перед использованием

## 📝 Changelog

### v1.0.0 (2026-01-30)
- ✅ Интеграция с Confluence API
- ✅ Поддержка CorpGPT External Knowledge API формата
- ✅ Извлечение полного контента страниц
- ✅ Очистка HTML и форматирование текста
- ✅ Автоматический деплой на Render

## 📄 Лицензия

MIT

## 👤 Автор

Vladimir Anianov (@vsanyanov-ux)
