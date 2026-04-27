import { useEffect, useState } from 'react';
import { T } from '../../tokens.js';
import Icon from '../../components/Icon.jsx';

const API = 'http://localhost:8765';

// Per-provider help text — shown next to the API key field so the user
// knows where to get a key without leaving Settings. Keeping this in the
// component (vs a doc link buried elsewhere) was a deliberate call: the
// "Test" button is the moment of friction, not the moment of reading.
const PROVIDER_HELP = {
  tavily: {
    label: 'Tavily',
    docsUrl: 'https://tavily.com/',
    placeholder: 'tvly-...',
    blurb: 'Recommended. Designed for LLM agents — returns relevance scores out of the box.',
  },
  brave: {
    label: 'Brave Search',
    docsUrl: 'https://api.search.brave.com/',
    placeholder: 'BSA...',
    blurb: 'Independent index, useful as a diversity hedge. Free tier ~2k queries/month.',
  },
  duckduckgo: {
    label: 'DuckDuckGo',
    docsUrl: 'https://duckduckgo.com/',
    placeholder: null,
    blurb: 'No API key needed. HTML-Lite scrape — last-resort fallback, brittle by design.',
  },
};

const PROVIDER_ORDER = ['tavily', 'brave', 'duckduckgo'];

// ── Tiny shared primitives, kept local on purpose ─────────────────────────────
//
// Replicates the visual language of SettingsScreen.jsx (BodyShell / Card /
// Row) without depending on the 3263-line monolith — that file is currently
// being modified by parallel work, and reaching into it would invite merge
// conflicts. When the broader Settings extraction lands, these can collapse
// into a shared shell module.

function Shell({ children }) {
  return (
    <div className="dlk-scroll" style={{ flex: 1, overflowY: 'auto' }}>
      <div style={{ padding: '28px 36px 40px', maxWidth: 860 }}>
        <div className="mono" style={{
          fontSize: 10, color: T.cyan, letterSpacing: '.14em', marginBottom: 8,
        }}>02 / CAPABILITIES → WEB SEARCH</div>
        <div style={{
          fontSize: 22, fontWeight: 600, letterSpacing: '-0.02em', marginBottom: 8,
        }}>Web Search</div>
        <div style={{
          color: T.muted, fontSize: 13, lineHeight: 1.55, marginBottom: 24,
        }}>
          Configure how agents reach the web for current information. Pick a
          provider, save the API key in your OS keychain, and run a quick
          probe to confirm it's wired up.
        </div>
        {children}
      </div>
    </div>
  );
}

function Card({ title, n, right, children }) {
  return (
    <div style={{ border: `1px solid ${T.border}`, background: T.bg1, marginBottom: 16 }}>
      {title !== undefined && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10,
          padding: '10px 14px', borderBottom: `1px solid ${T.border}`,
        }}>
          {n && <span className="mono" style={{ color: T.cyan, fontSize: 10, letterSpacing: '.12em' }}>{n}</span>}
          <span style={{ fontSize: 13, fontWeight: 500 }}>{title}</span>
          <div style={{ flex: 1 }} />
          {right}
        </div>
      )}
      {children}
    </div>
  );
}

function StatusBadge({ ok, label }) {
  const color = ok ? T.green : T.dim;
  const bg = ok ? '#0c2a1f' : 'transparent';
  return (
    <span className="mono" style={{
      fontSize: 10, color, letterSpacing: '.08em',
      padding: '2px 8px', background: bg, border: `1px solid ${color}33`,
    }}>● {label}</span>
  );
}

// ── The section ───────────────────────────────────────────────────────────────

export default function WebSearchSection() {
  const [providers, setProviders] = useState(null);
  const [defaultProvider, setDefaultProvider] = useState('');
  const [keyDraft, setKeyDraft] = useState({});      // {tavily: 'tvly-...', brave: 'BSA-...'}
  const [busy, setBusy] = useState({});              // {tavily: 'saving' | 'testing'}
  const [results, setResults] = useState({});        // {tavily: {ok, error, result_count}}
  const [error, setError] = useState(null);

  const reload = async () => {
    try {
      const r = await fetch(`${API}/search/providers`);
      const data = await r.json();
      if (!data.ok) throw new Error('failed to load providers');
      setProviders(data.providers);
      setDefaultProvider(data.default || '');
    } catch (e) {
      setError(`Could not load providers: ${e.message}`);
    }
  };

  useEffect(() => { reload(); }, []);

  const setBusyFor = (name, label) =>
    setBusy(b => ({ ...b, [name]: label }));
  const clearBusyFor = (name) =>
    setBusy(b => { const { [name]: _, ...rest } = b; return rest; });

  const saveKey = async (name) => {
    const apiKey = keyDraft[name] ?? '';
    setBusyFor(name, 'saving');
    setResults(r => ({ ...r, [name]: null }));
    try {
      const r = await fetch(`${API}/search/providers/${name}/credentials`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: apiKey }),
      });
      const data = await r.json();
      if (!data.ok) throw new Error(data.error || 'save failed');
      setKeyDraft(d => ({ ...d, [name]: '' }));
      await reload();
    } catch (e) {
      setResults(r => ({ ...r, [name]: { ok: false, error: e.message } }));
    } finally {
      clearBusyFor(name);
    }
  };

  const clearKey = async (name) => {
    setBusyFor(name, 'clearing');
    try {
      await fetch(`${API}/search/providers/${name}/credentials`, { method: 'DELETE' });
      await reload();
    } finally {
      clearBusyFor(name);
    }
  };

  const testProvider = async (name) => {
    setBusyFor(name, 'testing');
    setResults(r => ({ ...r, [name]: null }));
    try {
      const r = await fetch(`${API}/search/providers/${name}/test`, { method: 'POST' });
      const data = await r.json();
      setResults(rs => ({ ...rs, [name]: data }));
    } catch (e) {
      setResults(rs => ({ ...rs, [name]: { ok: false, error: e.message } }));
    } finally {
      clearBusyFor(name);
    }
  };

  const saveDefault = async (name) => {
    setDefaultProvider(name);
    try {
      // Settings endpoint accepts an arbitrary subset.
      await fetch(`${API}/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ web_search_provider: name || null }),
      });
    } catch (e) {
      setError(`Could not save default: ${e.message}`);
    }
  };

  if (providers === null) {
    return (
      <Shell>
        <div style={{ color: T.dim, fontSize: 12 }}>Loading providers…</div>
      </Shell>
    );
  }

  const ordered = PROVIDER_ORDER
    .map(name => providers.find(p => p.name === name))
    .filter(Boolean);

  return (
    <Shell>
      {error && (
        <div style={{
          padding: '10px 14px', border: `1px solid ${T.red}55`, background: '#2a0c0c',
          color: T.red, fontSize: 12, marginBottom: 16,
        }}>{error}</div>
      )}

      <Card
        title="Default provider"
        n="A"
        right={defaultProvider && (
          <span className="mono" style={{ fontSize: 10, color: T.dim, letterSpacing: '.1em' }}>
            {defaultProvider.toUpperCase()}
          </span>
        )}
      >
        <div style={{ padding: '14px 14px', fontSize: 12, color: T.muted, lineHeight: 1.55 }}>
          When an agent calls <span className="mono" style={{ color: T.text }}>POST /search/web</span> without
          specifying a provider, dialekt routes to your default. Fallback order if the default isn't
          configured: <span className="mono" style={{ color: T.text }}>tavily → brave → duckduckgo</span>.
        </div>
        <div style={{ padding: '0 14px 14px', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {[{ name: '', label: '— auto —' }, ...PROVIDER_ORDER.map(n => ({
            name: n, label: PROVIDER_HELP[n].label,
          }))].map(opt => {
            const isActive = defaultProvider === opt.name;
            return (
              <button
                key={opt.name || 'auto'}
                onClick={() => saveDefault(opt.name)}
                style={{
                  padding: '6px 12px', fontSize: 12,
                  background: isActive ? T.cyan : 'transparent',
                  color: isActive ? '#000' : T.text,
                  border: `1px solid ${isActive ? T.cyan : T.border}`,
                  cursor: 'pointer', fontFamily: 'inherit',
                }}
              >{opt.label}</button>
            );
          })}
        </div>
      </Card>

      {ordered.map((p, idx) => {
        const help = PROVIDER_HELP[p.name];
        const result = results[p.name];
        const isBusy = !!busy[p.name];
        const draftValue = keyDraft[p.name] ?? '';
        return (
          <Card
            key={p.name}
            title={help.label}
            n={String.fromCharCode(66 + idx)}  // B, C, D, …
            right={
              <StatusBadge
                ok={p.configured}
                label={p.configured ? 'CONFIGURED' : (p.needs_api_key ? 'NO KEY' : 'READY')}
              />
            }
          >
            <div style={{ padding: '12px 14px', fontSize: 12, color: T.muted, lineHeight: 1.55 }}>
              {help.blurb}{' '}
              {help.docsUrl && (
                <a href={help.docsUrl} target="_blank" rel="noreferrer"
                  style={{ color: T.cyan, textDecoration: 'none' }}>
                  {help.docsUrl.replace(/^https?:\/\//, '')}
                </a>
              )}
            </div>

            {p.needs_api_key && (
              <div style={{
                padding: '12px 14px', borderTop: `1px solid ${T.border}`,
                display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap',
              }}>
                <input
                  type="password"
                  value={draftValue}
                  onChange={(e) => setKeyDraft(d => ({ ...d, [p.name]: e.target.value }))}
                  placeholder={p.configured ? '•••• key on file (replace to update)' : help.placeholder}
                  spellCheck={false}
                  style={{
                    flex: 1, minWidth: 240,
                    padding: '6px 10px', fontSize: 12,
                    background: T.bg2, color: T.text, border: `1px solid ${T.border}`,
                    fontFamily: 'inherit',
                  }}
                />
                <button
                  onClick={() => saveKey(p.name)}
                  disabled={isBusy || !draftValue}
                  style={{
                    padding: '6px 12px', fontSize: 12,
                    background: !draftValue ? 'transparent' : T.cyan,
                    color: !draftValue ? T.dim : '#000',
                    border: `1px solid ${!draftValue ? T.border : T.cyan}`,
                    cursor: !draftValue || isBusy ? 'default' : 'pointer',
                    opacity: isBusy ? 0.6 : 1,
                    fontFamily: 'inherit',
                  }}
                >{busy[p.name] === 'saving' ? 'Сохранение…' : 'Сохранить'}</button>
                {p.configured && (
                  <button
                    onClick={() => clearKey(p.name)}
                    disabled={isBusy}
                    style={{
                      padding: '6px 12px', fontSize: 12,
                      background: 'transparent', color: T.red,
                      border: `1px solid ${T.red}55`,
                      cursor: isBusy ? 'default' : 'pointer',
                      fontFamily: 'inherit',
                    }}
                  >Удалить</button>
                )}
              </div>
            )}

            <div style={{
              padding: '10px 14px', borderTop: `1px solid ${T.border}`,
              display: 'flex', alignItems: 'center', gap: 12,
            }}>
              <button
                onClick={() => testProvider(p.name)}
                disabled={isBusy || (p.needs_api_key && !p.configured)}
                style={{
                  padding: '6px 12px', fontSize: 12,
                  background: 'transparent', color: T.text,
                  border: `1px solid ${T.border}`,
                  cursor: (isBusy || (p.needs_api_key && !p.configured)) ? 'default' : 'pointer',
                  opacity: (p.needs_api_key && !p.configured) ? 0.5 : 1,
                  fontFamily: 'inherit',
                }}
              >
                {busy[p.name] === 'testing' ? 'Проверка…' : 'Проверить'}
              </button>
              {result && (
                <span style={{
                  fontSize: 12, color: result.ok ? T.green : T.red,
                  display: 'flex', alignItems: 'center', gap: 6,
                }}>
                  <Icon name={result.ok ? 'shield' : 'cross'} size={12}
                    color={result.ok ? T.green : T.red} />
                  {result.ok
                    ? `OK — ${result.result_count ?? 0} result(s)`
                    : (result.error || 'failed')}
                </span>
              )}
            </div>
          </Card>
        );
      })}
    </Shell>
  );
}
