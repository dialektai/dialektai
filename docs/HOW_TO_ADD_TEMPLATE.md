# How to add a template to the Agent Library

After a pilot ships an agent that works well, generalize it and add it
to the public catalog so future pilots from similar industries can
install it with one click.

This is the v1 curation flow: **a git PR to `library_seed.py`**.
v2 will move authoring to a founder admin UI; until then, every
template change goes through code review.

---

## Checklist

1. **Generalize the agent's manifest.** Strip everything pilot-specific
   from the manifest YAML:
   - Replace company / product names with placeholders
     (e.g., `"Acme Corp"` → `"your company"`)
   - Replace any `connection_id`, table names, or schema references
     with generic ones — use Jinja-style placeholders
     (`{{connection_id}}`)
   - Replace tone / branding instructions specific to one pilot's
     style guide with neutral language
   - Remove any system_prompt content that mentions a pilot's
     workflow shorthand or internal jargon
   - Bump `metadata.version` to `1.0.0` (it's the first public version)

   **NEVER include client / pilot identifiers anywhere.** Not in the
   agent name, not in the description, not in the slug, not in tags,
   not in system_prompt, not in tests. The library is public — names
   leak who's piloting the product.

2. **Verify the generic manifest passes the validator:**

   ```bash
   cd python && source venv/bin/activate
   python -c "
   from dialekt_manifest import ManifestValidator
   import sys
   yaml_str = open('your-new-template.yaml').read()
   r = ManifestValidator().validate_string(yaml_str)
   if not r.valid:
       for e in r.errors:
           print(f'ERROR  {e.code.value}: {e.message}')
       sys.exit(1)
   print('OK', len(r.warnings), 'warnings')
   "
   ```

3. **Verify the agent runs** without the pilot's specific data:
   - Install it locally via `POST /library/{id}/install` after seeding
   - Open a chat and exercise its golden path (run the catalog's sample
     query, ask the agent to do its main task)
   - If it requires_connection, point it at a sandbox DB (the existing
     ecom integration database is fine)
   - Confirm the agent doesn't hallucinate references to pilot-specific
     data because the system_prompt is now too vague

4. **Add a `LibraryTemplate` entry** to
   `dialekt-cloud/src/dialekt_cloud/services/library_seed.py`:

   ```python
   LIBRARY_TEMPLATES: tuple[LibraryTemplate, ...] = (
       # ...existing entries...
       LibraryTemplate(
           id="your-slug",                     # kebab-case, stable
           category="documents",               # one of the controlled vocab values
           tags=("tag1", "tag2", "tag3"),
           manifest_yaml=_yaml("""
               spec_version: "1.1.0"
               # ... full manifest ...
           """),
       ),
   )
   ```

5. **Pick a stable UUID v4** for `metadata.id` and pin it. Don't
   regenerate on every commit — the same library entry must keep the
   same UUID across versions. Use:

   ```bash
   python3 -c "import uuid; print(uuid.uuid4())"
   ```

6. **Open a PR** with these changes:
   - The new entry in `library_seed.py`
   - A line in `docs/AGENT_CATALOG.md` if the agent fits a category
     there
   - Test the seed loader doesn't crash:
     ```bash
     cd dialekt-cloud && python -m pytest tests/test_library_seed.py
     ```

7. **After merge**, the next cloud deploy will pick it up. Verify:

   ```bash
   curl https://api.dias.now/public/library | jq '.entries[].id'
   # → should include "your-slug"
   ```

8. **Update `docs/AGENT_CATALOG.md`** with a paragraph describing the
   agent and a sample query. The library is the install surface; the
   catalog is the human-readable inventory.

---

## Things that will get a PR rejected

- **Pilot leakage.** Any mention of a real client / company / pilot
  name in the agent's name, slug, description, system_prompt, tags,
  or comments. Even internal references like "based on the IBA flow"
  in commit messages (commit messages are public on the GitHub repo).

- **Pilot-specific table names or schemas** in the system_prompt
  (e.g., `instructors_resume` if that's a table that only exists at
  one pilot). Use generic examples or refer to schema introspection
  tools.

- **Hardcoded credentials** of any kind, even in placeholder form.
  Connection IDs go through `{{connection_id}}` template variable.

- **Non-validating manifests.** If the validator returns errors,
  the seed loader's idempotent upsert will store the broken YAML
  but `/library/{id}/install` will 422 at runtime — broken catalog.

- **Agents with known broken behavior.** Mentor flagged the catalog's
  Data Engineer (loops on missing schema hints) and Kazakh translator
  (broken grammar) as not seed-ready. Same gate applies to new
  submissions — verify the agent works on its golden path before PR.

- **Adding fields to the schema** (`verified`, `installed_count`,
  `pilot_source`, etc.). Those were rejected by design in
  [`AGENT_TEMPLATE_SPEC.md`](AGENT_TEMPLATE_SPEC.md). If you have a
  use case that genuinely needs one, open an architecture issue first.

---

## Reference

- [`AGENT_TEMPLATE_SPEC.md`](AGENT_TEMPLATE_SPEC.md) — schema, API, architecture
- [`AGENT_CATALOG.md`](AGENT_CATALOG.md) — human-readable inventory
- [`dialekt-cloud/src/dialekt_cloud/services/library_seed.py`](../dialekt-cloud/src/dialekt_cloud/services/library_seed.py) — the seed module itself
- [`python/server.py`](../python/server.py) `import_manifest_yaml()` — shared install path
