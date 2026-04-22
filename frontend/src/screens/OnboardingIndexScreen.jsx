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

function Check({ on }) {
  return (
    <div style={{
      width: 16, height: 16, border: `1px solid ${on ? T.cyan : T.borderHi}`,
      background: on ? T.cyan : T.bg0, display: 'flex', alignItems: 'center', justifyContent: 'center',
      cursor: 'pointer', flexShrink: 0,
    }}>
      {on && <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke={T.bg0} strokeWidth="2"><path d="M2 5l2 2 4-5" /></svg>}
    </div>
  );
}

function Toggle({ on, onClick }) {
  return (
    <div onClick={onClick} style={{ width: 32, height: 18, borderRadius: 9, padding: 2, background: on ? T.cyan : T.bg0, border: `1px solid ${on ? T.cyan : T.borderHi}`, cursor: 'pointer', flexShrink: 0 }}>
      <div style={{ width: 12, height: 12, borderRadius: '50%', background: on ? T.bg0 : T.dim, marginLeft: on ? 14 : 0, transition: 'margin-left .15s' }} />
    </div>
  );
}

const INIT_WORKSPACES = [
  { p: '~/code',               n: '14,204 files · 1.2 GB', sel: true,  eta: '2m 40s' },
  { p: '~/Documents/notes',    n: '412 files · 38 MB',     sel: true,  eta: '12s' },
  { p: '~/Downloads',          n: '2,188 files · 12 GB',   sel: false, warn: 'mixed content' },
  { p: '~/projects/archive',   n: '48,912 files · 8.4 GB', sel: false, warn: 'large — will skip binaries' },
];

const INIT_TOGGLES = [
  { title: 'Index binaries & images', sub: 'Off by default. Uses vision model.', on: false },
  { title: 'Watch for changes',       sub: 'Re-index modified files in background.', on: true },
  { title: 'Respect .gitignore',      sub: 'Strongly recommended.', on: true, locked: true },
  { title: 'Include hidden files',    sub: 'Skips ~/.ssh and credentials.', on: false },
];

function IndexBody() {
  const [workspaces, setWorkspaces] = useState(INIT_WORKSPACES);
  const [toggles, setToggles] = useState(INIT_TOGGLES);

  const toggleWS = (i) => setWorkspaces(prev => prev.map((w, idx) => idx === i ? { ...w, sel: !w.sel } : w));
  const toggleOpt = (i) => setToggles(prev => prev.map((t, idx) => idx === i && !t.locked ? { ...t, on: !t.on } : t));

  const selectedCount = workspaces.filter(w => w.sel).length;
  const totalFiles = workspaces.filter(w => w.sel).reduce((acc, w) => {
    const n = parseInt(w.n.replace(/,/g, ''));
    return acc + (isNaN(n) ? 0 : n);
  }, 0);

  return (
    <div>
      <div style={{ border: `1px solid ${T.border}`, background: T.bg1 }}>
        {workspaces.map((w, i) => (
          <div key={i} onClick={() => toggleWS(i)} style={{
            display: 'grid', gridTemplateColumns: '24px 1fr auto auto', gap: 14, alignItems: 'center',
            padding: '12px 16px', borderBottom: i < workspaces.length - 1 ? `1px solid ${T.border}` : 'none',
            background: w.sel ? T.bg2 : 'transparent', cursor: 'pointer',
          }}>
            <Check on={w.sel} />
            <div>
              <div className="mono" style={{ fontSize: 12, color: T.text }}>{w.p}</div>
              <div className="mono" style={{ fontSize: 10, color: T.dim, marginTop: 2 }}>{w.n}</div>
            </div>
            {w.warn && <span className="mono" style={{ fontSize: 10, color: T.amber }}>⚠ {w.warn}</span>}
            <span className="mono" style={{ fontSize: 10, color: w.sel ? T.cyan : T.dim, minWidth: 60, textAlign: 'right' }}>
              {w.sel ? `ETA ${w.eta}` : 'skipped'}
            </span>
          </div>
        ))}
        <div style={{ padding: '10px 16px', display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
          <Icon name="plus" size={12} color={T.cyan} />
          <span className="mono" style={{ fontSize: 11, color: T.cyan }}>add another path…</span>
        </div>
      </div>

      <div style={{ marginTop: 14, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
        {toggles.map((t, i) => (
          <div key={i} onClick={() => toggleOpt(i)} style={{
            display: 'flex', alignItems: 'center', gap: 12, padding: '10px 12px',
            border: `1px solid ${T.border}`, background: T.bg1,
            opacity: t.locked ? 0.8 : 1, cursor: t.locked ? 'default' : 'pointer',
          }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 12, color: T.text, display: 'flex', alignItems: 'center', gap: 6 }}>
                {t.title}
                {t.locked && <Icon name="shield" size={10} color={T.dim} />}
              </div>
              <div style={{ fontSize: 10, color: T.dim, marginTop: 2 }}>{t.sub}</div>
            </div>
            <Toggle on={t.on} onClick={e => { e.stopPropagation(); toggleOpt(i); }} />
          </div>
        ))}
      </div>

      <div style={{ marginTop: 14, padding: 14, border: `1px solid ${T.border}`, background: T.bg0, display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)' }}>
        <Stat k="Paths"       v={`${selectedCount} sel.`} mono />
        <Stat k="Files"       v={totalFiles > 0 ? `~${(totalFiles / 1000).toFixed(0)}k` : '0'} mono />
        <Stat k="Embeddings"  v={selectedCount > 0 ? '≈ 82k' : '—'} mono />
        <Stat k="Status"      v={selectedCount > 0 ? 'ready' : 'skip'} accent last />
      </div>
    </div>
  );
}

export default function OnboardingIndexScreen({ onNav }) {
  return (
    <OnboardingShell step={4} onNav={onNav}
      title={<>Give dialekt<br /><span style={{ color: T.cyan }}>a map of your work.</span></>}
      blurb="Local semantic index. Files never leave the machine. Skip if you'd rather build it as you go.">
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', marginBottom: 16,
        border: `1px solid ${T.border}`, background: T.bg1,
      }}>
        <div style={{
          padding: '2px 7px', background: T.bg0, border: `1px solid ${T.borderHi}`,
          fontFamily: 'monospace', fontSize: 10, color: T.cyan, letterSpacing: '.1em', flexShrink: 0,
        }}>COMING v1.1</div>
        <span style={{ fontSize: 12, color: T.dim }}>
          Workspace indexing is not yet implemented. This step is a preview — click Continue to proceed.
        </span>
      </div>
      <div style={{ opacity: 0.4, pointerEvents: 'none' }}>
        <IndexBody />
      </div>
    </OnboardingShell>
  );
}
