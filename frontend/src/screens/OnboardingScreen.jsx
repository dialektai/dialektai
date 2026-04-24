import { useState, useEffect, useMemo } from 'react';
import { T } from '../tokens.js';
import { AppFrame, Logo } from '../components/Shell.jsx';

const MODELS = [
  {
    name: 'llama3.1', tag: '70b-instruct-q4_K_M', vendor: 'Meta · via Ollama',
    blurb: 'Best all-rounder. Strong reasoning, full tool-use.',
    sizeGB: 42.1, ctx: '128k', tokS: 22, ramGB: 48,
    tags: ['reasoning','coding','tool-use'],
  },
  {
    name: 'qwen2.5-coder', tag: '32b-instruct-q5_K_M', vendor: 'Alibaba · via Ollama',
    blurb: 'Purpose-built for code. Fastest patch & refactor loops.',
    sizeGB: 22.8, ctx: '128k', tokS: 38, ramGB: 28,
    tags: ['coding','fast'],
  },
  {
    name: 'deepseek-r1', tag: '32b-q4_K_M', vendor: 'DeepSeek · via Ollama',
    blurb: 'Extended thinking. Slower but stronger on planning tasks.',
    sizeGB: 19.4, ctx: '64k', tokS: 14, ramGB: 24,
    tags: ['reasoning','agents'],
  },
  {
    name: 'mistral-nemo', tag: '12b-instruct-q6_K', vendor: 'Mistral · via Ollama',
    blurb: 'Balanced quality at a fraction of the RAM. Good daily driver.',
    sizeGB: 9.1, ctx: '128k', tokS: 46, ramGB: 14,
    tags: ['balanced','fast'],
  },
  {
    name: 'qwen2.5-coder', tag: '7b-instruct-q4_K_M', vendor: 'Alibaba · via Ollama',
    blurb: 'Smaller code model. Runs on modest hardware.',
    sizeGB: 4.7, ctx: '128k', tokS: 58, ramGB: 8,
    tags: ['coding','lightweight'],
  },
  {
    name: 'llama3.2-vision', tag: '11b-q4_K_M', vendor: 'Meta · via Ollama',
    blurb: 'Reads screenshots, PDFs, diagrams. Pair with a text model.',
    sizeGB: 7.2, ctx: '32k', tokS: 32, ramGB: 11,
    tags: ['vision'],
  },
  {
    name: 'gemma3', tag: '12b-q4_K_M', vendor: 'Google · via Ollama',
    blurb: 'Modern balanced model from Google. Strong for size.',
    sizeGB: 7.3, ctx: '128k', tokS: 34, ramGB: 14,
    tags: ['balanced'],
  },
  {
    name: 'gemma2', tag: '2b-q4_0', vendor: 'Google · via Ollama',
    blurb: 'Tiny model. Runs anywhere, even low-end laptops.',
    sizeGB: 1.6, ctx: '8k', tokS: 80, ramGB: 4,
    tags: ['lightweight','fast'],
  },
  {
    name: 'llama3.1', tag: '405b-q4_K_M', vendor: 'Meta · via Ollama',
    blurb: "Frontier quality. Exceeds typical desktop memory.",
    sizeGB: 240, ctx: '128k', tokS: 2, ramGB: 256,
    tags: ['frontier'],
  },
];

// Normalise Ollama tag — "qwen2.5-coder:7b" matches "qwen2.5-coder:7b-instruct-q4_K_M"
// by stripping quantisation suffix.
function ollamaFamily(tag) {
  if (!tag) return '';
  const head = tag.split(':')[0];
  const rest = tag.split(':')[1] || '';
  const size = rest.split('-')[0]; // e.g. "7b" from "7b-instruct-q4_K_M"
  return size ? `${head}:${size}` : head;
}

function modelIsInstalled(model, installedTags) {
  if (!installedTags || installedTags.size === 0) return false;
  const targetSize = (model.tag || '').split('-')[0];
  const wantedFamily = `${model.name}:${targetSize}`;
  for (const t of installedTags) {
    if (ollamaFamily(t) === wantedFamily) return true;
    // Also accept :latest installs of the base name
    if (t === `${model.name}:latest` && !targetSize) return true;
  }
  return false;
}

function modelFits(model, ramGB) {
  if (ramGB == null) return null; // unknown
  return model.ramGB <= ramGB;
}

function Filter({ label, n, active }) {
  return (
    <div style={{
      padding: '5px 10px', fontSize: 11, fontWeight: active ? 600 : 400,
      color: active ? T.bg0 : T.muted,
      background: active ? T.cyan : 'transparent',
      border: `1px solid ${active ? T.cyan : T.border}`,
      display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer',
    }}>
      {label}
      <span className="mono" style={{ fontSize: 9, opacity: .7 }}>{n}</span>
    </div>
  );
}

function ModelCard({ rank, model, ramTotalGB, installed, fits, selected, onClick }) {
  // Disable only when we know it doesn't fit. Unknown RAM → allow click
  // so users on non-Chromium browsers aren't locked out.
  const tooBig = fits === false;
  const shortBy = tooBig ? model.ramGB - (ramTotalGB || 0) : 0;
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
        {selected && (
          <div className="mono" style={{ fontSize: 10, color: T.cyan, letterSpacing: '.1em', display: 'flex', alignItems: 'center', gap: 4 }}>
            <div style={{ width: 10, height: 10, background: T.cyan, transform: 'rotate(45deg)' }} />
            SELECTED
          </div>
        )}
      </div>

      <div style={{ fontSize: 12, color: T.muted, lineHeight: 1.55, marginTop: 6, marginBottom: 12 }}>{model.blurb}</div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', borderTop: `1px solid ${T.border}`, borderBottom: `1px solid ${T.border}` }}>
        <Spec k="Size" v={`${model.sizeGB} GB`} />
        <Spec k="Ctx" v={model.ctx} />
        <Spec k="Speed" v={`≈ ${model.tokS} tok/s`} last={false} />
        <Spec k="RAM" v={`${model.ramGB} GB`} last />
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 12 }}>
        {model.tags.map((t, i) => (
          <span key={i} className="mono" style={{ fontSize: 9, color: T.muted, border: `1px solid ${T.border}`, padding: '2px 5px', letterSpacing: '.06em', textTransform: 'uppercase' }}>{t}</span>
        ))}
        <div style={{ flex: 1 }} />
        {tooBig ? (
          <span className="mono" style={{ fontSize: 10, color: T.amber, display: 'flex', alignItems: 'center', gap: 4 }}>
            <span className="dlk-dot amber" /> exceeds RAM
          </span>
        ) : fits === null ? (
          <span className="mono" style={{ fontSize: 10, color: T.dim, display: 'flex', alignItems: 'center', gap: 4 }}>
            RAM check unavailable
          </span>
        ) : (
          <span className="mono" style={{ fontSize: 10, color: T.green, display: 'flex', alignItems: 'center', gap: 4 }}>
            <span className="dlk-dot" /> good fit
          </span>
        )}
      </div>

      <div style={{ marginTop: 10 }}>
        <div style={{ height: 3, background: T.bg0, border: `1px solid ${T.border}`, position: 'relative' }}>
          <div style={{
            position: 'absolute', left: 0, top: 0, bottom: 0,
            width: tooBig ? '100%' : `${Math.min(95, ramTotalGB ? (model.ramGB / ramTotalGB) * 100 : 50)}%`,
            background: tooBig ? T.amber : T.cyan,
          }} />
        </div>
        <div className="mono" style={{ fontSize: 9, color: T.dim, marginTop: 4, display: 'flex', justifyContent: 'space-between' }}>
          <span>mem · {model.ramGB} GB of {ramTotalGB ? `${ramTotalGB} GB` : '?'}</span>
          <span>
            {tooBig
              ? `needs +${shortBy} GB`
              : fits === null
                ? ''
                : 'fits'}
          </span>
        </div>
      </div>
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

function Row({ k, v }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
      <span style={{ color: T.dim, letterSpacing: '.08em' }}>{k}</span>
      <span style={{ color: T.text }}>{v}</span>
    </div>
  );
}

const STEPS = [
  { n: '01', t: 'License & privacy', done: true },
  { n: '02', t: 'Choose your model', active: true },
  { n: '03', t: 'Grant permissions' },
  { n: '04', t: 'Index your workspace' },
  { n: '05', t: 'First conversation' },
];

export default function OnboardingScreen({ onNav }) {
  const [installedTags, setInstalledTags] = useState(() => new Set());
  const [ramTotalGB, setRamTotalGB] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetch('http://127.0.0.1:11434/api/tags')
      .then(r => r.ok ? r.json() : { models: [] })
      .then(data => {
        if (cancelled) return;
        setInstalledTags(new Set((data.models || []).map(m => m.name)));
      })
      .catch(() => { if (!cancelled) setInstalledTags(new Set()); });

    // navigator.deviceMemory is Chromium-only and rounded to powers of 2 — prefer the backend.
    fetch('http://127.0.0.1:8765/system')
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (cancelled || !data) return;
        if (typeof data.ram_total_gb === 'number') setRamTotalGB(data.ram_total_gb);
        else if (typeof navigator.deviceMemory === 'number') setRamTotalGB(navigator.deviceMemory);
      })
      .catch(() => {
        if (cancelled) return;
        if (typeof navigator.deviceMemory === 'number') setRamTotalGB(navigator.deviceMemory);
      });

    return () => { cancelled = true; };
  }, []);

  // Decorate each model with install/fit info, then sort: installed+fits > fits > unknown > too-big.
  const annotated = useMemo(() => {
    return MODELS.map(m => ({
      model: m,
      installed: modelIsInstalled(m, installedTags),
      fits: modelFits(m, ramTotalGB),
    }));
  }, [installedTags, ramTotalGB]);

  const sorted = useMemo(() => {
    const rank = (e) => {
      if (e.installed && e.fits !== false) return 0;
      if (e.fits === true) return 1;
      if (e.fits === null) return 2;
      return 3; // too big
    };
    return [...annotated]
      .map((e, origIdx) => ({ ...e, origIdx }))
      .sort((a, b) => rank(a) - rank(b));
  }, [annotated]);

  const compatibleCount = annotated.filter(e => e.fits !== false).length;

  // Auto-select first installed+fits model; if none installed, first fits; never a too-big.
  const defaultSelected = useMemo(() => {
    const firstPick =
      sorted.find(e => e.installed && e.fits !== false) ||
      sorted.find(e => e.fits === true) ||
      sorted.find(e => e.fits === null) ||
      sorted[0];
    return firstPick ? `${firstPick.model.name}:${firstPick.model.tag}` : null;
  }, [sorted]);

  const [selectedKey, setSelectedKey] = useState(null);
  const activeKey = selectedKey || defaultSelected;
  const sel = annotated.find(e => `${e.model.name}:${e.model.tag}` === activeKey) || annotated[0];
  const fullName = sel ? `${sel.model.name}:${sel.model.tag}` : '';

  const selectedTooBig = sel && sel.fits === false;

  const handleDownload = () => {
    if (selectedTooBig) return;
    if (sel && sel.installed) {
      onNav?.('onboarding-step4');
      return;
    }
    onNav?.('download', {
      model: fullName,
      onComplete: () => onNav?.('onboarding-step4'),
    });
  };

  return (
    <AppFrame title="dialekt.ai — welcome">
      <div style={{ flex: 1, display: 'flex', background: T.bg0, minWidth: 0 }}>
        {/* Left rail */}
        <div style={{ width: 320, background: T.bg1, borderRight: `1px solid ${T.border}`, padding: '36px 32px', display: 'flex', flexDirection: 'column', flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 40 }}>
            <Logo />
            <div>
              <div style={{ fontSize: 15, fontWeight: 600 }}>dialekt<span style={{ color: T.cyan }}>.ai</span></div>
              <div className="mono" style={{ fontSize: 10, color: T.dim, letterSpacing: '.1em' }}>LOCAL-FIRST · v0.8.2</div>
            </div>
          </div>

          <div style={{ marginBottom: 32 }}>
            <div className="mono" style={{ fontSize: 10, color: T.cyan, letterSpacing: '.14em', marginBottom: 10 }}>02 / 05</div>
            <div style={{ fontSize: 26, fontWeight: 600, letterSpacing: '-0.02em', lineHeight: 1.15, marginBottom: 10 }}>
              Pick a model<br />to run <span style={{ color: T.cyan }}>on this machine.</span>
            </div>
            <div style={{ fontSize: 13, color: T.muted, lineHeight: 1.55 }}>
              Your prompts never leave the device. Ollama handles inference. Switch or add models later from Settings.
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
              <Row k="CPU"  v="12 cores · x86_64" />
              <Row k="RAM"  v={ramTotalGB ? `${ramTotalGB} GB` : '—'} />
              <Row k="DISK" v="915 GB NVMe" />
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 10, fontSize: 10 }}>
              <span className="dlk-dot cyan live" />
              <span className="mono" style={{ color: T.cyan, letterSpacing: '.08em' }}>
                {ramTotalGB == null
                  ? 'RAM check unavailable'
                  : `compatible with ${compatibleCount} model${compatibleCount === 1 ? '' : 's'}`}
              </span>
            </div>
          </div>
        </div>

        {/* Right — model grid */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '36px 44px', position: 'relative' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20 }}>
            <Filter label="All" n={MODELS.length} active />
            <div style={{ flex: 1 }} />
            <span className="mono" style={{ fontSize: 10, color: T.dim }}>sort: recommended</span>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,1fr)', gap: 14 }}>
            {sorted.map((entry, i) => {
              const key = `${entry.model.name}:${entry.model.tag}`;
              return (
                <ModelCard
                  key={key}
                  rank={String(i + 1).padStart(2, '0')}
                  model={entry.model}
                  ramTotalGB={ramTotalGB}
                  installed={entry.installed}
                  fits={entry.fits}
                  selected={key === activeKey}
                  onClick={() => setSelectedKey(key)}
                />
              );
            })}
          </div>

          {/* Sticky footer */}
          <div style={{
            position: 'sticky', bottom: -36, marginTop: 28,
            borderTop: `1px solid ${T.border}`, padding: '16px 0 0',
            background: `linear-gradient(${T.bg0}00 0%, ${T.bg0} 40%)`,
            display: 'flex', alignItems: 'center', gap: 14,
          }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 12, color: T.muted }}>Selected</div>
              <div className="mono" style={{ fontSize: 13, color: T.text }}>
                {fullName}
                {sel && (
                  <span style={{ color: T.dim }}>
                    {' · '}
                    {sel.installed
                      ? 'already installed — no download'
                      : `${sel.model.sizeGB} GB download`}
                  </span>
                )}
                {selectedTooBig && (
                  <span style={{ color: T.amber, marginLeft: 8 }}>
                    · requires {sel.model.ramGB} GB RAM
                  </span>
                )}
              </div>
            </div>
            <button className="dlk-btn" onClick={() => onNav?.('onboarding-step2')}>Back</button>
            <button className="dlk-btn" onClick={() => onNav?.('onboarding-step4')}>Skip for now</button>
            <button
              className="dlk-btn primary"
              style={{ padding: '7px 16px', opacity: selectedTooBig ? 0.4 : 1, cursor: selectedTooBig ? 'not-allowed' : 'pointer' }}
              disabled={selectedTooBig}
              onClick={handleDownload}
            >
              {sel && sel.installed
                ? 'Use this model'
                : <>Download & continue <span className="mono" style={{ fontSize: 10, opacity: .7, marginLeft: 4 }}>⏎</span></>}
            </button>
          </div>
        </div>
      </div>
    </AppFrame>
  );
}
