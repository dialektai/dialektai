import { useEffect, useMemo, useRef, useState } from 'react';
import { T } from '../tokens.js';

const API = 'http://localhost:8765';

/**
 * Bulk import a JSON bundle exported via GET /mcp-servers/export.
 *
 * Paste-only: user copies the bundle from Export and pastes here.
 * (File upload deferred — paste covers the dominant clipboard-from-
 * Export flow; admins receiving a `.json` via email/Slack open in an
 * editor and paste. Reintroduce as a follow-up commit if pilots ask.)
 * Strict keystroke parse with debounced feedback (mentor ruling Q2):
 * bad JSON disables Confirm inline rather than waiting for a server
 * round-trip 422.
 *
 * Preview lists exact server names that WILL be imported and which
 * names will be SKIPPED due to existing collisions (mentor ruling Q3).
 *
 * Error contract: 422 from POST keeps modal open with inline error;
 * 200 closes + parent refreshes + parent's toast surfaces the count
 * of credentials still owed (mentor P2 — full secrets_needed list
 * doesn't fit a toast cleanly, per-server Edit form is the right
 * surface for filling them).
 */
export default function McpBulkImportModal({ existingNames, onClose, onImported }) {
  const [pasted, setPasted] = useState('');
  const [parsedBundle, setParsedBundle] = useState(null);
  const [parseError, setParseError] = useState('');
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState('');
  const debounceRef = useRef(null);

  // Debounced keystroke parse — show inline JSON errors without
  // bouncing off the server.
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      if (!pasted.trim()) {
        setParsedBundle(null);
        setParseError('');
        return;
      }
      try {
        const obj = JSON.parse(pasted);
        if (!obj || typeof obj !== 'object' || !Array.isArray(obj.servers)) {
          setParsedBundle(null);
          setParseError('JSON must be an object with a `servers` array.');
          return;
        }
        setParsedBundle(obj);
        setParseError('');
      } catch (e) {
        setParsedBundle(null);
        setParseError(`Bad JSON: ${e.message}`);
      }
    }, 250);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [pasted]);

  // Esc closes (configuration surface, not a permission gate).
  useEffect(() => {
    const onKey = (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose?.();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const willImport = useMemo(() => {
    if (!parsedBundle) return [];
    const set = new Set(existingNames || []);
    return (parsedBundle.servers || [])
      .map((s) => s?.name)
      .filter((n) => typeof n === 'string' && n && !set.has(n));
  }, [parsedBundle, existingNames]);

  const willSkip = useMemo(() => {
    if (!parsedBundle) return [];
    const set = new Set(existingNames || []);
    return (parsedBundle.servers || [])
      .map((s) => s?.name)
      .filter((n) => typeof n === 'string' && n && set.has(n));
  }, [parsedBundle, existingNames]);

  const submit = async () => {
    if (!parsedBundle) return;
    setBusy(true);
    setSubmitError('');
    try {
      const r = await fetch(`${API}/mcp-servers/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(parsedBundle),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        const detail = body?.detail || `HTTP ${r.status}`;
        setSubmitError(typeof detail === 'string' ? detail : JSON.stringify(detail));
        return;
      }
      onImported?.(body);
      onClose?.();
    } catch (e) {
      setSubmitError(`Import failed: ${String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const canSubmit = !!parsedBundle && !parseError && willImport.length > 0;

  return (
    <div role="dialog" aria-labelledby="bulk-title" style={{
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
          <div id="bulk-title" style={{ fontSize: 13, color: T.text, letterSpacing: '.04em', flex: 1 }}>
            Import MCP servers from JSON
          </div>
          <button onClick={onClose} aria-label="close" style={{
            background: 'transparent', border: 'none', color: T.dim,
            fontSize: 16, cursor: 'pointer', padding: '0 4px',
          }}>×</button>
        </div>

        <div style={{ padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ fontSize: 12, color: T.muted, lineHeight: 1.5 }}>
            Paste a bundle exported from another seat (Settings → MCP
            Servers → Export). Credentials are NOT included in exports
            — fill them in per server after import.
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={{ fontSize: 11, color: T.dim }}>Bundle JSON</label>
            <textarea value={pasted} onChange={(e) => setPasted(e.target.value)}
              rows={8} placeholder='{"version": 1, "servers": [...]}'
              style={{ background: T.bg2, border: `1px solid ${T.border}`, color: T.text,
                padding: '8px 10px', fontSize: 11, fontFamily: 'var(--code-font, monospace)',
                outline: 'none', resize: 'vertical' }} />
          </div>

          {parseError && (
            <div style={{ fontSize: 11, color: T.red, padding: '8px 12px',
              border: `1px solid ${T.red}44`, background: `${T.red}0a` }}>{parseError}</div>
          )}

          {parsedBundle && !parseError && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8,
              padding: '10px 12px', border: `1px solid ${T.border}`, background: T.bg2 }}>
              <div style={{ fontSize: 11, color: T.dim }}>
                Bundle version: <span className="mono" style={{ color: T.text }}>
                  {parsedBundle.version ?? '?'}
                </span>
                {parsedBundle.exported_at && (
                  <> · exported {parsedBundle.exported_at}</>
                )}
              </div>
              {willImport.length > 0 && (
                <div style={{ fontSize: 12, color: T.green }}>
                  Will import {willImport.length}: <span className="mono"
                    style={{ color: T.text }}>{willImport.join(', ')}</span>
                </div>
              )}
              {willSkip.length > 0 && (
                <div style={{ fontSize: 12, color: T.amber }}>
                  Will skip {willSkip.length} (already exists): <span className="mono"
                    style={{ color: T.muted }}>{willSkip.join(', ')}</span>
                </div>
              )}
              {willImport.length === 0 && willSkip.length === 0 && (
                <div style={{ fontSize: 12, color: T.dim }}>
                  Bundle parses but contains 0 servers.
                </div>
              )}
            </div>
          )}

          {submitError && (
            <div style={{ fontSize: 11, color: T.red, padding: '8px 12px',
              border: `1px solid ${T.red}44`, background: `${T.red}0a` }}>{submitError}</div>
          )}
        </div>

        <div style={{ padding: '12px 18px', borderTop: `1px solid ${T.border}`,
          display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button onClick={onClose} disabled={busy} style={{
            background: 'transparent', border: `1px solid ${T.border}`, color: T.text,
            padding: '8px 16px', fontSize: 12, cursor: busy ? 'default' : 'pointer',
          }}>Cancel</button>
          <button onClick={submit} disabled={busy || !canSubmit} style={{
            background: canSubmit ? T.cyan : T.bg2, color: canSubmit ? '#000' : T.dim,
            border: 'none', padding: '8px 22px', fontSize: 12, fontWeight: 600,
            cursor: busy || !canSubmit ? 'default' : 'pointer', letterSpacing: '.04em',
          }}>{busy ? 'Importing…' : 'Import'}</button>
        </div>
      </div>
    </div>
  );
}
