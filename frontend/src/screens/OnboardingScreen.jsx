import { useState } from 'react';
import { T } from '../tokens.js';
import { AppFrame, Logo } from '../components/Shell.jsx';

const MODELS = [
  {
    rank: '01',
    name: 'llama3.1', tag: '70b-instruct-q4_K_M', vendor: 'Meta · via Ollama',
    blurb: 'Best all-rounder. Strong reasoning, full tool-use. Fits this machine.',
    specs: [['Size','42.1 GB'],['Ctx','128k'],['Speed','≈ 22 tok/s'],['RAM','48 GB']],
    tags: ['reasoning','coding','tool-use'], fit: 'good-fit',
  },
  {
    rank: '02',
    name: 'qwen2.5-coder', tag: '32b-instruct-q5_K_M', vendor: 'Alibaba · via Ollama',
    blurb: 'Purpose-built for code. Fastest patch & refactor loops.',
    specs: [['Size','22.8 GB'],['Ctx','128k'],['Speed','≈ 38 tok/s'],['RAM','28 GB']],
    tags: ['coding','fast'], fit: 'good-fit',
  },
  {
    rank: '03',
    name: 'deepseek-r1', tag: '32b-q4_K_M', vendor: 'DeepSeek · via Ollama',
    blurb: 'Extended thinking. Slower but stronger on planning tasks.',
    specs: [['Size','19.4 GB'],['Ctx','64k'],['Speed','≈ 14 tok/s'],['RAM','24 GB']],
    tags: ['reasoning','agents'], fit: 'good-fit',
  },
  {
    rank: '04',
    name: 'mistral-nemo', tag: '12b-instruct-q6_K', vendor: 'Mistral · via Ollama',
    blurb: 'Balanced quality at a fraction of the RAM. Good daily driver.',
    specs: [['Size','9.1 GB'],['Ctx','128k'],['Speed','≈ 46 tok/s'],['RAM','14 GB']],
    tags: ['balanced','fast'], fit: 'good-fit',
  },
  {
    rank: '05',
    name: 'llama3.2-vision', tag: '11b-q4_K_M', vendor: 'Meta · via Ollama',
    blurb: 'Reads screenshots, PDFs, diagrams. Pair with a text model.',
    specs: [['Size','7.2 GB'],['Ctx','32k'],['Speed','≈ 32 tok/s'],['RAM','11 GB']],
    tags: ['vision'], fit: 'good-fit',
  },
  {
    rank: '06',
    name: 'llama3.1', tag: '405b-q4_K_M', vendor: 'Meta · via Ollama',
    blurb: "Frontier quality. Exceeds this machine's memory — offload to a workstation.",
    specs: [['Size','240 GB'],['Ctx','128k'],['Speed','≈ 2 tok/s'],['RAM','256 GB']],
    tags: ['frontier'], fit: 'too-big',
  },
];

const DEFAULT_IDX = 0;

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

function ModelCard({ rank, name, tag, vendor, blurb, specs, tags, fit, selected, onClick }) {
  const tooBig = fit === 'too-big';
  const ramTotal = 32;
  const ramVal = parseInt(specs[3][1]);
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
            <span className="mono" style={{ fontSize: 15, fontWeight: 600, color: T.text, letterSpacing: '-0.01em' }}>{name}</span>
            <span className="mono" style={{ fontSize: 11, color: T.muted }}>:{tag.split('-').slice(-1)[0] || tag}</span>
          </div>
          <div className="mono" style={{ fontSize: 10, color: T.dim, marginTop: 2, letterSpacing: '.04em' }}>{vendor}</div>
        </div>
        {selected && (
          <div className="mono" style={{ fontSize: 10, color: T.cyan, letterSpacing: '.1em', display: 'flex', alignItems: 'center', gap: 4 }}>
            <div style={{ width: 10, height: 10, background: T.cyan, transform: 'rotate(45deg)' }} />
            SELECTED
          </div>
        )}
      </div>

      <div style={{ fontSize: 12, color: T.muted, lineHeight: 1.55, marginTop: 6, marginBottom: 12 }}>{blurb}</div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', borderTop: `1px solid ${T.border}`, borderBottom: `1px solid ${T.border}` }}>
        {specs.map(([k, v], i) => (
          <div key={i} style={{ padding: '8px 10px', borderRight: i < specs.length - 1 ? `1px solid ${T.border}` : 'none' }}>
            <div className="upper" style={{ color: T.dim, fontSize: 9 }}>{k}</div>
            <div className="mono" style={{ fontSize: 11, color: T.text, marginTop: 2 }}>{v}</div>
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 12 }}>
        {tags.map((t, i) => (
          <span key={i} className="mono" style={{ fontSize: 9, color: T.muted, border: `1px solid ${T.border}`, padding: '2px 5px', letterSpacing: '.06em', textTransform: 'uppercase' }}>{t}</span>
        ))}
        <div style={{ flex: 1 }} />
        {tooBig ? (
          <span className="mono" style={{ fontSize: 10, color: T.amber, display: 'flex', alignItems: 'center', gap: 4 }}>
            <span className="dlk-dot amber" /> exceeds RAM
          </span>
        ) : (
          <span className="mono" style={{ fontSize: 10, color: T.green, display: 'flex', alignItems: 'center', gap: 4 }}>
            <span className="dlk-dot" /> good fit
          </span>
        )}
      </div>

      <div style={{ marginTop: 10 }}>
        <div style={{ height: 3, background: T.bg0, border: `1px solid ${T.border}`, position: 'relative' }}>
          <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: tooBig ? '100%' : `${Math.min(95, (ramVal / ramTotal) * 100)}%`, background: tooBig ? T.amber : T.cyan }} />
        </div>
        <div className="mono" style={{ fontSize: 9, color: T.dim, marginTop: 4, display: 'flex', justifyContent: 'space-between' }}>
          <span>mem · {specs[3][1]} of {ramTotal} GB</span>
          <span>{tooBig ? '+192 GB short' : 'fits'}</span>
        </div>
      </div>
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
  const [selectedIdx, setSelectedIdx] = useState(DEFAULT_IDX);
  const sel = MODELS[selectedIdx];
  const fullName = `${sel.name}:${sel.tag}`;

  const handleDownload = () => {
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
              <Row k="RAM"  v="32 GB" />
              <Row k="DISK" v="915 GB NVMe" />
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 10, fontSize: 10 }}>
              <span className="dlk-dot cyan live" />
              <span className="mono" style={{ color: T.cyan, letterSpacing: '.08em' }}>compatible with 5 models</span>
            </div>
          </div>
        </div>

        {/* Right — model grid */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '36px 44px', position: 'relative' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20 }}>
            <Filter label="All" n={12} active />
            <Filter label="Coding" n={5} />
            <Filter label="Reasoning" n={4} />
            <Filter label="Vision" n={3} />
            <Filter label="Lightweight" n={6} />
            <div style={{ flex: 1 }} />
            <span className="mono" style={{ fontSize: 10, color: T.dim }}>sort: recommended</span>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,1fr)', gap: 14 }}>
            {MODELS.map((m, i) => (
              <ModelCard
                key={i}
                {...m}
                selected={i === selectedIdx}
                onClick={() => setSelectedIdx(i)}
              />
            ))}
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
                {fullName} <span style={{ color: T.dim }}>· {sel.specs[0][1]} download</span>
              </div>
            </div>
            <button className="dlk-btn" onClick={() => onNav?.('onboarding-step2')}>Back</button>
            <button className="dlk-btn" onClick={() => onNav?.('onboarding-step4')}>Skip for now</button>
            <button className="dlk-btn primary" style={{ padding: '7px 16px' }} onClick={handleDownload}>
              Download & continue <span className="mono" style={{ fontSize: 10, opacity: .7, marginLeft: 4 }}>⏎</span>
            </button>
          </div>
        </div>
      </div>
    </AppFrame>
  );
}
