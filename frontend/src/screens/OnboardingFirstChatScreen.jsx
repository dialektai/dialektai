import { useState } from 'react';
import { T } from '../tokens.js';
import Icon from '../components/Icon.jsx';
import OnboardingShell from './OnboardingShell.jsx';

function Stat({ k, v, mono, accent, last }) {
  return (
    <div style={{ padding: '10px 14px', borderRight: last ? 'none' : `1px solid ${T.border}` }}>
      <div className="upper" style={{ color: T.dim, fontSize: 9 }}>{k}</div>
      <div className={mono || accent ? 'mono' : ''} style={{ fontSize: 14, fontWeight: 500, marginTop: 4, color: accent ? T.cyan : T.text }}>{v}</div>
    </div>
  );
}

function AttachChipOB({ label }) {
  return (
    <span className="mono" style={{
      display: 'inline-flex', alignItems: 'center', gap: 5, padding: '2px 6px',
      background: T.bg1, border: `1px solid ${T.border}`, fontSize: 10, color: T.muted,
    }}><Icon name="folder" size={11} color={T.cyan} />{label}</span>
  );
}

const starters = [
  { t: 'Summarize what this repo does', sub: 'reads README, package.json, top-level dirs', recommended: true },
  { t: 'Find the 3 largest files in ~/Downloads', sub: 'read-only · no writes' },
  { t: 'Explain the failing test in this file', sub: 'attach a file, I\'ll walk it' },
  { t: 'Draft a commit message from my diff', sub: 'runs git diff against HEAD' },
];

function FirstChatBody({ onSelect, selected, onTextChange }) {
  return (
    <div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 20 }}>
        {starters.map((s, i) => {
          const active = selected === s.t;
          return (
            <div key={i} onClick={() => onSelect(s.t)} style={{
              display: 'flex', alignItems: 'center', gap: 12, padding: '12px 14px',
              border: `1px solid ${active ? T.cyan : s.recommended ? `${T.cyan}44` : T.border}`,
              background: active ? T.bg2 : s.recommended ? T.bg1 : T.bg0, cursor: 'pointer',
              transition: 'border-color .12s, background .12s',
            }}>
              <span className="mono" style={{ fontSize: 10, color: active || s.recommended ? T.cyan : T.dim, letterSpacing: '.14em', width: 24 }}>{String(i + 1).padStart(2, '0')}</span>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, color: T.text }}>{s.t}</div>
                <div className="mono" style={{ fontSize: 10, color: T.dim, marginTop: 2 }}>{s.sub}</div>
              </div>
              {s.recommended && <span className="mono" style={{ fontSize: 9, color: T.cyan, letterSpacing: '.1em', border: `1px solid ${T.cyan}55`, padding: '2px 6px' }}>RECOMMENDED</span>}
              <Icon name="chevR" size={12} color={active ? T.cyan : T.muted} />
            </div>
          );
        })}
      </div>

      <div style={{ border: `1px solid ${T.borderHi}`, background: T.bg0, padding: 12 }}>
        <div className="mono" style={{ fontSize: 12, color: T.text, display: 'flex', alignItems: 'center' }}>
          <span style={{ color: T.cyan, marginRight: 6 }}>›</span>
          <input
            value={selected}
            onChange={e => onTextChange(e.target.value)}
            placeholder="describe your first task…"
            style={{
              flex: 1, background: 'transparent', border: 'none', outline: 'none',
              fontFamily: T.mono, fontSize: 12, color: T.text, caretColor: T.cyan,
            }}
          />
          {selected && <span className="dlk-caret" />}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 10, paddingTop: 10, borderTop: `1px solid ${T.border}` }}>
          <AttachChipOB label="~/code/acme-api" />
          <div style={{ flex: 1 }} />
          <span className="mono" style={{ fontSize: 10, color: T.amber }}>autonomy · ask before write</span>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', marginTop: 14, border: `1px solid ${T.border}` }}>
        <Stat k="Model"  v="gemma3-12b" mono />
        <Stat k="Scope"  v="~/code · read" mono />
        <Stat k="Cloud"  v="disabled" accent last />
      </div>
    </div>
  );
}

export default function OnboardingFirstChatScreen({ onNav }) {
  const [selected, setSelected] = useState('Summarize what this repo does');

  const handleSend = () => {
    if (selected.trim()) onNav?.('main', { initialMessage: selected.trim() });
    else onNav?.('main');
  };

  return (
    <OnboardingShell
      step={5}
      onNav={onNav}
      cta="Send first prompt"
      onCtaClick={handleSend}
      title={<>All set. Let's try<br /><span style={{ color: T.cyan }}>something small.</span></>}
      blurb="Pick a starter or write your own. I'll stay in ask-before-write mode for the first session."
    >
      <FirstChatBody onSelect={setSelected} selected={selected} onTextChange={setSelected} />
    </OnboardingShell>
  );
}
