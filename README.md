# CorpGPT XWiki RAG Service

FastAPI‑сервис, который подключает внешнюю базу знаний XWiki к CorpGPT через семантический поиск (RAG) на основе Mistral Embeddings и FAISS.

***

## Возможности

- Импорт документации из XWiki (plain export).
- Разбиение страниц на чанки и индексация во векторном хранилище (FAISS).
- Семантический поиск по базе знаний (учитывает формы слов и перефразировки).
- Полный RAG‑цикл: retrieval + генерация ответа через Mistral LLM.
- Интеграция с CorpGPT через специальный endpoint `/retrieval`.
- Защищённый endpoint для переиндексации (`/rag/index` с API‑ключом).

***

## Архитектура

- **FastAPI** — HTTP‑сервис.
- **Mistral Embeddings** — векторизация текста XWiki и запросов.
- **FAISS** — векторная база для nearest‑neighbor поиска.
- **XWiki** — источник знаний, экспорт через `XWIKI_EXPORT_URL`.
- **Render** — хостинг сервиса и авто‑индексация при старте.

***

## Основные модули

- `main.py`  
  - `GET /` — статус сервиса.  
  - `GET /health` — health‑check.  
  - `POST /rag/index` — индексация XWiki (требует заголовок `x-api-key: ADMIN_API_KEY`).  
  - `POST /rag/query` — семантический retrieval: промпт + источники + расстояния.  
  - `POST /rag/answer` — полный RAG: retrieval + ответ через `mistral-small-latest`.  
  - `POST /retrieval` — адаптер под CorpGPT (возвращает `records` в ожидаемом формате).

- `rag_service.py`  
  - Инициализация Mistral клиента и FAISS‑хранилища.  
  - `retrieve(query, k)`:
    - строит эмбеддинг запроса,
    - ищет релевантные чанки в FAISS,
    - формирует `context`, промпт и список `sources` с текстом чанков.

- `indexer.py`  
  - Загрузка контента XWiki через `fetch_xwiki_export()`.  
  - Фильтрация пустых/коротких страниц.  
  - Разбиение в текстовые чанки.  
  - Пакетное создание эмбеддингов и запись в FAISS.  
  - Сохранение индекса на диск.

***

## Переменные окружения

Обязательные:

- `MISTRAL_API_KEY` — ключ для Mistral API.
- `XWIKI_EXPORT_URL` — URL экспорта XWiki (plain JSON).  
- `ADMIN_API_KEY` — секрет для доступа к `/rag/index`.

Опциональные:

- `XWIKI_BASE_URL`, `XWIKI_USERNAME`, `XWIKI_PASSWORD` — доступ к XWiki REST.  
- `CONFLUENCE_BASE_URL`, `CONFLUENCE_USERNAME`, `CONFLUENCE_API_TOKEN` — задел под Confluence.

***

## Работа с индексом

### Ручная индексация

```bash
curl -X POST https://<your-service>/rag/index \
  -H "x-api-key: <ADMIN_API_KEY>"
```

### Авто‑индексация

При старте сервиса:

- Если векторный индекс пустой, автоматически вызывается `index_xwiki_content` и все страницы XWiki переиндексируются.

***

## Интеграция с CorpGPT

В CorpGPT (Mistral Studio):

- Внешняя база знаний `xWiki` настроена на вызов endpoint`а:

  ```text
  POST https://<your-service>/retrieval
  ```

- Сервис ожидает `RetrievalRequest` и возвращает `records` с полями:
  - `title` — заголовок страницы,
  - `content` — текст чанка,
  - `metadata.path` — URL XWiki,
  - `score` — релевантность (на основе расстояния в векторном пространстве).

Благодаря семантическому поиску:

- Запросы вроде `систему блокирует` корректно находят статьи, где текст в базе «система блокирует».

***

## Локальный запуск

```bash
pip install -r requirements.txt

export MISTRAL_API_KEY=...
export XWIKI_EXPORT_URL=...
export ADMIN_API_KEY=...

uvicorn main:app --reload
```

Индексация:

```bash
curl -X POST http://localhost:8000/rag/index \
  -H "x-api-key: $ADMIN_API_KEY"
```

Проверка RAG:

```bash
curl -X POST "http://localhost:8000/rag/query?question=equipment%20status&k=2"
curl -X POST "http://localhost:8000/rag/answer?question=систему%20блокирует&k=3"
```
