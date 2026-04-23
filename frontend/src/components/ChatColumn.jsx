import { useState, useRef, useEffect, useCallback } from 'react';
import { T } from '../tokens.js';
import Icon from './Icon.jsx';
import { Logo } from './Shell.jsx';

const API = 'http://localhost:8765';

// ── Helpers ───────────────────────────────────────────────────────

function fmt(ts) {
  return ts ? new Date(ts).toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' }) : '—';
}

// Group messages into user / ai-turn / confirmation blocks
function groupMessages(messages) {
  const groups = [];
  let i = 0;
  while (i < messages.length) {
    const m = messages[i];
    if (m.type === 'confirmation') {
      groups.push({ type: 'confirmation', msg: m });
      i++;
    } else if (m.role === 'user') {
      groups.push({ type: 'user', msg: m });
      i++;
    } else if (m.role === 'system' || m.type === 'error') {
      groups.push({ type: 'error', msg: m });
      i++;
    } else {
      // Collect consecutive assistant/tool messages into one AI turn
      const turn = [];
      while (
        i < messages.length &&
        messages[i].role !== 'user' &&
        messages[i].type !== 'confirmation' &&
        messages[i].role !== 'system' &&
        messages[i].type !== 'error'
      ) {
        turn.push(messages[i]);
        i++;
      }
      if (turn.length > 0) {
        groups.push({ type: 'ai', msgs: turn, id: turn[0].id });
      }
    }
  }
  return groups;
}

// ── Shared UI atoms ───────────────────────────────────────────────

function TaskChip({ label, warn }) {
  return (
    <span className="mono" style={{
      fontSize: 10, color: warn ? T.amber : T.muted,
      border: `1px solid ${warn ? T.amber + '44' : T.border}`,
      padding: '3px 6px', letterSpacing: '.06em',
    }}>{label}</span>
  );
}

function DayDivider({ children }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '4px 0 22px', color: T.dim }}>
      <div style={{ flex: 1, height: 1, background: T.border }} />
      <span className="mono" style={{ fontSize: 10, letterSpacing: '.12em' }}>{children}</span>
      <div style={{ flex: 1, height: 1, background: T.border }} />
    </div>
  );
}

function AttachChip({ icon, label }) {
  return (
    <span className="mono" style={{
      display: 'inline-flex', alignItems: 'center', gap: 5, padding: '3px 6px',
      background: T.bg0, border: `1px solid ${T.border}`, fontSize: 10, color: T.muted,
    }}>
      <Icon name={icon || 'file'} size={11} color={T.cyan} />{label}
    </span>
  );
}

// ── User bubble ───────────────────────────────────────────────────

function UserBubble({ content, ts }) {
  const lines = content.split('\n');
  const chips = [];
  const textLines = [];
  for (const line of lines) {
    const m = line.match(/^@(file|screenshot):(.+)$/);
    if (m) chips.push({ type: m[1], path: m[2].trim() });
    else textLines.push(line);
  }
  const cleanText = textLines.join('\n').trim();

  return (
    <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 28 }}>
      <div style={{ maxWidth: '78%' }}>
        <div className="upper" style={{ color: T.dim, textAlign: 'right', marginBottom: 6 }}>
          You · {ts}
        </div>
        <div style={{
          padding: '10px 14px', background: T.bg2,
          border: `1px solid ${T.border}`, borderRadius: 4,
          fontSize: 13, lineHeight: 1.55, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
        }}>
          {cleanText}
          {chips.length > 0 && (
            <div style={{ marginTop: 8, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {chips.map((c, i) => (
                <AttachChip key={i} icon={c.type === 'screenshot' ? 'screen' : 'file'} label={c.path.split('/').pop()} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Code / Console / Error atoms ──────────────────────────────────

function CodeBubble({ format, content, ts }) {
  const [copied, setCopied] = useState(false);
  const doCopy = () => {
    navigator.clipboard.writeText(content || '').then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  const lines = (content || '').split('\n');
  const isShort = lines.length <= 2;

  if (isShort && (format === 'shell' || format === 'bash' || format === 'sh' || format === 'python')) {
    return (
      <div style={{ marginBottom: 2 }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px',
          background: T.bg1, border: `1px solid ${T.border}`, borderLeft: `2px solid ${T.cyan}`,
        }}>
          <Icon name="terminal" size={13} color={T.cyan} />
          <span className="mono" style={{ fontSize: 11, color: T.cyan, letterSpacing: '.04em' }}>
            {format === 'python' ? 'python' : 'shell'}
          </span>
          <span style={{ color: T.border }}>·</span>
          <span className="mono" style={{ fontSize: 11, color: T.muted, flex: 1, whiteSpace: 'pre', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {lines[0]?.trim()}
          </span>
          <button className="dlk-btn ghost" style={{ padding: 2 }} onClick={doCopy} title="Copy">
            <Icon name="copy" size={11} color={copied ? T.green : T.dim} />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div style={{ border: `1px solid ${T.border}`, background: T.bg1 }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, padding: '6px 10px',
        borderBottom: `1px solid ${T.border}`, background: T.bg2,
      }}>
        <Icon name="file" size={12} color={T.cyan} />
        <span className="mono" style={{ fontSize: 10, color: T.text }}>{format || 'code'} block</span>
        <span className="mono" style={{ fontSize: 9, color: T.dim, border: `1px solid ${T.border}`, padding: '0 4px' }}>
          {format || 'text'}
        </span>
        <div style={{ flex: 1 }} />
        <span className="mono" style={{ fontSize: 10, color: T.dim }}>{ts}</span>
        <button className="dlk-btn ghost" style={{ padding: 2 }} onClick={doCopy} title="Copy">
          <Icon name="copy" size={11} color={copied ? T.green : T.dim} />
        </button>
      </div>
      <div style={{ padding: '8px 0', fontFamily: T.mono, fontSize: 11, lineHeight: 1.65 }}>
        {lines.map((line, i) => {
          const isAdd = line.startsWith('+') && !line.startsWith('+++');
          const isDel = line.startsWith('-') && !line.startsWith('---');
          return (
            <div key={i} style={{
              display: 'flex', gap: 10, padding: '0 10px',
              background: isAdd ? '#0c2a1f' : isDel ? '#2a0f12' : 'transparent',
              borderLeft: `2px solid ${isAdd ? T.green : isDel ? T.red : 'transparent'}`,
            }}>
              <span style={{ color: T.dim, width: 28, textAlign: 'right', userSelect: 'none', flexShrink: 0 }}>{i + 1}</span>
              <span style={{ color: isAdd ? T.green : isDel ? T.red : T.text, whiteSpace: 'pre', overflowX: 'auto' }}>{line}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const MEDIA_RE = /(\/[^\s'"`,\]]+\.(?:png|jpg|jpeg|gif|webp|mp4|webm|mov))/gi;
const VIDEO_EXT = /\.(mp4|webm|mov)$/i;

function extractMedia(text) {
  return [...new Set([...(text || '').matchAll(MEDIA_RE)].map(m => m[1]))];
}

function MediaBubble({ paths }) {
  if (!paths.length) return null;
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
      {paths.map(p => {
        const src = `${API}/files?path=${encodeURIComponent(p)}`;
        if (VIDEO_EXT.test(p)) return (
          <video key={p} src={src} controls style={{
            maxWidth: '100%', maxHeight: 360,
            border: `1px solid ${T.border}`, background: '#000',
          }} />
        );
        return (
          <img key={p} src={src} alt="" style={{
            maxWidth: '100%', maxHeight: 420,
            border: `1px solid ${T.border}`, cursor: 'pointer', display: 'block',
          }}
            onClick={() => window.open(src, '_blank')}
            onError={e => { e.target.style.display = 'none'; }}
          />
        );
      })}
    </div>
  );
}

function ConsoleBubble({ content }) {
  const isErr = /error|traceback|exception/i.test(content);
  const lines = (content || '').split('\n');
  const media = extractMedia(content);
  return (
    <div>
      <div style={{ border: `1px solid ${T.border}`, background: '#05080c' }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10, padding: '6px 10px',
          borderBottom: `1px solid ${T.border}`, background: T.bg2,
        }}>
          <Icon name="terminal" size={12} color={isErr ? T.red : T.green} />
          <span className="mono" style={{ fontSize: 10, color: T.text }}>output</span>
          {lines.length > 1 && (
            <span className="mono" style={{ fontSize: 9, color: T.dim }}>{lines.length} lines</span>
          )}
          <div style={{ flex: 1 }} />
          {isErr && <span className="mono" style={{ fontSize: 9, color: T.amber }}>exit 1</span>}
        </div>
        <pre style={{
          margin: 0, padding: '10px 12px', fontFamily: T.mono, fontSize: 11, lineHeight: 1.65,
          color: isErr ? '#ff8a8a' : '#9fefb4', overflowX: 'auto', maxHeight: 280,
          overflowY: lines.length > 20 ? 'auto' : 'visible',
        }}>{content}</pre>
      </div>
      {media.length > 0 && <MediaBubble paths={media} />}
    </div>
  );
}

function ErrorBubble({ content }) {
  return (
    <div style={{ marginBottom: 12, padding: '10px 14px', border: `1px solid ${T.amber}44`, background: '#2a1f0a', display: 'flex', gap: 10 }}>
      <Icon name="stop" size={14} color={T.amber} />
      <span className="mono" style={{ fontSize: 12, color: T.amber, lineHeight: 1.55 }}>{content}</span>
    </div>
  );
}

// ── AI group (one full turn with Logo header) ─────────────────────

function AIGroup({ msgs, streaming, activeModel, streamingMsgId, onContextMenu }) {
  const firstTs = fmt(msgs[0]?.ts || Date.now());
  const isLiveStream = streaming;

  return (
    <div
      style={{ display: 'flex', gap: 12, marginBottom: 28, position: 'relative' }}
      onContextMenu={e => { e.preventDefault(); onContextMenu?.(e, msgs); }}
    >
      <div style={{ flexShrink: 0 }}><Logo /></div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
          <span className="upper" style={{ color: T.text }}>dialekt</span>
          <span className="mono" style={{ fontSize: 10, color: T.dim }}>
            {activeModel || 'gemma3-12b'} · {firstTs}
          </span>
          {isLiveStream && (
            <>
              <span className="dlk-dot cyan live" />
              <span className="mono" style={{ fontSize: 10, color: T.cyan }}>working</span>
            </>
          )}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {msgs.map(m => {
            if (m.type === 'message') {
              const media = extractMedia(m.content);
              return (
                <div key={m.id}>
                  <div style={{ fontSize: 13, lineHeight: 1.65, color: T.text, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                    {m.content}
                    {isLiveStream && m.id === streamingMsgId && <span className="dlk-caret" style={{ display: 'inline-block' }} />}
                  </div>
                  {media.length > 0 && <MediaBubble paths={media} />}
                </div>
              );
            }
            if (m.type === 'code') return <CodeBubble key={m.id} format={m.format} content={m.content} ts={fmt(m.ts)} />;
            if (m.type === 'console') return <ConsoleBubble key={m.id} content={m.content} />;
            return null;
          })}

          {/* Streaming indicator inside the bubble when active but last msg isn't a text msg */}
          {isLiveStream && msgs[msgs.length - 1]?.type !== 'message' && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px',
              background: T.bg1, border: `1px dashed ${T.cyan}88`,
            }}>
              <span className="dlk-dot cyan live" />
              <span className="mono" style={{ fontSize: 11, color: T.cyan, letterSpacing: '.06em', textTransform: 'uppercase' }}>stream</span>
              <span className="dlk-caret" />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Standalone streaming indicator (before first AI chunk) ────────

function StreamingIndicator() {
  return (
    <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
      <div style={{ flexShrink: 0 }}><Logo /></div>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px',
        background: T.bg1, border: `1px dashed ${T.cyan}88`,
      }}>
        <span className="dlk-dot cyan live" />
        <span className="mono" style={{ fontSize: 11, color: T.cyan, letterSpacing: '.06em', textTransform: 'uppercase' }}>stream</span>
        <span className="dlk-caret" />
      </div>
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────

function EmptyState() {
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: T.dim }}>
      <div style={{ width: 40, height: 40, border: `1px solid ${T.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 14 }}>
        <svg width="22" height="22" viewBox="0 0 18 18" fill="none">
          <path d="M2 9 L9 2 L16 9 L9 16 Z" stroke={T.dim} strokeWidth="1.1" />
          <circle cx="9" cy="9" r="2" fill={T.dim} />
        </svg>
      </div>
      <div className="mono" style={{ fontSize: 11, letterSpacing: '.1em' }}>NEW SESSION</div>
      <div style={{ fontSize: 12, color: T.dim, marginTop: 6 }}>Type a message to begin</div>
    </div>
  );
}

// ── Confirmation modal overlay ─────────────────────────────────────

function ConfirmationModal({ content, code, onApprove, onDeny }) {
  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 20 }}>
      <div style={{ position: 'absolute', inset: 0, background: 'rgba(5,8,12,.72)', backdropFilter: 'blur(3px)' }} />
      <div style={{
        position: 'absolute', top: 60, left: '50%', transform: 'translateX(-50%)',
        width: 580, maxWidth: 'calc(100% - 40px)',
      }}>
        <div style={{ border: `1px solid ${T.amber}66`, background: T.bg1, boxShadow: '0 24px 80px rgba(0,0,0,.6)' }}>
          {/* Header */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px',
            borderBottom: `1px solid ${T.border}`, background: '#2a1f0a',
          }}>
            <span className="mono" style={{ fontSize: 10, color: T.amber, letterSpacing: '.14em' }}>△ PERMISSION REQUEST</span>
            <div style={{ flex: 1 }} />
            <span className="mono" style={{ fontSize: 10, color: T.dim }}>tool · exec</span>
          </div>

          {/* Body */}
          <div style={{ padding: '20px 20px 12px' }}>
            <div style={{ fontSize: 14, fontWeight: 500, marginBottom: 4 }}>
              {content || 'Run this code?'}
            </div>
            <div style={{ fontSize: 12, color: T.muted }}>
              dialekt wants to execute the following command.
            </div>
          </div>

          {/* Code preview */}
          {code && (
            <div style={{ margin: '0 20px 16px', padding: 12, background: '#05080c', border: `1px solid ${T.border}`, fontFamily: T.mono, fontSize: 12 }}>
              <pre style={{ margin: 0, color: T.text, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 180, overflowY: 'auto' }}>{code}</pre>
            </div>
          )}

          {/* Footer */}
          <div style={{
            padding: '12px 20px', borderTop: `1px solid ${T.border}`,
            display: 'flex', alignItems: 'center', gap: 8,
          }}>
            <div style={{ flex: 1 }} />
            <button className="dlk-btn" onClick={onDeny}>Deny</button>
            <button className="dlk-btn" onClick={onApprove}>Allow once</button>
            <button
              className="dlk-btn primary"
              style={{ padding: '6px 14px' }}
              onClick={onApprove}
            >
              Allow · run <span className="mono" style={{ fontSize: 10, opacity: .7, marginLeft: 4 }}>⌘↵</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Context menu ──────────────────────────────────────────────────

function ContextMenu({ x, y, msgs, onClose }) {
  const ref = useRef(null);

  useEffect(() => {
    const fn = (e) => { if (!ref.current?.contains(e.target)) onClose(); };
    document.addEventListener('mousedown', fn);
    return () => document.removeEventListener('mousedown', fn);
  }, [onClose]);

  const textContent = msgs?.filter(m => m.type === 'message').map(m => m.content).join('\n\n') || '';

  const sections = [
    { items: [
      { icon: 'copy', label: 'Copy message', kbd: '⌘C', action: () => navigator.clipboard.writeText(textContent).catch(() => {}) },
      { icon: 'copy', label: 'Copy as markdown', action: () => {
        const md = msgs?.map(m => {
          if (m.type === 'message') return m.content;
          if (m.type === 'code') return `\`\`\`${m.format || ''}\n${m.content}\n\`\`\``;
          if (m.type === 'console') return `\`\`\`\n${m.content}\n\`\`\``;
          return '';
        }).filter(Boolean).join('\n\n');
        navigator.clipboard.writeText(md || '').catch(() => {});
      }},
      { icon: 'file', label: 'Save to file…', action: () => {
        const blob = new Blob([textContent], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a'); a.href = url; a.download = 'message.txt'; a.click(); URL.revokeObjectURL(url);
      }},
    ]},
    { label: 'Act', items: [
      { icon: 'refresh', label: 'Regenerate', kbd: '⌘R', action: onClose },
      { icon: 'sparkle', label: 'Continue from here', action: onClose },
    ]},
    { label: 'Revise', items: [
      { icon: 'search', label: 'Make more concise', action: onClose },
      { icon: 'search', label: 'Explain step-by-step', action: onClose },
      { icon: 'chat', label: 'Branch conversation', action: onClose },
    ]},
    { last: true, items: [
      { icon: 'x', label: 'Delete message', danger: true, action: onClose },
    ]},
  ];

  // Clamp to viewport
  const style = {
    position: 'fixed',
    left: Math.min(x, window.innerWidth - 260),
    top: Math.min(y, window.innerHeight - 320),
    width: 240,
    background: T.bg1,
    border: `1px solid ${T.borderHi}`,
    boxShadow: '0 16px 40px rgba(0,0,0,.5)',
    zIndex: 200,
  };

  return (
    <div ref={ref} style={style}>
      {sections.map((sec, si) => (
        <div key={si} style={{ borderBottom: sec.last ? 'none' : `1px solid ${T.border}`, padding: '4px 0' }}>
          {sec.label && (
            <div className="upper" style={{ color: T.dim, padding: '4px 12px 2px', fontSize: 9 }}>{sec.label}</div>
          )}
          {sec.items.map((it, ii) => (
            <div
              key={ii}
              onClick={() => { it.action?.(); onClose(); }}
              onMouseEnter={e => e.currentTarget.style.background = T.bg2}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
              style={{
                display: 'flex', alignItems: 'center', gap: 10, padding: '6px 12px',
                cursor: 'pointer', fontSize: 12,
                color: it.danger ? T.red : T.muted,
              }}
            >
              <Icon name={it.icon} size={12} color={it.danger ? T.red : T.dim} />
              <span style={{ flex: 1 }}>{it.label}</span>
              {it.kbd && <span className="mono" style={{ fontSize: 10, color: T.dim }}>{it.kbd}</span>}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

// ── Ham dropdown menu ─────────────────────────────────────────────

function HamMenu({ sessionId, sessionTitle, messages, onNewSession, onRenameSuccess }) {
  const [open, setOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [renameVal, setRenameVal] = useState('');
  const menuRef = useRef(null);
  const renameRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    const fn = (e) => { if (!menuRef.current?.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', fn);
    return () => document.removeEventListener('mousedown', fn);
  }, [open]);

  useEffect(() => {
    if (renaming) { setRenameVal(sessionTitle || ''); renameRef.current?.focus(); }
  }, [renaming, sessionTitle]);

  const doRename = async () => {
    const title = renameVal.trim();
    if (!title || !sessionId) return setRenaming(false);
    await fetch(`${API}/sessions/${sessionId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    }).catch(() => {});
    onRenameSuccess?.(title);
    setRenaming(false);
    setOpen(false);
  };

  const doExport = () => {
    const lines = messages.map(m => {
      if (m.role === 'user' && m.type === 'message') return `**You:** ${m.content}`;
      if (m.type === 'code') return `\`\`\`${m.format || ''}\n${m.content}\n\`\`\``;
      if (m.type === 'console') return `**Output:**\n\`\`\`\n${m.content}\n\`\`\``;
      if (m.role === 'assistant' && m.type === 'message') return `**dialekt:** ${m.content}`;
      return null;
    }).filter(Boolean).join('\n\n');
    const blob = new Blob([lines], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${(sessionTitle || 'session').replace(/[^a-z0-9]/gi, '-')}.md`;
    a.click();
    URL.revokeObjectURL(url);
    setOpen(false);
  };

  const items = [
    { icon: 'edit', label: 'Rename session', action: () => { setOpen(false); setRenaming(true); } },
    { icon: 'download', label: 'Export as .md', action: doExport },
    { icon: 'copy', label: 'Copy all messages', action: () => {
      const text = messages.filter(m => m.type === 'message').map(m => `${m.role === 'user' ? 'You' : 'dialekt'}: ${m.content}`).join('\n\n');
      navigator.clipboard.writeText(text).catch(() => {});
      setOpen(false);
    }},
    { sep: true },
    { icon: 'sparkle', label: 'New session', action: () => { setOpen(false); onNewSession?.(); } },
  ];

  return (
    <div ref={menuRef} style={{ position: 'relative' }}>
      {renaming ? (
        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <input
            ref={renameRef}
            value={renameVal}
            onChange={e => setRenameVal(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') doRename(); if (e.key === 'Escape') setRenaming(false); }}
            style={{
              background: T.bg0, border: `1px solid ${T.cyan}`, outline: 'none',
              color: T.text, fontFamily: T.mono, fontSize: 11, padding: '3px 6px', width: 180,
            }}
          />
          <button className="dlk-btn ghost" style={{ padding: '3px 6px', fontSize: 10 }} onClick={doRename}>ok</button>
          <button className="dlk-btn ghost" style={{ padding: '3px 6px', fontSize: 10 }} onClick={() => setRenaming(false)}>✕</button>
        </div>
      ) : (
        <button className="dlk-btn ghost" style={{ padding: 4 }} onClick={() => setOpen(o => !o)} title="Session menu">
          <Icon name="ham" size={13} color={open ? T.cyan : T.muted} />
        </button>
      )}

      {open && (
        <div style={{
          position: 'absolute', top: '100%', right: 0, marginTop: 4,
          background: T.bg2, border: `1px solid ${T.border}`, minWidth: 180, zIndex: 100,
          boxShadow: '0 8px 24px rgba(0,0,0,.5)',
        }}>
          {items.map((item, i) => item.sep ? (
            <div key={i} style={{ height: 1, background: T.border, margin: '4px 0' }} />
          ) : (
            <div
              key={i}
              onClick={item.action}
              style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', cursor: 'pointer', fontSize: 12, color: T.text }}
              onMouseEnter={e => e.currentTarget.style.background = T.bg1}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >
              <Icon name={item.icon} size={12} color={T.muted} />
              {item.label}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Autonomy picker ───────────────────────────────────────────────

const AUTONOMY_LEVELS = [
  { key: 'ask',       label: 'ask',              desc: 'Confirm before every code block' },
  { key: 'ask-write', label: 'ask before write',  desc: 'Auto-run reads, confirm writes/deletes' },
  { key: 'auto',      label: 'auto',              desc: 'Run everything automatically' },
];

function AutonomyPicker({ value, onChange }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    const fn = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', fn);
    return () => document.removeEventListener('mousedown', fn);
  }, [open]);

  const current = AUTONOMY_LEVELS.find(l => l.key === value) || AUTONOMY_LEVELS[1];

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <span
        className="mono"
        onClick={() => setOpen(o => !o)}
        style={{ fontSize: 10, color: T.dim, cursor: 'pointer', userSelect: 'none' }}
      >
        autonomy:{' '}
        <span style={{ color: T.amber, textDecoration: 'underline', textUnderlineOffset: 3 }}>
          {current.label}
        </span>
      </span>
      {open && (
        <div style={{
          position: 'absolute', bottom: '100%', left: 0, marginBottom: 6,
          background: T.bg2, border: `1px solid ${T.border}`, zIndex: 100,
          boxShadow: '0 -8px 24px rgba(0,0,0,.5)', minWidth: 220,
        }}>
          <div className="upper" style={{ padding: '8px 12px 4px', fontSize: 9, color: T.dim, borderBottom: `1px solid ${T.border}` }}>
            Autonomy level
          </div>
          {AUTONOMY_LEVELS.map(lv => (
            <div
              key={lv.key}
              onClick={() => { onChange?.(lv.key); setOpen(false); }}
              style={{
                padding: '8px 12px', cursor: 'pointer',
                background: lv.key === value ? T.bg1 : 'transparent',
                borderLeft: `2px solid ${lv.key === value ? T.amber : 'transparent'}`,
              }}
              onMouseEnter={e => e.currentTarget.style.background = T.bg1}
              onMouseLeave={e => e.currentTarget.style.background = lv.key === value ? T.bg1 : 'transparent'}
            >
              <div className="mono" style={{ fontSize: 11, color: lv.key === value ? T.amber : T.text }}>
                {lv.label}
                {lv.key === value && <span style={{ color: T.cyan, marginLeft: 6 }}>✓</span>}
              </div>
              <div style={{ fontSize: 10, color: T.dim, marginTop: 2 }}>{lv.desc}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Composer ──────────────────────────────────────────────────────

function Composer({ onSend, streaming, connected, autonomy, onAutonomyChange, messages }) {
  const [text, setText] = useState('');
  const [uploading, setUploading] = useState(false);
  const taRef = useRef(null);
  const fileRef = useRef(null);

  const appendText = (str) => {
    setText(t => t ? t + '\n' + str : str);
    setTimeout(() => taRef.current?.focus(), 50);
  };

  const submit = useCallback(() => {
    const t = text.trim();
    if (!t || streaming || !connected) return;
    // onSend may be wrapped by parent to inject activeAgentId — pass text only here.
    onSend(t);
    setText('');
    if (taRef.current) taRef.current.style.height = 'auto';
  }, [text, streaming, connected, onSend]);

  const onKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
  };

  const autoResize = (e) => {
    e.target.style.height = 'auto';
    e.target.style.height = Math.min(e.target.scrollHeight, 200) + 'px';
    setText(e.target.value);
  };

  const onFiles = async (e) => {
    const files = Array.from(e.target.files || []);
    e.target.value = '';
    if (!files.length) return;
    setUploading(true);
    for (const f of files) {
      try {
        const fd = new FormData();
        fd.append('file', f, f.name);
        const res = await fetch(`${API}/upload`, { method: 'POST', body: fd });
        const { path } = await res.json();
        appendText(`@file:${path}`);
      } catch {
        appendText(`@file:${f.name}`);
      }
    }
    setUploading(false);
  };

  const handleScreen = async () => {
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 1 }, audio: false });
      const track = stream.getVideoTracks()[0];
      const capture = new ImageCapture(track);
      const bitmap = await capture.grabFrame();
      track.stop();
      stream.getTracks().forEach(t => t.stop());
      const canvas = document.createElement('canvas');
      canvas.width = bitmap.width; canvas.height = bitmap.height;
      canvas.getContext('2d').drawImage(bitmap, 0, 0);
      canvas.toBlob(async (blob) => {
        try {
          const fd = new FormData();
          fd.append('file', blob, 'screenshot.png');
          const res = await fetch(`${API}/upload`, { method: 'POST', body: fd });
          const { path } = await res.json();
          appendText(`@screenshot:${path}`);
        } catch { appendText('@screenshot:failed'); }
      }, 'image/png');
    } catch (err) {
      if (err.name !== 'NotAllowedError') appendText(`[screen capture error: ${err.message}]`);
    }
  };

  const handleTerminal = async () => {
    await fetch(`${API}/terminal`, { method: 'POST' }).catch(() => {});
  };

  const contextChips = [];
  for (const line of text.split('\n')) {
    const m = line.match(/^@(file|screenshot):(.+)$/);
    if (m) contextChips.push({ type: m[1], label: m[2].split('/').pop() });
  }

  const msgCount = messages?.length || 0;
  const approxTokens = msgCount * 120;

  return (
    <div style={{ borderTop: `1px solid ${T.border}`, padding: '14px 28px 18px', background: T.bg1, flexShrink: 0 }}>
      <input ref={fileRef} type="file" multiple style={{ display: 'none' }} onChange={onFiles} />
      <div style={{ maxWidth: 820, margin: '0 auto' }}>
        {contextChips.length > 0 && (
          <div style={{ display: 'flex', gap: 6, marginBottom: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            {contextChips.slice(0, 3).map((c, i) => (
              <AttachChip key={i} icon={c.type === 'screenshot' ? 'screen' : 'file'} label={c.label} />
            ))}
            {contextChips.length > 3 && (
              <span className="mono" style={{ fontSize: 10, color: T.dim }}>+ {contextChips.length - 3} more</span>
            )}
            <div style={{ flex: 1 }} />
            <span className="mono" style={{ fontSize: 10, color: T.dim }}>
              {approxTokens.toLocaleString()} / 128k ctx
            </span>
          </div>
        )}

        <div style={{ border: `1px solid ${connected ? T.borderHi : T.border}`, background: T.bg0, borderRadius: 3 }}>
          <textarea
            ref={taRef}
            value={text}
            onChange={autoResize}
            onKeyDown={onKey}
            disabled={streaming}
            placeholder={streaming ? 'dialekt is working…' : '› Ask, instruct, paste a trace…'}
            rows={1}
            style={{
              display: 'block', width: '100%', boxSizing: 'border-box',
              background: 'transparent', border: 'none', outline: 'none',
              fontFamily: T.mono, fontSize: 13, color: streaming ? T.dim : T.text,
              padding: '12px 14px', resize: 'none', lineHeight: 1.55,
              caretColor: T.cyan, minHeight: 44,
            }}
          />
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px', borderTop: `1px solid ${T.border}` }}>
            <button className="dlk-btn ghost" style={{ padding: '4px 6px', opacity: uploading ? 0.5 : 1 }} onClick={() => fileRef.current?.click()} disabled={uploading} title="Attach file">
              <Icon name="attach" size={13} color={T.muted} />
            </button>
            <button className="dlk-btn ghost" style={{ padding: '4px 6px' }} onClick={handleScreen} title="Capture screenshot">
              <Icon name="screen" size={13} color={T.muted} />
            </button>
            <button className="dlk-btn ghost" style={{ padding: '4px 6px' }} onClick={handleTerminal} title="Open terminal">
              <Icon name="terminal" size={13} color={T.muted} />
            </button>
            <div style={{ width: 1, height: 16, background: T.border, margin: '0 2px' }} />
            <div style={{ flex: 1 }} />
            {!connected && <span className="mono" style={{ fontSize: 10, color: T.amber }}>backend offline</span>}
            {uploading && <span className="mono" style={{ fontSize: 10, color: T.cyan }}>uploading…</span>}
            <span className="mono" style={{ fontSize: 10, color: T.dim }}>⇧⏎ newline</span>
            <button
              className="dlk-btn primary"
              style={{ padding: '5px 12px', opacity: (!text.trim() || streaming || !connected) ? 0.4 : 1 }}
              onClick={submit}
              disabled={!text.trim() || streaming || !connected}
            >
              {streaming ? 'Working…' : 'Send'}{' '}
              <span className="mono" style={{ fontSize: 10, opacity: .7, marginLeft: 4 }}>⏎</span>
            </button>
          </div>
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }}>
          <AutonomyPicker value={autonomy} onChange={onAutonomyChange} />
          <span className="mono" style={{ fontSize: 10, color: T.dim }}>
            {connected
              ? <><span style={{ color: T.green }}>◆</span> inference local · 0 tokens sent to cloud</>
              : <><span style={{ color: T.amber }}>◆</span> connecting to backend…</>}
          </span>
        </div>
      </div>
    </div>
  );
}

// ── Main export ───────────────────────────────────────────────────

export default function ChatColumn({
  messages = [], streaming = false, connected = false,
  sessionTitle, sessionId, autonomy = 'ask-write', activeModel,
  onSend, onStop, onNewSession, onSessionTitleChange, onAutonomyChange, onConfirm,
}) {
  const bottomRef = useRef(null);
  const [ctxMenu, setCtxMenu] = useState(null); // {x, y, msgs}

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streaming]);

  // Find active confirmation (if any)
  const confirmMsg = messages.find(m => m.type === 'confirmation');

  // Group non-confirmation messages
  const displayMessages = messages.filter(m => m.type !== 'confirmation');
  const groups = groupMessages(displayMessages);

  // Find the currently streaming message id (for caret)
  const lastMsg = messages[messages.length - 1];
  const streamingMsgId = streaming && lastMsg?.type === 'message' ? lastMsg.id : null;

  const toolCount = messages.filter(m => m.type === 'code' || m.type === 'console').length;
  const now = fmt(Date.now());
  const title = sessionTitle || (messages.length ? 'Session active' : 'New conversation');

  const handleContextMenu = useCallback((e, msgs) => {
    e.preventDefault();
    setCtxMenu({ x: e.clientX, y: e.clientY, msgs });
  }, []);

  return (
    <main style={{ flex: 1, display: 'flex', flexDirection: 'column', background: T.bg0, minWidth: 0, position: 'relative' }}>
      {/* Context menu */}
      {ctxMenu && (
        <ContextMenu
          x={ctxMenu.x}
          y={ctxMenu.y}
          msgs={ctxMenu.msgs}
          onClose={() => setCtxMenu(null)}
        />
      )}

      {/* Confirmation modal overlay */}
      {confirmMsg && (
        <ConfirmationModal
          content={confirmMsg.content}
          code={confirmMsg.code}
          onApprove={() => onConfirm?.(confirmMsg.id, true)}
          onDeny={() => onConfirm?.(confirmMsg.id, false)}
        />
      )}

      {/* Header */}
      <header style={{
        height: 44, display: 'flex', alignItems: 'center', gap: 14,
        borderBottom: `1px solid ${T.border}`, padding: '0 18px', background: T.bg1, flexShrink: 0,
      }}>
        <span className="mono" style={{ color: T.cyan, fontSize: 10, letterSpacing: '.14em' }}>02 //</span>

        <div style={{ minWidth: 0 }}>
          <div style={{
            fontSize: 13, fontWeight: 500, color: messages.length ? T.text : T.dim,
            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 320,
          }}>
            {title}
          </div>
          {messages.length > 0 && (
            <div className="mono" style={{ fontSize: 10, color: T.dim }}>
              {activeModel || 'gemma3-12b'} · <span style={{ color: T.muted }}>local · ollama</span>
            </div>
          )}
        </div>

        <div style={{ flex: 1 }} />

        {toolCount > 0 && <TaskChip label={`${toolCount} tools`} />}
        {streaming && <TaskChip label="working…" warn />}

        <div style={{ width: 1, height: 20, background: T.border, margin: '0 4px' }} />

        {streaming && (
          <button className="dlk-btn ghost" style={{ padding: 4 }} onClick={onStop} title="Stop generation">
            <Icon name="stop" size={13} color={T.amber} />
          </button>
        )}
        <button
          className="dlk-btn ghost"
          style={{ padding: 4, opacity: streaming ? 0.4 : 1 }}
          onClick={() => window.location.reload()}
          title="Reload"
        >
          <Icon name="refresh" size={13} color={T.muted} />
        </button>
        <HamMenu
          sessionId={sessionId}
          sessionTitle={sessionTitle}
          messages={messages}
          onNewSession={onNewSession}
          onRenameSuccess={onSessionTitleChange}
        />
      </header>

      {/* Messages */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '22px 0', display: 'flex', flexDirection: 'column' }}>
        {groups.length === 0 && !streaming ? (
          <EmptyState />
        ) : (
          <div style={{ maxWidth: 820, margin: '0 auto', padding: '0 28px', width: '100%' }}>
            <DayDivider>Today · {now}</DayDivider>

            {groups.map((g, gi) => {
              const isLastGroup = gi === groups.length - 1;
              const ts = fmt(g.msg?.ts || g.msgs?.[0]?.ts || Date.now());

              if (g.type === 'user') {
                return <UserBubble key={g.msg.id} content={g.msg.content} ts={ts} />;
              }

              if (g.type === 'error') {
                return <ErrorBubble key={g.msg.id} content={g.msg.content} />;
              }

              if (g.type === 'ai') {
                return (
                  <AIGroup
                    key={g.id}
                    msgs={g.msgs}
                    streaming={streaming && isLastGroup}
                    activeModel={activeModel}
                    streamingMsgId={streamingMsgId}
                    onContextMenu={handleContextMenu}
                  />
                );
              }

              return null;
            })}

            {/* Standalone streaming indicator — before first AI chunk arrives */}
            {streaming && groups.length > 0 && groups[groups.length - 1]?.type === 'user' && (
              <StreamingIndicator />
            )}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <Composer
        onSend={onSend}
        streaming={streaming}
        connected={connected}
        autonomy={autonomy}
        onAutonomyChange={onAutonomyChange}
        messages={messages}
      />
    </main>
  );
}
