import { useState, useEffect, useCallback, useRef } from 'react';
import { T } from '../tokens.js';
import Icon from './Icon.jsx';
import { Logo, Meter } from './Shell.jsx';

const API = 'http://localhost:8765';

function shortModel(m) {
  return m.replace(/:latest$/, '');
}

function timeAgo(iso) {
  const diff = (Date.now() - new Date(iso)) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 172800) return 'yesterday';
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function LeftPanel({
  active = -1,
  model = 'gemma3-12b',
  models = [],
  running = true,
  currentSessionId = null,
  onNav,
  onSessionSwitch,
  onNewSession,
  onModelSwitch,
  selectedAgentId: selectedAgentIdProp,
  onAgentSelect,
}) {
  const [sessions, setSessions] = useState([]);
  const [search, setSearch] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  const [hoverId, setHoverId] = useState(null);
  const [tooltipY, setTooltipY] = useState(0);
  const [modelOpen, setModelOpen] = useState(false);
  const [sysStats, setSysStats] = useState({ cpu: 0, ram: 0, gpu: null, disk: 0 });
  const [mode, setMode] = useState('builder');
  const [agents, setAgents] = useState([]);
  const [selectedAgentIdInner, setSelectedAgentIdInner] = useState(null);
  // Controlled if parent supplies prop; otherwise fall back to local state.
  const selectedAgentId = selectedAgentIdProp !== undefined ? selectedAgentIdProp : selectedAgentIdInner;
  const selectAgent = onAgentSelect || setSelectedAgentIdInner;
  const [agentsOpen, setAgentsOpen] = useState(true);
  const [showNewAgent, setShowNewAgent] = useState(false);
  const [newAgentName, setNewAgentName] = useState('');
  const asideRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch(`${API}/sessions`);
      const data = await r.json();
      setSessions(data);
    } catch {}
  }, []);

  const loadMode = useCallback(async () => {
    try {
      const r = await fetch(`${API}/config/mode`);
      const data = await r.json();
      setMode(data.mode ?? 'builder');
    } catch {}
  }, []);

  const loadAgents = useCallback(async () => {
    try {
      const r = await fetch(`${API}/agents`);
      if (r.ok) setAgents(await r.json());
    } catch {}
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [load]);

  useEffect(() => {
    loadMode();
    loadAgents();
  }, [loadMode, loadAgents]);

  useEffect(() => {
    const fetchStats = () =>
      fetch(`${API}/system`).then(r => r.json()).then(setSysStats).catch(() => {});
    fetchStats();
    const t = setInterval(fetchStats, 4000);
    return () => clearInterval(t);
  }, []);

  const handleMouseEnter = useCallback((id, e) => {
    setHoverId(id);
    if (asideRef.current) {
      const asideRect = asideRef.current.getBoundingClientRect();
      const rowRect = e.currentTarget.getBoundingClientRect();
      setTooltipY(rowRect.top - asideRect.top + rowRect.height / 2 - 60);
    }
  }, []);

  const del = async (e, id) => {
    e.stopPropagation();
    await fetch(`${API}/sessions/${id}`, { method: 'DELETE' });
    setSessions(prev => prev.filter(s => s.id !== id));
    if (currentSessionId === id) onNewSession?.();
  };

  const handleClick = (session) => {
    if (onSessionSwitch) {
      onSessionSwitch(session.id);
    } else {
      onNav?.('main', { sessionId: session.id });
    }
  };

  const filtered = sessions.filter(s =>
    !search || (s.title ?? '').toLowerCase().includes(search.toLowerCase())
  );

  const renderSession = (s) => {
    const isCurrent = s.id === currentSessionId;
    const isHover = s.id === hoverId;
    return (
      <div
        key={s.id}
        onClick={() => handleClick(s)}
        onMouseEnter={(e) => handleMouseEnter(s.id, e)}
        onMouseLeave={() => setHoverId(null)}
        style={{
          padding: '8px 10px', marginBottom: 1, position: 'relative',
          border: `1px solid ${isHover ? T.borderHi : 'transparent'}`,
          borderLeft: `2px solid ${isCurrent ? T.cyan : isHover ? T.borderHi : 'transparent'}`,
          background: isCurrent || isHover ? T.bg2 : 'transparent',
          cursor: 'pointer',
          transition: 'background .1s',
          zIndex: isHover ? 2 : 1,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {isCurrent && <span className="dlk-dot cyan live" />}
          <div style={{
            fontSize: 12, color: isCurrent ? T.text : T.muted,
            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
            fontWeight: isCurrent ? 500 : 400, flex: 1,
          }}>
            {s.title}
          </div>
        </div>
        <div className="mono" style={{ fontSize: 10, color: T.dim, marginTop: 2, paddingLeft: isCurrent ? 12 : 0 }}>
          {isCurrent ? `active · ${s.message_count} msgs` : `${timeAgo(s.updated_at)} · ${s.message_count} msgs`}
        </div>
        {isHover && (
          <div style={{ display: 'flex', gap: 3, marginTop: 6, paddingLeft: isCurrent ? 10 : 0 }}>
            <button className="dlk-btn ghost" style={{ padding: 3 }} onClick={e => e.stopPropagation()} title="Copy link">
              <Icon name="copy" size={10} color={T.muted} />
            </button>
            <button className="dlk-btn ghost" style={{ padding: 3 }} onClick={e => e.stopPropagation()} title="Export">
              <Icon name="file" size={10} color={T.muted} />
            </button>
            <button className="dlk-btn ghost" style={{ padding: 3 }} onClick={e => e.stopPropagation()} title="Stop">
              <Icon name="stop" size={10} color={T.amber} />
            </button>
            <div style={{ flex: 1 }} />
            <button className="dlk-btn ghost" style={{ padding: 3 }} onClick={e => del(e, s.id)} title="Delete">
              <Icon name="x" size={10} color={T.dim} />
            </button>
            <button className="dlk-btn ghost" style={{ padding: 3 }} onClick={e => e.stopPropagation()} title="More">
              <Icon name="ham" size={10} color={T.muted} />
            </button>
          </div>
        )}
      </div>
    );
  };

  const renderGroupedSessions = () => {
    const agentMap = Object.fromEntries(agents.map(a => [a.id, a]));
    const groups = {};
    for (const s of filtered) {
      const key = s.agent_id || '__none__';
      if (!groups[key]) groups[key] = [];
      groups[key].push(s);
    }
    const agentIds = Object.keys(groups).sort((a, b) => {
      const nameA = agentMap[a]?.name ?? 'Unknown';
      const nameB = agentMap[b]?.name ?? 'Unknown';
      return nameA.localeCompare(nameB);
    });
    return agentIds.map(agentId => {
      const agent = agentMap[agentId];
      const groupSessions = groups[agentId];
      const statusColor = agent?.status === 'published' ? T.green
        : agent?.status === 'archived' ? T.dim : T.amber;
      return (
        <div key={agentId}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 4px 2px', marginTop: 4 }}>
            {agent && <span style={{ width: 4, height: 4, borderRadius: '50%', background: statusColor, flexShrink: 0 }} />}
            <span className="upper" style={{ fontSize: 8, color: T.dim, letterSpacing: '.1em', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {agent?.name ?? 'Unknown agent'}
            </span>
            <div style={{ flex: 1, height: 1, background: T.border }} />
          </div>
          {groupSessions.map(s => renderSession(s))}
        </div>
      );
    });
  };

  return (
    <aside ref={asideRef} style={{
      width: 240, background: T.bg1, borderRight: `1px solid ${T.border}`,
      display: 'flex', flexDirection: 'column', flexShrink: 0, position: 'relative',
    }}>
      {/* Logo */}
      <div style={{ padding: '14px 16px 12px', display: 'flex', alignItems: 'center', gap: 10, borderBottom: `1px solid ${T.border}` }}>
        <Logo />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 600, letterSpacing: '-0.01em' }}>
            dialekt<span style={{ color: T.cyan }}>.ai</span>
          </div>
          <div className="mono" style={{ fontSize: 9, color: T.dim, letterSpacing: '.1em' }}>v0.8.2 · LOCAL</div>
        </div>
        <button
          className="dlk-btn ghost"
          style={{ padding: 4 }}
          title="New conversation"
          onClick={() => {
            onNewSession?.(selectedAgentId);
            onNav?.('empty');
          }}
        >
          <Icon name="plus" size={14} color={T.muted} />
        </button>
      </div>

      {/* Search */}
      <div style={{ padding: '10px 12px', borderBottom: `1px solid ${T.border}` }}>
        {searchOpen ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', background: T.bg0, border: `1px solid ${T.cyan}55`, borderRadius: 3 }}>
            <Icon name="search" size={12} color={T.cyan} />
            <input
              autoFocus
              value={search}
              onChange={e => setSearch(e.target.value)}
              onBlur={() => { if (!search) setSearchOpen(false); }}
              onKeyDown={e => {
                if (e.key === 'Escape') { setSearch(''); setSearchOpen(false); }
                if ((e.metaKey || e.ctrlKey) && e.key === 'k') { e.preventDefault(); onNav?.('palette'); }
              }}
              placeholder="find session…"
              style={{
                flex: 1, background: 'transparent', border: 'none', outline: 'none',
                fontFamily: T.mono, fontSize: 11, color: T.text, caretColor: T.cyan,
              }}
            />
            {search && (
              <div onClick={() => { setSearch(''); setSearchOpen(false); }} style={{ cursor: 'pointer' }}>
                <Icon name="x" size={10} color={T.dim} />
              </div>
            )}
          </div>
        ) : (
          <div
            onClick={() => onNav?.('palette')}
            style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', background: T.bg0, border: `1px solid ${T.border}`, borderRadius: 3, cursor: 'pointer' }}
          >
            <Icon name="search" size={12} color={T.dim} />
            <span className="mono" style={{ color: T.dim, fontSize: 11 }}>find…</span>
            <div style={{ flex: 1 }} />
            <span className="mono" style={{ color: T.dim, fontSize: 9, border: `1px solid ${T.border}`, padding: '1px 4px', borderRadius: 2 }}>⌘K</span>
          </div>
        )}
      </div>

      {/* My Agents — builder mode only */}
      {mode === 'builder' && (
        <div style={{ borderBottom: `1px solid ${T.border}` }}>
          <div
            style={{ padding: '8px 12px 4px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer' }}
            onClick={() => setAgentsOpen(o => !o)}
          >
            <span className="upper" style={{ color: T.dim }}>
              My Agents <span className="mono" style={{ color: T.dim }}>· {agents.length}</span>
            </span>
            <div style={{ display: 'flex', gap: 4 }}>
              <button
                className="dlk-btn ghost"
                style={{ padding: '2px 6px', fontSize: 9, letterSpacing: '.06em' }}
                title="Open agent wizard"
                onClick={e => { e.stopPropagation(); onNav?.('wizard'); }}
              >
                WIZARD
              </button>
              <button
                className="dlk-btn ghost"
                style={{ padding: 3 }}
                title="Quick create"
                onClick={e => { e.stopPropagation(); setShowNewAgent(v => !v); setAgentsOpen(true); }}
              >
                <Icon name="plus" size={10} color={T.muted} />
              </button>
            </div>
          </div>

          {agentsOpen && showNewAgent && (
            <div style={{ padding: '4px 8px 6px' }}>
              <form
                onSubmit={async e => {
                  e.preventDefault();
                  if (!newAgentName.trim()) return;
                  try {
                    await fetch(`${API}/agents`, {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ name: newAgentName.trim(), system_prompt: '' }),
                    });
                    setNewAgentName('');
                    setShowNewAgent(false);
                    loadAgents();
                  } catch {}
                }}
                style={{ display: 'flex', gap: 4 }}
              >
                <input
                  autoFocus
                  value={newAgentName}
                  onChange={e => setNewAgentName(e.target.value)}
                  placeholder="agent name…"
                  style={{
                    flex: 1, background: T.bg0, border: `1px solid ${T.cyan}55`,
                    outline: 'none', padding: '4px 7px',
                    fontFamily: T.mono, fontSize: 11, color: T.text, caretColor: T.cyan,
                  }}
                />
                <button type="submit" className="dlk-btn primary" style={{ padding: '3px 8px', fontSize: 10 }}>+</button>
              </form>
            </div>
          )}

          {agentsOpen && (
            <div style={{ padding: '0 8px 6px', display: 'flex', flexDirection: 'column', gap: 1 }}>
              {agents.length === 0 && (
                <div className="mono" style={{ padding: '10px', fontSize: 10, color: T.dim, textAlign: 'center' }}>
                  No agents yet
                </div>
              )}
              {agents.map(a => {
                const isSelected = a.id === selectedAgentId;
                const statusColor = a.status === 'published' ? T.green : a.status === 'archived' ? T.dim : T.amber;
                const mcpNames = Array.isArray(a.mcp_server_names) ? a.mcp_server_names : [];
                const hasMcp = mcpNames.length > 0;
                return (
                  <div
                    key={a.id}
                    onClick={() => selectAgent(selectedAgentId === a.id ? null : a.id)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 8,
                      padding: '6px 8px',
                      borderLeft: `2px solid ${isSelected ? T.cyan : 'transparent'}`,
                      background: isSelected ? T.bg2 : 'transparent',
                      cursor: 'pointer',
                    }}
                  >
                    <span style={{ width: 5, height: 5, borderRadius: '50%', background: statusColor, flexShrink: 0 }} />
                    <span style={{ fontSize: 11, color: isSelected ? T.text : T.muted, flex: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {a.name}
                    </span>
                    {hasMcp && (
                      <Icon
                        name="plug"
                        size={11}
                        color={isSelected ? T.cyan : T.muted}
                        title={`Uses MCP: ${mcpNames.join(', ')}`}
                      />
                    )}
                    {isSelected && <span className="mono" style={{ fontSize: 9, color: T.cyan }}>active</span>}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Sessions header */}
      <div style={{ padding: '10px 12px 4px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span className="upper" style={{ color: T.dim }}>
          Sessions <span className="mono" style={{ color: T.dim }}>· {sessions.length}</span>
        </span>
        <span className="mono" style={{ color: T.dim, fontSize: 9 }}>
          {mode === 'builder' ? 'by agent' : 'recent'}
        </span>
      </div>

      {/* Sessions list */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px' }}>
        {filtered.length === 0 && (
          <div className="mono" style={{ padding: '18px 10px', fontSize: 11, color: T.dim, textAlign: 'center' }}>
            {sessions.length === 0 ? 'No sessions yet' : 'No matches'}
          </div>
        )}
        {mode === 'builder' && filtered.length > 0 && renderGroupedSessions()}
        {mode !== 'builder' && filtered.map(s => renderSession(s))}
      </div>

      {/* Session hover tooltip */}
      {hoverId && (() => {
        const s = sessions.find(x => x.id === hoverId);
        if (!s) return null;
        return (
          <div style={{
            position: 'absolute', left: 244, top: Math.max(8, tooltipY),
            zIndex: 50, width: 280,
            background: T.bg0, border: `1px solid ${T.borderHi}`,
            boxShadow: '0 10px 30px rgba(0,0,0,.5)', padding: 12,
            pointerEvents: 'none',
          }}>
            <div className="upper" style={{ color: T.cyan, marginBottom: 6 }}>SESSION PREVIEW</div>
            <div style={{ fontSize: 12, color: T.text, marginBottom: 6, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {s.title || 'Untitled'}
            </div>
            <div className="mono" style={{ fontSize: 10, color: T.dim, lineHeight: 1.7 }}>
              <div>model · {shortModel(s.model)}</div>
              <div>msgs · {s.message_count}</div>
              <div>started · {timeAgo(s.created_at)}</div>
              <div>updated · {timeAgo(s.updated_at)}</div>
            </div>
          </div>
        );
      })()}

      {/* Model selector */}
      <div style={{ borderTop: `1px solid ${T.border}`, padding: '10px 12px', position: 'relative' }}>
        <div className="upper" style={{ color: T.dim, marginBottom: 6 }}>Model</div>
        <div
          onClick={() => setModelOpen(o => !o)}
          style={{
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '8px 10px', background: T.bg0,
            border: `1px solid ${modelOpen ? T.cyan + '88' : T.border}`,
            borderRadius: 3, cursor: 'pointer',
          }}
        >
          <span className={`dlk-dot${running ? ' cyan live' : ''}`} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="mono" style={{ fontSize: 11, color: T.text, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {shortModel(model)}
            </div>
            <div className="mono" style={{ fontSize: 9, color: T.dim }}>ollama · local</div>
          </div>
          <Icon name="chev" size={12} color={modelOpen ? T.cyan : T.dim} />
        </div>
        {modelOpen && models.length > 0 && (
          <div style={{
            position: 'absolute', left: 12, right: 12, bottom: '100%', marginBottom: 4,
            background: T.bg1, border: `1px solid ${T.cyan}55`,
            boxShadow: '0 -8px 24px rgba(0,0,0,.5)', zIndex: 100,
          }}>
            {models.map(m => {
              const short = shortModel(m);
              const isActive = short === shortModel(model) || m === model;
              return (
                <div
                  key={m}
                  onClick={() => { onModelSwitch?.(short); setModelOpen(false); }}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px',
                    borderBottom: `1px solid ${T.border}`,
                    background: isActive ? T.bg2 : 'transparent',
                    cursor: 'pointer',
                  }}
                >
                  <span className="dlk-dot" style={{ background: isActive ? T.cyan : T.dim }} />
                  <span className="mono" style={{ fontSize: 11, color: isActive ? T.text : T.muted, flex: 1 }}>{short}</span>
                  {isActive && <span className="mono" style={{ fontSize: 9, color: T.cyan }}>active</span>}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* System status */}
      <div style={{ borderTop: `1px solid ${T.border}`, padding: '10px 12px 12px', background: T.bg0 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <span className="upper" style={{ color: T.dim }}>System</span>
          <span className="mono" style={{ fontSize: 9, color: running ? T.green : T.amber }}>
            {running ? '◆ healthy' : '◆ offline'}
          </span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          <Meter label="CPU" value={sysStats.cpu} />
          <Meter label="RAM" value={sysStats.ram} />
          {sysStats.gpu !== null
            ? <Meter label="GPU" value={sysStats.gpu} warn={85} crit={95} />
            : <Meter label="GPU" value={0} />}
          <Meter label="DSK" value={sysStats.disk} />
        </div>
      </div>

      {/* Nav footer */}
      <div style={{ borderTop: `1px solid ${T.border}`, display: 'flex', background: T.bg1 }}>
        {[
          { icon: 'chat', screen: 'main', label: 'Chat' },
          { icon: 'cog', screen: 'settings', label: 'Settings' },
        ].map(({ icon, screen, label }) => (
          <button
            key={screen}
            className="dlk-btn ghost"
            onClick={() => onNav?.(screen)}
            style={{ flex: 1, padding: '10px 8px', borderRadius: 0, justifyContent: 'center', gap: 6, fontSize: 11, color: T.muted }}
            title={label}
          >
            <Icon name={icon} size={14} color={T.muted} />
            <span className="upper" style={{ fontSize: 9 }}>{label}</span>
          </button>
        ))}
      </div>
    </aside>
  );
}
