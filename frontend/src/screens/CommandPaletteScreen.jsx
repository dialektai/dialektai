import { useState, useEffect, useRef, useCallback } from 'react';
import { T } from '../tokens.js';
import Icon from '../components/Icon.jsx';
import { AppFrame } from '../components/Shell.jsx';
import LeftPanel from '../components/LeftPanel.jsx';
import RightPanel from '../components/RightPanel.jsx';

function FootHint({ k, label }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span className="mono" style={{ fontSize: 10, color: T.text, border: `1px solid ${T.border}`, padding: '1px 5px' }}>{k}</span>
      <span className="mono" style={{ fontSize: 10, color: T.dim }}>{label}</span>
    </span>
  );
}

function DimmedBackdrop() {
  return (
    <div style={{ position: 'absolute', inset: 0, padding: '22px 28px', display: 'flex', flexDirection: 'column', gap: 18, opacity: .35 }}>
      <div style={{ height: 44, background: T.bg1, border: `1px solid ${T.border}` }} />
      <div style={{ alignSelf: 'flex-end', width: '60%', height: 60, background: T.bg2, border: `1px solid ${T.border}` }} />
      <div style={{ width: '72%', height: 120, background: T.bg1, border: `1px solid ${T.border}` }} />
      <div style={{ width: '72%', height: 80, background: T.bg1, border: `1px solid ${T.border}` }} />
    </div>
  );
}

const ALL_GROUPS = [
  { label: 'Actions', items: [
    { icon: 'plus',     t: 'New conversation',          sk: '⌘N', action: 'empty' },
    { icon: 'folder',   t: 'Open folder…',              sk: '⌘O', action: 'empty' },
    { icon: 'file',     t: 'Attach file to chat',       sk: '⌘⇧F', action: 'main' },
    { icon: 'screen',   t: 'Capture screen region',     sk: '⌘⇧3', action: 'main' },
    { icon: 'terminal', t: 'Run shell command…',        sk: '⌘T', badge: 'ASK', action: 'main' },
  ]},
  { label: 'Navigate', items: [
    { icon: 'chat', t: 'Refactor auth middleware',    sub: 'session · 2m ago',   sk: '↵', action: 'main' },
    { icon: 'chat', t: 'Debug websocket disconnects', sub: 'session · 2h ago',   action: 'main' },
    { icon: 'chat', t: 'Analyze q3 sales.csv',        sub: 'session · yesterday',action: 'main' },
  ]},
  { label: 'Switch model', items: [
    { icon: 'sparkle', t: 'llama3.1:70b-instruct-q4_K_M', sub: 'active · local', sk: '⌘1', live: true, action: null },
    { icon: 'sparkle', t: 'qwen2.5-coder:32b',            sub: 'loaded · local', sk: '⌘2', action: null },
    { icon: 'sparkle', t: 'deepseek-r1:32b',               sub: 'loaded · local', sk: '⌘3', action: null },
  ]},
  { label: 'Settings', items: [
    { icon: 'shield',  t: 'Permissions', sk: '⌘,', action: 'settings' },
    { icon: 'cog',     t: 'MCP tools (12 connected)', sk: '', action: 'settings' },
  ]},
];

function highlight(text, query) {
  if (!query) return text;
  const i = text.toLowerCase().indexOf(query.toLowerCase());
  if (i < 0) return text;
  return <>
    {text.slice(0, i)}
    <span style={{ color: T.cyan, background: `${T.cyan}18`, padding: '0 2px' }}>{text.slice(i, i + query.length)}</span>
    {text.slice(i + query.length)}
  </>;
}

function filterGroups(query) {
  if (!query) return ALL_GROUPS;
  const q = query.toLowerCase();
  return ALL_GROUPS
    .map(g => ({ ...g, items: g.items.filter(it => it.t.toLowerCase().includes(q) || it.sub?.toLowerCase().includes(q)) }))
    .filter(g => g.items.length > 0);
}

export default function CommandPaletteScreen({ onNav }) {
  const [query, setQuery] = useState('');
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef(null);

  const groups = filterGroups(query);
  const flat = groups.flatMap(g => g.items);
  const total = flat.length;

  const execute = useCallback((item) => {
    if (item?.action) onNav?.(item.action);
    else onNav?.('main');
  }, [onNav]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    setCursor(0);
  }, [query]);

  const onKeyDown = (e) => {
    if (e.key === 'Escape') { onNav?.('main'); return; }
    if (e.key === 'ArrowDown') { e.preventDefault(); setCursor(c => (c + 1) % total); return; }
    if (e.key === 'ArrowUp') { e.preventDefault(); setCursor(c => (c - 1 + total) % total); return; }
    if (e.key === 'Enter') { e.preventDefault(); execute(flat[cursor]); return; }
  };

  // Map flat index back to group+item for rendering
  let globalIdx = 0;

  return (
    <AppFrame title="dialekt.ai — ~/code/acme-api">
      <LeftPanel active={0} onNav={onNav} />
      <div style={{ flex: 1, position: 'relative', background: T.bg0, overflow: 'hidden' }}>
        <DimmedBackdrop />
        <div
          style={{ position: 'absolute', inset: 0, background: 'rgba(5,8,12,.7)', backdropFilter: 'blur(2px)' }}
          onClick={() => onNav?.('main')}
        />

        <div style={{ position: 'absolute', top: 56, left: '50%', transform: 'translateX(-50%)', width: 640 }}>
          <div style={{
            background: T.bg1, border: `1px solid ${T.cyan}55`,
            boxShadow: `0 24px 80px rgba(0,0,0,.6), 0 0 0 1px ${T.border}`,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 16px', borderBottom: `1px solid ${T.border}` }}>
              <span className="mono" style={{ color: T.cyan, fontSize: 14 }}>›</span>
              <input
                ref={inputRef}
                value={query}
                onChange={e => setQuery(e.target.value)}
                onKeyDown={onKeyDown}
                placeholder="search commands…"
                style={{
                  flex: 1, background: 'transparent', border: 'none', outline: 'none',
                  fontFamily: T.mono, fontSize: 14, color: T.text, caretColor: T.cyan,
                }}
              />
              <span
                className="mono"
                onClick={() => onNav?.('main')}
                style={{ fontSize: 10, color: T.dim, border: `1px solid ${T.border}`, padding: '2px 5px', cursor: 'pointer' }}
              >esc</span>
            </div>

            <div className="dlk-scroll" style={{ maxHeight: 520, overflowY: 'auto' }}>
              {groups.length === 0 && (
                <div className="mono" style={{ padding: '18px 16px', fontSize: 12, color: T.dim, textAlign: 'center' }}>
                  No results for "{query}"
                </div>
              )}
              {groups.map((g, gi) => (
                <div key={gi}>
                  <div className="upper" style={{ color: T.dim, padding: '8px 16px 6px', background: T.bg0, borderBottom: `1px solid ${T.border}` }}>{g.label}</div>
                  {g.items.map((it) => {
                    const idx = globalIdx++;
                    const active = idx === cursor;
                    return (
                      <div
                        key={it.t}
                        onMouseEnter={() => setCursor(idx)}
                        onClick={() => execute(it)}
                        style={{
                          display: 'flex', alignItems: 'center', gap: 12, padding: '9px 16px',
                          background: active ? T.bg2 : 'transparent',
                          borderLeft: `2px solid ${active ? T.cyan : 'transparent'}`,
                          paddingLeft: active ? 14 : 16,
                          borderBottom: `1px solid ${T.border}`,
                          cursor: 'pointer',
                        }}
                      >
                        <Icon name={it.icon} size={13} color={active ? T.cyan : T.muted} />
                        <div style={{ flex: 1, display: 'flex', alignItems: 'baseline', gap: 10 }}>
                          <span className="mono" style={{ fontSize: 12, color: active ? T.text : T.muted }}>
                            {highlight(it.t, query)}
                          </span>
                          {it.sub && <span className="mono" style={{ fontSize: 10, color: T.dim }}>· {it.sub}</span>}
                        </div>
                        {it.live && <span className="dlk-dot cyan live" />}
                        {it.badge && <span className="mono" style={{ fontSize: 9, color: T.amber, border: `1px solid ${T.amber}55`, padding: '1px 5px', letterSpacing: '.06em' }}>{it.badge}</span>}
                        {it.sk && <span className="mono" style={{ fontSize: 10, color: T.dim, border: `1px solid ${T.border}`, padding: '1px 5px' }}>{it.sk}</span>}
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '8px 14px', background: T.bg0, borderTop: `1px solid ${T.border}` }}>
              <FootHint k="↑↓" label="navigate" />
              <FootHint k="↵"  label="run" />
              <FootHint k="⌘↵" label="run + confirm" />
              <div style={{ flex: 1 }} />
              <span className="mono" style={{ fontSize: 10, color: T.dim }}>{total} results</span>
            </div>
          </div>

          <div className="mono" style={{ textAlign: 'center', marginTop: 10, fontSize: 10, color: T.dim, letterSpacing: '.1em' }}>
            TYPE <span style={{ color: T.cyan }}>/</span> FOR COMMANDS · <span style={{ color: T.cyan }}>#</span> FOR FILES · <span style={{ color: T.cyan }}>@</span> FOR MENTIONS
          </div>
        </div>
      </div>
      <RightPanel items={[]} />
    </AppFrame>
  );
}
