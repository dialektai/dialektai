# Cross-Border Consent & UI Texts
## Wording catalogue for the dias.now user interface

**Version:** 1.0
**Date:** 25 April 2026
**Related:** Privacy Policy v1.0, Terms of Service v1.0, Public Offer v1.0

> **Informational translation.** The Russian master document published at https://dias.now/cross-border-consent.html is the authoritative source. The Russian version contains both EN and RU variants of every UI string side-by-side, plus the implementation notes and database schemas the development team relies on. This English summary lists the same sections and the English UI strings only. In case of any discrepancy, the Russian master prevails.

---

## Purpose of the document

This document collects ready-made consent and notification copy to embed in the dias.now product UI. Each text is drafted to satisfy:

- Articles 7–8 of the Law of the Republic of Kazakhstan on Personal Data and Their Protection No. 94-V (as amended on 18 January 2026);
- Articles 6, 7, 9, 13, and 49 of the GDPR;
- the ePrivacy Directive 2002/58/EC (forward-looking, for cookie consent).

**Each text in the master document is paired with a developer spec block** stating:
- where the string is rendered (URL / screen / context);
- the UI element type (checkbox, banner, modal);
- the default state (pre-filled / not pre-filled);
- the audit-log requirements (timestamp + text version persisted to the consent log).

---

## A. SIGNUP FORM — landing-page registration

**Location:** https://dias.now (signup form)
**Context:** before an Account is created in dialekt-cloud.

### A.1 Primary consent for personal-data processing and acceptance of documents

**Type:** required checkbox · **Default:** ☐ NOT pre-filled · **Blocks:** "Sign up" button

> ☐ I have read and accept the [Privacy Policy](https://dias.now/legal/privacy), [Terms of Service](https://dias.now/legal/terms), and [Public Offer](https://dias.now/legal/offer). I consent to the processing of my personal data (name, email, country, intended use, IP address) by TOO "Dialekt.ai" for the purposes of creating and maintaining my account, issuing the licence, and operational communication.

### A.2 Consent to international transfer of personal data

**Type:** required checkbox with expandable "Learn more" block · **Default:** ☐ NOT pre-filled · **Blocks:** "Sign up" · **Shown to:** **all visitors**, regardless of country.

**Title:** Consent to International Transfer of Personal Data

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

> ☐ I provide my separate, explicit consent to the international transfer of my personal data to the United States to the processors identified above for the purposes stated, in accordance with Articles 7–8 of the Law of Kazakhstan on Personal Data No. 94-V (where applicable to me) and Article 49 GDPR (where applicable to me).

### A.3 Optional consent to marketing communications

**Type:** optional checkbox **separate from A.1 and A.2** · **Default:** ☐ NOT pre-filled · Does NOT block signup.

> ☐ I consent to receive product updates, feature announcements, and offers from TOO "Dialekt.ai". I understand I can unsubscribe at any time via the link in each email or by emailing privacy@dias.now.

> **Implementation note (critical):** this checkbox **must not** be combined with A.1 or A.2. Bundling several consents into one checkbox violates GDPR Art.7(2) + Recital 32 and Article 8 of the KZ Data Protection Law. Each marketing email must include a one-click unsubscribe link (no email-entry, no login required).

---

## B. FIRST-RUN WIZARD — after Product installation

**Location:** dias.now desktop application, first launch · **Context:** before any functional use of the Product.

### B.1 Informational notice on local processing

**Type:** informational screen (no consent required) · **Action:** "Continue" button.

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

### B.2 Optional telemetry collection (forward-looking)

> **Note:** under the current architecture dias.now collects no telemetry. This block is added to the UI **only** after optional telemetry is implemented and the Privacy Policy is updated. Until then, B.2 is not shown to users.

**Type:** optional checkbox · **Default:** ☐ NOT pre-filled.

> ☐ Help improve dias.now: allow sending anonymous error reports and feature usage data. No content of prompts, responses, or files will be transmitted. See [Privacy Policy, Telemetry section](https://dias.now/legal/privacy#telemetry) for details.

---

## C. CLOUD LLM PROVIDER ACTIVATION

**Location:** dias.now application, settings / model picker · **Context:** before first activation of each cloud LLM provider. Consent is requested **separately per provider** and **only once**.

### C.1 Consent template — generic form

**Type:** modal with a required checkbox · **Default:** ☐ NOT pre-filled · **Blocks:** API-key entry and provider activation.

> ### Activate Cloud LLM Provider: {PROVIDER_NAME}
>
> You are about to activate **{PROVIDER_NAME}**. This means:
>
> 1. **Where your data goes:**
>    - Your prompts, attached files, and conversation context will be transmitted directly from this device to {PROVIDER_NAME}'s API.
>    - {PROVIDER_NAME}'s servers are located in **{PROVIDER_JURISDICTION}**.
>    - Requests **do not pass through dias.now's servers**.
>
> 2. **Who is responsible for your data:**
>    - {PROVIDER_NAME} becomes an independent controller of your data within the meaning of applicable law.
>    - Use of {PROVIDER_NAME} is governed by that provider's own terms and privacy policy.
>    - dias.now is not responsible for the provider's processing of your data.
>
> 3. **What you need to do:**
>    - Read the [{PROVIDER_NAME} terms of service]({PROVIDER_TOS_URL});
>    - Read the [{PROVIDER_NAME} privacy policy]({PROVIDER_PRIVACY_URL});
>    - Obtain and enter your own {PROVIDER_NAME} API key.
>
> 4. **Particularly relevant for Kazakhstan residents:**
>    - Transfer of data to **{PROVIDER_JURISDICTION}** constitutes a cross-border transfer of personal data within the meaning of Articles 7–8 of the Law of Kazakhstan on Personal Data No. 94-V.
>    - {ADEQUACY_STATEMENT}
>
> ☐ I confirm I have read the above, accept {PROVIDER_NAME}'s terms, and consent to the international transfer of my data to {PROVIDER_JURISDICTION} for the purpose of receiving responses from the {PROVIDER_NAME} model. I understand I can withdraw this consent at any time by deactivating this provider in the Product settings.
>
> [Cancel] [Continue and enter API key]

**Template variables:**

- `{PROVIDER_NAME}` — display name (e.g. "Anthropic", "OpenAI", "DeepSeek")
- `{PROVIDER_JURISDICTION}` — default country of provider data centres
- `{PROVIDER_TOS_URL}` — provider's Terms of Service URL
- `{PROVIDER_PRIVACY_URL}` — provider's Privacy Policy URL
- `{ADEQUACY_STATEMENT}` — standard sentence depending on jurisdiction (see C.2)

### C.2 Standard adequacy statements (`{ADEQUACY_STATEMENT}`)

| Provider's jurisdiction | Adequacy text inserted into the modal |
|---|---|
| EU/EEA, United Kingdom, Switzerland, Canada (commercial), Japan, South Korea, New Zealand | "{JURISDICTION} is recognised by certain regulators as providing an adequate level of personal-data protection." |
| United States | "The United States is not currently on the Kazakh list of jurisdictions providing adequate personal-data protection. Transfers are made on the basis of an executed Data Processing Agreement and Standard Contractual Clauses (where the Customer is in the EEA/UK)." |
| China, Russia, Iran, North Korea | "{JURISDICTION} is not on the list of jurisdictions providing an adequate level of personal-data protection. Standard Contractual Clauses do not apply. The Licensor cannot guarantee the level of protection required by Article 12 of the KZ Data Protection Law for transfers to {JURISDICTION}." |
| Other (default) | "Adequacy decisions are jurisdiction-specific. Confirm with your data protection officer before activating in a regulated environment." |

### C.3 Hard block in `regulated_mode`

When `regulated_mode` is on, all cloud LLM providers are disabled at application level. The activation flow is replaced with a static informational screen:

> ### Cloud LLM providers are disabled
>
> Your dialekt installation is configured in **Regulated Mode** (`regulated_mode = true`). All cloud LLM providers are disabled at application level for compliance with sector-specific regulation.
>
> Use the local Ollama backend for all model inference. To enable a cloud provider, deactivate Regulated Mode in your configuration — note that this may breach your sector's compliance requirements.

### C.4 Additional unconditional block for DeepSeek and Z.AI

DeepSeek and Z.AI are blocked unconditionally at the code level when `regulated_mode = true`, separate from the generic block in C.3. This is a defence-in-depth measure for jurisdictions where transfers to the People's Republic of China are barred from regulated-industry workloads.

---

## D. WITHDRAWAL OF CONSENT

**Location:** Account settings on dialekt-cloud (`/settings/consents`) and within the desktop Product (Settings → Privacy → Consents).

### D.1 Active consents list with withdrawal option

A table of active consents granted by the user, with a "Withdraw" button on each:

| Consent | Granted at | Version | Withdraw |
|---|---|---|---|
| Privacy Policy / Terms / Public Offer (A.1) | _timestamp_ | 1.0 | — *(cannot be withdrawn while account is active)* |
| Cross-border transfer of data to the United States (A.2) | _timestamp_ | 1.0 | [Withdraw → closes the account] |
| Marketing communications (A.3) | _timestamp_ | 1.0 | [Withdraw] |
| Activation of Cloud LLM Provider {PROVIDER_NAME} (C.1) | _timestamp_ | 1.0 | [Withdraw → deactivates provider] |
| Optional telemetry (B.2) | _timestamp_ | 1.0 | [Withdraw] |

Withdrawal flows are confirmation modals with a clear effect statement (e.g. "Withdrawing consent A.2 will close your account because the international transfer is required to operate the Service. Continue?"). Each withdrawal is recorded in `consent_log` with `withdrawn_at`.

---

## E. COOKIE BANNER — forward-looking

dias.now's landing site does not currently set non-essential cookies. The block below is the baseline banner to deploy if/when analytics or advertising cookies are introduced.

### E.1 Baseline cookie banner

Type: dismissible banner, persistent until choice is recorded.

> ### Cookies on dias.now
>
> We use a small number of strictly-necessary cookies to remember your language preference and authenticate you to the Account. These do not require consent.
>
> **Optional analytics cookies** help us understand which pages are useful. You can accept, decline, or customise:
>
> [Accept all] [Decline non-essential] [Customise]

The "Customise" option opens a modal with per-category toggles (Essential / Analytics / Advertising) and a per-vendor list. Default state for all non-essential categories is OFF.

---

## F. AUDIT TRAIL — consent journalling

The master document specifies the `consent_log` and `consent_versions` PostgreSQL schemas, the retention policy (3 years after withdrawal or account deletion), and the integrity-protection measures (append-only journal, hash-chained per-row signatures). Refer to the Russian master at https://dias.now/cross-border-consent.html for the schema-level detail.

---

## G. CONSENT REFRESH ON TERMS CHANGE

Re-prompt the user for consent in the following circumstances:

1. **Material change** to the Privacy Policy or Terms of Service that affects the user's rights or the categories of data processed;
2. **New sub-processor** added to A.2 (e.g. replacing Zoho with another transactional-email provider);
3. **New cloud LLM provider** added to the supported list (per-provider re-prompt is unnecessary — only the user who activates the new provider sees C.1);
4. **Any change** to the regulated-mode behaviour that affects which providers are permitted.

The re-prompt UI uses the same A.1 / A.2 / C.1 templates with an additional summary of what changed since the user's previous acceptance.

---

## H. IMPLEMENTATION CHECKLIST

A summarised version of the developer checklist from the Russian master:

- [ ] Each consent string is versioned in `consent_versions`.
- [ ] Consent grant is logged in `consent_log` with `granted_at`, `ip_address`, `user_agent`, `text_hash`.
- [ ] Withdrawal is logged with `withdrawn_at`.
- [ ] No consent is silently bundled — A.1, A.2, A.3, C.1, B.2 each have their own row.
- [ ] Default checkbox state for every consent is `unchecked`.
- [ ] On-screen rendering uses the user's selected language; the active version is stored regardless of which language the user saw.
- [ ] Marketing emails (A.3) include one-click unsubscribe.
- [ ] Cloud LLM activation modal (C.1) is shown only on first activation per provider.
- [ ] When `regulated_mode = true`, all C.* templates are skipped and C.3 is shown instead.
- [ ] DeepSeek and Z.AI are unconditionally blocked at code level when `regulated_mode = true` (C.4).
- [ ] When sub-processors change (A.2), all active users are re-prompted by email.
- [ ] Audit log retention is 3 years past consent withdrawal or account deletion.

---

**End of document, version 1.0**
