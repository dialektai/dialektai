# Frontend E2E Test Prompt

## Контекст

dialekt desktop app (Tauri + React) имеет 219 unit/integration тестов для Python backend, но frontend (React UI) покрыт минимально. Надо прогнать полный functional test всех UI flows end-to-end и выдать отчёт что работает, что сломано, что недоделано.

Этот промпт — для Claude Code с Chrome MCP (или Playwright) доступом. Claude Code должен реально кликать по UI, не просто читать код.

---

## Промпт

```
Задача: провести полный end-to-end functional test frontend dialekt
desktop app. Не читать код — реально кликать по UI и проверять что
каждый flow работает.

Важно: это НЕ задача на починку багов. Только инвентаризация. Сломано →
фиксируй в отчёте, не чини. Фиксить будем отдельными промптами.

## Подготовка

1. Убедись что сервисы работают:
   - dialekt-server (python backend) — локально на :8765
   - dialekt-cloud — https://dialekt-cloud.dias.now/health должен
     вернуть 200
   - Ollama — локально на :11434 (если не работает, запусти
     `ollama serve` в фоне)

2. Запусти desktop UI в dev режиме:
   cd desktop && npm run tauri dev
   ИЛИ если Tauri в headless недоступен, запусти vite:
   cd desktop && npm run dev
   И открой http://localhost:5173 через Chrome MCP.

3. Если есть Chrome MCP — используй его. Если нет — используй Playwright
   headed mode.

4. Перед началом: очисти state.
   rm -rf ~/.dialekt/
   rm -rf ~/.config/dialekt/
   Это гарантирует что ты начинаешь с чистого onboarding.

## Чек-лист (сокращенный — см. оригинал для деталей)

### 1. First launch & onboarding (1.1-1.11)
### 2. Main screen / Chat interface (2.1-2.10)
### 3. Database connections (3.1-3.8)
### 4. SQL Analyst (4.1-4.8)
### 5. Builder Wizard (5.1-5.11)
### 6. Schema RAG (6.1-6.5)
### 7. Settings (7.1-7.6)
### 8. License revocation flow (8.1-8.5)
### 9. Admin Dashboard (9.1-9.8)
### 10. Performance & stability (10.1-10.5)

## Формат отчёта

# Frontend E2E Test Report — YYYY-MM-DD

## Executive Summary
- Total items tested: XX / 95
- Works / Partial / Broken / Cannot test
- Critical blockers for investor demo
- Top 3 UX issues

## Detailed results (per section)

## Screenshots / evidence

## Recommendations (Critical / Important / Nice-to-have)
```
