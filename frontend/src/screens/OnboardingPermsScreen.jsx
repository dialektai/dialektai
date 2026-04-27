import { useState } from 'react';
import { T } from '../tokens.js';
import Icon from '../components/Icon.jsx';
import OnboardingShell from './OnboardingShell.jsx';
import { TriSegment } from './SettingsScreen.jsx';

const INITIAL_CAPS = [
  { icon: 'folder',   t: 'Filesystem',       sub: 'Read & write inside paths you choose.', state: 'allow', paths: '3 paths' },
  { icon: 'terminal', t: 'Terminal & shell', sub: 'Run commands in a sandboxed shell.',   state: 'ask',   paths: 'prompt per cmd' },
  { icon: 'globe',    t: 'Browser',          sub: 'Navigate, read, fill forms.',          state: 'ask' },
  { icon: 'screen',   t: 'Screen capture',   sub: 'Take screenshots when asked.',         state: 'ask' },
  { icon: 'cpu',      t: 'Mouse & keyboard', sub: 'Drive your desktop. Powerful — stays off until you need it.', state: 'deny' },
  { icon: 'file',     t: 'Keychain & secrets', sub: 'Access saved passwords. Sealed.',    state: 'deny', locked: true },
];

function PermsBody() {
  const [caps, setCaps] = useState(INITIAL_CAPS);

  const setCapState = (i, val) => {
    setCaps(prev => prev.map((c, idx) => idx === i ? { ...c, state: val } : c));
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {caps.map((c, i) => (
        <div key={i} style={{
          display: 'grid', gridTemplateColumns: '36px 1fr auto', gap: 14, alignItems: 'center',
          padding: '14px 16px', border: `1px solid ${T.border}`, background: T.bg1,
        }}>
          <div style={{ width: 36, height: 36, border: `1px solid ${T.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center', background: T.bg0 }}>
            <Icon name={c.icon} size={16} color={c.state === 'allow' ? T.cyan : c.state === 'ask' ? T.amber : T.dim} />
          </div>
          <div>
            <div style={{ fontSize: 13, color: T.text, display: 'flex', alignItems: 'center', gap: 8 }}>
              {c.t}
              {c.locked && <span className="mono" style={{ fontSize: 9, color: T.dim, border: `1px solid ${T.border}`, padding: '1px 5px', letterSpacing: '.08em' }}>SEALED</span>}
              {c.paths && <span className="mono" style={{ fontSize: 10, color: T.cyan, letterSpacing: '.06em' }}>· {c.paths}</span>}
            </div>
            <div style={{ fontSize: 11, color: T.dim, marginTop: 3 }}>{c.sub}</div>
          </div>
          <TriSegment value={c.state} onChange={val => setCapState(i, val)} disabled={c.locked} />
        </div>
      ))}
      <div style={{ marginTop: 8, padding: 12, border: `1px dashed ${T.border}`, display: 'flex', alignItems: 'center', gap: 10 }}>
        <Icon name="shield" size={14} color={T.green} />
        <span style={{ fontSize: 12, color: T.muted }}>
          Everything runs in a per-session sandbox. Prompts are never sent to the cloud.
        </span>
      </div>
    </div>
  );
}

export default function OnboardingPermsScreen({ onNav, onComplete }) {
  const [completing, setCompleting] = useState(false);
  const handleClick = async () => {
    if (completing) return;
    setCompleting(true);
    try { await onComplete?.(); }
    catch { setCompleting(false); }
  };
  return (
    <OnboardingShell step={4} onNav={onNav} onCtaClick={handleClick} loading={completing}
      title={<>Grant the agent<br /><span style={{ color: T.cyan }}>the keys it needs.</span></>}
      blurb="Off by default. Pick what dialekt can touch — you can change any of this later.">
      <PermsBody />
    </OnboardingShell>
  );
}
