# CorpGPT XWiki RAG Service

FastAPI‑сервис, который подключает внешнюю базу знаний XWiki к CorpGPT через семантический поиск (RAG) на основе Mistral Embeddings и FAISS.

***

## Возможности

- Импорт документации из XWiki (plain export).
- Разбиение страниц на чанки и индексация во векторном хранилище (FAISS).
- Семантический поиск по базе знаний (учитывает формы слов и перефразировки).
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


---

## Архитектура

Сервис реализует классический RAG (Retrieval-Augmented Generation) пайплайн поверх XWiki. CorpGPT вызывает этот сервис через webhook `/retrieval` для получения релевантных фрагментов знаний по запросу пользователя.

### Поток запроса (CorpGPT → RAG сервис)

1. Пользователь задаёт вопрос в CorpGPT, используя knowledge base `xwiki`.
2. CorpGPT отправляет HTTP POST запрос на endpoint `/retrieval` с `knowledge_id`, текстом запроса и параметрами поиска (`top_k`, `score_threshold`).
3. `main.py` (FastAPI приложение) валидирует запрос и делегирует поиск RAG-слою в `rag_service.py`.
4. `rag_service.retrieve()` создаёт эмбеддинг запроса через Mistral embeddings и выполняет поиск по векторному хранилищу в `vector_store.py`.
5. Найденные чанки (с метаданными и расстояниями) преобразуются в формат `records[]` CorpGPT и возвращаются из `/retrieval`.
6. CorpGPT использует эти records как контекст для генерации финального ответа пользователю.

### Поток данных (XWiki → векторное хранилище)

1. Страницы XWiki экспортируются через export endpoint (plain JSON) и/или REST API.
2. `xwiki_client.py` инкапсулирует все взаимодействия с XWiki (export URL, REST endpoints, нормализация URL, аутентификация) и возвращает очищенные данные страниц.
3. `indexer.py` организует пайплайн индексации: загружает страницы из XWiki, фильтрует пустой/короткий контент и разбивает каждую страницу на чанки фиксированного размера (например, 2048 символов).
4. Для каждого чанка `rag_service.py` создаёт текстовые эмбеддинги через Mistral embeddings API и связывает их с расширенными метаданными (title, URL, space, page name, chunk index, updated timestamp и т.д.).
5. `vector_store.py` сохраняет результирующие векторы в FAISS индекс вместе с метаданными и обеспечивает эффективный поиск по сходству и персистентность (сохранение/загрузка индекса на диск).

### Схема жизненного цикла запроса

```text
[Пользователь в CorpGPT]
  |
  v
[CorpGPT /retrieval webhook]
  |
  v
main.py
(FastAPI, endpoint /retrieval)
  |
  v
rag_service.py
(эмбеддинг запроса + поиск)
  |
  v
vector_store.py (FAISS)
(поиск по индексированным
 чанкам из XWiki)
  |
  v
rag_service.py
(сбор контекста и метаданных)
  |
  v
main.py
(форматирование records[]
 под протокол CorpGPT)
  |
  v
CorpGPT
(генерирует ответ для
 пользователя)
```

### Схема жизненного цикла данных (индексация)

```text
XWiki
(страницы, экспорт)
  |
  v
xwiki_client.py
(REST + export JSON API)
  |
  v
indexer.py
(парсинг экспорта, чанкование,
 вызов эмбеддингов, сбор метаданных)
  |
  v
rag_service.py
(батч-эмбеддинги через
 Mistral Embeddings)
  |
  v
vector_store.py (FAISS)
(сохранение векторов +
 метаданных)
  |
  v
сохранение индекса на диск
```

### Ответственность модулей

- **`main.py`** — HTTP API и интеграционный слой (FastAPI приложение, health checks, `/rag/index`, `/rag/query`, `/rag/answer`, `/retrieval`), плюс опциональная авто-индексация при старте.
- **`rag_service.py`** — основная RAG логика: вспомогательные функции для чанкования, вызовы эмбеддингов Mistral, поиск по сходству через векторное хранилище и конструирование промптов для генерации ответов.
- **`indexer.py`** — пакетная индексация знаний из XWiki: запускает полный пайплайн от экспорта XWiki до заполненного FAISS индекса.
- **`vector_store.py`** — абстракция над FAISS: добавление/поиск эмбеддингов и управление персистентностью индекса и связанных метаданных на диске.
- **`xwiki_client.py`** — адаптер для XWiki: доступ к REST/export, построение URL и нормализация идентификаторов страниц XWiki в стабильные URL и поля.
