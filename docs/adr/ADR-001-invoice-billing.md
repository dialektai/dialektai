# ADR-001: Invoice-based billing (no Stripe)

**Date:** 2026-04-22
**Status:** Accepted

## Context

dialekt targets B2B customers in Kazakhstan where:
- Stripe is not available for KZ IPs without a foreign entity
- Clients expect bank-transfer invoices (`счёт на оплату`)
- The founder conducts all sales manually (direct outreach, POC calls)
- Volume is small (< 20 pilot clients in first year)

## Decision

Payment is fully manual:
1. Founder creates tenant in admin panel (draft, no license yet)
2. Founder generates PDF invoice and sends by email
3. Client pays by bank transfer (1-3 business days)
4. Founder confirms payment, clicks "Activate" in admin panel
5. System generates `license_key`, emails to tenant admin
6. Tenant admin enters key in dialekt desktop app

No Stripe, no automated billing, no self-serve checkout.

## Consequences

**Good:**
- No payment processor dependency
- Works with any bank in KZ/RU
- No additional legal complexity for digital services VAT

**Bad:**
- Manual process does not scale past ~50 clients without tooling
- No automatic renewal/dunning
- Churn requires manual action (suspend tenant in admin panel)

## Review trigger

Re-evaluate if:
- Monthly sign-ups exceed 10 without self-serve
- Stripe KZ support becomes available
- A reseller partner in EU is established
