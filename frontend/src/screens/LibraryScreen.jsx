import { useState, useEffect, useMemo } from 'react';
import { T } from '../tokens.js';
import { AppFrame } from '../components/Shell.jsx';
import LeftPanel from '../components/LeftPanel.jsx';

const API = 'http://localhost:8765';

const CATEGORY_LABELS = {
  'all': 'All',
  'data-analytics': 'Data analytics',
  'development': 'Development',
  'documents': 'Documents',
  'other': 'Other',
};

const CATEGORY_ICONS = {
  'data-analytics': '📊',
  'development': '⚙',
  'documents': '📄',
  'other': '🧩',
};

function CategoryChip({ active, label, count, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: '6px 14px',
        background: active ? T.cyan : 'transparent',
        color: active ? T.bg0 : T.muted,
        border: `1px solid ${active ? T.cyan : T.border}`,
        fontSize: 11,
        fontWeight: active ? 600 : 400,
        cursor: 'pointer',
        letterSpacing: '.04em',
        display: 'inline-flex',
        alignItems: 'center',
        gap: 8,
        transition: 'all .12s',
      }}
    >
      {label}
      {count != null && (
        <span className="mono" style={{ fontSize: 10, opacity: .7 }}>{count}</span>
      )}
    </button>
  );
}

function TemplateCard({ entry, installed, installing, onInstall, onCustomize }) {
  return (
    <div style={{
      border: `1px solid ${T.border}`,
      background: T.bg1,
      padding: 18,
      display: 'flex',
      flexDirection: 'column',
      gap: 10,
      transition: 'border-color .15s',
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
        <div style={{ fontSize: 22, lineHeight: 1 }}>{CATEGORY_ICONS[entry.category] || '🧩'}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: T.text, letterSpacing: '-0.01em' }}>
            {entry.name}
          </div>
          <div className="mono" style={{ fontSize: 10, color: T.dim, marginTop: 2, letterSpacing: '.06em' }}>
            {entry.id}
          </div>
        </div>
      </div>
      <div style={{ fontSize: 12, color: T.muted, lineHeight: 1.55, minHeight: 36 }}>
        {entry.description}
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <span className="mono" style={{
          fontSize: 9, color: T.cyan, border: `1px solid ${T.cyan}55`,
          padding: '2px 6px', letterSpacing: '.06em', textTransform: 'uppercase',
        }}>{CATEGORY_LABELS[entry.category] || entry.category}</span>
        {entry.requires_connection && (
          <span className="mono" style={{
            fontSize: 9, color: T.amber, border: `1px solid ${T.amber}55`,
            padding: '2px 6px', letterSpacing: '.06em', textTransform: 'uppercase',
          }}>needs DB</span>
        )}
        {entry.requires_mcp && (
          <span className="mono" style={{
            fontSize: 9, color: T.amber, border: `1px solid ${T.amber}55`,
            padding: '2px 6px', letterSpacing: '.06em', textTransform: 'uppercase',
          }}>needs MCP</span>
        )}
        {Array.isArray(entry.requires_secrets) && entry.requires_secrets.length > 0 && (
          <span
            className="mono"
            title={`Secrets: ${entry.requires_secrets.join(', ')}`}
            style={{
              fontSize: 9, color: T.amber, border: `1px solid ${T.amber}55`,
              padding: '2px 6px', letterSpacing: '.06em', textTransform: 'uppercase',
            }}
          >
            needs {entry.requires_secrets.length} secret{entry.requires_secrets.length === 1 ? '' : 's'}
          </span>
        )}
        {(entry.tags || []).slice(0, 3).map((t, i) => (
          <span key={i} className="mono" style={{
            fontSize: 9, color: T.dim, border: `1px solid ${T.border}`,
            padding: '2px 6px', letterSpacing: '.04em',
          }}>#{t}</span>
        ))}
      </div>
      <div style={{ flex: 1 }} />
      <div style={{ display: 'flex', gap: 6 }}>
        <button
          onClick={onInstall}
          disabled={installing}
          style={{
            padding: '8px 14px',
            background: installed ? 'transparent' : T.cyan,
            color: installed ? T.green : T.bg0,
            border: installed ? `1px solid ${T.green}` : 'none',
            fontSize: 12,
            fontWeight: 700,
            cursor: installing ? 'wait' : 'pointer',
            letterSpacing: '.06em',
            opacity: installing ? 0.6 : 1,
            flex: 1,
          }}
        >
          {installing ? 'Installing…' : installed ? '✓ Installed' : 'Install'}
        </button>
        <button
          onClick={onCustomize}
          disabled={installing}
          style={{
            padding: '8px 12px',
            background: 'transparent',
            color: T.muted,
            border: `1px solid ${T.border}`,
            fontSize: 11,
            fontWeight: 600,
            cursor: installing ? 'wait' : 'pointer',
            letterSpacing: '.06em',
            opacity: installing ? 0.6 : 1,
          }}
          title="Open this template in the wizard so you can edit name, prompt, and capabilities before saving."
        >
          Customize…
        </button>
      </div>
    </div>
  );
}

function ConnectionRequiredModal({ entry, onConfigure, onSkip, onClose }) {
  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
        backdropFilter: 'blur(4px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
      }}
    >
      <div onClick={e => e.stopPropagation()} style={{
        width: 480, background: T.bg1, border: `1px solid ${T.border}`, padding: 28,
      }}>
        <div className="mono" style={{ fontSize: 10, color: T.cyan, letterSpacing: '.14em', marginBottom: 10 }}>
          INSTALLED — NEXT STEP
        </div>
        <div style={{ fontSize: 18, fontWeight: 700, color: T.text, marginBottom: 8 }}>
          {entry.name} needs a database connection
        </div>
        <div style={{ fontSize: 13, color: T.muted, lineHeight: 1.6, marginBottom: 22 }}>
          The agent is installed in your workspace, but it can't run queries until you
          point it at a database connection. Configure one now, or come back later.
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button onClick={onConfigure} style={{
            padding: '10px 20px', background: T.cyan, color: T.bg0, border: 'none',
            fontSize: 13, fontWeight: 700, cursor: 'pointer', letterSpacing: '.04em',
          }}>CONFIGURE NOW →</button>
          <button onClick={onSkip} style={{
            padding: '10px 20px', background: 'transparent', color: T.muted,
            border: `1px solid ${T.border}`, fontSize: 12, cursor: 'pointer',
          }}>Later</button>
        </div>
      </div>
    </div>
  );
}

// Post-install modal that prompts the user to fill the per-agent
// secrets the manifest declares (Bitrix webhook URL, Instagram
// access token, etc.). Mirrors the ConnectionRequiredModal pattern
// so the experience stays consistent.
function SecretsRequiredModal({ entry, agentId, names, onSubmit, onSkip, onClose }) {
  const [values, setValues] = useState(() => Object.fromEntries(names.map(n => [n, ''])));
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState('');

  const handleSubmit = async () => {
    setSubmitting(true);
    setErr('');
    try {
      const filled = {};
      for (const [k, v] of Object.entries(values)) {
        if (v && v.trim()) filled[k] = v;
      }
      if (Object.keys(filled).length === 0) {
        setErr('Fill at least one secret or click Later.');
        setSubmitting(false);
        return;
      }
      const r = await fetch(`${API}/agents/${agentId}/secrets`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ secrets: filled }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        setErr(body.detail || body.error || `HTTP ${r.status}`);
        setSubmitting(false);
        return;
      }
      onSubmit && onSubmit();
    } catch (e) {
      setErr(e.message || 'Network error');
      setSubmitting(false);
    }
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
        backdropFilter: 'blur(4px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
      }}
    >
      <div onClick={e => e.stopPropagation()} style={{
        width: 520, background: T.bg1, border: `1px solid ${T.border}`, padding: 28,
      }}>
        <div className="mono" style={{ fontSize: 10, color: T.cyan, letterSpacing: '.14em', marginBottom: 10 }}>
          INSTALLED — NEXT STEP
        </div>
        <div style={{ fontSize: 18, fontWeight: 700, color: T.text, marginBottom: 8 }}>
          {entry.name} needs {names.length} secret{names.length === 1 ? '' : 's'}
        </div>
        <div style={{ fontSize: 13, color: T.muted, lineHeight: 1.6, marginBottom: 18 }}>
          Paste the credentials the agent's tools need. Values are stored in
          your OS keychain under <span className="mono" style={{ color: T.cyan }}>agent:{agentId}:&lt;name&gt;</span>{' '}
          — never in logs, audit rows, or the manifest.
        </div>
        {names.map(name => (
          <div key={name} style={{ marginBottom: 10 }}>
            <div className="mono" style={{ fontSize: 10, color: T.dim, marginBottom: 4, letterSpacing: '.06em' }}>
              {name}
            </div>
            <input
              type="password"
              value={values[name] || ''}
              onChange={e => setValues(v => ({ ...v, [name]: e.target.value }))}
              placeholder={name}
              style={{
                width: '100%', boxSizing: 'border-box',
                padding: '8px 10px',
                background: T.bg0, color: T.text,
                border: `1px solid ${T.border}`,
                fontFamily: T.mono, fontSize: 12,
              }}
            />
          </div>
        ))}
        {err ? (
          <div className="mono" style={{ fontSize: 11, color: T.red || '#f55', marginTop: 8 }}>
            {err}
          </div>
        ) : null}
        <div style={{ display: 'flex', gap: 10, marginTop: 18 }}>
          <button
            onClick={handleSubmit}
            disabled={submitting}
            style={{
              padding: '10px 20px', background: T.cyan, color: T.bg0, border: 'none',
              fontSize: 13, fontWeight: 700, cursor: submitting ? 'wait' : 'pointer',
              letterSpacing: '.04em', opacity: submitting ? 0.6 : 1,
            }}
          >
            {submitting ? 'SAVING…' : 'SAVE SECRETS →'}
          </button>
          <button onClick={onSkip} style={{
            padding: '10px 20px', background: 'transparent', color: T.muted,
            border: `1px solid ${T.border}`, fontSize: 12, cursor: 'pointer',
          }}>Later</button>
        </div>
      </div>
    </div>
  );
}

export default function LibraryScreen({ onNav }) {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [category, setCategory] = useState('all');
  const [search, setSearch] = useState('');
  const [installingId, setInstallingId] = useState(null);
  const [installedIds, setInstalledIds] = useState(() => new Set());
  const [pendingModal, setPendingModal] = useState(null); // { entry, agentId } when requires_connection
  const [pendingSecretsModal, setPendingSecretsModal] = useState(null); // { entry, agentId, names }
  const [toast, setToast] = useState(null);

  // Load both: cached library + already-installed agents (so cards can
  // show "✓ Installed" instead of letting the user install duplicates).
  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      // Background sync — best-effort, doesn't block the UI on cloud
      // failure. The list endpoint serves the local cache regardless.
      fetch(`${API}/library/sync`, { method: 'POST' }).catch(() => {});
      const [libR, agentsR] = await Promise.all([
        fetch(`${API}/library`),
        fetch(`${API}/agents`),
      ]);
      const lib = libR.ok ? await libR.json() : { entries: [] };
      const agents = agentsR.ok ? await agentsR.json() : [];
      setEntries(lib.entries || []);
      const installed = new Set();
      for (const a of agents) {
        if (a.source_template_id) installed.add(a.source_template_id);
      }
      setInstalledIds(installed);
    } catch (e) {
      setError('Could not load library. Check that the backend is running.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = useMemo(() => {
    let xs = entries;
    if (category !== 'all') xs = xs.filter(e => e.category === category);
    const q = search.trim().toLowerCase();
    if (q) {
      xs = xs.filter(e =>
        e.name.toLowerCase().includes(q)
        || e.description.toLowerCase().includes(q)
        || (e.tags || []).some(t => String(t).toLowerCase().includes(q))
      );
    }
    return xs;
  }, [entries, category, search]);

  const categoryCounts = useMemo(() => {
    const counts = { all: entries.length };
    for (const e of entries) counts[e.category] = (counts[e.category] || 0) + 1;
    return counts;
  }, [entries]);

  const categoriesPresent = useMemo(() => {
    const s = new Set(['all']);
    for (const e of entries) s.add(e.category);
    return Array.from(s);
  }, [entries]);

  const handleInstall = async (entry) => {
    setInstallingId(entry.id);
    try {
      const r = await fetch(`${API}/library/${encodeURIComponent(entry.id)}/install`, { method: 'POST' });
      if (!r.ok) {
        const text = await r.text();
        throw new Error(text || `HTTP ${r.status}`);
      }
      const data = await r.json();
      setInstalledIds(prev => new Set([...prev, entry.id]));
      const secretNames = Array.isArray(entry.requires_secrets) ? entry.requires_secrets : [];
      if (entry.requires_connection) {
        // Connection modal first; secrets modal chains afterwards.
        setPendingModal({
          entry, agentId: data.id,
          followUpSecrets: secretNames,
        });
      } else if (secretNames.length > 0) {
        setPendingSecretsModal({ entry, agentId: data.id, names: secretNames });
      } else {
        setToast(`Installed: ${entry.name}`);
        setTimeout(() => setToast(null), 3000);
      }
    } catch (e) {
      setToast(`Install failed: ${e.message}`);
      setTimeout(() => setToast(null), 4000);
    } finally {
      setInstallingId(null);
    }
  };

  return (
    <AppFrame title="dialekt — Library">
      <LeftPanel active={-1} running={false} model="" onNav={onNav} />
      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', background: T.bg0, minWidth: 0 }}>
        {/* Header */}
        <div style={{ padding: '32px 44px 16px', borderBottom: `1px solid ${T.border}` }}>
          <div className="mono" style={{ fontSize: 10, color: T.cyan, letterSpacing: '.14em', marginBottom: 6 }}>
            AGENT LIBRARY
          </div>
          <div style={{ fontSize: 26, fontWeight: 700, letterSpacing: '-0.02em', color: T.text, marginBottom: 6 }}>
            Pre-built templates, ready to install
          </div>
          <div style={{ fontSize: 13, color: T.muted, lineHeight: 1.55, maxWidth: 640 }}>
            Curated agents you can install with one click. Pick a template, configure
            its connection if needed, and start chatting — no manual builder required.
          </div>
        </div>

        {/* Filter strip */}
        <div style={{ padding: '16px 44px', display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {categoriesPresent.map(c => (
              <CategoryChip
                key={c}
                active={category === c}
                label={CATEGORY_LABELS[c] || c}
                count={categoryCounts[c] ?? 0}
                onClick={() => setCategory(c)}
              />
            ))}
          </div>
          <div style={{ flex: 1 }} />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="🔍  Search templates…"
            style={{
              width: 280,
              background: T.bg1, border: `1px solid ${T.border}`, color: T.text,
              padding: '8px 12px', fontSize: 12, outline: 'none',
            }}
          />
          <button onClick={refresh} title="Refresh from cloud"
            style={{
              padding: '8px 12px', background: 'transparent', color: T.muted,
              border: `1px solid ${T.border}`, fontSize: 11, cursor: 'pointer',
              letterSpacing: '.04em',
            }}>↻ Refresh</button>
        </div>

        {/* Body */}
        <div className="dlk-scroll" style={{ flex: 1, overflowY: 'auto', padding: '12px 44px 44px' }}>
          {loading ? (
            <div style={{ padding: '60px 0', textAlign: 'center', color: T.dim, fontSize: 13 }}>
              Loading library…
            </div>
          ) : error ? (
            <div style={{ padding: '60px 0', textAlign: 'center', color: T.amber, fontSize: 13 }}>
              {error}
            </div>
          ) : filtered.length === 0 ? (
            <div style={{ padding: '60px 0', textAlign: 'center', color: T.dim, fontSize: 13 }}>
              {entries.length === 0
                ? 'No templates cached yet. Click ↻ Refresh to pull from the catalog.'
                : 'No templates match this filter.'}
            </div>
          ) : (
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
              gap: 14,
            }}>
              {filtered.map(entry => (
                <TemplateCard
                  key={entry.id}
                  entry={entry}
                  installed={installedIds.has(entry.id)}
                  installing={installingId === entry.id}
                  onInstall={() => handleInstall(entry)}
                  onCustomize={() => onNav('wizard', { fromTemplate: entry.id })}
                />
              ))}
            </div>
          )}
        </div>

        {pendingModal && (
          <ConnectionRequiredModal
            entry={pendingModal.entry}
            onConfigure={() => {
              const followUp = pendingModal.followUpSecrets || [];
              const entry = pendingModal.entry;
              const agentId = pendingModal.agentId;
              setPendingModal(null);
              if (followUp.length > 0) {
                setPendingSecretsModal({ entry, agentId, names: followUp });
              } else {
                onNav?.('settings', { initialSection: 'Connections' });
              }
            }}
            onSkip={() => {
              const followUp = pendingModal.followUpSecrets || [];
              const entry = pendingModal.entry;
              const agentId = pendingModal.agentId;
              setPendingModal(null);
              if (followUp.length > 0) {
                setPendingSecretsModal({ entry, agentId, names: followUp });
              } else {
                setToast(`Installed: ${entry.name}. Configure a connection later in Settings.`);
                setTimeout(() => setToast(null), 4000);
              }
            }}
            onClose={() => setPendingModal(null)}
          />
        )}

        {pendingSecretsModal && (
          <SecretsRequiredModal
            entry={pendingSecretsModal.entry}
            agentId={pendingSecretsModal.agentId}
            names={pendingSecretsModal.names}
            onSubmit={() => {
              const name = pendingSecretsModal.entry.name;
              setPendingSecretsModal(null);
              setToast(`Installed: ${name}. Secrets saved to keychain.`);
              setTimeout(() => setToast(null), 3000);
            }}
            onSkip={() => {
              const name = pendingSecretsModal.entry.name;
              setPendingSecretsModal(null);
              setToast(`Installed: ${name}. Fill secrets later in Settings → Agents.`);
              setTimeout(() => setToast(null), 4000);
            }}
            onClose={() => setPendingSecretsModal(null)}
          />
        )}

        {toast && (
          <div style={{
            position: 'fixed', bottom: 24, right: 24, zIndex: 999,
            background: T.bg2, border: `1px solid ${T.cyan}`, color: T.text,
            padding: '10px 16px', fontSize: 12,
          }}>{toast}</div>
        )}
      </main>
    </AppFrame>
  );
}
