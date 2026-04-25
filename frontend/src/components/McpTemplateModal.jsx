import { useEffect, useMemo, useState } from 'react';
import { T } from '../tokens.js';

const API = 'http://localhost:8765';

/**
 * Quick Add modal driven by a catalog entry from GET /mcp-templates.
 *
 * The template carries:
 *  - locked `command` array (stdio) or `url_placeholder` (http gateway)
 *  - `secret_prompts: list` — masked inputs the modal renders
 *  - `string_prompts: list` — non-secret editable inputs (e.g. fs sandbox path)
 *  - validation status + optional upstream warning banner
 *
 * On `[Test & Save]`:
 *   1. Substitute ${prompt:<key>} placeholders in `command` (frontend-side
 *      per the v0.21 plan §1 substitution-boundary contract).
 *   2. POST /mcp-servers with the resolved payload (same shape the
 *      existing inline form uses — no new backend endpoint).
 *   3. POST /mcp-servers/{id}/test.
 *   4. On test fail → modal stays open with [Save anyway] / [Retry test].
 *      On POST 422/409 → modal stays open with inline error, no row.
 *   5. On success → close, refresh server list (parent handler).
 */
export default function McpTemplateModal({ template, onClose, onSaved }) {
  // All hooks must run on every render (React rules-of-hooks). The
  // null-template path returns at the bottom, not before any hook.
  const [name, setName] = useState('');
  const [secrets, setSecrets] = useState({});
  const [strings, setStrings] = useState({});
  const [url, setUrl] = useState('');
  const [timeout, setTimeoutValue] = useState('30');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [testFailedRowId, setTestFailedRowId] = useState(null);

  // Reset state when template changes (modal opens for a different tile).
  useEffect(() => {
    if (!template) return;
    setName(template.id || '');
    setSecrets({});
    setStrings({});
    setUrl(template.url_placeholder || '');
    setTimeoutValue(String(template.default_timeout_seconds || 30));
    setError('');
    setTestFailedRowId(null);
  }, [template]);

  // Esc closes (template modal is dismissible — unlike consent modal,
  // this is configuration not a permission gate).
  useEffect(() => {
    if (!template) return;
    const onKey = (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose?.();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [template, onClose]);

  const isHttp = template?.transport === 'http';

  // Frontend-side ${prompt:<key>} substitution per v0.21 plan §1.
  const commandResolved = useMemo(() => {
    if (!template || !Array.isArray(template.command)) return null;
    return template.command.map((arg) =>
      arg.replace(/\$\{prompt:([a-zA-Z0-9_]+)\}/g, (_, key) => strings[key] || '')
    );
  }, [template, strings]);

  if (!template) return null;

  const validate = () => {
    if (!/^[a-z][a-z0-9-]{0,63}$/.test(name)) {
      return 'Name must be kebab-case (a-z, 0-9, -), start with a letter.';
    }
    for (const sp of (template.string_prompts || [])) {
      if (!strings[sp.ref]?.trim()) return `${sp.label} is required.`;
    }
    for (const sec of (template.secret_prompts || [])) {
      if (!secrets[sec.ref]) return `${sec.label} is required.`;
    }
    if (isHttp && !/^https?:\/\//.test(url.trim())) {
      return 'URL must start with http:// or https://.';
    }
    const ts = parseFloat(timeout);
    if (!Number.isFinite(ts) || ts < 5 || ts > 300) {
      return 'Timeout must be between 5 and 300 seconds.';
    }
    return '';
  };

  const buildPayload = () => {
    const env_secrets = Object.entries(template.env_refs || {})
      .map(([envName, refName]) => ({ ref: refName, value: secrets[refName] || '' }))
      .filter((p) => p.value);
    const payload = {
      name: name.trim(),
      transport: template.transport,
      timeout_seconds: parseFloat(timeout),
      env_refs: { ...(template.env_refs || {}) },
      env_secrets,
    };
    if (template.transport === 'stdio') {
      payload.command = commandResolved;
    } else {
      payload.url = url.trim();
      if (template.auth_type === 'bearer' && secrets.auth_token) {
        payload.auth_type = 'bearer';
        payload.auth_token = secrets.auth_token;
      }
    }
    return payload;
  };

  const submit = async () => {
    const v = validate();
    if (v) { setError(v); return; }
    setError('');
    setBusy(true);
    try {
      const r = await fetch(`${API}/mcp-servers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildPayload()),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        const msg = body?.detail
          ? (typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail))
          : `HTTP ${r.status}`;
        setError(msg);
        return;
      }
      const created = await r.json();
      const tr = await fetch(`${API}/mcp-servers/${created.id}/test`, { method: 'POST' });
      const tdata = await tr.json().catch(() => ({}));
      if (!tdata?.success) {
        setTestFailedRowId(created.id);
        setError(tdata?.error || 'Connection test failed.');
        return;
      }
      onSaved?.(created);
      onClose?.();
    } catch (e) {
      setError(`Save failed: ${String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const retryTest = async () => {
    if (!testFailedRowId) return;
    setBusy(true);
    try {
      const tr = await fetch(`${API}/mcp-servers/${testFailedRowId}/test`, { method: 'POST' });
      const tdata = await tr.json().catch(() => ({}));
      if (tdata?.success) {
        onSaved?.({ id: testFailedRowId, name });
        onClose?.();
      } else {
        setError(tdata?.error || 'Connection test failed.');
      }
    } catch (e) {
      setError(`Retry failed: ${String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const saveAnyway = () => {
    if (testFailedRowId) onSaved?.({ id: testFailedRowId, name });
    onClose?.();
  };

  const showStatusBadge = template.validated
    ? { color: T.green, text: '✓ Validated' }
    : { color: T.amber, text: '⚠ Untested community package' };

  return (
    <div role="dialog" aria-labelledby="tpl-title" style={{
      position: 'fixed', inset: 0, zIndex: 10001,
      background: 'rgba(0,0,0,0.6)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16,
    }} onClick={(e) => { if (e.target === e.currentTarget) onClose?.(); }}>
      <div style={{
        width: 'min(560px, calc(100vw - 32px))',
        maxHeight: 'calc(100vh - 32px)', overflowY: 'auto',
        background: T.bg1, border: `1px solid ${T.border}`,
        boxShadow: '0 12px 48px rgba(0,0,0,0.7)',
        display: 'flex', flexDirection: 'column',
      }}>
        <div style={{ padding: '14px 18px', borderBottom: `1px solid ${T.border}`,
          background: T.bg2, display: 'flex', alignItems: 'center', gap: 10 }}>
          <div id="tpl-title" style={{ fontSize: 13, color: T.text, letterSpacing: '.04em', flex: 1 }}>
            {template.label} MCP
          </div>
          <span className="mono" style={{ fontSize: 10, color: showStatusBadge.color }}>
            {showStatusBadge.text}
          </span>
          <button onClick={onClose} aria-label="close" style={{
            background: 'transparent', border: 'none', color: T.dim,
            fontSize: 16, cursor: 'pointer', padding: '0 4px',
          }}>×</button>
        </div>

        <div style={{ padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ fontSize: 12, color: T.muted, lineHeight: 1.5 }}>{template.description}</div>

          {template.upstream_status_warning && (
            <div style={{ fontSize: 11, color: T.amber, padding: '8px 10px',
              border: `1px solid ${T.amber}66`, background: `${T.amber}0a` }}>
              ⚠ Upstream notice: {template.upstream_status_warning}
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={{ fontSize: 11, color: T.dim }}>Server name *</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder={template.id}
              style={{ background: T.bg2, border: `1px solid ${T.border}`, color: T.text,
                padding: '7px 10px', fontSize: 12, fontFamily: 'var(--code-font, monospace)', outline: 'none' }} />
            <span style={{ fontSize: 10, color: T.dim }}>kebab-case, must be unique across your MCP servers</span>
          </div>

          {template.transport === 'stdio' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <label style={{ fontSize: 11, color: T.dim }}>How dialekt will call it (locked)</label>
              <div className="mono" style={{ background: T.bg2, border: `1px solid ${T.border}`,
                padding: '7px 10px', fontSize: 11, color: T.muted, overflow: 'auto' }}>
                {(template.command || []).join(' ')}
              </div>
            </div>
          )}

          {isHttp && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <label style={{ fontSize: 11, color: T.dim }}>URL *</label>
              <input value={url} onChange={(e) => setUrl(e.target.value)}
                placeholder={template.url_placeholder || 'https://...'}
                style={{ background: T.bg2, border: `1px solid ${T.border}`, color: T.text,
                  padding: '7px 10px', fontSize: 12, fontFamily: 'var(--code-font, monospace)', outline: 'none' }} />
            </div>
          )}

          {(template.string_prompts || []).map((sp) => (
            <div key={sp.ref} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <label style={{ fontSize: 11, color: T.dim }}>{sp.label} *</label>
              <input value={strings[sp.ref] || ''}
                onChange={(e) => setStrings((p) => ({ ...p, [sp.ref]: e.target.value }))}
                placeholder={sp.placeholder || ''}
                style={{ background: T.bg2, border: `1px solid ${T.border}`, color: T.text,
                  padding: '7px 10px', fontSize: 12, outline: 'none' }} />
              {sp.help_text && <span style={{ fontSize: 10, color: T.dim }}>{sp.help_text}</span>}
            </div>
          ))}

          {(template.secret_prompts || []).map((sec) => (
            <div key={sec.ref} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <label style={{ fontSize: 11, color: T.dim }}>{sec.label} *</label>
              <input type="password" value={secrets[sec.ref] || ''}
                onChange={(e) => setSecrets((p) => ({ ...p, [sec.ref]: e.target.value }))}
                placeholder={sec.placeholder || ''}
                style={{ background: T.bg2, border: `1px solid ${T.border}`, color: T.text,
                  padding: '7px 10px', fontSize: 12, fontFamily: 'var(--code-font, monospace)', outline: 'none' }} />
              {sec.help_text && (
                <span style={{ fontSize: 10, color: T.dim }}>
                  {sec.help_text}
                  {sec.help_url && <> <a href={sec.help_url} target="_blank" rel="noreferrer"
                    style={{ color: T.cyan, textDecoration: 'underline' }}>Open →</a></>}
                </span>
              )}
            </div>
          ))}

          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={{ fontSize: 11, color: T.dim }}>Timeout (seconds)</label>
            <input value={timeout} onChange={(e) => setTimeoutValue(e.target.value)}
              style={{ background: T.bg2, border: `1px solid ${T.border}`, color: T.text,
                padding: '7px 10px', fontSize: 12, outline: 'none', width: 100 }} />
          </div>

          {error && (
            <div style={{ fontSize: 11, color: T.red, padding: '8px 12px',
              border: `1px solid ${T.red}44`, background: `${T.red}0a` }}>{error}</div>
          )}
        </div>

        <div style={{ padding: '12px 18px', borderTop: `1px solid ${T.border}`,
          display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          <button onClick={onClose} disabled={busy} style={{
            background: 'transparent', border: `1px solid ${T.border}`, color: T.text,
            padding: '8px 16px', fontSize: 12, cursor: busy ? 'default' : 'pointer',
          }}>Cancel</button>
          {testFailedRowId ? (
            <>
              <button onClick={saveAnyway} disabled={busy} style={{
                background: 'transparent', border: `1px solid ${T.amber}66`, color: T.amber,
                padding: '8px 16px', fontSize: 12, cursor: busy ? 'default' : 'pointer',
              }}>Save anyway</button>
              <button onClick={retryTest} disabled={busy} style={{
                background: T.cyan, color: '#000', border: 'none',
                padding: '8px 22px', fontSize: 12, fontWeight: 600,
                cursor: busy ? 'default' : 'pointer', letterSpacing: '.04em',
              }}>{busy ? '…' : 'Retry test'}</button>
            </>
          ) : (
            <button onClick={submit} disabled={busy} style={{
              background: T.cyan, color: '#000', border: 'none',
              padding: '8px 22px', fontSize: 12, fontWeight: 600,
              cursor: busy ? 'default' : 'pointer', letterSpacing: '.04em',
            }}>{busy ? 'Working…' : 'Test & Save'}</button>
          )}
        </div>
      </div>
    </div>
  );
}
