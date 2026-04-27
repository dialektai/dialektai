# Privacy Policy

**Product:** dias.now
**Controller:** Limited Liability Partnership "Dialekt.ai" (TOO "Dialekt.ai")
**Effective date:** 25 April 2026
**Version:** 1.0
**Last updated:** 25 April 2026

---

## 1. Introduction and scope

This Privacy Policy describes how Limited Liability Partnership "Dialekt.ai" ("**dialekt**", "**we**", "**our**", "**us**") collects, processes, stores, and protects personal data of users of the dias.now software product (the "**Product**"), the dias.now website at https://dias.now (the "**Website**"), and the dialekt-cloud licensing infrastructure (collectively, the "**Services**").

This Policy applies to:

- Visitors to the Website who submit a registration form;
- Individuals who download, install, and use the Product on their own devices;
- Authorised users of customer organisations to whom Product licences have been issued;
- Individuals who contact us at any of the email addresses listed in Section 16.

This Policy does **not** apply to:

- Personal data processed locally on the user's own device by the Product, where dialekt has no technical means of access (see Section 4.3);
- Personal data submitted by the user directly to third-party Large Language Model providers when the user enables such providers within the Product (see Section 4.4 and Section 7);
- Third-party websites or services linked from the Website or Product.

The Services are intended for business and professional use by individuals aged 18 and older. We do not knowingly collect personal data from minors (see Section 13).

---

## 2. Controller details

The data controller within the meaning of Article 4(7) of Regulation (EU) 2016/679 (the "**GDPR**") and the operator of personal data within the meaning of the Law of the Republic of Kazakhstan No. 94-V dated 21 May 2013 "On Personal Data and Their Protection" (the "**Law on Personal Data**") is:

| Field | Value |
|---|---|
| Legal name | Limited Liability Partnership "Dialekt.ai" (TOO "Dialekt.ai") |
| Business Identification Number (BIN) | 260140001608 |
| Date of state registration | 6 January 2026 |
| Registration authority | Department of Registration of Legal Entities of the Branch of NAO "Government Corporation 'Government for Citizens'" for the city of Astana |
| Registered office | Republic of Kazakhstan, Astana, Esil district, Е 652 Street, building 4, premise 1, postal code 010000 |
| Acting on the basis of | Standard Charter |
| Director | Dias Zhumagaliyev Kaisaruly |
| General contact | hello@dias.now |
| Privacy contact | privacy@dias.now |
| Security contact | security@dias.now |
| Billing contact | billing@dias.now |

### 2.1 Data Protection Officer

In accordance with Article 27 of the Law on Personal Data and Article 37 of the GDPR, we have designated a Data Protection Officer ("**DPO**"):

- **Name:** Dias Zhumagaliyev Kaisaruly
- **Email:** dpo@dias.now
- **Postal address:** as set out in Section 2 above

The DPO is the primary point of contact for all matters relating to the processing of personal data and the exercise of data subject rights (see Section 11).

### 2.2 Representative in the European Union

In accordance with Article 27 of the GDPR, we have appointed a representative in the European Union to act as a contact point for EU-based data subjects and supervisory authorities:

- **Representative:** [PRIGHTER GROUP — to be inserted upon completion of registration]
- **Address:** [EU ADDRESS — to be inserted]
- **Email:** [REPRESENTATIVE EMAIL — to be inserted]

The EU representative acts as a contact point in addition to, and not in substitution for, the controller. EU data subjects may contact either the EU representative or the controller directly using the contacts in Section 2.

> **Note for publication:** Section 2.2 must be finalised with the actual representative details before this Policy is published. Until appointment is complete, this Policy is not to be published.

### 2.3 Representative in the United Kingdom

A UK representative under Article 27 of the UK GDPR has not been appointed as of the effective date of this Policy. UK-based data subjects may contact the controller directly at privacy@dias.now or dpo@dias.now. We will appoint a UK representative if and when our user base in the United Kingdom reaches a level requiring such appointment under applicable UK law.

---

## 3. Definitions

For the purposes of this Policy:

- **"Personal data"** means any information relating to an identified or identifiable natural person, as defined in Article 4(1) GDPR and Article 1(1) of the Law on Personal Data.
- **"Processing"** means any operation performed on personal data, whether or not by automated means.
- **"Data subject"** means the natural person to whom personal data relates.
- **"Sub-processor"** means a third party engaged by us to process personal data on our behalf.
- **"Cross-border transfer"** means the transmission of personal data to a country outside the Republic of Kazakhstan (under the Law on Personal Data) or to a country outside the European Economic Area (under the GDPR).
- **"Cloud LLM provider"** means a third-party Large Language Model service (such as Anthropic, OpenAI, Google, AWS, and others listed in Section 7) that the user may optionally enable from within the Product.
- **"Local device"** means the user's own computer on which the Product is installed.

---

## 4. Categories of personal data we process

### 4.1 Registration data (collected via Website signup form)

| Field | Type | Required | Source |
|---|---|---|---|
| Email address | Identifier | Yes | Provided by user |
| Full name | Identifier | Yes | Provided by user |
| Country of residence | Demographic | Yes | Provided by user (ISO 3166-1) |
| Intended use of the Product | Free-text description | Yes | Provided by user |
| Signup source (UTM parameters) | Marketing metadata | No | Automatically captured if present in URL |
| IP address | Technical | Yes | Automatically captured for anti-abuse |
| User-agent string | Technical | Yes | Automatically captured for anti-abuse |

After activation of the Product, the user may additionally provide:

| Field | Type | Required | Source |
|---|---|---|---|
| Company name | Business | Optional | Provided by user during first-run setup |
| Role within company | Business | Optional | Provided by user during first-run setup |

### 4.2 Billing data (for licensed customers)

| Field | Type | Required | Source |
|---|---|---|---|
| Payer name (individual or legal entity) | Identifier | Yes | Provided by customer |
| BIN / INN / Tax ID | Tax identifier | Yes for KZ legal entities | Provided by customer |
| Bank account details (where applicable) | Financial | Yes for SEPA/SWIFT payments | Provided by customer |
| Invoice records | Financial transaction history | Yes | Generated by us |

We do not currently process online payments. Payments are made by bank transfer to our settlement account at JSC "Bank CenterCredit" (BIC: KCJBKZKX) on the basis of issued invoices. If we add online payment processing in the future, this Policy will be updated and customers will be notified at least 30 days in advance.

### 4.3 Data processed locally on the user's device (NOT on our infrastructure)

The following categories of data are processed exclusively on the local device of the user. With respect to this data, we have no technical means of access. dialekt's cloud infrastructure does not receive, store, or process this data.

- User prompts submitted to Large Language Models;
- Responses returned by Large Language Models (whether local Ollama models or cloud LLM providers);
- Chat history stored in a local SQLite database at `~/.dialekt/dialekt.db`;
- Files and directory contents to which the user grants the Product access;
- API keys for cloud LLM providers, stored in the operating system's secure keychain (GNOME Keyring, KDE Wallet, macOS Keychain, or Windows Credential Manager).

The user acts as the controller of personal data processed locally on their own device within the meaning of Article 4(7) GDPR and the equivalent provisions of the Law on Personal Data.

### 4.4 Cloud LLM provider routing (optional, user-enabled)

Where the user enables a cloud LLM provider from within the Product, prompts are transmitted directly from the user's device to the API of that provider over HTTPS. **Such prompts do not transit through dialekt's cloud infrastructure.** The cloud LLM provider acts as an independent controller or processor of those data under its own terms.

A list of supported cloud LLM providers, their jurisdictions, and links to their privacy policies is provided in Section 7.

### 4.5 Cloud infrastructure logs (dialekt-cloud)

We collect technical logs from our cloud infrastructure for security, debugging, and abuse prevention purposes:

- HTTP access logs (path, status code, timestamp, IP address, user-agent);
- Application error logs (without prompt content);
- Authentication events (login, logout, failed attempts).

We do **not** log the content of user prompts, LLM responses, or chat history in the cloud infrastructure.

### 4.6 Communications

When you contact us by email, we process the contents of your message, your email address, and any attachments you provide.

### 4.7 Cookies and tracking on the Website

The Website uses only strictly necessary cookies for security (Cloudflare bot protection) and session management. We do not use third-party analytics, behavioural tracking, advertising cookies, or fingerprinting on the Website. If we add analytics in the future (such as Plausible or PostHog), this Policy will be updated and a cookie consent banner will be implemented prior to such deployment.

---

## 5. Purposes of processing and lawful basis

We process personal data only where we have a lawful basis to do so. The table below sets out the purposes of processing, the lawful basis under the GDPR, and the basis under the Law on Personal Data.

| Purpose | Lawful basis (GDPR Art. 6) | Basis (Law on Personal Data) |
|---|---|---|
| Creating and maintaining your user account | Performance of contract (Art. 6(1)(b)) | Consent and contract performance (Art. 7) |
| Issuing licence keys and delivery of the Product | Performance of contract (Art. 6(1)(b)) | Consent and contract performance |
| Sending operational emails (password resets, security notices, service announcements) | Performance of contract / legitimate interest (Art. 6(1)(b), 6(1)(f)) | Consent and contract performance |
| Sending product updates and marketing communications | Consent (Art. 6(1)(a)), separate non-pre-ticked opt-in | Separate explicit consent (Art. 8) |
| Anti-abuse, rate limiting, and fraud prevention (IP address, user-agent) | Legitimate interest (Art. 6(1)(f)) | Operator's legitimate interest in protection of rights |
| Issuing and storing invoices, tax accounting | Legal obligation (Art. 6(1)(c)) | Tax Code of the Republic of Kazakhstan |
| Lead qualification and customer segmentation (manual review of "intended use" field) | Legitimate interest (Art. 6(1)(f)) | Consent (Art. 7) |
| Responding to data subject rights requests | Legal obligation (Art. 6(1)(c)) | Legal obligation (Articles 24–27 of the Law) |
| Investigating and responding to security incidents | Legitimate interest / legal obligation | Legal obligation under Article 25 of the Law |

### 5.1 Marketing communications and consent

Marketing communications are sent only to data subjects who have provided **separate, explicit, freely given, specific, informed, and non-pre-ticked** consent on the signup form or via subsequent opt-in. Each marketing email contains an unsubscribe link allowing the recipient to withdraw consent in a single action. Withdrawal of marketing consent does not affect the lawfulness of processing carried out prior to such withdrawal.

### 5.2 Automated decision-making

We do not engage in automated decision-making, including profiling, that produces legal or similarly significant effects on data subjects within the meaning of Article 22 GDPR. The "intended use" field submitted at signup is reviewed manually by a human operator for lead qualification purposes.

---

## 6. Data retention

We retain personal data only for as long as necessary to fulfil the purposes for which it was collected, or as required by applicable law.

| Category of data | Retention period | Action upon expiry |
|---|---|---|
| Active customer account (tenant and authorised users) | For the duration of the customer agreement | Deleted within 30 days of verified deletion request |
| Trial account that did not convert to paid | 12 months from last activity | Anonymisation (email hash) or deletion |
| Invoices and payment records | 5 years from the date of issuance | Archival storage; not deleted (Tax Code of the Republic of Kazakhstan) |
| Email delivery logs | 30 days | Deletion |
| HTTP access logs (cloud infrastructure) | 90 days | Rotation and deletion |
| IP addresses captured at signup | 30 days | Deletion |
| Internal admin audit log (`founder_admin_log`) | 3 years | Archival storage |
| Marketing consent records | For the duration of consent + 3 years following withdrawal | Deletion |
| Data subject rights request records | 3 years from response | Deletion |

### 6.1 Deletion and backups

Upon receipt of a verified deletion request under Article 17 GDPR or Article 25 of the Law on Personal Data, personal data is removed from our active production systems within 30 days. Residual copies present in encrypted backup snapshots are deleted within the standard backup rotation cycle (a maximum of 7 days following removal from active systems), during which they are not accessible for any processing operation other than restoration in the event of a disaster.

---

## 7. Sub-processors and third parties

We engage a limited number of sub-processors to provide the Services. Each sub-processor is bound by a written data processing agreement (DPA) requiring it to process personal data only on our documented instructions and to maintain appropriate technical and organisational measures.

### 7.1 Current sub-processors

| Sub-processor | Legal entity | Jurisdiction | Categories of data processed | DPA |
|---|---|---|---|---|
| Cloudflare, Inc. | Cloudflare, Inc., 101 Townsend Street, San Francisco, CA 94107, USA | United States, with global edge network including EU | DNS resolution, traffic routing, DDoS protection metadata, IP addresses | https://www.cloudflare.com/cloudflare-customer-dpa/ |
| GitHub, Inc. | GitHub, Inc., 88 Colin P Kelly Jr Street, San Francisco, CA 94107, USA (subsidiary of Microsoft Corporation) | United States, with EU edge | Hosting and distribution of Product binary releases (.exe, .dmg, .deb files); release metadata | https://docs.github.com/en/site-policy/privacy-policies/global-privacy-practices |
| Zoho Corporation Pvt. Ltd. | Zoho Corporation, 4141 Hacienda Drive, Pleasanton, CA 94588, USA | United States | Email communications: incoming and outgoing emails, including transactional emails (licence keys, password resets, invoices); email recipient addresses; email content | https://www.zoho.com/dpa.html |

### 7.2 Cloud LLM providers (engaged only with explicit user activation)

Where the user enables a cloud LLM provider from within the Product, that provider acts as an **independent controller or processor** of the prompts and responses transmitted to it, under its own terms of service and privacy policy. dialekt is not a party to that processing relationship and does not act as a sub-processor or controller of those data.

The user is responsible for reviewing and accepting the terms of each cloud LLM provider before enabling it. Within the Product, a privacy notice is displayed for each provider before activation.

The currently supported cloud LLM providers, their default jurisdictions, and links to their privacy policies are:

| Provider | Default jurisdiction | Privacy policy |
|---|---|---|
| Anthropic | United States | https://www.anthropic.com/legal/privacy |
| OpenAI | United States | https://openai.com/policies/privacy-policy |
| Google (Gemini, Vertex AI) | United States | https://policies.google.com/privacy |
| Amazon Web Services (Bedrock) | User-selectable region | https://aws.amazon.com/privacy/ |
| Microsoft Azure (Azure OpenAI) | User-selectable region | https://privacy.microsoft.com/ |
| NVIDIA NIM | United States | https://www.nvidia.com/en-us/about-nvidia/privacy-policy/ |
| Mistral AI | France (European Union) | https://mistral.ai/terms/#privacy-policy |
| DeepSeek | People's Republic of China | https://www.deepseek.com/privacy |
| xAI | United States | https://x.ai/legal/privacy-policy |
| Cohere | Canada / United States | https://cohere.com/privacy |
| Groq | United States | https://groq.com/privacy-policy/ |
| Together AI | United States | https://www.together.ai/privacy |
| Fireworks AI | United States | https://fireworks.ai/privacy-policy |
| Perplexity | United States | https://www.perplexity.ai/hub/legal/privacy-policy |
| OpenRouter | United States | https://openrouter.ai/privacy |
| Cerebras | United States | https://www.cerebras.net/privacy-policy/ |
| Replicate | United States | https://replicate.com/privacy |
| Z.AI / GLM | People's Republic of China | https://z.ai/privacy |

This list is reproduced and kept up to date in the Cloud LLM Providers Reference Table available at https://dias.now/legal/cloud-providers (the "**Reference Table**"). The Reference Table forms an integral part of this Policy.

### 7.3 Regulated mode

The Product includes a configurable setting (`regulated_mode`) intended for customers in regulated industries (banking, healthcare, government, critical infrastructure). When `regulated_mode` is enabled, all cloud LLM providers are disabled at the application level, and only locally-hosted models (Ollama) may be used. In this mode, no prompts or responses leave the user's local device.

### 7.4 Future sub-processors

We will notify customers at least 30 days before engaging any new sub-processor that processes personal data on our behalf. Notification is sent by email to the primary administrator of each customer tenant. Customers have the opportunity to object to the engagement of a new sub-processor; if such objection cannot be reasonably resolved, the customer has the right to terminate the affected portion of the Services without penalty.

---

## 8. International transfers

### 8.1 Transfers from Kazakhstan

Personal data of data subjects resident in the Republic of Kazakhstan is transferred outside Kazakhstan in connection with the use of the sub-processors listed in Section 7. Specifically:

- Email address and registration data are transferred to **Zoho Corporation in the United States**;
- DNS and traffic-protection metadata are transferred to **Cloudflare, Inc. in the United States** and its global edge network;
- Application binaries and download metadata are hosted with **GitHub, Inc. in the United States**.

The United States is not currently included in the list of countries providing an adequate level of personal data protection for the purposes of cross-border transfer under the Law on Personal Data No. 94-V (as amended on 18 January 2026). Accordingly, we obtain **separate, explicit, written consent** from each Kazakhstani data subject to the cross-border transfer of their personal data to the United States, in accordance with Articles 7 and 8 of the Law on Personal Data. This consent is collected via the signup form and may be withdrawn at any time by contacting privacy@dias.now.

Withdrawal of cross-border transfer consent will result in the inability to provide the Services and will lead to the closure of the user's account.

### 8.2 Transfers from the European Economic Area

Personal data of data subjects resident in the European Economic Area is transferred to the Republic of Kazakhstan (the controller's jurisdiction) and to the United States (Cloudflare, GitHub, Zoho).

- **Transfers to Kazakhstan:** Kazakhstan is not currently the subject of an adequacy decision by the European Commission under Article 45 GDPR. Accordingly, transfers from the EEA to Kazakhstan are made on the basis of **Standard Contractual Clauses** ("**SCCs**") adopted by the European Commission pursuant to Implementing Decision (EU) 2021/914, supplemented by additional safeguards as described in our Transfer Impact Assessment, available on request from privacy@dias.now.
- **Transfers to the United States:** transfers to Cloudflare, GitHub, and Zoho are made on the basis of the EU-U.S. Data Privacy Framework (where the relevant entity is certified) or SCCs.

### 8.3 Transfers initiated by the user (cloud LLM providers)

Where the user enables a cloud LLM provider, the resulting transfer of prompts and responses is initiated by the user from the user's own device, directly to the provider, and is not routed through our infrastructure. The user is responsible for ensuring that such transfers comply with any applicable obligations under the laws of the user's jurisdiction.

For Kazakhstani users, this includes obtaining their own valid basis for cross-border transfer where required. The Product surfaces a privacy notice and obtains in-app consent from the user before the first activation of each cloud LLM provider.

### 8.4 Restriction for users in regulated industries

For users operating under `regulated_mode` (Section 7.3), no cross-border transfer of prompts or responses occurs, as cloud LLM providers are disabled at the application level. The DeepSeek and Z.AI providers, which transmit data to the People's Republic of China, are blocked unconditionally in `regulated_mode` regardless of user attempts to enable them.

---

## 9. Security

We implement appropriate technical and organisational measures designed to ensure a level of security appropriate to the risk, in accordance with Article 32 GDPR and Article 25 of the Law on Personal Data.

### 9.1 Technical measures

- **Encryption in transit:** all communications with our cloud infrastructure are protected by TLS 1.2 or higher (HTTPS). Email transmission uses STARTTLS or implicit TLS.
- **Encryption at rest:** the production PostgreSQL database is hosted on encrypted file systems. Local API keys for cloud LLM providers are stored in the operating system's secure keychain (GNOME Keyring, KDE Wallet, macOS Keychain, or Windows Credential Manager); a fallback XOR + scrypt-derived key mechanism is used where keychain access is not available.
- **Access control:** role-based access control is enforced for all administrative endpoints. JWT-based authentication is required for all cloud-side operations.
- **Multi-factor authentication:** mandatory for all administrative accounts with access to customer personal data.
- **Audit logging:** all administrative actions on customer tenants are recorded in an immutable audit log retained for 3 years.
- **Backups:** daily encrypted snapshots of the production database, with a 7-day rotation cycle.

### 9.2 Organisational measures

- Access to customer personal data is restricted to personnel who require such access to perform their duties;
- All personnel with access to personal data are bound by written confidentiality obligations;
- Sub-processors are engaged only under written agreements containing data protection obligations no less protective than those in this Policy.

### 9.3 Personal data breach notification

In the event of a personal data breach as defined in Article 4(12) GDPR or Article 1(7-1) of the Law on Personal Data:

- We will notify the competent supervisory authority without undue delay and, where feasible, no later than **72 hours** after becoming aware of the breach (Article 33 GDPR);
- We will notify affected data subjects without undue delay where the breach is likely to result in a high risk to their rights and freedoms (Article 34 GDPR);
- We will notify the Personal Data Protection Committee of the Republic of Kazakhstan in accordance with the Law on Personal Data;
- Security incidents may be reported to security@dias.now. We acknowledge security reports within 24 hours.

---

## 10. Disclosure of personal data to third parties

We do not sell personal data. We do not share personal data with third parties for their own marketing purposes.

We disclose personal data to third parties only in the following circumstances:

- **Sub-processors** acting on our documented instructions (Section 7);
- **Legal obligations:** where disclosure is required by applicable law, court order, or binding request of a competent authority;
- **Protection of rights:** where disclosure is necessary to establish, exercise, or defend legal claims, or to investigate fraud or security incidents;
- **Business transfers:** in the event of a merger, acquisition, reorganisation, or sale of assets, personal data may be transferred to the acquiring entity, provided the acquiring entity is bound by terms no less protective than this Policy and data subjects are notified.

Where we receive a request for disclosure from a public authority, we will (where legally permitted) review the request for compliance with applicable law, narrow its scope to the minimum necessary, and notify affected data subjects.

---

## 11. Your rights

Depending on the law applicable to you, you have the following rights with respect to your personal data.

### 11.1 Rights under the GDPR (for EEA, UK, and Swiss data subjects)

- **Right of access** (Article 15): to obtain confirmation of processing and a copy of your personal data;
- **Right to rectification** (Article 16): to request correction of inaccurate or incomplete data;
- **Right to erasure** (Article 17): to request deletion of your data ("right to be forgotten");
- **Right to restriction of processing** (Article 18);
- **Right to data portability** (Article 20): to receive your data in a structured, commonly used, machine-readable format;
- **Right to object** (Article 21): to processing based on legitimate interests, including profiling;
- **Right to withdraw consent** (Article 7(3)): at any time, without affecting the lawfulness of prior processing;
- **Right not to be subject to automated decision-making** (Article 22);
- **Right to lodge a complaint** with a supervisory authority — for EEA residents, the data protection authority of your country of residence; the lead supervisory authority for dialekt is to be confirmed once the EU representative is appointed.

### 11.2 Rights under the Law on Personal Data (for Kazakhstani data subjects)

- **Right of access** (Article 24): to know whether your personal data is being processed;
- **Right to rectification** (Article 25): to request correction of inaccurate data;
- **Right to blocking** (Article 26): to request temporary suspension of processing in case of dispute;
- **Right to deletion** (Article 27): to request deletion of your data where the legal basis has ceased to exist;
- **Right to withdraw consent**: at any time;
- **Right to lodge a complaint** with the Personal Data Protection Committee of the Republic of Kazakhstan.

### 11.3 How to exercise your rights

To exercise any of the above rights, please contact us at **privacy@dias.now** or **dpo@dias.now**. We will respond to your request within **30 calendar days** from the date of receipt. In complex cases, this period may be extended by up to 60 additional days, in which case we will inform you of the extension and the reasons for it within the original 30-day period.

We may request reasonable information to verify your identity before responding to your request. We will not charge a fee for handling your request unless it is manifestly unfounded or excessive, in which case we may charge a reasonable fee or refuse to act on the request.

---

## 12. Cookies

The Website uses only the following cookies:

| Cookie | Provider | Purpose | Duration | Type |
|---|---|---|---|---|
| `__cf_bm` | Cloudflare | Bot protection (Cloudflare Bot Management) | 30 minutes | Strictly necessary |
| `cf_clearance` | Cloudflare | Verifies a successful challenge response | 30 minutes to 1 year | Strictly necessary |

We do not use analytics cookies, advertising cookies, social media cookies, or fingerprinting techniques. If we add any non-strictly-necessary cookies in the future, this Policy will be updated and a cookie consent banner will be implemented prior to such deployment in compliance with Article 7 GDPR and the ePrivacy Directive.

---

## 13. Children

The Services are intended for use by individuals aged 18 and older in a professional or business context. We do not knowingly collect personal data from individuals under 18. If you become aware that a minor has provided us with personal data, please contact privacy@dias.now and we will delete the data and the associated account without undue delay.

---

## 14. Changes to this Policy

We may update this Policy from time to time. The "Effective date" and "Version" at the top of this document indicate when the Policy was last revised.

For material changes that affect the rights of data subjects or the categories of data processed, we will notify registered users by email at least **30 days before** the changes take effect. For non-material changes (such as clarifications of language or updates to sub-processor addresses), we may publish the updated Policy on the Website without prior notification.

Historical versions of this Policy are retained and are available on request from privacy@dias.now.

---

## 15. Governing law

This Policy is governed by the laws of the Republic of Kazakhstan with respect to the obligations of the controller as a Kazakhstani legal entity, and by the GDPR with respect to the rights of EEA and UK data subjects. Where the two regimes provide different levels of protection, the regime more favourable to the data subject applies.

---

## 16. Contact

For all matters relating to the processing of your personal data:

- **Data subject rights requests, complaints, consent withdrawal:** privacy@dias.now
- **Direct contact with the Data Protection Officer:** dpo@dias.now
- **Security incidents and vulnerability disclosure:** security@dias.now
- **Billing and invoicing matters:** billing@dias.now
- **General enquiries:** hello@dias.now

Postal address:

Limited Liability Partnership "Dialekt.ai"
Republic of Kazakhstan, Astana, Esil district
Е 652 Street, building 4, premise 1
Postal code 010000

---

**End of Privacy Policy v1.0**
