import { useState, useEffect, useRef } from 'react';
import { T } from '../tokens.js';
import Icon from './Icon.jsx';
import { SectionLabel } from './Shell.jsx';

// ── helpers ────────────────────────────────────────────────────────

function fmtElapsed(ms) {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2,'0')}:${String(s % 60).padStart(2,'0')}`;
}

const KIND_META = {
  code:      { icon: 'terminal', label: 'code' },
  'shell.out':{ icon: 'terminal', label: 'shell' },
  error:     { icon: 'stop',     label: 'error' },
  thinking:  { icon: 'sparkle',  label: 'thinking' },
};

// ── ActivityRow ────────────────────────────────────────────────────

function ActivityRow({ item, isLast }) {
  const { status, kind, headline, detail, warn, live, diff } = item;
  const meta = KIND_META[kind] || { icon: 'chat', label: kind };
  const statusColor = warn   ? T.amber
                    : live   ? T.cyan
                    : status === 'done' ? T.green
                    : T.dim;
  const statusLabel = warn   ? 'warn'
                    : live   ? 'exec'
                    : status === 'fail' ? 'fail'
                    : 'done';
  const dotClass = live ? 'cyan live' : '';

  return (
    <div style={{
      padding: '10px 14px',
      borderBottom: `1px solid ${T.border}`,
      background: live ? T.bg2 : 'transparent',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span
          className={`dlk-dot ${dotClass}`}
          style={{ background: warn ? T.amber : live ? undefined : status === 'fail' ? T.red : status === 'done' ? T.green : T.dim }}
        />
        <Icon name={meta.icon} size={13} color={live ? T.cyan : warn ? T.amber : T.muted} />
        <span className="mono" style={{ fontSize: 10, color: statusColor, width: 40, letterSpacing: '.08em' }}>
          {statusLabel}
        </span>
        <span className="mono" style={{ fontSize: 10, color: T.dim, marginLeft: 'auto' }}>
          {meta.label}
        </span>
      </div>

      <div style={{ marginTop: 4, paddingLeft: 22, display: 'flex', flexDirection: 'column', gap: 2 }}>
        <div className="mono" style={{
          fontSize: 11,
          color: live ? T.text : status === 'fail' || warn ? T.amber : T.text,
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        }}>
          {headline}
          {live && <span className="dlk-caret" style={{ marginLeft: 4 }} />}
        </div>
        {detail && (
          <div className="mono" style={{ fontSize: 10, color: T.dim }}>{detail}</div>
        )}
      </div>

      {/* Inline diff for code blocks */}
      {diff && (
        <div style={{ marginTop: 8, marginLeft: 22, padding: 8, background: T.bg0, border: `1px solid ${T.border}` }} className="mono">
          {diff.map((line, i) => (
            <div key={i} style={{ fontSize: 10, color: line.startsWith('+') ? T.green : line.startsWith('-') ? T.red : T.muted, lineHeight: 1.6 }}>
              {line}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── EmptyState ─────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 24, gap: 10 }}>
      <div style={{ width: 36, height: 36, border: `1px solid ${T.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Icon name="cpu" size={18} color={T.dim} />
      </div>
      <div className="mono" style={{ fontSize: 10, color: T.dim, letterSpacing: '.1em', textTransform: 'uppercase', textAlign: 'center' }}>
        No activity yet
      </div>
      <div style={{ fontSize: 11, color: T.dim, textAlign: 'center', lineHeight: 1.5 }}>
        Agent actions — file reads, shell commands, browser calls — will appear here in real time.
      </div>
    </div>
  );
}

// ── StepProgress ───────────────────────────────────────────────────

function StepProgress({ done, total, pct }) {
  return (
    <div style={{ marginTop: 8, height: 3, background: T.bg0, border: `1px solid ${T.border}` }}>
      <div style={{ height: '100%', width: `${pct}%`, background: T.cyan, transition: 'width .4s ease' }} />
    </div>
  );
}

// ── Main export ────────────────────────────────────────────────────

export default function RightPanel({ messages = [], streaming = false, collapsed = false, onToggle }) {
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef(null);

  // Derived data from messages
  const userMessages  = messages.filter(m => m.role === 'user' && m.type === 'message');
  const toolMessages  = messages.filter(m => m.type === 'code' || m.type === 'console' || m.type === 'error');
  const currentTask   = userMessages[userMessages.length - 1]?.content || null;
  const warnCount     = messages.filter(m => m.type === 'error' || (m.type === 'console' && /error|traceback|exception/i.test(m.content))).length;
  const totalSteps    = toolMessages.length + (streaming ? 1 : 0);
  const doneSteps     = toolMessages.length;
  const pct           = totalSteps > 0 ? Math.round((doneSteps / totalSteps) * 100) : 0;

  // Elapsed timer — starts on first message, ticks while streaming
  useEffect(() => {
    if (messages.length > 0 && !startRef.current) {
      startRef.current = Date.now();
    }
    if (messages.length === 0) {
      startRef.current = null;
      setElapsed(0);
    }
  }, [messages.length]);

  useEffect(() => {
    if (!streaming) return;
    const t = setInterval(() => {
      if (startRef.current) setElapsed(Date.now() - startRef.current);
    }, 500);
    return () => clearInterval(t);
  }, [streaming]);

  // Build activity items from messages
  const activityItems = toolMessages.map((m, idx) => {
    const isLatest = idx === toolMessages.length - 1;
    const linesArr  = m.content?.split('\n') || [];
    const lineCount = linesArr.length;

    if (m.type === 'code') {
      const headline = linesArr.find(l => l.trim()) || `${m.format || 'code'} block`;
      const diff = lineCount <= 12
        ? linesArr.slice(0, 12).map(l => l.startsWith('+') || l.startsWith('-') ? l : `  ${l}`)
        : null;
      return {
        kind: 'code',
        status: 'done',
        headline: headline.slice(0, 70),
        detail: `${lineCount} lines · ${m.format || 'code'}`,
        diff: diff && diff.some(l => l.startsWith('+') || l.startsWith('-')) ? diff : null,
      };
    }

    if (m.type === 'console') {
      const hasErr = /error|traceback|exception/i.test(m.content);
      const headline = linesArr[0]?.trim() || 'shell output';
      return {
        kind: 'shell.out',
        status: hasErr ? 'fail' : 'done',
        headline: headline.slice(0, 70),
        detail: lineCount > 1 ? `${lineCount} lines` : '',
        warn: hasErr,
      };
    }

    if (m.type === 'error') {
      return {
        kind: 'error',
        status: 'fail',
        headline: m.content?.slice(0, 70) || 'error',
        detail: '',
        warn: true,
      };
    }

    return null;
  }).filter(Boolean);

  // While streaming — add a live "thinking" item at the end
  if (streaming) {
    activityItems.push({
      kind: 'thinking',
      status: 'run',
      headline: 'Processing…',
      detail: '',
      live: true,
    });
  }

  const hasActivity = activityItems.length > 0 || currentTask;

  if (collapsed) {
    return (
      <aside style={{
        width: 32, minWidth: 32, background: T.bg1,
        borderLeft: `1px solid ${T.border}`,
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        paddingTop: 10, gap: 8, flexShrink: 0,
      }}>
        <button
          className="dlk-btn ghost"
          style={{ padding: 4, transform: 'rotate(180deg)' }}
          onClick={onToggle}
          title="Expand panel"
        >
          <Icon name="chevR" size={12} color={T.muted} />
        </button>
        {streaming && <span className="dlk-dot cyan live" style={{ marginTop: 4 }} />}
      </aside>
    );
  }

  return (
    <aside style={{
      width: 320, background: T.bg1, borderLeft: `1px solid ${T.border}`,
      display: 'flex', flexDirection: 'column', flexShrink: 0,
    }}>
      <SectionLabel n="03 //" right={
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {streaming && <span className="dlk-dot cyan live" />}
          <button
            className="dlk-btn ghost"
            style={{ padding: 3 }}
            onClick={onToggle}
            title="Collapse panel"
          >
            <Icon name="chevR" size={12} color={T.muted} />
          </button>
        </div>
      }>Agent Activity</SectionLabel>

      {/* Current task */}
      {currentTask ? (
        <div style={{ padding: '12px 14px', borderBottom: `1px solid ${T.border}` }}>
          <div className="upper" style={{ color: T.dim, marginBottom: 6 }}>Current task</div>
          <div style={{ fontSize: 13, color: T.text, marginBottom: 8, letterSpacing: '-0.01em', lineHeight: 1.4,
            display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
            {currentTask}
          </div>
          <div style={{ display: 'flex', gap: 10, fontSize: 10 }} className="mono">
            <span style={{ color: T.muted }}>
              <span style={{ color: T.cyan }}>◇</span> {doneSteps}/{totalSteps || 1} steps
            </span>
            {startRef.current && (
              <span style={{ color: T.muted }}>{fmtElapsed(elapsed)} elapsed</span>
            )}
            {warnCount > 0 && (
              <span style={{ color: T.amber }}>▲ {warnCount} warn</span>
            )}
          </div>
          {totalSteps > 0 && (
            <StepProgress done={doneSteps} total={totalSteps} pct={streaming ? Math.max(pct, 15) : 100} />
          )}
        </div>
      ) : (
        <div style={{ padding: '10px 14px', borderBottom: `1px solid ${T.border}` }}>
          <div className="upper" style={{ color: T.dim, marginBottom: 4 }}>Current task</div>
          <div className="mono" style={{ fontSize: 11, color: T.dim }}>no active task</div>
        </div>
      )}

      {/* Activity feed */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {activityItems.length === 0 ? (
          <EmptyState />
        ) : (
          activityItems.map((it, i) => (
            <ActivityRow key={i} item={it} isLast={i === activityItems.length - 1} />
          ))
        )}
      </div>

      {/* Permissions footer */}
      <div style={{ borderTop: `1px solid ${T.border}`, padding: '10px 14px', background: T.bg0, display: 'flex', alignItems: 'center', gap: 10 }}>
        <Icon name="shield" size={14} color={streaming ? T.cyan : messages.length ? T.green : T.dim} />
        <div style={{ flex: 1, fontSize: 11, color: T.muted }}>
          {messages.length
            ? <><span className="mono" style={{ color: T.text }}>{messages.length}</span> messages · sandboxed</>
            : 'ask-before-write mode'
          }
        </div>
        {streaming && (
          <span className="mono" style={{ fontSize: 10, color: T.cyan }}>working…</span>
        )}
      </div>
    </aside>
  );
}
