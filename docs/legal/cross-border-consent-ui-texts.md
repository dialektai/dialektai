# Cross-Border Consent & UI Texts
## Формулировки для интерфейса dias.now

**Версия:** 1.0
**Дата:** 25 апреля 2026 г.
**Связанные документы:** Privacy Policy v1.0, Terms of Service v1.0, Public Offer v1.0

---

## Назначение документа

Настоящий документ содержит готовые тексты согласий и информационных уведомлений для встраивания в пользовательский интерфейс продукта dias.now. Каждый текст разработан с учётом требований:

- статей 7–8 Закона РК «О персональных данных и их защите» №94-V (с изменениями от 18.01.2026);
- статей 6, 7, 9, 13, 49 GDPR;
- директивы ePrivacy 2002/58/EC (для cookie consent в будущем).

**Каждый текст имеет техническую разметку** для разработчиков с указанием:
- где размещается (URL/экран/контекст);
- тип элемента UI (чекбокс, баннер, модальное окно);
- состояние по умолчанию (предзаполнено / не предзаполнено);
- условия логирования согласия в БД (timestamp + версия текста).

---

## A. SIGNUP FORM — регистрация на лендинге

**Локация:** https://dias.now (форма регистрации)
**Контекст:** до создания Учётной записи в dialekt-cloud.

### A.1 Основное согласие на обработку ПДн и принятие документов

**Тип:** обязательный чекбокс
**По умолчанию:** ☐ НЕ предзаполнен
**Блокирует:** кнопку «Sign up» / «Зарегистрироваться»

#### Русский текст:

> ☐ Я ознакомился(-ась) и принимаю условия [Политики конфиденциальности](https://dias.now/legal/privacy), [Условий использования](https://dias.now/legal/terms) и [Публичного договора-оферты](https://dias.now/legal/offer). Я даю согласие на обработку моих персональных данных (имя, email, страна, цели использования, IP-адрес) ТОО «Dialekt.ai» в целях создания и поддержания учётной записи, выдачи лицензии и операционной коммуникации.

#### English text:

> ☐ I have read and accept the [Privacy Policy](https://dias.now/legal/privacy), [Terms of Service](https://dias.now/legal/terms), and [Public Offer](https://dias.now/legal/offer). I consent to the processing of my personal data (name, email, country, intended use, IP address) by TOO "Dialekt.ai" for the purposes of creating and maintaining my account, issuing the licence, and operational communication.

#### Технические требования:

- При сабмите формы записать в БД таблицу `consent_log`:
  - `user_id`, `consent_type = 'privacy_terms_offer'`, `version = '1.0'`, `text_hash`, `granted_at`, `ip_address`, `user_agent`
- Хранить полный текст согласия в версионированной таблице `consent_versions` для возможности предъявить регулятору.

---

### A.2 Согласие на трансграничную передачу персональных данных

**Тип:** обязательный чекбокс **с раскрывающимся блоком**
**По умолчанию:** ☐ НЕ предзаполнен
**Блокирует:** кнопку «Sign up»
**Показывается:** **всегда**, всем пользователям независимо от страны (упрощает архитектуру; KZ-резидентам это критично, остальным — информативно)

#### Русский текст:

**Заголовок:** Согласие на трансграничную передачу персональных данных

**Раскрывающийся блок (по клику «Подробнее»):**

> В целях оказания Сервисов dias.now передаёт ваши регистрационные данные (имя, email, страна, цели использования, IP-адрес) следующим обработчикам, расположенным за пределами Республики Казахстан:
>
> | Получатель | Юрисдикция | Передаваемые данные | Цель |
> |---|---|---|---|
> | Zoho Corporation | Соединённые Штаты Америки | email, имя, содержимое транзакционных писем | Доставка лицензионного ключа, восстановление пароля, инвойсы |
> | Cloudflare, Inc. | Соединённые Штаты Америки (с глобальной edge-сетью) | IP-адрес, метаданные DNS-запросов | Защита от DDoS, маршрутизация трафика |
> | GitHub, Inc. | Соединённые Штаты Америки | IP-адрес, метаданные загрузок | Доставка установочных файлов Программного продукта |
>
> **Срок передачи и хранения:** в течение срока действия вашей учётной записи. После удаления учётной записи данные удаляются в порядке, описанном в [Политике конфиденциальности](https://dias.now/legal/privacy).
>
> **Уровень защиты:** Соединённые Штаты Америки в настоящее время не входят в перечень государств, обеспечивающих адекватный уровень защиты персональных данных в значении Закона РК «О персональных данных и их защите» №94-V. С каждым из вышеуказанных получателей заключено соглашение об обработке персональных данных (DPA), обязывающее их применять меры защиты не ниже уровня, установленного законодательством РК.
>
> **Право отзыва:** вы вправе отозвать настоящее согласие в любой момент путём направления заявления на адрес privacy@dias.now. Отзыв согласия влечёт невозможность дальнейшего предоставления Сервисов и закрытие вашей учётной записи. Отзыв согласия не затрагивает правомерности обработки, осуществлённой до момента отзыва.

**Чекбокс согласия (под раскрывающимся блоком):**

> ☐ Я даю отдельное явное согласие на трансграничную передачу моих персональных данных в США указанным обработчикам в целях, указанных выше, в порядке статей 7–8 Закона РК «О персональных данных и их защите» №94-V.

#### English text:

**Title:** Consent to International Transfer of Personal Data

**Expandable block (on "Learn more" click):**

> To provide the Services, dias.now transfers your registration data (name, email, country, intended use, IP address) to the following processors located outside Kazakhstan and outside the European Economic Area:
>
> | Recipient | Jurisdiction | Data transferred | Purpose |
> |---|---|---|---|
> | Zoho Corporation | United States | email, name, contents of transactional emails | Delivery of licence key, password reset, invoices |
> | Cloudflare, Inc. | United States (with global edge network) | IP address, DNS metadata | DDoS protection, traffic routing |
> | GitHub, Inc. | United States | IP address, download metadata | Distribution of Product binaries |
>
> **Duration of transfer and storage:** for the duration of your account. Following account deletion, data is deleted in the manner described in the [Privacy Policy](https://dias.now/legal/privacy).
>
> **For EEA/UK residents:** transfers to Kazakhstan (where the controller is established) and to the United States are made on the basis of Standard Contractual Clauses adopted by the European Commission pursuant to Implementing Decision (EU) 2021/914, and (where applicable) the EU-U.S. Data Privacy Framework.
>
> **Right of withdrawal:** you may withdraw this consent at any time by emailing privacy@dias.now. Withdrawal will result in the inability to provide the Services and the closure of your account. Withdrawal does not affect the lawfulness of processing carried out prior to the withdrawal.

**Consent checkbox (below the expandable block):**

> ☐ I provide my separate, explicit consent to the international transfer of my personal data to the United States to the processors identified above for the purposes stated, in accordance with Articles 7–8 of the Law of Kazakhstan on Personal Data No. 94-V (where applicable to me) and Article 49 GDPR (where applicable to me).

#### Технические требования:

- Записать в `consent_log`: `consent_type = 'cross_border_us'`, `version`, `recipient_list_hash`, `granted_at`.
- Связать запись с конкретными sub-processors через таблицу `consent_recipients`.
- При изменении состава sub-processors (например, замена Zoho на ZeptoMail) — **переспросить согласие** у действующих пользователей по email.

---

### A.3 Опциональное согласие на маркетинговые рассылки

**Тип:** опциональный чекбокс **отдельный от A.1 и A.2**
**По умолчанию:** ☐ НЕ предзаполнен
**НЕ блокирует:** регистрацию

#### Русский текст:

> ☐ Я согласен(-на) получать от ТОО «Dialekt.ai» информационные рассылки о новых функциях продукта, обновлениях и предложениях. Я понимаю, что могу отписаться в один клик из любого письма или направив запрос на privacy@dias.now.

#### English text:

> ☐ I consent to receive product updates, feature announcements, and offers from TOO "Dialekt.ai". I understand I can unsubscribe at any time via the link in each email or by emailing privacy@dias.now.

#### Технические требования:

- **Критично:** этот чекбокс **не должен** быть объединён с A.1 или A.2. Объединение нескольких согласий в один чекбокс — нарушение GDPR Art.7(2) и Recital 32, а также ст.8 Закона РК.
- Записать в `consent_log` отдельной записью с `consent_type = 'marketing'`.
- Каждое маркетинговое письмо обязано содержать unsubscribe link, ведущий на one-click-unsubscribe (без ввода email и без обязательного логина).

---

## B. FIRST-RUN WIZARD — после установки Продукта

**Локация:** Программный продукт dias.now, первый запуск
**Контекст:** до начала функционального использования Продукта.

### B.1 Информационное уведомление о локальной обработке данных

**Тип:** информационный экран (не требует согласия)
**Действие:** кнопка «Continue» / «Продолжить»

#### Русский текст:

> ### Ваши данные остаются на вашем устройстве
>
> dias.now разработан так, чтобы по умолчанию все ваши промпты, ответы моделей, история переписки и файлы, к которым вы предоставляете доступ, обрабатывались **локально на этом устройстве**.
>
> На наши серверы передаются только:
> - данные вашей учётной записи и лицензии;
> - технические журналы доступа (для безопасности);
> - содержимое ваших обращений в поддержку.
>
> Если вы активируете облачного LLM-провайдера (Anthropic, OpenAI, Google, AWS и других), ваши промпты будут передаваться напрямую с этого устройства в API такого провайдера, минуя наши серверы. Перед активацией каждого провайдера вы получите отдельный запрос на согласие.

#### English text:

> ### Your data stays on your device
>
> dias.now is designed so that, by default, all your prompts, model responses, chat history, and files you grant access to are processed **locally on this device**.
>
> Only the following data is sent to our servers:
> - your account and licence data;
> - technical access logs (for security);
> - content of your support requests.
>
> If you activate a cloud LLM provider (Anthropic, OpenAI, Google, AWS, and others), your prompts will be transmitted directly from this device to the provider's API, bypassing our servers. Before activating each provider, you will receive a separate consent prompt.

---

### B.2 Опциональный сбор телеметрии (если будете добавлять в будущем)

> **Примечание:** в текущей архитектуре dias.now телеметрия не собирается. Этот блок добавляется в UI **только** после реализации опциональной телеметрии и обновления Privacy Policy. До этого момента раздел B.2 не отображается пользователю.

**Тип:** опциональный чекбокс
**По умолчанию:** ☐ НЕ предзаполнен

#### Русский текст:

> ☐ Помочь улучшить dias.now: разрешить отправку анонимных данных об ошибках и использовании функций. Никакое содержимое промптов, ответов или файлов передаваться не будет. Подробнее см. [Политику конфиденциальности, раздел Телеметрия](https://dias.now/legal/privacy#telemetry).

#### English text:

> ☐ Help improve dias.now: allow sending anonymous error reports and feature usage data. No content of prompts, responses, or files will be transmitted. See [Privacy Policy, Telemetry section](https://dias.now/legal/privacy#telemetry) for details.

---

## C. CLOUD LLM PROVIDER ACTIVATION — активация облачного LLM-провайдера

**Локация:** Программный продукт dias.now, экран настроек / выбор модели
**Контекст:** перед первой активацией каждого облачного LLM-провайдера. Согласие запрашивается **отдельно для каждого провайдера** и **только один раз** (повторный запрос не требуется при последующих использованиях того же провайдера).

### C.1 Шаблон согласия — общая форма

**Тип:** модальное окно с обязательным чекбоксом
**По умолчанию:** ☐ НЕ предзаполнен
**Блокирует:** ввод API-ключа и активацию провайдера

#### Русский текст (шаблон):

> ### Активация облачного LLM-провайдера: {PROVIDER_NAME}
>
> Вы собираетесь активировать **{PROVIDER_NAME}**. Это означает, что:
>
> 1. **Куда передаются ваши данные:**
>    - Ваши промпты, прикреплённые файлы и контекст диалога будут передаваться напрямую с этого устройства в API {PROVIDER_NAME}.
>    - Серверы {PROVIDER_NAME} расположены в **{PROVIDER_JURISDICTION}**.
>    - Запросы **не проходят через серверы dias.now**.
>
> 2. **Кто отвечает за ваши данные:**
>    - {PROVIDER_NAME} становится самостоятельным оператором ваших данных в значении применимого законодательства.
>    - Использование {PROVIDER_NAME} регулируется собственными условиями и политикой конфиденциальности этого провайдера.
>    - dias.now не несёт ответственности за обработку ваших данных провайдером.
>
> 3. **Что вам нужно сделать:**
>    - Ознакомиться с [условиями обслуживания {PROVIDER_NAME}]({PROVIDER_TOS_URL});
>    - Ознакомиться с [политикой конфиденциальности {PROVIDER_NAME}]({PROVIDER_PRIVACY_URL});
>    - Получить и ввести ваш собственный API-ключ от {PROVIDER_NAME}.
>
> 4. **Особенно важно для резидентов Казахстана:**
>    - Передача данных в **{PROVIDER_JURISDICTION}** является трансграничной передачей персональных данных в значении статей 7–8 Закона РК «О персональных данных и их защите» №94-V.
>    - {ADEQUACY_STATEMENT}
>
> ☐ Я подтверждаю, что ознакомился с указанной информацией, принимаю условия {PROVIDER_NAME} и даю согласие на трансграничную передачу моих данных в {PROVIDER_JURISDICTION} в целях получения ответов от модели {PROVIDER_NAME}. Я понимаю, что могу отозвать согласие в любой момент, отключив этого провайдера в настройках Продукта.
>
> [Cancel] [Continue and enter API key]

**Переменные шаблона:**

- `{PROVIDER_NAME}` — отображаемое имя провайдера (например, «Anthropic», «OpenAI», «DeepSeek»)
- `{PROVIDER_JURISDICTION}` — страна по умолчанию (см. таблицу ниже)
- `{PROVIDER_TOS_URL}` — ссылка на ToS провайдера
- `{PROVIDER_PRIVACY_URL}` — ссылка на Privacy Policy провайдера
- `{ADEQUACY_STATEMENT}` — стандартная фраза в зависимости от юрисдикции (см. C.2)

#### English text (template):

> ### Activate Cloud LLM Provider: {PROVIDER_NAME}
>
> You are about to activate **{PROVIDER_NAME}**. This means:
>
> 1. **Where your data goes:**
>    - Your prompts, attached files, and conversation context will be transmitted directly from this device to {PROVIDER_NAME}'s API.
>    - {PROVIDER_NAME}'s servers are located in **{PROVIDER_JURISDICTION}**.
>    - Requests **do not transit through dias.now servers**.
>
> 2. **Who is responsible for your data:**
>    - {PROVIDER_NAME} becomes an independent controller of your data under applicable law.
>    - Use of {PROVIDER_NAME} is governed by that provider's own terms and privacy policy.
>    - dias.now is not responsible for the provider's processing of your data.
>
> 3. **What you need to do:**
>    - Review [{PROVIDER_NAME}'s terms of service]({PROVIDER_TOS_URL});
>    - Review [{PROVIDER_NAME}'s privacy policy]({PROVIDER_PRIVACY_URL});
>    - Obtain and enter your own API key from {PROVIDER_NAME}.
>
> 4. **Especially important for residents of Kazakhstan:**
>    - Transfer of data to **{PROVIDER_JURISDICTION}** constitutes a cross-border transfer of personal data under Articles 7–8 of the Law of Kazakhstan on Personal Data No. 94-V.
>    - {ADEQUACY_STATEMENT}
>
> ☐ I confirm that I have reviewed the above information, accept {PROVIDER_NAME}'s terms, and consent to the cross-border transfer of my data to {PROVIDER_JURISDICTION} for the purpose of obtaining responses from {PROVIDER_NAME}'s model. I understand that I can withdraw consent at any time by deactivating this provider in the Product settings.
>
> [Cancel] [Continue and enter API key]

---

### C.2 Стандартные фразы об адекватности юрисдикции (`{ADEQUACY_STATEMENT}`)

**Логика подстановки:**

| Юрисдикция провайдера | Статус | Текст ADEQUACY_STATEMENT (RU) | Текст ADEQUACY_STATEMENT (EN) |
|---|---|---|---|
| Франция (Mistral) | Адекватная (ЕС в перечне РК) | Франция признаётся РК как страна с адекватным уровнем защиты персональных данных. Дополнительные согласия не требуются. | France is recognised by Kazakhstan as providing an adequate level of personal data protection. No additional consent is required for KZ residents. |
| США (большинство) | Неадекватная | США не входят в перечень стран с адекватным уровнем защиты по законодательству РК. Активируя провайдера, вы даёте отдельное явное согласие на трансграничную передачу. | The United States is not on the list of countries providing an adequate level of protection under Kazakhstani law. By activating this provider, you grant separate explicit consent to the cross-border transfer. |
| Канада (Cohere) | Условно адекватная | Канада обеспечивает уровень защиты, сопоставимый с РК для коммерческой обработки. Тем не менее, активируя провайдера, вы подтверждаете согласие на трансграничную передачу. | Canada provides a level of protection comparable to Kazakhstan for commercial processing. By activating this provider, you confirm consent to the cross-border transfer. |
| Китай (DeepSeek, Z.AI) | **Высокий риск** | **ВНИМАНИЕ:** Китайская Народная Республика не обеспечивает адекватный уровень защиты персональных данных, признаваемый РК. Передача данных в Китай сопряжена с повышенными рисками доступа со стороны государственных органов КНР. Активация этого провайдера может быть **несовместима с обязательствами вашей организации** в регулируемых отраслях (банки, медицина, госструктуры). | **WARNING:** The People's Republic of China does not provide a level of personal data protection recognised by Kazakhstan. Transfer of data to China carries elevated risks of access by Chinese government authorities. Activation of this provider may be **incompatible with your organisation's obligations** in regulated industries (banking, healthcare, government). |

### C.3 Жёсткая блокировка для regulated_mode

**Контекст:** если в настройках Продукта активирован `regulated_mode`, активация Облачных LLM-провайдеров **полностью заблокирована** на уровне приложения. Запрос согласия по C.1 не отображается; вместо этого показывается информационное уведомление.

#### Русский текст:

> ### Активация облачных LLM-провайдеров отключена
>
> Ваш экземпляр dias.now работает в **регулируемом режиме** (regulated_mode). В этом режиме разрешено использование только локально размещённых моделей (Ollama).
>
> Активация {PROVIDER_NAME} и других облачных провайдеров заблокирована для обеспечения соответствия требованиям регулируемых отраслей (банковский сектор, медицина, государственные органы).
>
> Если вам требуется доступ к облачным провайдерам, обратитесь к администратору вашей организации.

#### English text:

> ### Cloud LLM provider activation is disabled
>
> Your instance of dias.now is running in **regulated mode**. In this mode, only locally-hosted models (Ollama) are permitted.
>
> Activation of {PROVIDER_NAME} and other cloud providers is blocked to ensure compliance with the requirements of regulated industries (banking, healthcare, government).
>
> If you require access to cloud providers, please contact your organisation's administrator.

### C.4 Дополнительная безусловная блокировка DeepSeek и Z.AI в regulated_mode

В режиме `regulated_mode` провайдеры **DeepSeek** и **Z.AI** заблокированы безусловно на уровне кода (не только на уровне UI). Любая попытка их активации через изменение конфигурационных файлов должна приводить к ошибке валидации и журналированию инцидента в `founder_admin_log`.

---

## D. WITHDRAWAL OF CONSENT — отзыв согласия

**Локация:** Учётная запись пользователя в dialekt-cloud, раздел «Privacy & Data» / «Конфиденциальность и данные»
**Контекст:** механизм для реализации права на отзыв согласия (Art. 7(3) GDPR, ст. 8 Закона РК).

### D.1 Список действующих согласий с возможностью отзыва

#### Русский текст (страница с табличной формой):

> ### Управление согласиями
>
> Ниже приведены ваши действующие согласия. Вы вправе отозвать любое из них в любой момент.
>
> | Согласие | Дата предоставления | Версия | Действие |
> |---|---|---|---|
> | Принятие Политики, Условий и Оферты | {GRANT_DATE} | v1.0 | _Отзыв возможен только через закрытие учётной записи_ |
> | Трансграничная передача данных в США | {GRANT_DATE} | v1.0 | [Отозвать] |
> | Маркетинговые рассылки | {GRANT_DATE} | v1.0 | [Отозвать] |
> | Активация Anthropic | {GRANT_DATE} | v1.0 | [Отозвать в настройках Продукта] |
> | Активация OpenAI | {GRANT_DATE} | v1.0 | [Отозвать в настройках Продукта] |
> | _(другие активированные провайдеры)_ | | | |
>
> **Важно:** отзыв согласия на трансграничную передачу влечёт невозможность дальнейшего предоставления Сервисов и закрытие вашей учётной записи в течение 30 календарных дней. Отзыв согласия не затрагивает правомерности обработки, осуществлённой до момента отзыва.
>
> Если вы хотите полностью удалить вашу учётную запись и связанные с ней данные, направьте запрос на [privacy@dias.now](mailto:privacy@dias.now) или используйте кнопку ниже:
>
> [Запросить полное удаление учётной записи и данных]

#### English text:

> ### Manage Your Consents
>
> Below are your active consents. You may withdraw any of them at any time.
>
> | Consent | Granted | Version | Action |
> |---|---|---|---|
> | Acceptance of Privacy Policy, Terms, and Public Offer | {GRANT_DATE} | v1.0 | _Withdrawal only via account closure_ |
> | Cross-border transfer to the United States | {GRANT_DATE} | v1.0 | [Withdraw] |
> | Marketing communications | {GRANT_DATE} | v1.0 | [Withdraw] |
> | Anthropic activation | {GRANT_DATE} | v1.0 | [Withdraw in Product settings] |
> | OpenAI activation | {GRANT_DATE} | v1.0 | [Withdraw in Product settings] |
> | _(other activated providers)_ | | | |
>
> **Important:** withdrawal of cross-border transfer consent will result in the inability to provide the Services and closure of your account within 30 calendar days. Withdrawal does not affect the lawfulness of processing carried out prior to the withdrawal.
>
> If you wish to fully delete your account and associated data, email [privacy@dias.now](mailto:privacy@dias.now) or use the button below:
>
> [Request full account and data deletion]

---

## E. COOKIE BANNER — для будущего использования

**Статус:** в текущей архитектуре на лендинге используются только строго необходимые cookie (Cloudflare bot protection). Cookie banner **не требуется** до момента добавления аналитики, ремаркетинга или иных non-essential cookies.

**Этот раздел активируется только при добавлении non-essential cookies (Plausible, PostHog, Google Analytics и т.д.).**

### E.1 Шаблон baseline cookie banner

#### Русский текст:

> ### Использование cookie
>
> Мы используем cookie для обеспечения работы сайта и (с вашего согласия) для понимания того, как посетители используют наш сайт. Подробнее см. [Политику конфиденциальности](https://dias.now/legal/privacy#cookies).
>
> [Принять все] [Только необходимые] [Настроить]

#### English text:

> ### Use of Cookies
>
> We use cookies to operate the site and (with your consent) to understand how visitors use our site. See our [Privacy Policy](https://dias.now/legal/privacy#cookies) for details.
>
> [Accept all] [Necessary only] [Customise]

#### Технические требования:

- Кнопки «Принять все» и «Только необходимые» должны быть **визуально равноценными** (одинаковый размер, цвет, расположение). Это требование GDPR Recital 32 и решений CJEU (Planet49 C-673/17).
- До нажатия любой из кнопок non-essential cookies **не должны** ставиться.
- В разделе «Настроить» должны быть отдельные тогглы для каждой категории (analytics, marketing, functional), все по умолчанию выключены.

---

## F. AUDIT TRAIL — журналирование согласий

### F.1 Схема таблицы `consent_log` (PostgreSQL)

```sql
CREATE TABLE consent_log (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    consent_type VARCHAR(64) NOT NULL,           -- 'privacy_terms_offer', 'cross_border_us', 'marketing', 'llm_anthropic', etc.
    consent_version VARCHAR(16) NOT NULL,         -- '1.0'
    consent_text_hash VARCHAR(64) NOT NULL,       -- SHA-256 текста, который видел пользователь
    granted_at TIMESTAMPTZ NOT NULL,
    withdrawn_at TIMESTAMPTZ,                     -- NULL если действует
    ip_address INET NOT NULL,
    user_agent TEXT,
    locale VARCHAR(8) NOT NULL,                   -- 'ru', 'en'
    metadata JSONB                                -- доп. данные: список получателей при cross-border, и т.д.
);

CREATE INDEX idx_consent_log_user ON consent_log(user_id);
CREATE INDEX idx_consent_log_active ON consent_log(user_id, consent_type) WHERE withdrawn_at IS NULL;
```

### F.2 Схема таблицы `consent_versions`

```sql
CREATE TABLE consent_versions (
    consent_type VARCHAR(64) NOT NULL,
    version VARCHAR(16) NOT NULL,
    locale VARCHAR(8) NOT NULL,
    full_text TEXT NOT NULL,
    text_hash VARCHAR(64) NOT NULL,
    effective_from TIMESTAMPTZ NOT NULL,
    effective_until TIMESTAMPTZ,
    PRIMARY KEY (consent_type, version, locale)
);
```

**Назначение:** при проверке регулятором или в споре с пользователем мы должны иметь возможность предъявить **точный текст**, который пользователь видел в момент предоставления согласия. Хеш в `consent_log` сверяется с хешем в `consent_versions`.

### F.3 Retention журнала согласий

- Записи `consent_log` хранятся **3 года после отзыва согласия** или **3 года после удаления учётной записи**, в зависимости от того, что наступит раньше после удаления учётки.
- `consent_versions` — хранятся **бессрочно** (это история юридических документов, удалять нельзя).

### F.4 Защита от подделки согласий

- Записи `consent_log` доступны на запись только сервису согласий, не общему backend-приложению.
- Изменение существующих записей запрещено на уровне БД (триггер запрещает UPDATE, кроме поля `withdrawn_at`).
- Раз в неделю производится подписание актуального состояния таблицы хешем (Merkle root) с архивацией в внешнее immutable storage (опционально для compliance-зрелости уровня Enterprise).

---

## G. ОБНОВЛЕНИЕ СОГЛАСИЙ ПРИ ИЗМЕНЕНИИ УСЛОВИЙ

### G.1 Когда требуется переспросить согласие

| Изменение | Действие |
|---|---|
| Существенное изменение Privacy Policy (новые цели обработки, новые категории данных) | Email-уведомление + переподтверждение при следующем входе |
| Добавление нового sub-processor с новой юрисдикцией | Email-уведомление + переподтверждение cross-border consent |
| Замена существующего sub-processor (Zoho → ZeptoMail в той же юрисдикции) | Email-уведомление за 30 дней; переподтверждение **не требуется**, если не меняется юрисдикция |
| Изменение Terms of Service в части, не затрагивающей обработку ПДн | Email-уведомление за 30 дней без переподтверждения |
| Опечатки, уточнения формулировок | Без уведомления |

### G.2 Текст переподтверждения согласия (при следующем входе)

#### Русский текст:

> ### Обновление условий обработки данных
>
> Мы обновили [Политику конфиденциальности](https://dias.now/legal/privacy) и [Условия использования](https://dias.now/legal/terms). Существенные изменения:
>
> - {CHANGE_LIST}
>
> Изменения вступают в силу с {EFFECTIVE_DATE}. Чтобы продолжить использование Сервисов, ознакомьтесь с обновлёнными условиями и подтвердите согласие.
>
> ☐ Я ознакомился(-ась) с обновлёнными Политикой и Условиями и принимаю их.
> ☐ {ADDITIONAL_CONSENT_IF_CROSS_BORDER_CHANGED}
>
> [Принять и продолжить] [Отказаться и закрыть учётную запись]

---

## H. ЧЕКЛИСТ ВНЕДРЕНИЯ

Перед публичным релизом dias.now разработчик подтверждает следующее:

- [ ] **A.1** реализован: чекбокс не предзаполнен, блокирует submit, ведёт лог в `consent_log`.
- [ ] **A.2** реализован: раскрывающийся блок с актуальным списком sub-processors, чекбокс не предзаполнен, лог записывается с указанием получателей.
- [ ] **A.3** реализован: чекбокс маркетинга **отдельный**, не предзаполнен, не блокирует submit.
- [ ] **B.1** показывается при первом запуске Продукта.
- [ ] **C.1** реализован для **каждого** из 18 поддерживаемых LLM-провайдеров с правильным `{PROVIDER_JURISDICTION}` и `{ADEQUACY_STATEMENT}`.
- [ ] **C.3** проверен: при `regulated_mode = true` модальное окно C.1 не отображается, вместо него показывается C.3.
- [ ] **C.4** проверен: DeepSeek и Z.AI заблокированы на уровне кода в `regulated_mode`, не только в UI.
- [ ] **D.1** реализован: страница «Privacy & Data» с возможностью отозвать каждое согласие.
- [ ] **F.1, F.2** созданы: таблицы `consent_log` и `consent_versions` существуют в БД.
- [ ] **F.4** настроен: триггеры запрета UPDATE, ограничения доступа на запись.
- [ ] Все тексты доступны на двух языках (RU + EN), переключение языка работает.
- [ ] Unsubscribe link в маркетинговых письмах работает в один клик без логина.
- [ ] Endpoint `POST /api/v1/consent/withdraw` реализован для программного отзыва согласия.

---

**Конец документа Cross-Border Consent & UI Texts v1.0**
