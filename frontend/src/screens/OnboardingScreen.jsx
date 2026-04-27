import { useState, useEffect, useMemo, useRef } from 'react';
import { T } from '../tokens.js';
import { AppFrame, Logo } from '../components/Shell.jsx';

const API = 'http://localhost:8765';

const STEPS = [
  { n: '01', t: 'License & privacy', done: true },
  { n: '02', t: 'Choose your model', active: true },
  { n: '03', t: 'Grant permissions' },
  { n: '04', t: 'Index your workspace' },
  { n: '05', t: 'First conversation' },
];

const OLLAMA_CATEGORIES = [
  { id: 'all', label: 'All' },
  { id: 'general', label: 'General' },
  { id: 'reasoning', label: 'Reasoning' },
  { id: 'coding', label: 'Coding' },
  { id: 'vision', label: 'Vision' },
  { id: 'embedding', label: 'Embeddings' },
  { id: 'lightweight', label: 'Lightweight' },
  { id: 'frontier', label: 'Frontier' },
];

// ── Helpers ─────────────────────────────────────────────────────────────────

function ollamaFamily(tag) {
  if (!tag) return '';
  const head = tag.split(':')[0];
  const rest = tag.split(':')[1] || '';
  const size = rest.split('-')[0];
  return size ? `${head}:${size}` : head;
}

function modelIsInstalled(model, installedTags) {
  if (!installedTags || installedTags.size === 0) return false;
  const targetSize = (model.tag || '').split('-')[0];
  const wantedFamily = `${model.name}:${targetSize}`;
  for (const t of installedTags) {
    if (ollamaFamily(t) === wantedFamily) return true;
    if (t === `${model.name}:latest` && !targetSize) return true;
  }
  return false;
}

function modelFits(model, ramGB) {
  if (ramGB == null) return null;
  return model.ram_gb <= ramGB;
}

function Row({ k, v }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
      <span style={{ color: T.dim, letterSpacing: '.08em' }}>{k}</span>
      <span style={{ color: T.text }}>{v}</span>
    </div>
  );
}

function Spec({ k, v, last }) {
  return (
    <div style={{ padding: '8px 10px', borderRight: last ? 'none' : `1px solid ${T.border}` }}>
      <div className="upper" style={{ color: T.dim, fontSize: 9 }}>{k}</div>
      <div className="mono" style={{ fontSize: 11, color: T.text, marginTop: 2 }}>{v}</div>
    </div>
  );
}

function Chip({ active, onClick, children, count }) {
  return (
    <div
      onClick={onClick}
      style={{
        padding: '6px 12px', fontSize: 11, fontWeight: active ? 600 : 400,
        color: active ? T.bg0 : T.muted,
        background: active ? T.cyan : 'transparent',
        border: `1px solid ${active ? T.cyan : T.border}`,
        display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer',
        transition: 'all .12s',
      }}
    >
      {children}
      {count != null && (
        <span className="mono" style={{ fontSize: 9, opacity: .7 }}>{count}</span>
      )}
    </div>
  );
}

// ── Ollama model card ──────────────────────────────────────────────────────

function OllamaModelCard({ rank, model, ramTotalGB, installed, fits, selected, onClick }) {
  const tooBig = fits === false;
  const shortBy = tooBig ? model.ram_gb - (ramTotalGB || 0) : 0;
  const shortName = (model.tag || '').split('-')[0];
  return (
    <div
      onClick={tooBig ? undefined : onClick}
      style={{
        border: `1px solid ${selected ? T.cyan : T.border}`,
        background: selected ? T.bg2 : T.bg1,
        padding: 16, position: 'relative',
        opacity: tooBig ? 0.55 : 1,
        cursor: tooBig ? 'not-allowed' : 'pointer',
        transition: 'border-color .15s, background .15s',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 6 }}>
        <span className="mono" style={{ fontSize: 10, color: selected ? T.cyan : T.dim, letterSpacing: '.14em' }}>{rank}</span>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <span className="mono" style={{ fontSize: 15, fontWeight: 600, color: T.text, letterSpacing: '-0.01em' }}>{model.name}</span>
            <span className="mono" style={{ fontSize: 11, color: T.muted }}>:{shortName}</span>
          </div>
          <div className="mono" style={{ fontSize: 10, color: T.dim, marginTop: 2, letterSpacing: '.04em' }}>{model.vendor}</div>
        </div>
        {installed && (
          <span className="mono" style={{ fontSize: 9, color: T.green, border: `1px solid ${T.green}`, padding: '2px 6px', letterSpacing: '.08em', textTransform: 'uppercase' }}>
            ✓ Installed
          </span>
        )}
        {selected && !installed && (
          <span className="mono" style={{ fontSize: 9, color: T.cyan, letterSpacing: '.1em', display: 'flex', alignItems: 'center', gap: 4 }}>
            <div style={{ width: 8, height: 8, background: T.cyan, transform: 'rotate(45deg)' }} />
            SELECTED
          </span>
        )}
      </div>

      <div style={{ fontSize: 12, color: T.muted, lineHeight: 1.55, marginTop: 6, marginBottom: 12 }}>{model.blurb}</div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', borderTop: `1px solid ${T.border}`, borderBottom: `1px solid ${T.border}` }}>
        <Spec k="Size" v={`${model.size_gb} GB`} />
        <Spec k="Ctx" v={model.ctx} />
        <Spec k="RAM" v={`${model.ram_gb} GB`} last />
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 12, flexWrap: 'wrap' }}>
        {(model.categories || []).slice(0, 3).map((t, i) => (
          <span key={i} className="mono" style={{ fontSize: 9, color: T.muted, border: `1px solid ${T.border}`, padding: '2px 5px', letterSpacing: '.06em', textTransform: 'uppercase' }}>{t}</span>
        ))}
        <div style={{ flex: 1 }} />
        {tooBig ? (
          <span className="mono" style={{ fontSize: 10, color: T.amber, display: 'flex', alignItems: 'center', gap: 4 }}>
            <span className="dlk-dot amber" /> needs +{shortBy} GB RAM
          </span>
        ) : fits === null ? (
          <span className="mono" style={{ fontSize: 10, color: T.dim }}>RAM check unavailable</span>
        ) : (
          <span className="mono" style={{ fontSize: 10, color: T.green, display: 'flex', alignItems: 'center', gap: 4 }}>
            <span className="dlk-dot" /> good fit
          </span>
        )}
      </div>
    </div>
  );
}

// ── Cloud provider card ─────────────────────────────────────────────────────

function ProviderCard({ provider, configured, selected, onClick }) {
  return (
    <div
      onClick={onClick}
      style={{
        border: `1px solid ${selected ? T.cyan : T.border}`,
        background: selected ? T.bg2 : T.bg1,
        padding: 16, cursor: 'pointer', position: 'relative',
        transition: 'border-color .15s, background .15s',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: 14, fontWeight: 700, color: T.text, letterSpacing: '-0.01em', flex: 1 }}>
          {provider.name}
        </span>
        {configured ? (
          <span className="mono" style={{ fontSize: 9, color: T.green, border: `1px solid ${T.green}`, padding: '2px 6px', letterSpacing: '.08em' }}>
            ✓ CONFIGURED
          </span>
        ) : (
          <span className="mono" style={{ fontSize: 9, color: T.dim, border: `1px solid ${T.border}`, padding: '2px 6px', letterSpacing: '.08em' }}>
            NEEDS KEY
          </span>
        )}
      </div>
      <div style={{ fontSize: 12, color: T.muted, lineHeight: 1.55, marginBottom: 10, minHeight: 36 }}>
        {provider.blurb}
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {provider.free_tier && (
          <span className="mono" style={{ fontSize: 9, color: T.cyan, border: `1px solid ${T.cyan}55`, padding: '2px 5px', letterSpacing: '.06em' }}>FREE TIER</span>
        )}
        {provider.requires_org && (
          <span className="mono" style={{ fontSize: 9, color: T.amber, border: `1px solid ${T.amber}55`, padding: '2px 5px', letterSpacing: '.06em' }}>ENTERPRISE</span>
        )}
        <span className="mono" style={{ fontSize: 9, color: T.dim, border: `1px solid ${T.border}`, padding: '2px 5px', letterSpacing: '.06em' }}>
          {provider.auth_kind.replace('_', ' ')}
        </span>
      </div>
    </div>
  );
}

// ── Credentials modal ───────────────────────────────────────────────────────

function CredentialsModal({ provider, onClose, onSaved }) {
  const [fields, setFields] = useState({});
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [saving, setSaving] = useState(false);
  const [docsHover, setDocsHover] = useState(false);

  if (!provider) return null;

  const fieldLabel = (f) => ({
    api_key: 'API Key',
    organization: 'Organization (optional)',
    endpoint: 'Endpoint URL',
    api_version: 'API version',
    deployment: 'Deployment name',
    access_key_id: 'AWS Access Key ID',
    secret_access_key: 'AWS Secret Access Key',
    region: 'AWS region',
    session_token: 'AWS session token (optional)',
    service_account_json: 'Service account JSON',
    project_id: 'GCP Project ID',
    location: 'GCP location',
  }[f] || f);

  const isOptional = (f) => ['organization', 'session_token', 'api_version'].includes(f);
  const isLong = (f) => f === 'service_account_json';

  const allRequired = provider.auth_fields
    .filter(f => !isOptional(f))
    .every(f => (fields[f] || '').trim().length > 0);

  const save = async () => {
    setSaving(true);
    try {
      const r = await fetch(`${API}/llm/providers/${provider.id}/credentials`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(fields),
      });
      const d = await r.json();
      if (d.ok) {
        onSaved && onSaved();
        onClose && onClose();
      }
    } finally { setSaving(false); }
  };

  const test = async () => {
    setTesting(true); setTestResult(null);
    try {
      // Save first so the test endpoint can read from keychain
      await fetch(`${API}/llm/providers/${provider.id}/credentials`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(fields),
      });
      const r = await fetch(`${API}/llm/providers/${provider.id}/test`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const d = await r.json();
      setTestResult(d);
    } catch (e) {
      setTestResult({ ok: false, error: String(e) });
    } finally { setTesting(false); }
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
    }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{
        width: 540, maxHeight: '90vh', overflowY: 'auto',
        background: T.bg1, border: `1px solid ${T.border}`,
      }}>
        <div style={{ padding: '20px 24px', borderBottom: `1px solid ${T.border}`, display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 18, fontWeight: 700, letterSpacing: '-0.01em', color: T.text }}>
              {provider.name}
            </div>
            <div className="mono" style={{ fontSize: 10, color: T.dim, letterSpacing: '.1em', marginTop: 2 }}>
              CREDENTIALS · {provider.auth_kind.toUpperCase().replace('_', ' ')}
            </div>
          </div>
          <a href={provider.docs_url} target="_blank" rel="noreferrer"
             onMouseEnter={() => setDocsHover(true)} onMouseLeave={() => setDocsHover(false)}
             style={{ fontSize: 11, color: docsHover ? T.cyan : T.muted, textDecoration: 'none', borderBottom: `1px solid ${docsHover ? T.cyan : T.border}`, paddingBottom: 1 }}>
            Get API key →
          </a>
        </div>

        <div style={{ padding: '20px 24px' }}>
          <div style={{ background: T.bg0, border: `1px solid ${T.border}`, padding: 12, marginBottom: 16, fontSize: 11, color: T.muted, lineHeight: 1.55 }}>
            <span className="mono" style={{ fontSize: 9, color: T.amber, letterSpacing: '.1em' }}>PRIVACY · </span>
            {provider.privacy_note}
          </div>

          {provider.auth_fields.map((f) => (
            <div key={f} style={{ marginBottom: 14 }}>
              <label style={{ fontSize: 11, letterSpacing: '.08em', color: T.dim, display: 'block', marginBottom: 6 }}>
                {fieldLabel(f).toUpperCase()}{isOptional(f) && <span style={{ color: T.dim }}> (optional)</span>}
              </label>
              {isLong(f) ? (
                <textarea
                  value={fields[f] || ''}
                  onChange={e => setFields({ ...fields, [f]: e.target.value })}
                  placeholder={f === 'service_account_json' ? '{ "type": "service_account", ... }' : ''}
                  rows={5}
                  style={{
                    width: '100%', boxSizing: 'border-box',
                    background: T.bg0, border: `1px solid ${T.border}`, color: T.text,
                    padding: '8px 10px', fontSize: 11, fontFamily: T.mono, outline: 'none', resize: 'vertical',
                  }}
                />
              ) : (
                <input
                  type={f === 'api_key' || f === 'secret_access_key' ? 'password' : 'text'}
                  value={fields[f] || ''}
                  onChange={e => setFields({ ...fields, [f]: e.target.value })}
                  placeholder={
                    f === 'api_key' ? 'sk-…' :
                    f === 'region' ? 'us-east-1' :
                    f === 'location' ? 'us-central1' :
                    f === 'endpoint' ? 'https://your-resource.openai.azure.com/' :
                    f === 'api_version' ? '2024-10-21' :
                    ''
                  }
                  style={{
                    width: '100%', boxSizing: 'border-box',
                    background: T.bg0, border: `1px solid ${T.border}`, color: T.text,
                    padding: '8px 10px', fontSize: 12, fontFamily: T.mono, outline: 'none',
                  }}
                />
              )}
            </div>
          ))}

          {testResult && (
            <div style={{
              padding: '10px 12px', marginBottom: 12,
              border: `1px solid ${testResult.ok ? T.green : T.red}`,
              color: testResult.ok ? T.green : T.red, fontSize: 11,
            }}>
              {testResult.ok
                ? `✓ Connection OK · ${testResult.latency_ms}ms · ${testResult.model}`
                : `✗ ${testResult.error}`}
            </div>
          )}

          <div style={{ display: 'flex', gap: 10, marginTop: 8 }}>
            <button onClick={onClose}
              style={{ padding: '9px 18px', background: 'none', border: `1px solid ${T.border}`, color: T.muted, fontSize: 12, cursor: 'pointer' }}>
              Cancel
            </button>
            <button onClick={test} disabled={!allRequired || testing}
              style={{
                padding: '9px 18px', background: T.bg2, border: `1px solid ${T.border}`,
                color: allRequired ? T.text : T.dim, fontSize: 12,
                cursor: !allRequired || testing ? 'not-allowed' : 'pointer',
              }}>
              {testing ? 'Testing…' : 'Test connection'}
            </button>
            <div style={{ flex: 1 }} />
            <button onClick={save} disabled={!allRequired || saving}
              style={{
                padding: '9px 22px', background: allRequired ? T.cyan : T.bg2,
                color: allRequired ? T.bg0 : T.dim, border: 'none', fontSize: 12, fontWeight: 700, letterSpacing: '.06em',
                cursor: !allRequired || saving ? 'not-allowed' : 'pointer',
              }}>
              {saving ? 'SAVING…' : 'SAVE & USE'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Provider model picker (after credentials) ──────────────────────────────

function ProviderModelPicker({ provider, models, selectedModel, onSelect }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {models.map(m => {
        const active = m.id === selectedModel;
        return (
          <div key={m.id} onClick={() => onSelect(m.id)}
            style={{
              border: `1px solid ${active ? T.cyan : T.border}`,
              background: active ? T.bg2 : T.bg1,
              padding: '12px 14px', cursor: 'pointer',
              display: 'flex', alignItems: 'center', gap: 12,
            }}>
            <div style={{ flex: 1 }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: T.text }}>{m.label}</span>
                <span className="mono" style={{ fontSize: 10, color: T.dim }}>{m.id}</span>
              </div>
              <div style={{ fontSize: 11, color: T.muted, marginTop: 3 }}>{m.blurb}</div>
            </div>
            <span className="mono" style={{ fontSize: 10, color: T.dim }}>ctx {m.ctx}</span>
            {active && <span style={{ width: 8, height: 8, background: T.cyan, borderRadius: '50%' }} />}
          </div>
        );
      })}
    </div>
  );
}

// ── Main screen ─────────────────────────────────────────────────────────────

export default function OnboardingScreen({ onNav }) {
  const [tab, setTab] = useState('local'); // local | cloud
  const [catalog, setCatalog] = useState({ ollama: [], providers: [], regulated_mode: false });
  const [providersStatus, setProvidersStatus] = useState([]); // [{ id, configured }]
  const [installedTags, setInstalledTags] = useState(() => new Set());
  const [ollamaReachable, setOllamaReachable] = useState(null); // null=unknown, true/false once /ollama/tags answers
  const [ramTotalGB, setRamTotalGB] = useState(null);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('all');
  const [selectedOllama, setSelectedOllama] = useState(null); // "name:tag"
  const [selectedProvider, setSelectedProvider] = useState(null); // provider id
  const [selectedProviderModel, setSelectedProviderModel] = useState(null);
  const [credModalProvider, setCredModalProvider] = useState(null);
  const [saving, setSaving] = useState(false);
  const [catalogLoaded, setCatalogLoaded] = useState(false);

  // ── Fetch catalog + system state on mount ────────────────────────────────
  // BackendBootGate already waited for /health, but the catalog endpoint can
  // still race with later sidecar warm-up steps (LLM provider registry init
  // runs after /health goes green). Retry until we get a non-empty ollama
  // catalog or the user gives up — the previous one-shot fetch left the
  // Continue button permanently disabled when the catalog came back empty.
  useEffect(() => {
    let cancelled = false;
    let timer = null;
    let attempts = 0;
    const tick = () => {
      attempts++;
      Promise.allSettled([
        fetch(`${API}/llm/catalog`).then(r => r.json()),
        fetch(`${API}/llm/providers`).then(r => r.json()),
        fetch(`${API}/ollama/tags`).then(r => r.ok ? r.json() : { models: [], reachable: false }),
        fetch(`${API}/system`).then(r => r.ok ? r.json() : null),
      ]).then(([cat, prov, tags, sys]) => {
        if (cancelled) return;
        const catOk = cat.status === 'fulfilled' && (cat.value?.ollama?.length > 0 || cat.value?.providers?.length > 0);
        if (catOk) { setCatalog(cat.value); setCatalogLoaded(true); }
        if (prov.status === 'fulfilled') setProvidersStatus(prov.value?.providers || []);
        if (tags.status === 'fulfilled') {
          setInstalledTags(new Set((tags.value?.models || []).map(m => m.name)));
          setOllamaReachable(tags.value?.reachable === true);
        }
        if (sys.status === 'fulfilled' && sys.value && typeof sys.value.ram_total_gb === 'number') {
          setRamTotalGB(sys.value.ram_total_gb);
        }
        // Mark catalog loaded even if empty on final attempt
        if (!catOk && attempts >= 20) setCatalogLoaded(true);
        // Re-poll until catalog populated, capped at 20 attempts (~30s wall).
        if (!catOk && attempts < 20) timer = setTimeout(tick, 1500);
      });
    };
    tick();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, []);

  const reloadProviders = () => {
    fetch(`${API}/llm/providers`).then(r => r.json()).then(d => {
      setProvidersStatus(d.providers || []);
    }).catch(() => {});
  };

  // ── Filter Ollama models ────────────────────────────────────────────────
  const ollamaAnnotated = useMemo(() => (catalog.ollama || []).map(m => ({
    model: m,
    installed: modelIsInstalled(m, installedTags),
    fits: modelFits(m, ramTotalGB),
  })), [catalog.ollama, installedTags, ramTotalGB]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return ollamaAnnotated.filter(({ model }) => {
      if (category !== 'all' && !(model.categories || []).includes(category)) return false;
      if (q) {
        const blob = `${model.name} ${model.tag} ${model.vendor} ${model.blurb}`.toLowerCase();
        if (!blob.includes(q)) return false;
      }
      return true;
    });
  }, [ollamaAnnotated, search, category]);

  const sorted = useMemo(() => {
    const rank = (e) => {
      if (e.installed && e.fits !== false) return 0;
      if (e.fits === true) return 1;
      if (e.fits === null) return 2;
      return 3;
    };
    return [...filtered].sort((a, b) => rank(a) - rank(b));
  }, [filtered]);

  const categoryCounts = useMemo(() => {
    const counts = { all: ollamaAnnotated.length };
    for (const cat of OLLAMA_CATEGORIES) {
      if (cat.id === 'all') continue;
      counts[cat.id] = ollamaAnnotated.filter(e => (e.model.categories || []).includes(cat.id)).length;
    }
    return counts;
  }, [ollamaAnnotated]);

  // ── Default selection ───────────────────────────────────────────────────
  useEffect(() => {
    if (selectedOllama) return;
    if (sorted.length === 0) return;
    const pick = sorted.find(e => e.installed && e.fits !== false)
      || sorted.find(e => e.fits === true)
      || sorted.find(e => e.fits === null)
      || sorted[0];
    if (pick) setSelectedOllama(`${pick.model.name}:${pick.model.tag}`);
  }, [sorted, selectedOllama]);

  // ── Continue handler ────────────────────────────────────────────────────
  const handleContinue = async () => {
    if (saving) return;
    if (tab === 'local') {
      if (!selectedOllama) return;
      const [name, ...rest] = selectedOllama.split(':');
      const tag = rest.join(':');
      const entry = ollamaAnnotated.find(e => `${e.model.name}:${e.model.tag}` === selectedOllama);
      setSaving(true);
      // Save provider+model to settings
      await fetch(`${API}/settings`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_provider: 'ollama', model: `${name}:${tag.split('-')[0]}` }),
      }).catch(() => {});
      if (entry?.installed) {
        onNav('onboarding-step4');
      } else {
        onNav('download', {
          model: selectedOllama,
          onComplete: () => onNav('onboarding-step4'),
        });
      }
    } else {
      if (!selectedProvider || !selectedProviderModel) return;
      setSaving(true);
      await fetch(`${API}/settings`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_provider: selectedProvider, model: selectedProviderModel }),
      }).catch(() => {});
      onNav('onboarding-step4');
    }
  };

  // ── Render ──────────────────────────────────────────────────────────────
  const compatibleCount = ollamaAnnotated.filter(e => e.fits !== false).length;
  const cloudHidden = catalog.regulated_mode === true;
  const activeProvider = selectedProvider ? (catalog.providers || []).find(p => p.id === selectedProvider) : null;
  const activeProviderConfigured = activeProvider
    ? (providersStatus.find(p => p.id === activeProvider.id)?.configured)
    : false;

  return (
    <AppFrame title="dias.now — welcome">
      <div style={{ flex: 1, display: 'flex', background: T.bg0, minWidth: 0 }}>
        {/* Left rail */}
        <div style={{ width: 320, background: T.bg1, borderRight: `1px solid ${T.border}`, padding: '36px 32px', display: 'flex', flexDirection: 'column', flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 40 }}>
            <Logo />
            <div>
              <div style={{ fontSize: 15, fontWeight: 600 }}>dialekt<span style={{ color: T.cyan }}>.ai</span></div>
              <div className="mono" style={{ fontSize: 10, color: T.dim, letterSpacing: '.1em' }}>LOCAL-FIRST · v0.9.0</div>
            </div>
          </div>

          <div style={{ marginBottom: 32 }}>
            <div className="mono" style={{ fontSize: 10, color: T.cyan, letterSpacing: '.14em', marginBottom: 10 }}>02 / 05</div>
            <div style={{ fontSize: 26, fontWeight: 600, letterSpacing: '-0.02em', lineHeight: 1.15, marginBottom: 10 }}>
              Pick a model<br />to power <span style={{ color: T.cyan }}>your agents.</span>
            </div>
            <div style={{ fontSize: 13, color: T.muted, lineHeight: 1.55 }}>
              Run locally via Ollama, or connect any cloud provider. Switch anytime.
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {STEPS.map((s, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', color: s.active ? T.text : s.done ? T.muted : T.dim }}>
                <span className="mono" style={{ fontSize: 10, color: s.active ? T.cyan : s.done ? T.green : T.dim, width: 22 }}>{s.done ? '✓' : s.n}</span>
                <span style={{ fontSize: 12, fontWeight: s.active ? 500 : 400 }}>{s.t}</span>
                {s.active && <div style={{ flex: 1, height: 1, marginLeft: 6, background: `linear-gradient(90deg, ${T.cyan}, transparent)` }} />}
              </div>
            ))}
          </div>

          <div style={{ flex: 1 }} />

          <div style={{ marginTop: 24, padding: 12, border: `1px solid ${T.border}`, background: T.bg0 }}>
            <div className="upper" style={{ color: T.dim, marginBottom: 8 }}>Your machine</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }} className="mono">
              <Row k="RAM"  v={ramTotalGB ? `${ramTotalGB} GB` : '—'} />
              <Row k="OLLAMA" v={
                installedTags.size > 0
                  ? `${installedTags.size} models`
                  : ollamaReachable === true
                    ? 'running · 0 models'
                    : ollamaReachable === false
                      ? 'not running'
                      : '—'
              } />
            </div>
            {tab === 'local' && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 10, fontSize: 10 }}>
                <span className="dlk-dot cyan live" />
                <span className="mono" style={{ color: T.cyan, letterSpacing: '.08em' }}>
                  {ramTotalGB == null ? 'RAM check unavailable' : `${compatibleCount} models fit`}
                </span>
              </div>
            )}
          </div>
        </div>

        {/* Right — picker */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          {/* Tabs */}
          <div style={{ display: 'flex', borderBottom: `1px solid ${T.border}`, padding: '0 44px' }}>
            <TabBtn active={tab === 'local'} onClick={() => setTab('local')}
              label="Local · Ollama" count={(catalog.ollama || []).length} />
            <TabBtn active={tab === 'cloud'} disabled={cloudHidden} onClick={() => !cloudHidden && setTab('cloud')}
              label={cloudHidden ? 'Cloud (disabled — regulated mode)' : 'Cloud · Providers'}
              count={cloudHidden ? null : (catalog.providers || []).length} />
            <div style={{ flex: 1 }} />
          </div>

          {/* Content */}
          <div style={{ flex: 1, overflowY: 'auto', padding: '28px 44px' }}>
            {tab === 'local' ? (
              <LocalTab
                sorted={sorted}
                ramTotalGB={ramTotalGB}
                selected={selectedOllama}
                onSelect={setSelectedOllama}
                search={search} setSearch={setSearch}
                category={category} setCategory={setCategory}
                categoryCounts={categoryCounts}
              />
            ) : (
              <CloudTab
                providers={catalog.providers || []}
                catalogLoaded={catalogLoaded}
                providersStatus={providersStatus}
                selectedProvider={selectedProvider}
                onSelectProvider={setSelectedProvider}
                selectedProviderModel={selectedProviderModel}
                onSelectModel={setSelectedProviderModel}
                onOpenCredentials={setCredModalProvider}
              />
            )}
          </div>

          {/* Sticky footer */}
          <Footer
            tab={tab}
            selectedOllama={selectedOllama}
            ollamaAnnotated={ollamaAnnotated}
            selectedProvider={activeProvider}
            selectedProviderModel={selectedProviderModel}
            providerConfigured={activeProviderConfigured}
            saving={saving}
            onContinue={handleContinue}
            onConfigure={() => setCredModalProvider(activeProvider)}
            onBack={() => onNav('mode-setup')}
            onSkip={() => onNav('onboarding-step4')}
          />
        </div>
      </div>

      {credModalProvider && (
        <CredentialsModal
          provider={credModalProvider}
          onClose={() => setCredModalProvider(null)}
          onSaved={reloadProviders}
        />
      )}
    </AppFrame>
  );
}

function TabBtn({ active, disabled, onClick, label, count }) {
  return (
    <div onClick={disabled ? undefined : onClick}
      style={{
        padding: '14px 20px', cursor: disabled ? 'not-allowed' : 'pointer',
        borderBottom: `2px solid ${active ? T.cyan : 'transparent'}`,
        color: disabled ? T.dim : active ? T.text : T.muted,
        fontSize: 13, fontWeight: active ? 600 : 400, letterSpacing: '-0.01em',
        display: 'flex', alignItems: 'center', gap: 8,
        opacity: disabled ? 0.5 : 1,
      }}>
      {label}
      {count != null && (
        <span className="mono" style={{ fontSize: 10, color: T.dim }}>{count}</span>
      )}
    </div>
  );
}

function LocalTab({ sorted, ramTotalGB, selected, onSelect, search, setSearch, category, setCategory, categoryCounts }) {
  return (
    <>
      {/* Search + filters */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginBottom: 18 }}>
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search models — qwen, coder, vision, embeddings…"
          style={{
            width: '100%', boxSizing: 'border-box',
            background: T.bg1, border: `1px solid ${T.border}`, color: T.text,
            padding: '10px 14px', fontSize: 13, outline: 'none',
          }}
        />
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {OLLAMA_CATEGORIES.map(c => (
            <Chip key={c.id} active={category === c.id} onClick={() => setCategory(c.id)} count={categoryCounts[c.id] ?? 0}>
              {c.label}
            </Chip>
          ))}
        </div>
      </div>

      {/* Grid */}
      {sorted.length === 0 ? (
        <div style={{ padding: '60px 0', textAlign: 'center', color: T.dim, fontSize: 13 }}>
          No models match your filter.
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12 }}>
          {sorted.map((entry, i) => {
            const key = `${entry.model.name}:${entry.model.tag}`;
            return (
              <OllamaModelCard
                key={key}
                rank={String(i + 1).padStart(2, '0')}
                model={entry.model}
                ramTotalGB={ramTotalGB}
                installed={entry.installed}
                fits={entry.fits}
                selected={key === selected}
                onClick={() => onSelect(key)}
              />
            );
          })}
        </div>
      )}
    </>
  );
}

function CloudTab({ providers, catalogLoaded, providersStatus, selectedProvider, onSelectProvider, selectedProviderModel, onSelectModel, onOpenCredentials }) {
  const statusMap = useMemo(() => {
    const m = new Map();
    for (const s of providersStatus) m.set(s.id, s.configured);
    return m;
  }, [providersStatus]);

  const modelsRef = useRef(null);

  // Scroll model list into view whenever the selected provider changes
  useEffect(() => {
    if (selectedProvider && modelsRef.current) {
      modelsRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, [selectedProvider]);

  if (providers.length === 0) {
    return (
      <div style={{ padding: '60px 0', textAlign: 'center', color: T.dim, fontSize: 13 }}>
        {catalogLoaded
          ? 'Cloud providers unavailable.'
          : <span className="mono" style={{ letterSpacing: '.1em' }}>LOADING PROVIDERS…</span>}
      </div>
    );
  }

  const active = selectedProvider ? providers.find(p => p.id === selectedProvider) : null;

  return (
    <>
      {/* Privacy banner */}
      <div style={{
        background: `${T.amber}11`, border: `1px solid ${T.amber}55`, padding: '12px 16px',
        marginBottom: 18, fontSize: 12, color: T.muted, lineHeight: 1.6,
      }}>
        <span className="mono" style={{ fontSize: 10, color: T.amber, letterSpacing: '.1em' }}>PRIVACY · </span>
        Cloud providers send your prompts to third-party servers. Each provider has its own data-handling policy. Local Ollama keeps everything on your machine.
      </div>

      {/* Provider grid — max-height so model list stays in view */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12, marginBottom: 24,
        maxHeight: 340, overflowY: 'auto', paddingRight: 4,
      }}>
        {providers.map(p => (
          <ProviderCard
            key={p.id}
            provider={p}
            configured={statusMap.get(p.id) === true}
            selected={selectedProvider === p.id}
            onClick={() => {
              onSelectProvider(p.id);
              if (statusMap.get(p.id) !== true) {
                onOpenCredentials(p);
              } else if (p.models?.length && !selectedProviderModel) {
                onSelectModel(p.models[0].id);
              }
            }}
          />
        ))}
      </div>

      {/* Provider's models */}
      {active ? (
        <div ref={modelsRef} style={{ paddingTop: 24, borderTop: `1px solid ${T.border}` }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: T.text }}>
                {active.name} models
              </div>
              <div style={{ fontSize: 11, color: T.dim, marginTop: 2 }}>
                Pick the model dialekt should use for new sessions.
              </div>
            </div>
            <button onClick={() => onOpenCredentials(active)}
              style={{ padding: '6px 14px', background: 'none', border: `1px solid ${T.border}`, color: T.muted, fontSize: 11, cursor: 'pointer' }}>
              {statusMap.get(active.id) ? 'Update credentials' : 'Add credentials'}
            </button>
          </div>
          <ProviderModelPicker
            provider={active}
            models={active.models || []}
            selectedModel={selectedProviderModel}
            onSelect={onSelectModel}
          />
        </div>
      ) : (
        <div style={{ padding: '20px 0', textAlign: 'center', color: T.dim, fontSize: 12 }}>
          <span className="mono" style={{ letterSpacing: '.08em' }}>← SELECT A PROVIDER ABOVE</span>
        </div>
      )}
    </>
  );
}

function Footer({ tab, selectedOllama, ollamaAnnotated, selectedProvider, selectedProviderModel, providerConfigured, saving, onContinue, onConfigure, onBack, onSkip }) {
  const ollamaEntry = selectedOllama ? ollamaAnnotated.find(e => `${e.model.name}:${e.model.tag}` === selectedOllama) : null;
  const ollamaInstalled = ollamaEntry?.installed;

  let label, disabled = false, action = onContinue;

  if (saving) {
    label = 'Saving…';
    disabled = true;
  } else if (tab === 'local') {
    if (ollamaAnnotated.length === 0) {
      // Catalog still warming up — make it obvious why Continue is grey.
      label = 'Loading models…';
      disabled = true;
    } else {
      label = ollamaInstalled ? 'Use this model →' : 'Download & continue →';
      disabled = !selectedOllama;
    }
  } else {
    if (!selectedProvider) {
      label = 'Pick a provider';
      disabled = true;
    } else if (!providerConfigured) {
      label = 'Add credentials →';
      action = onConfigure;
    } else if (!selectedProviderModel) {
      label = 'Pick a model';
      disabled = true;
    } else {
      label = 'Use this model →';
    }
  }

  return (
    <div style={{
      borderTop: `1px solid ${T.border}`, padding: '16px 44px',
      background: T.bg0, display: 'flex', alignItems: 'center', gap: 14,
    }}>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 11, color: T.dim, letterSpacing: '.08em' }}>SELECTED</div>
        <div className="mono" style={{ fontSize: 13, color: T.text, marginTop: 2 }}>
          {tab === 'local'
            ? (selectedOllama || '—')
            : (selectedProvider && selectedProviderModel
                ? `${selectedProvider}/${selectedProviderModel}`
                : selectedProvider || '—')}
          {tab === 'local' && ollamaEntry && (
            <span style={{ color: T.dim }}>
              {' · '}
              {ollamaInstalled ? 'already installed' : `${ollamaEntry.model.size_gb} GB download`}
            </span>
          )}
        </div>
      </div>
      <button className="dlk-btn" onClick={onBack}>Back</button>
      <button className="dlk-btn" onClick={onSkip}>Skip</button>
      <button
        className="dlk-btn primary"
        style={{ padding: '8px 18px', opacity: disabled ? 0.4 : 1, cursor: disabled ? 'not-allowed' : 'pointer' }}
        disabled={disabled}
        onClick={action}
      >
        {label}
      </button>
    </div>
  );
}
