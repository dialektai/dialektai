# Agent Manifest Specification

**Version:** 1.0.1
**Status:** Draft (reviewed)
**Last updated:** 22 April 2026

---

## Overview

Agent Manifest — это портативный YAML-файл, полностью описывающий AI-агента
в экосистеме dialekt. Manifest содержит конфигурацию агента (модель, system
prompt, инструменты, права, способ ввода/вывода, расписание), но **никогда**
не содержит данных пользователя или секретов.

Manifest — это "исходный код" агента. Его можно:
- Сохранить в git-репозитории
- Опубликовать в cloud для других членов команды
- Передать коллеге для импорта в его dialekt
- Прочитать через год и понять, что делает агент

**Ключевое различие:** manifest описывает **template** (конфигурация), а не
**instance** (запущенный агент с данными). Разговоры, файлы, результаты —
остаются локально на машине каждого пользователя.

---

## Format

YAML (YAML Ain't Markup Language). Причины:
- Человекочитаемый, поддерживает комментарии
- Стандарт для конфигурационных файлов в индустрии (Kubernetes, Docker Compose,
  GitHub Actions)
- Разработчики чувствуют себя как дома
- Легко diff-ится в git

Расширение файла: `.agent.yaml` или `.agent.yml`.

---

## Minimum viable manifest

Это полный пример минимально-валидного manifest'а:

```yaml
spec_version: "1.0.1"
minimum_dialekt_version: "1.0.0"

metadata:
  id: "550e8400-e29b-41d4-a716-446655440000"
  name: "SQL Analyst"
  description: "Natural language to SQL for sales analytics"
  version: "1.0.0"
  author:
    name: "Yerzhan Kasymov"
    email: "yerzhan@example.kz"
  created_at: "2026-04-22T10:00:00+06:00"
  updated_at: "2026-04-22T10:00:00+06:00"

model:
  preferred: "qwen2.5-coder:32b"
  acceptable:
    - "qwen2.5-coder:14b"
    - "deepseek-coder:6.7b"
  min_context_window: 32000
  requirements:
    min_ram_gb: 24
    min_vram_gb: 0          # 0 = CPU-only acceptable
    recommended_ram_gb: 32
  parameters:
    temperature: 0.2
    top_p: 0.9
    max_tokens: 4096

system_prompt: |
  Ты опытный SQL-аналитик. Отвечай на языке пользователя
  (русский, английский, казахский).

  Правила:
  1. Всегда показывай SQL-запрос перед выполнением
  2. Объясняй логику запроса простыми словами
  3. Только SELECT-запросы, никаких DROP/DELETE/UPDATE
  4. Если вопрос неоднозначный — задай уточняющий вопрос

capabilities:
  groups:
    - database_read
  exceptions: []

connections:
  required:
    - type: postgres
      role: "readonly"
      database_category: "analytics"
      purpose: "Reading sales and analytics data"
      required_permissions: ["SELECT"]

autonomy:
  recommended: "ask-before-write"
  max_allowed: "ask-before-write"

input:
  type: "chat"

output:
  format: "table"
  streaming: true
  destination:
    type: "notification"

trigger:
  type: "interactive"
```

---

## Field reference

### Top-level fields

| Field | Type | Required | Description |
|---|---|---|---|
| `spec_version` | string | Yes | Версия формата manifest (semver). Текущая: `"1.0.0"` |
| `minimum_dialekt_version` | string | Yes | Минимальная версия dialekt, необходимая для запуска агента |
| `metadata` | object | Yes | Идентификация и авторство агента |
| `model` | object | Yes | Требования к LLM-модели |
| `system_prompt` | string | Yes | Системный промпт агента |
| `capabilities` | object | Yes | Какие группы возможностей разрешены |
| `connections` | object | No | Внешние подключения (БД, MCP-серверы) |
| `autonomy` | object | Yes | Уровень автономии агента |
| `input` | object | Yes | Как пользователь взаимодействует с агентом |
| `output` | object | Yes | Формат и канал вывода результата |
| `trigger` | object | Yes | Как агент запускается |
| `secrets_required` | array | No | Имена секретов, которые агент запросит у пользователя |
| `variables` | object | No | Переменные для подстановки в system prompt |
| `environments` | object | No | Готовые наборы значений переменных |

---

### `metadata`

Идентификация агента. UUID — глобальный идентификатор, имя — для людей.

```yaml
metadata:
  id: "550e8400-e29b-41d4-a716-446655440000"  # UUID v4, required
  name: "SQL Analyst"                          # 1-80 символов, required
  description: "Natural language to SQL"       # до 500 символов, required
  version: "1.0.0"                             # semver агента, required
  author:
    name: "Yerzhan Kasymov"                    # required
    email: "yerzhan@example.kz"                # required
  created_at: "2026-04-22T10:00:00+06:00"      # ISO 8601, required
  updated_at: "2026-04-22T10:00:00+06:00"      # ISO 8601, required

  # Optional:
  tags: ["sql", "analytics", "russian"]        # для категоризации
  icon: "📊"                                    # emoji или путь к файлу
  language: "multi"                             # "ru", "en", "kk", "multi"
  ui:                                           # UI customization
    primary_action_label: "Проанализировать"   # кастомная надпись на кнопке запуска
```

**`ui.primary_action_label`:** опциональное поле. По умолчанию кнопка запуска
агента подписана "Запустить" (Run). Этим полем автор может задать контекстную
надпись — "Проанализировать", "Сгенерировать отчет", "Создать карусель" — что
делает UX заметно лучше. Максимум 30 символов.

**Зарезервировано в v1.1:** другие UI-поля (accent_color, theme, layout) —
отложены до появления реального запроса от пользователей, чтобы избежать
UI-chaos на раннем этапе.

**Поведение при обновлении агента:** когда автор выпускает новую версию
(увеличивает `metadata.version`), пользователи, которым назначен этот агент,
получают **уведомление** "Доступна новая версия X.Y.Z агента Имя, обновить?".
Они могут принять или остаться на текущей версии.

---

### `model`

```yaml
model:
  preferred: "qwen2.5-coder:32b"               # required
  acceptable:                                   # optional, fallback chain
    - "qwen2.5-coder:14b"
    - "deepseek-coder:6.7b"
  min_context_window: 32000                    # required, в токенах
  requirements:                                 # required
    min_ram_gb: 24                             # минимум RAM для preferred
    min_vram_gb: 0                             # 0 если CPU-only, иначе требуемый VRAM
    recommended_ram_gb: 32                     # рекомендуемый RAM для комфортной работы
  parameters:                                   # required
    temperature: 0.2                           # 0.0-2.0
    top_p: 0.9                                  # 0.0-1.0
    max_tokens: 4096                           # int
```

**Поведение при несовпадении модели:**
1. Если `preferred` модель установлена **и** железо удовлетворяет `requirements` —
   использовать её
2. Если нет — пройти по `acceptable` по порядку, использовать первую
   доступную с warning'ом: "Агент оптимизирован для X, запущен на Y, качество
   может отличаться"
3. Если ни одна не доступна — показать пользователю выбор из установленных
   с сильным предупреждением

**Context window:** если ни одна из установленных моделей не удовлетворяет
`min_context_window`, агент не запускается.

**Hardware requirements:** dialekt при импорте проверяет установленный RAM и
VRAM пользователя. Если железо не удовлетворяет `min_ram_gb` для preferred —
автоматически предлагает `acceptable` альтернативы с меньшими требованиями.
Если ни одна не подходит — ясное сообщение: "Этому агенту требуется минимум
24 GB RAM. На этой машине доступно 16 GB. Агент не может быть запущен."

---

### `system_prompt`

Inline-текст системного промпта. Поддерживает подстановку переменных
через синтаксис `{{variable_name}}` (двойные фигурные скобки).

```yaml
system_prompt: |
  Ты SQL-аналитик для отдела {{department}} компании {{company_name}}.
  Используй таблицы с префиксом {{table_prefix}}_*.
  Отвечай на языке пользователя (русский, английский, казахский).

variables:
  department:
    type: string
    required: true
    description: "Название отдела"
  company_name:
    type: string
    required: true
    description: "Название компании"
  table_prefix:
    type: string
    required: true
    description: "Префикс таблиц в БД"

environments:
  sales:
    department: "отдел продаж"
    company_name: "Halyk Bank"
    table_prefix: "sales"
  marketing:
    department: "маркетинг"
    company_name: "Halyk Bank"
    table_prefix: "mkt"
```

**Почему двойные скобки:** одинарные `{}` часто встречаются в технических
промптах (JSON-примеры, SQL с JSONB-полями, Python f-strings, примеры кода).
Двойные `{{}}` позволяют безконфликтно подставлять переменные даже в
промптах с кодом. Это тот же подход, что в Handlebars, Mustache, Jinja2.

**Escape:** если нужно вывести буквально `{{text}}` в результате — используйте
`\{{text\}}` (обратная косая отключает подстановку).

**Multi-language:** prompt должен быть написан так, чтобы модель сама
определяла язык пользователя и отвечала соответственно. Правило в prompt'е
"отвечай на языке пользователя" или "respond in user's language" работает
на современных моделях.

**Хранение:** prompt всегда inline в YAML. Для длинных промптов используется
YAML block scalar (`|`), который сохраняет переносы строк.

---

### `capabilities`

Декларация групп разрешений + точечные исключения.

```yaml
capabilities:
  groups:
    - filesystem_read
    - filesystem_write
    - database_read
  exceptions:
    - deny: "filesystem_read:~/.ssh/**"
    - deny: "filesystem_read:**/.env"
    - deny: "database_write:*"
```

**Группы capabilities (v1.0):**
- `filesystem_read` — чтение файлов в пределах разрешённых путей
- `filesystem_write` — запись файлов в пределах разрешённых путей
- `database_read` — SELECT-запросы к подключённым БД
- `database_write` — INSERT/UPDATE/DELETE (требует явного разрешения)
- `shell_execute` — выполнение shell-команд
- `network` — исходящие HTTP-запросы
- `browser` — автоматизация браузера (v1.1)
- `screen_capture` — скриншоты (v1.1)

**Exceptions:** точечные правила в формате `{action}:{pattern}`, всегда
рассматриваются как более приоритетные, чем groups.

---

### `connections`

Именованные подключения к внешним ресурсам (БД, MCP-серверы). Manifest
**не содержит credentials**, только описание того, какое подключение нужно.

```yaml
connections:
  required:
    - type: postgres
      role: "readonly"
      database_category: "analytics"
      purpose: "Reading sales and analytics data"
      required_permissions: ["SELECT"]
    - type: mcp-server
      server: "@modelcontextprotocol/server-github"
      role: "readonly"
      purpose: "Reading issues and PRs"
```

**Pattern:** при первом запуске агента, dialekt сопоставляет `required`
connections с подключениями, которые пользователь настроил в своих
глобальных настройках. Если подходящего нет — пользователь выбирает или
создаёт новое. Credentials сохраняются локально в OS keychain.

**Поля:**
- `type` — тип подключения (`postgres`, `mysql`, `clickhouse`, `mcp-server`, `http-api`)
- `role` — роль доступа: `readonly`, `readwrite`, `admin`
- `database_category` — категория данных (для БД): `analytics`, `transactional`,
  `warehouse`, `reporting`, `operational`
- `purpose` — человекочитаемое описание, что агент делает с этим подключением
- `required_permissions` — минимальные SQL-привилегии (для БД): `["SELECT"]`,
  `["SELECT", "INSERT"]`, и т.д.

**Matching logic:** при импорте агента dialekt ищет у пользователя подключения,
удовлетворяющие всем критериям (`type`, `role`, `database_category`). Показывает
пользователю список кандидатов:

```
Агент требует: postgres readonly, категория analytics
Доступные у вас подключения:
  ✓ prod-analytics-ro (postgres, readonly, analytics) — рекомендуется
  ✓ staging-analytics (postgres, readonly, analytics)
  ✗ prod-transactional (не подходит: категория "transactional")

Выбрать: [prod-analytics-ro] [staging-analytics] [Создать новое]
```

**Строгая типизация** (вместо `name_hint`) обеспечивает надёжное сопоставление
и защищает от ошибок — агент для аналитики не подключится случайно к
production OLTP-базе.

---

### `autonomy`

Уровень автономии агента.

```yaml
autonomy:
  recommended: "ask-before-write"
  max_allowed: "ask-before-write"
```

**Уровни:**
- `review-only` — агент только объясняет, ничего не выполняет
- `ask-before-write` — спрашивает подтверждение перед записью/выполнением
- `autonomous` — действует в пределах capabilities без подтверждения
- `sandbox-only` — никаких подтверждений (только для изолированных sandbox-окружений)

**Поведение:** автор manifest'а задаёт `recommended` (что он считает
правильным) и `max_allowed` (максимум, на который пользователь может
повысить). Пользователь может **понизить** автономию всегда, **повысить** —
только до `max_allowed`.

**`sandbox-only` safety:** этот уровень автоматически требует, чтобы агент
работал в изолированном окружении (Docker-контейнер, VM, Tauri sandbox).
Dialekt проверяет sandbox-environment при попытке повысить до этого уровня.
Имя `sandbox-only` выбрано специально, чтобы явно коммуницировать ограничение
использования — в отличие от более неформальных названий, которые могут
ввести в заблуждение.

---

### `input`

Как пользователь взаимодействует с агентом.

**Вариант chat:**

```yaml
input:
  type: "chat"
  placeholder: "Спросите что-нибудь про продажи..."
```

**Вариант form:**

```yaml
input:
  type: "form"
  fields:
    - name: "topic"
      label: "Тема поста"
      type: "text"
      required: true
      max_length: 200

    - name: "description"
      label: "Описание"
      type: "textarea"
      required: false
      max_length: 2000

    - name: "slides_count"
      label: "Количество слайдов"
      type: "number"
      required: true
      min: 1
      max: 10
      default: 5

    - name: "tone"
      label: "Tone of voice"
      type: "dropdown"
      required: true
      options: ["formal", "casual", "technical", "friendly"]
      default: "friendly"

    - name: "add_emoji"
      label: "Добавить emoji?"
      type: "checkbox"
      default: true

    - name: "tags"
      label: "Теги"
      type: "multi-select"
      options: ["product", "marketing", "sales", "tech"]

    - name: "publish_date"
      label: "Дата публикации"
      type: "date"

    - name: "reference_doc"
      label: "Референсный документ"
      type: "file"
      accept: [".pdf", ".docx", ".txt"]
      max_size_mb: 10

    - name: "source_url"
      label: "Ссылка на источник"
      type: "url"
```

**Вариант no-input (для scheduled агентов):**

```yaml
input:
  type: "no-input"
```

**Поддерживаемые типы полей формы:**
- `text` — однострочный текст
- `textarea` — многострочный текст
- `number` — число (с min/max/default)
- `dropdown` — один выбор из списка
- `checkbox` — boolean
- `multi-select` — несколько выборов из списка
- `date` — дата
- `file` — загрузка файла (с accept и max_size_mb)
- `url` — URL с валидацией

---

### `output`

Формат и канал доставки результата.

```yaml
output:
  format: "table"
  streaming: true                  # показывать промежуточный вывод (default: true)
  destination:
    type: "notification"
```

**Форматы (`format`):**
- `markdown` — markdown-текст с таблицами, кодом, списками
- `table` — структурированная таблица (для SQL-результатов)
- `image` — изображение (для креативных агентов)
- `file` — файл (Excel, PDF, CSV, PNG)
- `json` — структурированные данные

**Streaming (`streaming`):** true/false, default: true.
- `true` — UI показывает промежуточный вывод по мере генерации модели
  (аналогично ChatGPT). Критично для долгих задач (отчёты 3+ минут).
- `false` — показывается только финальный результат. Используется когда
  промежуточное состояние бессмысленно (например, для `format: image` —
  показывать наполовину нарисованную картинку нет смысла).

**Каналы доставки (`destination.type`):**
- `notification` — OS notification + сохранение в истории (v1.0)
- `filesystem` — файл по указанному пути (v1.0)
- `webhook` — HTTP POST на URL (v1.1)
- `email_or_telegram` — email или Telegram-сообщение (v1.1)

**В v1.0 поддержаны только `notification` и `filesystem`.** Manifest с
другими destination — валиден по структуре, но агент не запустится до
реализации соответствующего канала. UI покажет warning.

**Filesystem destination:**

```yaml
output:
  format: "file"
  destination:
    type: "filesystem"
    path: "{user_home}/reports/daily-sales-{date}.xlsx"
    overwrite: false  # если true — перезаписывает, если false — добавляет suffix
```

**Path variables:**
**Path variables:** используют **одинарные** фигурные скобки, чтобы отличать
системные path-переменные от пользовательских переменных в system_prompt.
- `{user_home}` — домашняя директория пользователя
- `{workspace}` — рабочая директория агента
- `{date}` — текущая дата (YYYY-MM-DD)
- `{datetime}` — текущее datetime (YYYY-MM-DD-HHMM)
- `{agent_id}` — UUID агента

**Важно:** path variables — это **закрытый список системных плейсхолдеров**,
которые dialekt подставляет автоматически. Они не пересекаются с переменными
из секции `variables` (которые используют `{{double}}` в system_prompt).

---

### `trigger`

Как агент запускается.

**Interactive (запускается пользователем):**

```yaml
trigger:
  type: "interactive"
```

**Scheduled (по расписанию):**

```yaml
trigger:
  type: "scheduled"
  schedule: "0 9 * * *"          # cron expression
  timezone: "Asia/Almaty"         # IANA timezone
  missed_run_policy: "run_on_startup"
```

**Cron syntax:** стандартный POSIX cron. В builder mode dialekt показывает
визуальный редактор расписания ("каждый день", "каждый будний день",
"каждое 1 число месяца"), который генерирует cron за пользователя.

**Missed-run recovery:** если в запланированное время ПК был выключен, при
следующем запуске dialekt агент запускается **немедленно** (не ждёт следующего
scheduled time). Поле `missed_run_policy`:
- `run_on_startup` — запустить при старте dialekt, если пропущено (default)
- `skip` — пропустить, ждать следующего запланированного запуска

**Лимит для missed runs:** если пропущено более 7 дней — агент **не запускается**
автоматически, показывается уведомление "Агент X не запускался 10 дней, запустить?".

---

### `secrets_required`

Список имён секретов, которые агент запросит у пользователя при первом
запуске. Сохраняются в OS keychain, в manifest никогда не попадают.

```yaml
secrets_required:
  - name: "comfyui_api_key"
    description: "API key for local ComfyUI instance"
    required: true
  - name: "openai_fallback_key"
    description: "OpenAI API key (optional, only for fallback mode)"
    required: false
```

---

## Security rules

### Hard ban (валидатор manifest отклоняет)

Следующие типы данных **никогда** не должны появляться в manifest-файле.
Валидатор при импорте или публикации будет сканировать и отклонять manifest
с этими паттернами:

1. **Пароли** — строки вида `password: ...`, `passwd: ...`, `pwd: ...`
   с значением
2. **API keys** — паттерны OpenAI (`sk-...`), Anthropic (`sk-ant-...`),
   GitHub tokens (`ghp_...`), Telegram bot tokens (`\d+:[A-Za-z0-9_-]+`)
3. **Приватные ключи** — блоки `-----BEGIN * PRIVATE KEY-----`
4. **Токены авторизации** — JWT (три base64-блока через точку), OAuth tokens,
   session IDs
5. **Database connection strings с credentials** — `postgresql://user:pass@host`,
   `mysql://user:pass@host`

Если валидатор обнаруживает любой из этих паттернов — manifest **отклоняется**
с ошибкой и указанием на конкретную строку.

### Warning (валидатор предупреждает, не блокирует)

Следующие данные могут быть частью manifest'а легитимно, но требуют
осознанного выбора автора:

1. Internal URLs компании (`https://internal.company.kz`)
2. PII в примерах промпта (конкретные имена/email/телефоны)
3. Имена внутренних систем/серверов
4. Email-адреса (кроме email автора в metadata)
5. Полные ФИО сотрудников

При обнаружении — warning: "Возможно чувствительная информация в строке N,
убедись, что она не должна быть секретной".

### Import verification

При импорте manifest'а (из файла или из cloud):

1. ✓ Валидация структуры — все required-поля на месте, типы корректны
2. ✓ Проверка `spec_version` совместимости с версией dialekt
3. ✓ Проверка `minimum_dialekt_version`
4. ✓ Сканирование на запрещённые секреты (hard ban)
5. ✓ Предупреждения по soft warnings
6. ✓ Проверка наличия модели (preferred или acceptable)
7. ✓ Проверка доступности MCP-серверов
8. ✓ Показ пользователю **summary** manifest'а перед первым запуском:

   ```
   Импорт агента: "SQL Analyst" by Yerzhan Kasymov

   Модель: qwen2.5-coder:32b (установлена ✓)
   Разрешения: чтение БД
   Подключения: требуется postgres с правами SELECT
   Автономия: ask-before-write
   Запуск: по запросу пользователя

   Продолжить? [Да] [Нет]
   ```

9. ⏳ Цифровая подпись автора — v1.1

---

## Versioning policy

### Spec version (семантика)

Формат manifest-спецификации следует semver:
- **Major** (1.x → 2.0) — breaking changes. Старые manifest'ы могут не
  работать без миграции
- **Minor** (1.0 → 1.1) — новые поля, неломающие. Старые manifest'ы
  продолжают работать
- **Patch** (1.0.0 → 1.0.1) — уточнения в документации или валидации,
  без изменения формата

### Compatibility

- **Backwards compatible:** dialekt версии X читает manifest'ы всех версий
  от 1.0.0 до X
- **Minimum version:** manifest может объявить `minimum_dialekt_version`.
  Если установленная версия ниже — ясная ошибка "Обновите dialekt до версии Y"
- **Forward compatibility:** manifest версии выше, чем поддерживает dialekt,
  **не загружается** (в отличие от silent-ignore-unknown-fields подхода)

### Deprecation

Поля, помеченные как deprecated в minor-версии (например, в 1.5), **продолжают
работать** как минимум до следующей major-версии. Минимальный lifetime
deprecated поля — одна minor-версия (если deprecated в 1.5, может быть удалено
не раньше 2.0).

При загрузке manifest'а с deprecated полями — warning: "Поле X deprecated
с версии 1.5, будет удалено в 2.0. Используйте Y вместо него."

### Migration

- **Automatic migration at load time:** dialekt при загрузке старого
  manifest'а конвертирует его в память к актуальному формату. Пользователь
  ничего не замечает.
- **Explicit migration tool:** команда `dialekt migrate <manifest.yaml>`
  конвертирует файл на диске к актуальной версии (полезно для публикации
  обновлённых manifest'ов в git).

Migration tool пишется только при выпуске major-версии. Для patch/minor —
не нужен.

---

## Example manifests

### Example 1: SQL Analyst for Sales

```yaml
spec_version: "1.0.1"
minimum_dialekt_version: "1.0.0"

metadata:
  id: "7f3a8b2c-1234-4567-8901-abcdef012345"
  name: "SQL Analyst: Sales"
  description: "Natural language to SQL for sales analytics"
  version: "1.0.0"
  author:
    name: "Yerzhan Kasymov"
    email: "yerzhan@halyk.kz"
  created_at: "2026-04-22T10:00:00+06:00"
  updated_at: "2026-04-22T10:00:00+06:00"
  tags: ["sql", "analytics", "sales"]
  icon: "📊"
  language: "multi"
  ui:
    primary_action_label: "Проанализировать"

model:
  preferred: "qwen2.5-coder:32b"
  acceptable:
    - "qwen2.5-coder:14b"
  min_context_window: 32000
  requirements:
    min_ram_gb: 24
    min_vram_gb: 0
    recommended_ram_gb: 32
  parameters:
    temperature: 0.2
    top_p: 0.9
    max_tokens: 4096

system_prompt: |
  Ты опытный SQL-аналитик для отдела продаж {{company_name}}.
  Отвечай на языке пользователя (русский, английский, казахский).

  Работаешь с таблицами: {{table_list}}

  Правила:
  1. Всегда показывай SQL-запрос перед выполнением
  2. Объясняй логику запроса простыми словами
  3. Только SELECT-запросы
  4. Если вопрос неоднозначный — задай уточняющий вопрос
  5. Результаты форматируй как таблицу

variables:
  company_name:
    type: string
    required: true
    description: "Название компании"
  table_list:
    type: string
    required: true
    description: "Список таблиц через запятую"

environments:
  halyk_sales:
    company_name: "Halyk Bank"
    table_list: "sales_transactions, sales_customers, sales_products"

capabilities:
  groups:
    - database_read
  exceptions:
    - deny: "database_write:*"

connections:
  required:
    - type: postgres
      role: "readonly"
      database_category: "analytics"
      purpose: "Reading sales data"
      required_permissions: ["SELECT"]

autonomy:
  recommended: "ask-before-write"
  max_allowed: "ask-before-write"

input:
  type: "chat"
  placeholder: "Например: сколько продаж было в прошлом месяце?"

output:
  format: "table"
  streaming: true
  destination:
    type: "notification"

trigger:
  type: "interactive"
```

---

### Example 2: Instagram Carousel Generator

```yaml
spec_version: "1.0.1"
minimum_dialekt_version: "1.0.0"

metadata:
  id: "b0971d56-092b-4ce4-8c39-9b30a2688439"
  name: "Instagram Carousel Generator"
  description: "Creates multi-slide Instagram carousels as PNG images"
  version: "1.0.0"
  author:
    name: "Yerzhan Kasymov"
    email: "yerzhan@halyk.kz"
  created_at: "2026-04-22T11:00:00+06:00"
  updated_at: "2026-04-22T11:00:00+06:00"
  tags: ["marketing", "social-media", "creative"]
  icon: "🎨"
  ui:
    primary_action_label: "Создать карусель"

model:
  preferred: "llama3.1:70b"
  acceptable:
    - "mistral-nemo:12b"
  min_context_window: 8192
  requirements:
    min_ram_gb: 48
    min_vram_gb: 0
    recommended_ram_gb: 64
  parameters:
    temperature: 0.8
    top_p: 0.95
    max_tokens: 4096

system_prompt: |
  Ты креативный маркетолог-копирайтер для {{brand_name}}.
  Tone of voice: {{brand_tone}}

  Задача: создать многостраничную карусель для Instagram.

  Для каждого слайда:
  1. Заголовок (до 50 символов)
  2. Основной текст (до 150 символов)
  3. Стиль оформления (цвета, шрифт)

  Финальный output — HTML/CSS для каждого слайда, который можно
  отрендерить в PNG 1080x1080.

variables:
  brand_name:
    type: string
    required: true
  brand_tone:
    type: string
    required: true

capabilities:
  groups:
    - filesystem_write
  exceptions: []

autonomy:
  recommended: "ask-before-write"
  max_allowed: "autonomous"

input:
  type: "form"
  fields:
    - name: "topic"
      label: "Тема карусели"
      type: "text"
      required: true
      max_length: 200

    - name: "description"
      label: "Детальное описание"
      type: "textarea"
      required: false
      max_length: 2000

    - name: "slides_count"
      label: "Количество слайдов"
      type: "number"
      required: true
      min: 3
      max: 10
      default: 5

    - name: "tone_override"
      label: "Переопределить tone"
      type: "dropdown"
      required: false
      options: ["formal", "casual", "inspiring", "educational", "default"]
      default: "default"

    - name: "add_cta"
      label: "Добавить call-to-action"
      type: "checkbox"
      default: true

    - name: "reference_image"
      label: "Референсное изображение"
      type: "file"
      accept: [".jpg", ".jpeg", ".png"]
      max_size_mb: 5

output:
  format: "file"
  streaming: false
  destination:
    type: "filesystem"
    path: "{user_home}/Desktop/carousels/{date}-{topic}.png"
    overwrite: false

trigger:
  type: "interactive"
```

---

### Example 3: Daily Sales Report

```yaml
spec_version: "1.0.1"
minimum_dialekt_version: "1.0.0"

metadata:
  id: "add9891b-6e9a-427a-b2ff-a64c61ef389f"
  name: "Daily Sales Report"
  description: "Generates Excel sales report every morning at 9 AM"
  version: "1.0.0"
  author:
    name: "Yerzhan Kasymov"
    email: "yerzhan@halyk.kz"
  created_at: "2026-04-22T09:00:00+06:00"
  updated_at: "2026-04-22T09:00:00+06:00"
  tags: ["reports", "finance", "scheduled"]
  icon: "📈"

model:
  preferred: "mistral-nemo:12b"
  acceptable:
    - "qwen2.5-coder:14b"
  min_context_window: 16000
  requirements:
    min_ram_gb: 16
    min_vram_gb: 0
    recommended_ram_gb: 24
  parameters:
    temperature: 0.1
    top_p: 0.9
    max_tokens: 8192

system_prompt: |
  Ты финансовый аналитик. Твоя задача — сгенерировать ежедневный
  отчёт по продажам в формате Excel.

  Структура отчёта:
  1. Sheet 1: Сводка (total revenue, transactions count, avg check)
  2. Sheet 2: По категориям продуктов
  3. Sheet 3: По регионам
  4. Sheet 4: Топ-10 клиентов

  Сравнение с предыдущим днём, неделей, месяцем.

capabilities:
  groups:
    - database_read
    - filesystem_write
  exceptions:
    - deny: "database_write:*"

connections:
  required:
    - type: postgres
      role: "readonly"
      database_category: "analytics"
      purpose: "Reading sales data for reports"
      required_permissions: ["SELECT"]

autonomy:
  recommended: "autonomous"
  max_allowed: "autonomous"

input:
  type: "no-input"

output:
  format: "file"
  streaming: false
  destination:
    type: "filesystem"
    path: "{user_home}/Reports/sales/{date}-daily-sales.xlsx"
    overwrite: false

trigger:
  type: "scheduled"
  schedule: "0 9 * * *"
  timezone: "Asia/Almaty"
  missed_run_policy: "run_on_startup"
```

---

### Example 4: Code Review Assistant

```yaml
spec_version: "1.0.1"
minimum_dialekt_version: "1.0.0"

metadata:
  id: "b400a3f4-d2f7-4433-8950-3aee9b93682f"
  name: "Code Review Assistant"
  description: "Senior-level code review on git diff"
  version: "1.0.0"
  author:
    name: "Yerzhan Kasymov"
    email: "yerzhan@halyk.kz"
  created_at: "2026-04-22T14:00:00+06:00"
  updated_at: "2026-04-22T14:00:00+06:00"
  tags: ["code-review", "developer-tools"]
  icon: "🔍"
  ui:
    primary_action_label: "Провести review"

model:
  preferred: "deepseek-r1:32b"
  acceptable:
    - "qwen2.5-coder:32b"
  min_context_window: 64000
  requirements:
    min_ram_gb: 24
    min_vram_gb: 0
    recommended_ram_gb: 32
  parameters:
    temperature: 0.3
    top_p: 0.9
    max_tokens: 8192

system_prompt: |
  Ты senior-инженер, проводишь code review.
  Стиль: жёсткий, но конструктивный. Не смягчай критику.

  Для каждой проблемы:
  1. Файл и номер строки
  2. Уровень (BLOCKER / MAJOR / MINOR / NITPICK)
  3. Что не так и почему
  4. Конкретное предложение как исправить

  Приоритеты:
  - Security issues — BLOCKER
  - Performance issues в hot paths — MAJOR
  - Maintainability — MINOR
  - Style — NITPICK

capabilities:
  groups:
    - filesystem_read
    - shell_execute
  exceptions:
    - deny: "filesystem_read:~/.ssh/**"
    - deny: "filesystem_read:**/.env"
    - allow: "shell_execute:git *"

autonomy:
  recommended: "ask-before-write"
  max_allowed: "autonomous"

input:
  type: "chat"
  placeholder: "Укажи ветку или paste diff"

output:
  format: "markdown"
  streaming: true
  destination:
    type: "notification"

trigger:
  type: "interactive"
```

---

## Validation rules

### Syntactic validation (формальная)

- Manifest parseable as valid YAML
- All required fields present (см. field reference)
- Field types match spec (string, number, boolean, array, object)
- Enum values match allowed sets (например, `trigger.type` = "interactive" | "scheduled")
- String lengths within limits (name ≤ 80, description ≤ 500)
- Numbers within ranges (temperature 0.0-2.0, etc.)

### Semantic validation (осмысленная)

- `spec_version` — валидный semver, поддерживается текущим dialekt
- `minimum_dialekt_version` — валидный semver, ≤ установленной версии
- UUID корректно сформированы
- Timestamps в ISO 8601 с timezone
- Cron expression (если `trigger.type` = "scheduled") — валидный
- Timezone — валидный IANA timezone identifier
- Variables, упомянутые в system_prompt (`{{variable}}`) — все определены в `variables`
- Environments consistency — каждое environment содержит все required variables

### Security validation

См. раздел "Security rules → Hard ban / Warning".

### Compatibility validation

- Модель из `preferred` или `acceptable` — установлена (если нет —
  предложение скачать или warning)
- MCP-серверы из `connections` — доступны (если нет — instructions
  как установить)
- Capabilities groups — поддерживаются текущей версией dialekt

---

## Migration path

### Для пользователей

Когда выйдет spec 2.0 (предполагаемо через 12-18 месяцев):

1. **Automatic migration** при открытии старого manifest'а — dialekt
   конвертирует в память, агент запускается. Пользователь видит notification:
   "Manifest обновлён до версии 2.0".
2. **Explicit migration** для публикации обновлённого файла —
   `dialekt migrate <path>` перезаписывает файл в новом формате.

### Для authors

Когда готовишь агента к публикации:
1. Убедись, что `spec_version` и `minimum_dialekt_version` корректны
2. Прогони `dialekt validate <manifest.yaml>` — должны быть zero errors
3. Прогони `dialekt test <manifest.yaml>` — запуск в sandbox для проверки
4. Публикуй через dialekt UI

---

## Changelog

### Version 1.0.1 (2026-04-22)
- Incorporated external technical review feedback
- **Added:** `model.requirements` block with `min_ram_gb`, `min_vram_gb`,
  `recommended_ram_gb` — dialekt checks hardware before loading
- **Added:** `output.streaming` field (boolean, default true) — UI shows
  intermediate results during long tasks
- **Added:** `metadata.ui.primary_action_label` (optional) — custom CTA
  button label for better UX
- **Changed:** variable syntax `{variable}` → `{{variable}}` — prevents
  conflicts with code/JSON/SQL in prompts
- **Changed:** autonomy level `yolo` → `sandbox-only` — clearer, more
  professional naming that explicitly signals restriction
- **Changed:** `connections` schema — strict typing via `role` +
  `database_category` instead of fragile `name_hint`
- All four example manifests updated to reflect changes

### Version 1.0.0 (2026-04-22)
- Initial release
- Supports interactive and scheduled agents
- Output destinations: notification, filesystem (webhook, email_or_telegram
  reserved for 1.1)
- Digital signature — reserved for 1.1

---

## Open questions for future versions

Следующие области ждут реального use case, прежде чем будут добавлены в спецификацию:

- Multi-agent orchestration (агенты, вызывающие других агентов)
- Memory-enabled agents (persistent memory across sessions)
- Public marketplace с цифровыми подписями
- File-watcher triggers (запуск при изменении файла)
- Webhook triggers (запуск по HTTP-запросу)
- Custom output formats beyond markdown/table/image/file/json
- Internationalisation of form labels (сейчас labels — строки, без i18n)

---

**Конец спецификации.**
