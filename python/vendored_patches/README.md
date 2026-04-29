# Vendored patches

Local overrides of installed Python packages.

## `dialekt_manifest_schema.py`

Patched copy of `dialekt_manifest/schema.py`. Adds:

- `EmailOrTelegramDestination` fields: `telegram_chat_id`, `telegram_bot_token`,
  `email_to`, `smtp_host`, `smtp_port`, `smtp_user`, `smtp_password`,
  `smtp_from`, `smtp_use_tls`, `from`
- `ScheduledTrigger` fields: `rss_feeds`, `message`
- `Variable.default` field
- Capability groups: `web_search`, `web_crawl`, `rss_read`,
  `working_directory_read`, `working_directory_write`, `bitrix_write`,
  `instagram_publish`

Upstream `dialektai/dialekt-manifest-validator` should absorb these.
Until then, after fresh `pip install` run:

```
cp python/vendored_patches/dialekt_manifest_schema.py \
   python/venv/lib/python3.12/site-packages/dialekt_manifest/schema.py
```

Or run `python/scripts/apply_vendored_patches.sh` (see scripts/).
