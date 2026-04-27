# dialekt Platform Roadmap

**Текущая версия:** v0.26.12 (последний шипнутый билд, коммит `19274f6`)
**Текущая ветка разработки:** `feat/agent-library` (4 коммита от main, ещё не смёржена)
**Дата:** 2026-04-27
**Источник приоритетов:** пилот IBA + текущий состояние платформы по `IBA_PILOT_READINESS.md`, `WHAT_DIALEKT_DOES_TODAY.md`, `TOOLS_AVAILABLE_TODAY.md`, `CAPABILITIES_INVENTORY.md`, `CAPABILITIES_STATUS.md` (последний устарел — апрельский снимок до v0.20)

---

## Принцип приоритизации

- **P0** — блокирует текущих пилотов (если есть подписанный пилот, у которого хотя бы одна задача упёрлась в это)
- **P1** — нужно для следующих 3-5 пилотов (pattern-match на 2+ потенциальных клиентов в pipeline)
- **P2** — важно для масштабирования (>10 пилотов, ARR-driver)
- **P3** — nice to have

Сейчас мы между «1 первый пилот» (IBA, ещё не запущен) и «следующих 3-5». Так что P1 — это и про IBA, и про scaling.

---

## Заметка про текущее состояние

То что уже **сделано** в v0.20-v0.26 и не требует переработки:
- MCP Servers UI + ConsentModal + audit log + OS keychain для секретов (v0.20)
- MCP Server Templates + Bulk Import/Export (v0.21)
- Per-tool `allow_tools/deny_tools` runtime + UI (v0.22)
- "Approve all pending" + GitHub MCP миграция на Go binary (v0.24)
- MCP Audit Dashboard в Settings → Admin (v0.25)
- MCP Process Resilience (мониторинг крашей stdio-серверов) (v0.26)
- Wizard capability checkboxes — починены на schema-correct имена (`AgentWizardScreen.jsx:749-754`)

То что **в работе сейчас** на `feat/agent-library`:
- Cloud `library_entries` table + public catalog endpoints + 7 seed templates
- Desktop SQLite schema + рефакторинг `/agents/import-yaml`
- Frontend библиотеки **ещё не написан** — backend первым

То что **уже частично есть** в коде, но я думал «нет» до проверки:
- `describe_image_vision()` в `python/server.py:3045` — vision-pipeline целиком есть, нужна только модель в Ollama (`llava:13b` или эквивалент). Используется через маркер `@screenshot:<path>` в чате. См. раздел 5.
- ComfyUI txt2img / txt2vid (Flux Schnell + LTX-Video 22B) — `/comfy/txt2img` и `/comfy/txt2vid` живые в `server.py:3000+`. Только если на машине есть GPU.

---

## 1. Визуальный контент (P1)

**Статус:** новая капабилити, кода нет (`grep -lr replicate\|pillow python/` → пусто помимо bundled artefacts).
**Зачем:** задача 8 из IBA + ожидаемая универсальная боль для маркетинговых пилотов.

### 1.1 Шаблонный движок визуалов (Pillow only) — РЕКОМЕНДУЕМЫЙ ПЕРВЫЙ ШАГ

**Что делает.** Pillow рендерит финальный визуал из готового PNG-шаблона + наложение текста + лого + бренд-шрифты. Без AI-генерации фона. Подходит для большинства IBA-сценариев (анонс программы, расписание-карусель, регистрационный баннер).

**Архитектура.**
```
python/dialekt/tools/visual/
  __init__.py
  pillow_composer.py        # PIL/Pillow рендер: text-fit, кеглинг, отступы, лого
  template_registry.py      # реестр PNG-шаблонов + brand profile
  brand_profile.py          # цвета, шрифты, лого, защищённые зоны
  fonts/                    # шрифты пилота (PF Beau Sans, etc.)
~/.dialekt/visual/
  templates/<pilot_id>/     # PNG шаблоны под этого пилота
  brands/<pilot_id>.json    # brand profile (color tokens, font stack)
  out/                      # сгенерированные визуалы
```

**Endpoint:**
```
POST /visual/render
body: {
  "template_id": "iba_program_announcement_post",
  "fields": {"title": "...", "subtitle": "...", "date": "...", "trainer": "..."},
  "brand_id": "iba"
}
returns: {"ok": true, "files": ["/abs/path/visual.png"], "size_bytes": N, "ms": N}
```

**Schema changes.** Новой capability group НЕ нужно. Агент вызывает `/visual/render` через Python httpx (как делает SQL Analyst для `/connections/{id}/query`). Опционально добавить `network` capability как маркер в манифест (advisory).

**UI:** в чате — кнопка "📎 Visual" рядом с file-upload, открывает форму с template+fields. Превью PNG в чате-колонке, ссылка для скачивания. Файлы в `~/.dialekt/visual/out/` доступны через существующий `GET /files`.

**Что нужно от пилота:** brand book (лого SVG/PNG, hex-цвета, шрифт), 3-5 готовых шаблонов в Figma → экспорт в PNG-1080×1080 / 1080×1920 + JSON с координатами текст-зон.

**Зависимости:** нет (Pillow в Python venv уже есть как транзитивная зависимость).

**Оценка:** 2-3 дня — `pillow_composer.py` + `template_registry.py` + endpoint + 1 тест-fixture (IBA-пресет) + минимальное UI (кнопка + модалка).

### 1.2 Replicate API (динамический фон)

**Что делает.** Тот же pipeline что 1.1, но фон не из готового шаблона а сгенерён через Replicate (Flux Schnell `~$0.003/img`, или SDXL `~$0.005/img`).

**Архитектура (поверх 1.1):**
```
python/dialekt/tools/visual/
  replicate_client.py       # httpx-клиент: predict + poll, retries, cost-tracking
```

**Schema changes.** Новый секрет `replicate_api_token` — переиспользуем существующий keyring-flow (`dialekt.secrets`, `dialekt.mcp.secrets_resolver.keyring_key()`, который уже шипает в v0.20+).

**Endpoint расширяется:**
```
POST /visual/render
body: {
  ...,
  "background": {"type": "replicate", "model": "flux-schnell",
                  "prompt": "minimal abstract gradient, navy blue tones"},
  ...
}
```

**Стоимость:** трекается в `audit_log` через новый `kind=visual_generated` (повторяя паттерн `mcp_tool_call`). Админ видит в Settings → Admin → Usage расход за период.

**Зависимости:** 1.1 (template engine) — Replicate выдаёт сырой фон, всё равно нужно наложить текст и лого.

**Оценка:** 2 дня (после 1.1).

### 1.3 Brand asset uploader

UI в Settings → Branding (новый раздел): загрузка лого, hex-цветов, шрифтов; превью на тестовом шаблоне. Пишет в `~/.dialekt/visual/brands/<pilot>.json` + кладёт ассеты в `~/.dialekt/visual/templates/<pilot>/`.

**Файлы:** `frontend/src/screens/SettingsScreen.jsx` (BrandingSection — новая) + `POST /branding/upload` в server.py.

**Оценка:** 1 день.

**Итого по разделу 1:** 5-6 дней (рекомендую начать с 1.1 + 1.3 для IBA — этого достаточно; 1.2 добавим во второй пилот, у которого критичны уникальные фоны).

---

## 2. Instagram интеграция (P2 → возможно P1 после IBA discovery)

### 2.1 Публикация через Instagram Graph API

**Что делает.** Готовый текст + визуал → публикация в Instagram Business аккаунт через Graph API без copy-paste.

**Архитектура.**
```
python/dialekt/tools/social/
  __init__.py
  instagram_publisher.py    # Graph API client (httpx)
  oauth_flow.py             # OAuth handshake для access tokens
```

**Endpoints:**
```
POST /social/instagram/publish
body: {
  "kind": "feed_post" | "story" | "carousel",
  "media": ["/abs/path/visual.png", ...],
  "caption": "...",
  "scheduled_at": null   # сейчас только immediate
}
returns: {"ok": true, "ig_media_id": "...", "permalink": "..."}

GET  /social/instagram/oauth/start    → redirect URL (FB OAuth)
GET  /social/instagram/oauth/callback → принимает code, обменивает на long-lived token, кладёт в keyring
```

**Schema changes (опционально):** в манифесте capability `social_publish` (нужно расширить `CAPABILITY_GROUPS` в `dialekt_manifest/schema.py:11`). Для пилота можно обойтись advisory `network` capability + проверкой через OAuth-токен.

**Ограничения Instagram API (документировать в DEPLOY_RUNBOOK):**
- Только Business / Creator аккаунты (не Personal).
- Rate limit: 200 публикаций/сутки на аккаунт.
- Stories через Graph API доступны через `MediaContainer` с `media_type=STORIES` (отдельный flow).
- Reels требуют отдельный endpoint и доп. поля.

**Зависимости:** v0.20 secrets через keychain (есть). Brand asset uploader (1.3) — для лого которое накладывает агент.

**Оценка:** 5-7 дней — OAuth flow тонкий и требует тщательного теста; ConsentModal на каждую публикацию (как destructive MCP tool). Дополнительные 1-2 дня — тесты с реальным IG-Business аккаунтом.

**Решение для пилота IBA:** до запуска пилота — НЕ делаем (IBA сами публикуют, текст + визуал даём). После 2-3 недель пилота, если IBA попросит — закладываем 5-7 дней под отдельный SOW.

### 2.2 Планировщик публикаций

«Опубликовать пост в среду в 10:00 по Алматы». Зависит от scheduled triggers runtime (см. раздел 3.2). До тех пор — оператор IBA сам кладёт пост в IG-планировщик, а dialekt только готовит контент.

**Оценка:** после 3.2.

---

## 3. Web Search + мониторинг (P1)

### 3.1 Native Web Search через Tavily/Brave

**Что делает.** Агент может искать актуальную информацию в интернете через адаптер. Для IBA: ad-hoc мониторинг законодательства РК, поиск актуальных тем.

**Статус:** **НЕТ кода** (`grep -lr "tavily\|brave_search" python/` → пусто). В `WHAT_DIALEKT_DOES_TODAY.md` помечен как M2 backlog.

**Архитектура.**
```
python/dialekt/tools/search/
  __init__.py
  tavily_client.py
  brave_client.py
  router.py                 # выбирает адаптер по конфигу
```

**Endpoint:**
```
POST /search/web
body: {"query": "новые требования к учебным центрам РК 2026",
       "max_results": 10, "include_raw_content": false}
returns: {"results": [{"url": "...", "title": "...", "snippet": "...",
                       "score": 0.92}, ...]}
```

**Schema changes:** новый capability group `web_search` в `dialekt_manifest/schema.py:11` (расширяем существующий FrozenSet). Через миграцию spec_version 1.1.0 → 1.2.0 либо как additive в 1.1.0 (additive должно быть совместимо — uncritical).

**UI:** Settings → Connections → новый блок "Web Search" с выбором провайдера + полем для API-ключа (паттерн Brand Asset uploader, повторяем).

**Зависимости:** v0.20 secrets через keychain (есть).

**Оценка:** 3-4 дня — плюс E2E тест с реальным API-ключом (как делалось для GitHub MCP в `MCP_PRODUCTION_VALIDATION.md`).

### 3.2 Scheduled trigger runtime (cron)

**Что делает.** Агент срабатывает по расписанию (cron-выражение в манифесте). Уже **схема готова и принимает `trigger.type: scheduled`** (`python/venv/.../schema.py` Trigger union), просто **нет рантайма** — `CAPABILITIES_INVENTORY §4` фиксирует это с апреля.

**Архитектура.**
```
python/dialekt/scheduler/
  __init__.py
  apscheduler_runner.py     # APScheduler в отдельном процессе или внутри server.py
  cron_session.py           # WS-эмулятор для одного scheduled-запуска
  missed_run_policy.py      # реализация run_on_startup / skip
```

**Изменения в `server.py`:** при boot — поднимаем APScheduler, читаем `agents` где `trigger.type=scheduled`, регистрируем jobs. Каждый job открывает фейковую WS-сессию (без реального WS), запускает `make_interpreter` + `chat_turn` с предзаписанным сообщением, кладёт результат в новый раздел Audit (`kind=scheduled_run`).

**Schema changes:** нет — поля уже валидны. Возможно только убрать TODO-маркеры и добавить runtime warning если cron-выражение невалидное на boot.

**Endpoint расширяется:**
```
GET /agents/{id}/runs           — список запусков scheduled-агента
POST /agents/{id}/run-now       — ручной триггер scheduled-агента (полезно для теста)
```

**UI:** в Settings → Agents → раздел "Runs" для scheduled-агентов: история, статус последнего запуска, "Run now" кнопка. Шапка манифеста в Builder Wizard уже принимает scheduled.

**Зависимости:**
- APScheduler в pyproject.toml (добавить).
- Output destination `notification` плохо подходит для scheduled — нужно как минимум `audit_log` запись + Telegram bot или email (см. раздел 7).

**Оценка:** 5-7 дней (APScheduler + интеграция с существующим OI-loop + missed-run-policy + UI + E2E тест с минутным cron).

**Решение:** v0.27 кандидат. После v0.26 это самый назревший gap (упомянут в backlog с апреля).

---

## 4. Работа с сайтом клиента (P1)

### 4.1 CMS connection type

**Что делает.** Стандартный способ дать агенту доступ к CMS клиента (read + write страниц).

**Текущее состояние.** `dialekt_manifest.schema.CONNECTION_TYPES` уже включает `"http-api"` — но рантайма нет (`CAPABILITIES_INVENTORY §3`). Использовать его и добавить CMS-варианты как пресеты.

**Архитектура.**
```
python/mcp_servers/
  cms_mcp.py                # новый router /cms-connections
python/dialekt/cms/
  base.py                   # абстрактный CMSAdapter
  wordpress.py              # WP REST API + Application Password
  tilda.py                  # Tilda public API
  bitrix.py                 # Bitrix24 REST
  custom.py                 # generic httpx с настраиваемыми endpoints
```

**Endpoints (повторяем паттерн `postgres_mcp`):**
```
POST   /cms-connections           — создать (cms_type, url, token)
GET    /cms-connections           — список
DELETE /cms-connections/{id}
POST   /cms-connections/{id}/test — проверить доступ + права
GET    /cms-connections/{id}/pages?status=published&since=...
GET    /cms-connections/{id}/pages/{page_id}
POST   /cms-connections/{id}/pages/{page_id}  — обновить (destructive → ConsentModal)
GET    /cms-connections/{id}/sitemap          — обход sitemap.xml
```

**Schema changes:** ничего — `connections.type: http-api` уже валидно. Добавить опциональное поле `cms_type` в `ConnectionSpec` (additive в spec 1.1.0).

**UI:** Settings → Connections → "Add CMS" — выбор типа + URL + auth (token / app-password). Кнопка [Test] возвращает количество страниц.

**Зависимости:** v0.20 secrets через keychain.

**Оценка:**
- WordPress (REST API богатый, OAuth не обязателен, App Password достаточно) — 2 дня
- Tilda (ограниченный API: список + контент страниц, без записи) — 1.5 дня
- Bitrix24 (богатый REST, но порядок входов через portal token) — 3 дня
- Custom (httpx + JSON-конфиг endpoints) — 1.5 дня
- Общая инфраструктура router + CMSAdapter base — 2 дня

**Итого:** 10 дней на 4 CMS. Для пилота IBA — сначала только тот CMS на котором сидит IBA (узнаем на discovery), остальное добавляем по мере новых пилотов.

### 4.2 Автоматический обход sitemap + анализ

**Что делает.** Агент берёт `sitemap.xml`, обходит каждую страницу, складывает в LLM на анализ актуальности и качества продающего текста.

**Архитектура.** Поверх 4.1 — новый endpoint:
```
POST /cms-connections/{id}/audit
body: {"checks": ["outdated_dates", "missing_cta", "broken_links"],
       "agent_id": "<content_editor>"}
returns: SSE stream с per-page результатами
```

Агент-оркестратор берёт `content_editor` из IBA каталога и применяет к каждой странице.

**Зависимости:** 4.1 (CMS connection), `content_editor` манифест (есть).

**Оценка:** 2-3 дня поверх 4.1.

---

## 5. Работа с файлами и медиа (P1)

### 5.1 Vision модель — почти готова

**Текущее состояние (важно — не "новая фича"):**
- `describe_image_vision()` уже в `server.py:3045`. Принимает path → base64 → POST `/api/generate` Ollama → текстовое описание.
- Триггерится в `preprocess_content()` через маркер `@screenshot:<path>` (`server.py:3082`).
- Поддерживаемые модели по name-pattern: `llava, bakllava, moondream, minicpm, qwen2-vl, llama3.2, gemma3` (vision-варианты).
- `python/dialekt/llm/catalog.py:125` уже знает про `llava 13b` как опцию.
- Если ни одна vision-модель не установлена — fallback `[image at {path} — no vision model available]`.

**Что нужно сделать:**
1. Добавить `llava:13b` (или `qwen2-vl:7b`) в **рекомендуемый** список в OllamaInstallScreen / DownloadScreen (после Goal 1 Ollama lifecycle UI). Пока пилот его не пуллит — vision не работает.
2. Опционально: если `gemma3` уже скачан и поддерживает vision-вариант — приоритезировать его (catalog mapping logic).
3. Расширить chat UI — кнопка "📎 Photo" чтобы маркер `@screenshot:` ставился автоматически (сейчас пользователь должен сам напечатать).

**Зависимости:** Ollama (есть).

**Оценка:** 1 день (UI кнопка + изменение default моделей в installer + документация). НЕ 2 дня как казалось — половина работы уже сделана.

### 5.2 Batch обработка файлов

**Что делает.** Загрузить 10 резюме → агент обрабатывает по очереди → ZIP с 10 готовыми текстами.

**Архитектура.**
```
python/dialekt/batch/
  __init__.py
  job.py                    # Job model (агент, входы, выходы, статус)
  runner.py                 # пер-файловый запуск + progress + ZIP-сборка
```

**Endpoints:**
```
POST /batch                 — body: {agent_id, files: [...], variables: {...}}
                              returns: {job_id}
GET  /batch/{job_id}        — статус + per-file outcome
GET  /batch/{job_id}/zip    — скачать архив выходов
```

**UI:** в чате — drop 10 файлов → диалог "Batch process all 10? [Yes/No]" → SSE-прогресс → кнопка "Скачать ZIP".

**Зависимости:** `/upload` (есть). История чата (есть).

**Оценка:** 2-3 дня.

---

## 6. Улучшения Builder Wizard (P2)

### 6.1 AI auto-fill wizard

**Что делает.** Пользователь вводит "Хочу агента для SMM учебного центра" → Wizard заполняет каждый шаг (model, system_prompt, capabilities) AI-ассистентом, опираясь на library templates как examples.

**Архитектура.** Endpoint `POST /agents/draft` — принимает natural-language description → возвращает заполненный manifest YAML, который Wizard загружает в свои шаги для финального ревью.

**Зависимости:** Agent Library (в работе на `feat/agent-library`) — нужны seed-templates как few-shot examples для промпта-генератора.

**Оценка:** 5-7 дней — основное время на промпт-инжиниринг и тесты на ~10 различных описаниях.

### 6.2 Тестирование агента в Wizard

**Что делает.** Шаг 9 Wizard — мини-чат с агентом до публикации. Сейчас пользователь публикует слепо, потом идёт в чат пробовать.

**Архитектура.** Reuse `make_interpreter` + WS chat в режиме draft (агент имеет `id="draft-<uuid>"` и не сохраняется в DB до publish).

**Оценка:** 2-3 дня.

---

## 7. Output destinations: Telegram, Email, Filesystem (P1)

**Это закрытие давнего долга** (`CAPABILITIES_INVENTORY §4`):
> «**Destination: filesystem / webhook / email_or_telegram** — schema-valid, no delivery runtime»

Без этого scheduled-агенты (раздел 3.2) бесполезны — некуда положить результат.

### 7.1 Telegram bot delivery

**Архитектура.**
```
python/dialekt/delivery/
  __init__.py
  telegram.py               # python-telegram-bot client
  email.py                  # smtplib через aiosmtplib
  filesystem.py             # write to user-confirmed dir
```

**Endpoint:**
```
POST /delivery/test
body: {"destination": {"type": "email_or_telegram", ...}}
                            — тестовая отправка для проверки токена
```

**Schema changes:** нет — `output.destination.type` уже принимает `notification, filesystem, webhook, email_or_telegram`.

**Конфиг (новые секреты в keyring):**
- `telegram_bot_token`
- `email_smtp_host`, `email_smtp_user`, `email_smtp_password`

**UI:** Settings → Delivery — настройка bot token, SMTP, default folder.

**Зависимости:** v0.20 secrets через keychain.

**Оценка:**
- Telegram — 2 дня
- Email — 2 дня
- Filesystem — 1 день

**Итого:** 5 дней на все три. Telegram прежде всего — для KZ-пилотов это самый ожидаемый канал.

---

## 8. Мультиязычность (P2)

### 8.1 Казахский язык — модельная проблема

**Сейчас:** `gemma3-12b` плохо переводит на казахский (`AGENT_CATALOG.md` 3.2 — пример «Зур бар» вместо «Қайырлы таң»). `language: kk` принимается схемой, но качество нерабочее.

**Что попробовать:**
1. **`qwen2.5:14b` или `qwen2.5:32b`** — тестировать на тех же фразах, у Qwen лучше покрытие казахского по верхним бенчмаркам.
2. **Fine-tune `qwen2.5-coder:7b` на KK-корпусе** — есть открытые корпуса (Wikipedia kk, Tilmash). Делает 1 человек за неделю, требует GPU 24GB+ для тренировки.
3. **Платный путь:** Gemini 2.5 / Claude 3.5 через cloud API + `dialekt-cloud` adapter (нарушает «всё локально», но как опциональный fallback для KK мог бы работать).

**Архитектура.** В `pick_model_for_agent` уже есть family-match fallback. Добавить language-aware override: если `language: kk` и preferred модель плохо знает KK — мягко даунгрейдить на больший Qwen.

**Зависимости:** GPU 16GB+ для qwen2.5:14b (для пилотов часто проблема — см. раздел 9 про cloud-tenant как fallback).

**Оценка:**
- Исследование (день тестов на 10 KK-фразах с qwen2.5:14b/32b и сравнение) — 1-2 дня
- Реализация по результатам (если просто model swap) — 1 день
- Если fine-tune — 7-10 дней

**Решение:** до того как у нас будет пилот, у которого критичен казахский — это P3. У IBA казахский nice-to-have, не блокер. Поднимаем приоритет когда KZNARU (corp-клиент IBA) или подобный явно попросит.

---

## 9. Аналитика и отчётность (P2)

### 9.1 Pilot dashboard

**Что делает.** Settings → Admin → Usage уже показывает по-агентно использование (`AdminDashboardScreen.jsx`, Goal 6 в DIALEKT_STATE.md). Нужно расширить:
- Time-saved metric (среднее время на ручную задачу × кол-во запросов агенту → часов сэкономлено)
- Top-3 успешных промптов и top-3 неудачных (low feedback rate)
- Per-agent retention (DAU/WAU)

**Архитектура.** Расширение существующего `AdminDashboardScreen.jsx` + новые SQL-агрегации в `audit_log`.

**Зависимости:** v0.25 Audit Dashboard (есть).

**Оценка:** 3-5 дней.

### 9.2 Экспорт истории

**Что делает.** Выгрузка всех сессий за период в Excel/PDF для отчётности перед руководством клиента.

**Endpoint:**
```
GET /admin/export?from=2026-04-01&to=2026-04-30&format=xlsx
returns: бинарный xlsx или pdf
```

**Зависимости:** `openpyxl` или `xlsxwriter` (добавить в pyproject).

**Оценка:** 2-3 дня.

---

## 10. Tech debt + догоняющие фиксы (P1, низкоэффортные)

Из `CAPABILITIES_STATUS §5` (часть фиксов уже применена в v0.20+, но не все).

| ID | Фикс | Статус сейчас | Эффорт |
|---|---|---|---|
| F1 | Wizard capability имена | ✅ ДОНЕ (v0.20+) | — |
| F2 | MySQL/ClickHouse "Add connection" UI | ❓ нужно проверить | 30-45 min |
| F3 | Runtime enforcement для `capabilities.groups` | ❌ всё ещё advisory metadata | 1.5 hour + product-call |
| F4 | E2E verify MySQL/ClickHouse | ❓ нужно проверить (catalog 1.2/1.3 говорит ✅) | 30 min |
| F5 | Scheduled trigger runtime | см. раздел 3.2 | 5-7 days |
| F6 | Webhook trigger | M3 — не сейчас | — |
| F7 | OI `computer.*` API verification | ❌ untested | 30 min/feature |
| M1 | Recursive validate-loop в `retry_loop.py` | ❓ нужно проверить | 15 min |

**Решение:** F2, F4, M1 — делаем за один день в любом из ближайших спринтов. F3 — отдельный продуктовый разговор (**делаем capability checkboxes реальной защитой или явно говорим что это документация?** — ответ перевешивает дизайн на 1-2 года вперёд).

---

## Сводная таблица приоритетов

| Раздел | Feature | Priority | Оценка | Нужно для | Зависимости |
|---|---|---|---|---|---|
| 1.1 | Visual: Pillow templates | P1 | 2-3 дня | IBA пилот | — |
| 1.3 | Brand asset uploader | P1 | 1 день | IBA пилот | 1.1 |
| 1.2 | Visual: Replicate API | P1 | 2 дня | IBA + следующие | 1.1 |
| 4.1 | CMS WordPress | P1 | 2 дня | IBA если WP | secrets v0.20 ✅ |
| 4.1 | CMS Tilda | P1 | 1.5 дня | IBA если Tilda | secrets v0.20 ✅ |
| 4.1 | CMS Bitrix24 | P2 | 3 дня | следующие пилоты | secrets v0.20 ✅ |
| 4.1 | CMS Custom | P1 | 1.5 дня | универсальный fallback | secrets v0.20 ✅ |
| 4.2 | Sitemap audit | P1 | 2-3 дня | IBA задача 5 | 4.1 |
| 5.1 | Vision модель (pull + UI) | P1 | 1 день | IBA фото | Ollama ✅ |
| 5.2 | Batch обработка файлов | P1 | 2-3 дня | IBA резюме | /upload ✅ |
| 3.1 | Web search (Tavily/Brave) | P1 | 3-4 дня | IBA законы ad-hoc | secrets v0.20 ✅ |
| 7.1 | Telegram delivery | P1 | 2 дня | scheduled output | secrets v0.20 ✅ |
| 7.1 | Email delivery | P2 | 2 дня | enterprise | secrets v0.20 ✅ |
| 7.1 | Filesystem delivery | P2 | 1 день | export-heavy | — |
| 3.2 | Scheduled trigger runtime | P1 | 5-7 дней | IBA законы автомат | 7.1 (хотя бы Telegram) |
| 2.1 | Instagram Graph API publisher | P2 | 5-7 дней | IBA SMM полный | 1.1, secrets ✅ |
| 6.2 | Test agent inside Wizard | P2 | 2-3 дня | DX | — |
| 6.1 | AI auto-fill Wizard | P2 | 5-7 дней | onboarding | feat/agent-library |
| 9.1 | Pilot analytics dashboard | P2 | 3-5 дней | retention | v0.25 audit ✅ |
| 9.2 | Экспорт истории Excel/PDF | P2 | 2-3 дня | отчётность | 9.1 |
| 8.1 | Казахский — исследование | P2 | 1-2 дня | KZ корп-рынок | — |
| 10.* | Tech debt F2/F4/M1 | P1 | 1 день | стабильность | — |

---

## Следующий спринт — рекомендация

**v0.27 — IBA Pilot Sprint (предлагаемое название):**

Этап 1 (закрываем IBA блокеры):
1. **Visual templates + Brand uploader** (1.1 + 1.3) — 3-4 дня
2. **CMS connection: WordPress** (4.1 WP) — 2 дня (либо тот CMS что у IBA по факту)
3. **Vision model — recommend in installer + UI button** (5.1) — 1 день
4. **Tech debt F2/F4/M1** — 1 день

Этап 2 (расширение под следующих 3-5 пилотов):
5. **Web search Tavily** (3.1) — 3-4 дня
6. **Telegram delivery** (7.1 — только Telegram) — 2 дня
7. **Batch обработка файлов** (5.2) — 2-3 дня

Этап 3 (готовим к scheduled-эре):
8. **Scheduled trigger runtime** (3.2) — 5-7 дней
9. **Sitemap audit endpoint** (4.2) — 2-3 дня

**Итого:** 22-30 дней Claude Code работы. Поделить на v0.27 (этапы 1-2, ~15 дней) и v0.28 (этап 3, ~10 дней).

**Что НЕ делаем в v0.27:** IG publisher (отдельный SOW по запросу IBA), Replicate (после первого пилота), AI auto-fill Wizard (после Agent Library), казахский (после следующего пилота с KZ-кейсом).

---

## Зависимости и порядок (визуально)

```
v0.20 secrets keychain ── базовый блок
       │
       ├── 1.1 Visual templates ──── 1.3 Brand uploader
       │            │
       │            └── 1.2 Replicate (опционально) ── 2.1 IG publisher
       │
       ├── 3.1 Web search ──┐
       │                    ├── 3.2 Scheduled triggers ── 4.2 Sitemap audit
       ├── 7.1 Telegram ────┘
       │
       ├── 4.1 CMS connection ── 4.2 Sitemap audit
       │
       ├── 5.1 Vision UI (готово на 70%)
       │
       └── 5.2 Batch обработки

feat/agent-library (в работе) ── 6.1 AI auto-fill ── 6.2 Test in Wizard
                                                   │
                                                   └── 9.1 Pilot dashboard ── 9.2 Excel/PDF export
```

---

## Как использовать этот документ

Каждый пилот открывает новые потребности. После каждого pilot call — обновлять этот документ:

1. **Новые P0**, если что-то блокирует пилота (например, IBA сидит на 1С — нужен 1С-коннектор → P0).
2. **Повышение приоритета**, если несколько пилотов просят одно и то же (например, 2 из 3 потенциальных пилотов хотят IG publisher → переводим в P1).
3. **Добавление новых features** из discovery calls.
4. **Снимать с roadmap** что уже в проде — переводить в раздел «уже сделано» вверху документа, чтобы не плодить долг.

Этот документ = **живой product backlog dialekt**. Не путать с design docs (`M2_*_DESIGN.md`) и impl plans (`M2_V0XX_IMPL_PLAN.md`) — те создаются под конкретную версию когда фича уже взята в работу.

---

## Открытые вопросы для Диаса

1. **F3 (capability runtime enforcement).** Хотим ли мы чтобы галочка «Filesystem» в Wizard реально блокировала FS-доступ? Или оставляем декларативной? Этот вопрос полтора года отложен; сейчас он влияет на дизайн Visual + CMS capabilities.
2. **Cloud-tenant как fallback.** Для пилотов без GPU (а у IBA скорее всего его нет): запускаем dialekt в `dialekt-cloud` облачно? Если да — нужно подумать про data-residency для KZ (закон о ПДн 18.01.2026).
3. **Replicate vs локальный ComfyUI.** Если пилот выбрал локальный ComfyUI (есть GPU), Replicate ему не нужен. Это один и тот же endpoint `/visual/render` с разными background-провайдерами или два разных flow? Я в roadmap-е сделал один endpoint — подтвердить.
4. **Instagram publisher через MCP-сервер vs нативный модуль.** На сервере есть `ig.dias.now` (Instagram MCP, port 18744) — но он ваш inhouse, не публичный. Использовать его как MCP integration для пилотов или писать `instagram_publisher.py` нативно? MCP-путь меньше кода, но привязывает пилотов к моему серверу.
