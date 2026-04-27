import { useState, useEffect, useRef, useCallback, createContext, useContext } from 'react';
import { T } from '../tokens.js';
import Icon from '../components/Icon.jsx';
import { AppFrame } from '../components/Shell.jsx';
import LeftPanel from '../components/LeftPanel.jsx';
import { getCloudApi } from '../lib/cloud.js';
import McpTemplateModal from '../components/McpTemplateModal.jsx';
import McpBulkImportModal from '../components/McpBulkImportModal.jsx';
import McpToolList from '../components/McpToolList.jsx';
import MCPAuditDashboard from '../components/MCPAuditDashboard.jsx';

const API = 'http://localhost:8765';

// ── Context ───────────────────────────────────────────────────────────────────

const Ctx = createContext({});

// ── Defaults ──────────────────────────────────────────────────────────────────

const DEFAULTS = {
  model: 'gemma3-12b',
  system_prompt:
    "You are dialekt — a powerful local AI agent with full access to this computer.\n" +
    "You can read/write files, run shell commands, open browsers, and control the desktop.\n\n" +
    "CRITICAL RULE — HOW TO RUN CODE:\n" +
    "ALWAYS use fenced markdown code blocks to execute commands. NEVER use JSON.\n" +
    "Examples:\n```shell\nls ~/Desktop\n```\n```python\nprint('hello')\n```\n" +
    "Always explain briefly what you'll do, then the code block, then show results.\n" +
    "Desktop path: ~/Desktop",
  autonomy: 'ask-write',
  tone: 'technical',
  verbosity: 'balanced',
  response_language: 'auto',
  code_comments: false,
  emoji: false,
  font_size: '13',
  density: 'comfortable',
  code_font: 'JetBrains Mono',
  timestamps_fmt: 'relative',
  sidebar_width: '240',
  theme: 'Void',
  perm_fs_read: 'allow',
  perm_fs_write: 'ask',
  perm_fs_delete: 'deny',
  perm_terminal_run: 'ask',
  perm_terminal_network: 'allow',
  perm_browser_navigate: 'allow',
  perm_browser_fill: 'ask',
  perm_browser_sessions: 'deny',
  perm_screen_capture: 'ask',
  perm_input_control: 'deny',
  allowed_paths: [
    { p: '~/code',             r: 'read+write' },
    { p: '~/Documents/notes',  r: 'read only'  },
    { p: '~/Downloads',        r: 'read+write' },
    { p: '/tmp/dialekt-*',     r: 'sandbox'    },
  ],
  watch_changes: true,
  hidden_files: false,
  auto_read: true,
  max_file_size: '10',
  shell: '/bin/bash',
  cmd_timeout: '60',
  network_from_shell: true,
  sudo: false,
  allowed_cmds: ['git', 'npm', 'pnpm', 'python3', 'node', 'curl', 'ls', 'cat', 'grep', 'find'],
  env_vars: [
    { k: 'PATH',    v: '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin' },
    { k: 'DISPLAY', v: ':0' },
  ],
  browser_headless: false,
  cookie_policy: 'decline',
  adblock: true,
  session_isolation: true,
  screenshot_on_error: true,
  capture_overlay: true,
  capture_quality: 'high',
  vision_model: 'auto',
  mouse_control: false,
  keyboard_control: false,
  context_window: '8192',
  max_tokens: '4096',
  temperature: '0.7',
  streaming: true,
  concurrent_sessions: '1',
  crash_reports: false,
  usage_stats: false,
  session_retention: 'forever',
  facts: [
    { t: 'Prefers TypeScript over JavaScript for new code.', src: 'learned · 4 sessions ago' },
    { t: 'Uses pnpm, not npm or yarn.',                      src: 'learned · 2 weeks ago'   },
    { t: 'Avoids git force-push unless explicitly requested.', src: 'rule · pinned'         },
    { t: 'Always run tests before suggesting a commit.',     src: 'rule · pinned'           },
  ],
};

// ── Toast ─────────────────────────────────────────────────────────────────────

function ToastStack({ toasts }) {
  if (!toasts.length) return null;
  return (
    <div style={{
      position: 'fixed', bottom: 24, right: 24, zIndex: 9999,
      display: 'flex', flexDirection: 'column-reverse', gap: 8, pointerEvents: 'none',
    }}>
      {toasts.map(t => {
        const color = { ok: T.green, error: T.red, warn: T.amber, info: T.cyan }[t.type] || T.cyan;
        return (
          <div key={t.id} style={{
            display: 'flex', alignItems: 'center', gap: 10,
            padding: '10px 16px', background: T.bg1,
            border: `1px solid ${color}44`, borderLeft: `3px solid ${color}`,
            boxShadow: '0 4px 20px rgba(0,0,0,.6)', minWidth: 220,
          }}>
            <span style={{ width: 6, height: 6, background: color, display: 'inline-block', flexShrink: 0 }} />
            <span className="mono" style={{ fontSize: 11, color: T.text }}>{t.msg}</span>
          </div>
        );
      })}
    </div>
  );
}

// ── ConfirmModal ──────────────────────────────────────────────────────────────

function ConfirmModal({ title, body, action = 'Confirm', danger, onConfirm, onCancel }) {
  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 9998,
        background: 'rgba(0,0,0,.75)', display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
      onClick={e => { if (e.target === e.currentTarget) onCancel(); }}
    >
      <div style={{
        background: T.bg1, border: `1px solid ${danger ? T.red + '66' : T.borderHi}`,
        width: 420, padding: 28, boxShadow: '0 24px 64px rgba(0,0,0,.8)',
      }}>
        <div className="mono" style={{ fontSize: 10, color: danger ? T.red : T.cyan, letterSpacing: '.14em', marginBottom: 10 }}>
          {danger ? '⚠ DESTRUCTIVE ACTION' : 'CONFIRM'}
        </div>
        <div style={{ fontSize: 17, fontWeight: 600, letterSpacing: '-0.01em', marginBottom: 10 }}>{title}</div>
        <div style={{ fontSize: 13, color: T.muted, lineHeight: 1.6, marginBottom: 24 }}>{body}</div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
          <button className="dlk-btn" onClick={onCancel}>Cancel</button>
          <button
            className="dlk-btn"
            style={{ borderColor: (danger ? T.red : T.cyan) + '66', color: danger ? T.red : T.cyan }}
            onClick={onConfirm}
          >
            {action}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── PullModelModal ────────────────────────────────────────────────────────────

function PullModelModal({ onClose, onPull }) {
  const [name, setName] = useState('');
  const inputRef = useRef(null);
  useEffect(() => { inputRef.current?.focus(); }, []);

  const submit = () => { if (name.trim()) { onPull(name.trim()); onClose(); } };

  return (
    <div
      style={{ position: 'fixed', inset: 0, zIndex: 9998, background: 'rgba(0,0,0,.75)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{ background: T.bg1, border: `1px solid ${T.borderHi}`, width: 460, padding: 28, boxShadow: '0 24px 64px rgba(0,0,0,.8)' }}>
        <div className="mono" style={{ fontSize: 10, color: T.cyan, letterSpacing: '.14em', marginBottom: 10 }}>PULL MODEL</div>
        <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 6 }}>Download from Ollama registry</div>
        <div style={{ fontSize: 12, color: T.muted, marginBottom: 18, lineHeight: 1.55 }}>
          Enter a model name. Examples:{' '}
          <span className="mono" style={{ color: T.text }}>llama3.2</span>,{' '}
          <span className="mono" style={{ color: T.text }}>qwen2.5-coder:14b</span>,{' '}
          <span className="mono" style={{ color: T.text }}>phi4:latest</span>
        </div>
        <div style={{ display: 'flex', gap: 8, marginBottom: 18 }}>
          <input
            ref={inputRef}
            value={name}
            onChange={e => setName(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') submit(); if (e.key === 'Escape') onClose(); }}
            placeholder="model:tag"
            style={{
              flex: 1, background: T.bg0, border: `1px solid ${T.border}`,
              outline: 'none', fontFamily: T.mono, fontSize: 12, color: T.text,
              padding: '8px 10px', caretColor: T.cyan,
            }}
          />
          <button className="dlk-btn primary" style={{ padding: '0 18px', opacity: name.trim() ? 1 : 0.4 }}
            onClick={submit} disabled={!name.trim()}>Pull</button>
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <button className="dlk-btn" onClick={onClose}>
            Cancel <span className="mono" style={{ fontSize: 10, opacity: .6, marginLeft: 4 }}>Esc</span>
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Shared atoms ──────────────────────────────────────────────────────────────

function BodyShell({ crumb, title, desc, children }) {
  return (
    <div className="dlk-scroll" style={{ flex: 1, overflowY: 'auto' }}>
      <div style={{ padding: '28px 36px 40px', maxWidth: 860 }}>
        <div className="mono" style={{ fontSize: 10, color: T.cyan, letterSpacing: '.14em', marginBottom: 8 }}>{crumb}</div>
        <div style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.02em', marginBottom: 8 }}>{title}</div>
        <div style={{ color: T.muted, fontSize: 13, lineHeight: 1.55, marginBottom: 24 }}>{desc}</div>
        {children}
      </div>
    </div>
  );
}

function Card({ title, n, right, children }) {
  return (
    <div style={{ border: `1px solid ${T.border}`, background: T.bg1, marginBottom: 16 }}>
      {title !== undefined && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', borderBottom: `1px solid ${T.border}` }}>
          {n && <span className="mono" style={{ color: T.cyan, fontSize: 10, letterSpacing: '.12em' }}>{n}</span>}
          <span style={{ fontSize: 13, fontWeight: 500 }}>{title}</span>
          <div style={{ flex: 1 }} />
          {right}
        </div>
      )}
      {children}
    </div>
  );
}

function Row({ label, sub, children, last }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 16, padding: '12px 14px',
      borderBottom: last ? 'none' : `1px solid ${T.border}`,
    }}>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, color: T.text }}>{label}</div>
        {sub && <div style={{ fontSize: 11, color: T.dim, marginTop: 2 }}>{sub}</div>}
      </div>
      {children}
    </div>
  );
}

function Toggle({ value, onChange }) {
  return (
    <div onClick={() => onChange?.(!value)} style={{
      width: 36, height: 20, borderRadius: 10, cursor: 'pointer', flexShrink: 0,
      background: value ? T.cyan : T.borderHi, position: 'relative', transition: 'background .15s',
    }}>
      <div style={{
        position: 'absolute', top: 3, left: value ? 18 : 3,
        width: 14, height: 14, borderRadius: 7,
        background: value ? T.bg0 : T.dim, transition: 'left .15s',
      }} />
    </div>
  );
}

export function TriSegment({ value, onChange, disabled }) {
  const opts = [
    { k: 'allow', label: 'Allow', color: T.green },
    { k: 'ask',   label: 'Ask',   color: T.amber },
    { k: 'deny',  label: 'Deny',  color: T.red   },
  ];
  return (
    <div style={{ display: 'flex', border: `1px solid ${T.border}`, borderRadius: 3, opacity: disabled ? 0.5 : 1 }}>
      {opts.map(o => {
        const on = o.k === value;
        return (
          <div key={o.k} className="mono" onClick={() => !disabled && onChange?.(o.k)} style={{
            padding: '5px 10px', fontSize: 10, letterSpacing: '.08em', userSelect: 'none',
            background: on ? (o.k === 'allow' ? '#0c2a1f' : o.k === 'ask' ? '#2a1f0a' : '#2a0f12') : 'transparent',
            color: on ? o.color : T.dim,
            borderRight: o.k !== 'deny' ? `1px solid ${T.border}` : 'none',
            fontWeight: on ? 600 : 400, cursor: disabled ? 'default' : 'pointer',
          }}>{o.label.toUpperCase()}</div>
        );
      })}
    </div>
  );
}

function PermRow({ cap, stateKey, detail, locked }) {
  const { settings, update } = useContext(Ctx);
  const val = settings[stateKey] || 'deny';
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '1fr auto', gap: 16,
      padding: '12px 14px', borderBottom: `1px solid ${T.border}`, alignItems: 'center',
    }}>
      <div>
        <div style={{ fontSize: 13, color: T.text, display: 'flex', alignItems: 'center', gap: 8 }}>
          {cap}{locked && <Icon name="shield" size={11} color={T.dim} />}
        </div>
        <div style={{ fontSize: 11, color: T.dim, marginTop: 2 }}>{detail}</div>
      </div>
      <TriSegment value={val} onChange={v => !locked && update({ [stateKey]: v })} disabled={locked} />
    </div>
  );
}

function Select({ value, onChange, options }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    const close = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  const current = options.find(o => o.v === value);

  return (
    <div ref={ref} style={{ position: 'relative', flexShrink: 0 }}>
      <div onClick={() => setOpen(o => !o)} style={{
        display: 'flex', alignItems: 'center', gap: 8, minWidth: 150,
        padding: '5px 10px', cursor: 'pointer', userSelect: 'none',
        background: T.bg0, border: `1px solid ${open ? T.cyan + '66' : T.border}`,
        fontFamily: T.mono, fontSize: 11, color: T.text, transition: 'border-color .1s',
      }}>
        <span style={{ flex: 1 }}>{current?.l ?? value}</span>
        <svg width="10" height="10" viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0, transition: 'transform .15s', transform: open ? 'rotate(180deg)' : 'none' }}>
          <path d="M4 6l4 4 4-4" stroke={open ? T.cyan : T.dim} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
      {open && (
        <div style={{
          position: 'absolute', top: 'calc(100% + 2px)', right: 0, zIndex: 300,
          background: T.bg1, border: `1px solid ${T.cyan}44`,
          boxShadow: '0 8px 32px rgba(0,0,0,.7)', minWidth: '100%',
        }}>
          {options.map(o => {
            const active = o.v === value;
            return (
              <div key={o.v}
                onClick={() => { onChange(o.v); setOpen(false); }}
                onMouseEnter={e => { if (!active) e.currentTarget.style.background = T.bg2; }}
                onMouseLeave={e => { if (!active) e.currentTarget.style.background = 'transparent'; }}
                style={{
                  display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px',
                  cursor: 'pointer', fontFamily: T.mono, fontSize: 11,
                  background: active ? T.bg2 : 'transparent',
                  borderLeft: `2px solid ${active ? T.cyan : 'transparent'}`,
                  color: active ? T.text : T.muted,
                }}>
                <span style={{ width: 5, height: 5, flexShrink: 0, background: active ? T.cyan : 'transparent', display: 'inline-block' }} />
                {o.l}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Chip({ label, active, color, onClick }) {
  return (
    <span onClick={onClick} className="mono" style={{
      fontSize: 10, padding: '4px 10px', cursor: 'pointer', userSelect: 'none',
      border: `1px solid ${active ? (color || T.cyan) + '88' : T.border}`,
      color: active ? (color || T.cyan) : T.muted,
      background: active ? (color || T.cyan) + '18' : 'transparent',
      transition: 'all .1s',
    }}>{label}</span>
  );
}

function ScopeChip({ label }) {
  return <span className="mono" style={{ fontSize: 10, color: T.muted, border: `1px solid ${T.border}`, padding: '2px 6px' }}>{label}</span>;
}

const AUTONOMY_STOPS = [
  { k: 'review',    label: 'Review-only',   sub: 'explain, never execute' },
  { k: 'ask',       label: 'Ask before run', sub: 'confirm all shell/code' },
  { k: 'ask-write', label: 'Ask-write',      sub: 'confirm edits + shell' },
  { k: 'auto',      label: 'Autonomous',     sub: 'within allow-list' },
  { k: 'yolo',      label: 'YOLO',           sub: 'sandboxed envs only', warn: true },
];

function AutonomyTrack({ value, onChange }) {
  const activeIdx = AUTONOMY_STOPS.findIndex(s => s.k === value);
  const pct = activeIdx < 0 ? 0 : (activeIdx / (AUTONOMY_STOPS.length - 1)) * 100;
  return (
    <div>
      <div style={{ position: 'relative', display: 'flex', alignItems: 'center', height: 28 }}>
        <div style={{ position: 'absolute', left: 8, right: 8, top: 13, height: 2, background: T.border }} />
        <div style={{ position: 'absolute', left: 8, top: 13, height: 2, width: `calc(${pct}% * (1 - 16px/100%))`, background: T.cyan, transition: 'width .2s' }} />
        {AUTONOMY_STOPS.map((s, i) => {
          const on = s.k === value;
          return (
            <div key={i} onClick={() => onChange?.(s.k)} style={{ flex: 1, display: 'flex', justifyContent: 'center', zIndex: 1, cursor: 'pointer' }}>
              <div style={{
                width: on ? 14 : 10, height: on ? 14 : 10,
                background: on ? T.cyan : T.bg0,
                border: `2px solid ${s.warn ? T.amber : on ? T.cyan : T.borderHi}`,
                transform: on ? 'rotate(45deg)' : 'none', transition: 'all .15s',
              }} />
            </div>
          );
        })}
      </div>
      <div style={{ display: 'flex', marginTop: 10 }}>
        {AUTONOMY_STOPS.map((s, i) => {
          const on = s.k === value;
          return (
            <div key={i} onClick={() => onChange?.(s.k)} style={{ flex: 1, textAlign: 'center', cursor: 'pointer' }}>
              <div className="mono" style={{ fontSize: 10, color: on ? T.cyan : s.warn ? T.amber : T.muted, letterSpacing: '.06em', textTransform: 'uppercase' }}>{s.label}</div>
              <div style={{ fontSize: 10, color: T.dim, marginTop: 2 }}>{s.sub}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function PathsList() {
  const { settings, update } = useContext(Ctx);
  const paths = settings.allowed_paths || [];
  const [adding, setAdding] = useState(false);
  const [newPath, setNewPath] = useState('');
  const [newMode, setNewMode] = useState('read+write');

  const pathColor = (r) => r === 'read only' ? T.cyan : r === 'sandbox' ? T.amber : T.green;

  const remove = (i) => update({ allowed_paths: paths.filter((_, j) => j !== i) });
  const add = () => {
    if (newPath.trim()) {
      update({ allowed_paths: [...paths, { p: newPath.trim(), r: newMode }] });
      setNewPath(''); setNewMode('read+write');
    }
    setAdding(false);
  };

  return (
    <div style={{ padding: '10px 14px 14px' }}>
      <div className="upper" style={{ color: T.dim, marginBottom: 8 }}>Allow-list</div>
      <div style={{ border: `1px solid ${T.border}` }}>
        {paths.map((p, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 10px', borderBottom: `1px solid ${T.border}` }}>
            <Icon name="folder" size={12} color={T.muted} />
            <span className="mono" style={{ fontSize: 11, color: T.text, flex: 1 }}>{p.p}</span>
            <span className="mono" style={{ fontSize: 10, color: pathColor(p.r) }}>{p.r}</span>
            <div onClick={() => remove(i)} style={{ cursor: 'pointer', padding: '2px 4px' }}>
              <Icon name="x" size={11} color={T.dim} />
            </div>
          </div>
        ))}
        {adding ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px', borderBottom: `1px solid ${T.border}` }}>
            <Icon name="folder" size={12} color={T.cyan} />
            <input autoFocus value={newPath} onChange={e => setNewPath(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') add(); if (e.key === 'Escape') { setAdding(false); setNewPath(''); } }}
              placeholder="~/path/to/allow…"
              style={{ flex: 1, background: 'transparent', border: 'none', outline: 'none', fontFamily: T.mono, fontSize: 11, color: T.text, caretColor: T.cyan }} />
            <Select value={newMode} onChange={setNewMode} options={[
              { v: 'read+write', l: 'read+write' },
              { v: 'read only',  l: 'read only'  },
              { v: 'sandbox',    l: 'sandbox'     },
            ]} />
            <button className="dlk-btn" style={{ padding: '2px 8px', fontSize: 10 }} onClick={add}>Add</button>
            <div onClick={() => { setAdding(false); setNewPath(''); }} style={{ cursor: 'pointer' }}><Icon name="x" size={11} color={T.dim} /></div>
          </div>
        ) : (
          <div onClick={() => setAdding(true)} style={{ padding: '7px 10px', display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
            <Icon name="plus" size={12} color={T.cyan} />
            <span className="mono" style={{ fontSize: 11, color: T.cyan }}>add path…</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Coming soon banner ────────────────────────────────────────────────────────

function ComingSoonBanner({ version = 'v1.1', label }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px', marginBottom: 20,
      border: `1px solid ${T.border}`, background: T.bg1,
    }}>
      <div style={{
        padding: '2px 7px', background: T.bg0, border: `1px solid ${T.borderHi}`,
        fontFamily: 'monospace', fontSize: 10, color: T.cyan, letterSpacing: '.1em', flexShrink: 0,
      }}>COMING {version}</div>
      <span style={{ fontSize: 12, color: T.dim }}>
        {label || 'This feature is not yet wired up. Settings here are saved but have no effect yet.'}
      </span>
    </div>
  );
}

// ── Section: Branding ────────────────────────────────────────────────────────
//
// Pilot brand profile editor — colors + logo + optional font. Saves via
// POST /branding/upload (multipart) then renders a synthetic showcase
// PNG via POST /branding/{id}/preview so the user sees the result inline.
// One profile per pilot is enough for v0.27 — list/switch UX comes later.

const BRAND_DEFAULTS = {
  brand_id: '',
  name: '',
  primary_color:    '#FF5629',
  secondary_color:  '#3A5ADC',
  background_color: '#0C1014',
  text_color:       '#F5F1EA',
  font_family: '',
};

function isHex(s) {
  return /^#?(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(s.trim());
}

function ColorRow({ label, sub, value, onChange }) {
  // Browser <input type=color> needs strict #RRGGBB. The visible hex
  // input below it is unconstrained so the user can still paste 3-char
  // shorthand or alpha — server side normalises.
  const swatch = isHex(value) && value.length >= 4
    ? (value.length === 4
        ? '#' + value.slice(1).split('').map(c => c + c).join('')
        : value)
    : '#888888';
  return (
    <Row label={label} sub={sub}>
      <input
        type="color" value={swatch}
        onChange={e => onChange(e.target.value.toUpperCase())}
        style={{
          width: 36, height: 22, padding: 0, border: `1px solid ${T.border}`,
          background: 'transparent', cursor: 'pointer',
        }}
      />
      <input
        type="text" value={value}
        onChange={e => onChange(e.target.value)}
        placeholder="#RRGGBB"
        style={{
          width: 110, marginLeft: 10,
          background: T.bg0, border: `1px solid ${isHex(value) || !value ? T.border : T.amber}`,
          color: T.text, fontFamily: T.mono, fontSize: 12,
          padding: '4px 8px',
        }}
      />
    </Row>
  );
}

function DropFile({ label, sub, value, accept, onChange }) {
  const ref = useRef(null);
  const [over, setOver] = useState(false);
  const onPick = (file) => onChange(file || null);
  return (
    <div
      onDragEnter={e => { e.preventDefault(); setOver(true); }}
      onDragOver={e => { e.preventDefault(); }}
      onDragLeave={e => { if (e.currentTarget === e.target) setOver(false); }}
      onDrop={e => {
        e.preventDefault(); setOver(false);
        const f = e.dataTransfer?.files?.[0];
        if (f) onPick(f);
      }}
      style={{
        padding: '14px 16px',
        borderBottom: `1px solid ${T.border}`,
        background: over ? `${T.cyan}11` : 'transparent',
        outline: over ? `1px dashed ${T.cyan}` : 'none',
        outlineOffset: '-4px',
      }}
    >
      <input ref={ref} type="file" accept={accept} style={{ display: 'none' }}
             onChange={e => onPick(e.target.files?.[0])} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13, color: T.text }}>{label}</div>
          <div style={{ fontSize: 11, color: T.dim, marginTop: 2 }}>{sub}</div>
          {value && (
            <div className="mono" style={{ fontSize: 11, color: T.cyan, marginTop: 6 }}>
              {value.name} · {Math.ceil(value.size / 1024)}KB
            </div>
          )}
        </div>
        <button className="dlk-btn" onClick={() => ref.current?.click()}>
          {value ? 'Replace' : 'Choose file'}
        </button>
        {value && (
          <button className="dlk-btn ghost" onClick={() => onPick(null)} title="Clear">
            <Icon name="x" size={11} color={T.dim} />
          </button>
        )}
      </div>
    </div>
  );
}

function BrandingSection() {
  const [form, setForm] = useState(BRAND_DEFAULTS);
  const [logoFile, setLogoFile] = useState(null);
  const [fontFile, setFontFile] = useState(null);
  const [savedBrand, setSavedBrand] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [busy, setBusy] = useState(null);  // null | 'saving' | 'previewing'
  const [error, setError] = useState(null);
  const [brands, setBrands] = useState([]);

  const set = (k) => (v) => setForm(f => ({ ...f, [k]: v }));

  // Load existing brands on mount; pick the first one so the user can
  // edit instead of always starting blank.
  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${API}/branding`);
        if (!r.ok) return;
        const { brands: list } = await r.json();
        setBrands(list || []);
        if ((list || []).length > 0) {
          loadBrand(list[0]);
        }
      } catch {}
    })();
  }, []);

  const loadBrand = (b) => {
    setForm({
      brand_id: b.id,
      name: b.name,
      primary_color:    b.colors.primary    || '#000000',
      secondary_color:  b.colors.secondary  || '',
      background_color: b.colors.background || '#FFFFFF',
      text_color:       b.colors.text       || '#111111',
      font_family:      b.font_family       || '',
    });
    setSavedBrand(b);
    setPreviewUrl(null);
    setError(null);
  };

  const validate = () => {
    if (!form.brand_id || !/^[a-z0-9][a-z0-9_-]{0,62}$/.test(form.brand_id)) {
      return 'brand_id: 1–63 chars, [a-z0-9_-], must start with [a-z0-9]';
    }
    if (!form.name.trim()) return 'name is required';
    if (!isHex(form.primary_color)) return 'primary color must be #RRGGBB';
    if (form.secondary_color && !isHex(form.secondary_color)) return 'secondary color must be #RRGGBB';
    if (!isHex(form.background_color)) return 'background color must be #RRGGBB';
    if (!isHex(form.text_color)) return 'text color must be #RRGGBB';
    return null;
  };

  const saveAndPreview = async () => {
    const err = validate();
    if (err) { setError(err); return; }
    setError(null); setBusy('saving'); setPreviewUrl(null);
    try {
      const fd = new FormData();
      fd.append('brand_id', form.brand_id);
      fd.append('name', form.name);
      fd.append('primary_color', form.primary_color);
      fd.append('secondary_color', form.secondary_color);
      fd.append('background_color', form.background_color);
      fd.append('text_color', form.text_color);
      if (form.font_family) fd.append('font_family', form.font_family);
      if (logoFile) fd.append('logo', logoFile, logoFile.name);
      if (fontFile) fd.append('font', fontFile, fontFile.name);

      const r = await fetch(`${API}/branding/upload`, { method: 'POST', body: fd });
      if (!r.ok) {
        const txt = await r.text();
        setError(`save failed (${r.status}): ${txt}`);
        return;
      }
      const { brand } = await r.json();
      setSavedBrand(brand);
      // Refresh brand list
      const listR = await fetch(`${API}/branding`);
      if (listR.ok) setBrands((await listR.json()).brands || []);

      // Render preview
      setBusy('previewing');
      const pr = await fetch(`${API}/branding/${brand.id}/preview`, { method: 'POST' });
      if (!pr.ok) {
        setError(`preview failed: ${pr.status}`);
        return;
      }
      const { file } = await pr.json();
      // /files endpoint serves any path under /tmp/dialekt_files OR
      // ~/.dialekt/visual/out/, with a cache-buster to defeat browser
      // caching of the previous render under the same URL.
      setPreviewUrl(`${API}/files?path=${encodeURIComponent(file)}&_=${Date.now()}`);
    } catch (e) {
      setError(`unexpected error: ${e.message}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <BodyShell
      crumb="01 / SETUP → BRANDING"
      title="Branding"
      desc="Pilot brand profile applied to generated visuals (Instagram posts, announcements, schedules) when the agent renders a template with brand_id."
    >
      {brands.length > 1 && (
        <Card title="Existing brands" n="A">
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, padding: 12 }}>
            {brands.map(b => (
              <button
                key={b.id}
                className={`dlk-btn ${savedBrand?.id === b.id ? 'primary' : ''}`}
                onClick={() => loadBrand(b)}
              >
                {b.name}
              </button>
            ))}
            <button className="dlk-btn ghost" onClick={() => {
              setForm(BRAND_DEFAULTS);
              setSavedBrand(null); setPreviewUrl(null); setError(null);
              setLogoFile(null); setFontFile(null);
            }}>+ New brand</button>
          </div>
        </Card>
      )}

      <Card title="Identity" n={brands.length > 1 ? 'B' : 'A'}>
        <Row label="Brand ID" sub="lower-case identifier used in API and file paths (e.g. iba)">
          <input
            type="text" value={form.brand_id}
            onChange={e => set('brand_id')(e.target.value.toLowerCase())}
            disabled={!!savedBrand}
            placeholder="iba"
            style={{
              width: 200, background: T.bg0,
              border: `1px solid ${T.border}`, color: T.text,
              fontFamily: T.mono, fontSize: 12, padding: '5px 8px',
              opacity: savedBrand ? 0.5 : 1,
            }}
          />
        </Row>
        <Row label="Display name" sub="shown in the preview and brand picker" last>
          <input
            type="text" value={form.name}
            onChange={e => set('name')(e.target.value)}
            placeholder="International Business Academy"
            style={{
              width: 280, background: T.bg0,
              border: `1px solid ${T.border}`, color: T.text,
              fontSize: 12, padding: '5px 8px',
            }}
          />
        </Row>
      </Card>

      <Card title="Colors" n={brands.length > 1 ? 'C' : 'B'}>
        <ColorRow label="Primary" sub="main accent — headlines, buttons, eyebrow"
          value={form.primary_color} onChange={set('primary_color')} />
        <ColorRow label="Secondary" sub="optional — supporting accent"
          value={form.secondary_color} onChange={set('secondary_color')} />
        <ColorRow label="Background" sub="canvas fill"
          value={form.background_color} onChange={set('background_color')} />
        <ColorRow label="Text" sub="body copy on the canvas"
          value={form.text_color} onChange={set('text_color')} />
      </Card>

      <Card title="Assets" n={brands.length > 1 ? 'D' : 'C'}>
        <DropFile
          label="Logo"
          sub="PNG, SVG, JPG, or WebP. Drop or pick. Used by .brand-logo in templates."
          accept="image/png,image/svg+xml,image/jpeg,image/webp"
          value={logoFile}
          onChange={setLogoFile}
        />
        <DropFile
          label="Custom font (optional)"
          sub="TTF, OTF, WOFF, or WOFF2. Templates can reference var(--brand-font)."
          accept=".ttf,.otf,.woff,.woff2,font/ttf,font/otf,font/woff,font/woff2"
          value={fontFile}
          onChange={setFontFile}
        />
        <Row label="Font family alias" sub="CSS @font-face name (defaults to BrandFont)" last>
          <input
            type="text" value={form.font_family}
            onChange={e => set('font_family')(e.target.value)}
            placeholder="BrandFont"
            style={{
              width: 200, background: T.bg0,
              border: `1px solid ${T.border}`, color: T.text,
              fontFamily: T.mono, fontSize: 12, padding: '5px 8px',
            }}
          />
        </Row>
      </Card>

      {error && (
        <div className="mono" style={{
          padding: '10px 14px', marginBottom: 14, fontSize: 11,
          color: T.amber, border: `1px solid ${T.amber}55`,
          background: `${T.amber}0a`,
        }}>{error}</div>
      )}

      <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
        <button
          className="dlk-btn primary"
          style={{ padding: '8px 18px', opacity: busy ? 0.5 : 1 }}
          onClick={saveAndPreview}
          disabled={!!busy}
        >
          {busy === 'saving' ? 'Saving…'
            : busy === 'previewing' ? 'Rendering preview…'
            : 'Save & Preview'}
        </button>
        {savedBrand && (
          <button
            className="dlk-btn ghost"
            onClick={async () => {
              if (!confirm(`Delete brand ${savedBrand.id}?`)) return;
              await fetch(`${API}/branding/${savedBrand.id}`, { method: 'DELETE' });
              setForm(BRAND_DEFAULTS); setSavedBrand(null); setPreviewUrl(null);
              const r = await fetch(`${API}/branding`);
              if (r.ok) setBrands((await r.json()).brands || []);
            }}
          >
            Delete brand
          </button>
        )}
      </div>

      {previewUrl && (
        <Card title="Preview" n={brands.length > 1 ? 'E' : 'D'}
          right={<span className="mono" style={{ fontSize: 10, color: T.dim }}>1080×1080</span>}>
          <div style={{ padding: 14, display: 'flex', justifyContent: 'center' }}>
            <img
              src={previewUrl}
              alt="Brand preview"
              style={{ maxWidth: '100%', height: 'auto',
                       border: `1px solid ${T.border}` }}
            />
          </div>
        </Card>
      )}
    </BodyShell>
  );
}


// ── Section: Permissions ──────────────────────────────────────────────────────

function PermissionsSection() {
  const { settings, update } = useContext(Ctx);
  return (
    <BodyShell crumb="02 / CAPABILITIES → PERMISSIONS" title="Permissions"
      desc="Decide what dialekt can do on this machine. Changes take effect immediately in the active session.">
      <Card title="Autonomy level" n="A">
        <div style={{ padding: '14px 16px' }}>
          <div style={{ fontSize: 12, color: T.muted, marginBottom: 14 }}>How much should dialekt do without checking in?</div>
          <AutonomyTrack value={settings.autonomy || 'ask-write'} onChange={v => update({ autonomy: v })} />
        </div>
      </Card>
      <Card title="Filesystem" n="B" right={<ScopeChip label={`${(settings.allowed_paths || []).length} paths`} />}>
        <PermRow cap="Read files"        stateKey="perm_fs_read"    detail="within allow-listed paths" />
        <PermRow cap="Write & modify"    stateKey="perm_fs_write"   detail="requires confirmation for each edit" />
        <PermRow cap="Delete files"      stateKey="perm_fs_delete"  detail="blocked globally" />
        <PermRow cap="Read ~/.ssh, secrets, keychain" stateKey="perm_fs_secrets" detail="sealed — cannot be overridden" locked />
        <PathsList />
      </Card>
      <Card title="Terminal & shell" n="C" right={<ScopeChip label="sandboxed" />}>
        <PermRow cap="Run commands"             stateKey="perm_terminal_run"     detail="prompts per command; allow-list remembered" />
        <PermRow cap="Network calls from shell" stateKey="perm_terminal_network" detail="outbound only" />
        <PermRow cap="Sudo / privileged"        stateKey="perm_terminal_sudo"    detail="blocked" locked />
      </Card>
      <Card title="Browser control" n="D">
        <PermRow cap="Navigate & read pages"     stateKey="perm_browser_navigate" detail="public web only" />
        <PermRow cap="Fill forms & click"        stateKey="perm_browser_fill"     detail="confirms destructive actions" />
        <PermRow cap="Access logged-in sessions" stateKey="perm_browser_sessions" detail="disabled by default" />
      </Card>
      <Card title="Screen & input" n="E">
        <PermRow cap="Screen capture"           stateKey="perm_screen_capture"  detail="flashes overlay while capturing" />
        <PermRow cap="Mouse & keyboard control" stateKey="perm_input_control"   detail="requires explicit per-session grant" />
      </Card>
    </BodyShell>
  );
}

// ── Section: Models — Inference location subcard ─────────────────────────────
//
// Cloud-Assisted tier: lets pilots without a GPU forward Ollama traffic to
// the dialekt server's relay (gpu-relay.dias.now → RTX 3060 in Almaty KZ).
// Persisted to ~/.dialekt/relay.toml via the desktop sidecar's
// /relay/{config,test} endpoints. PluginContext consumes the same file at
// startup (Commit 5) — the lifespan rebuilds the context whenever this
// card POSTs an update so the change applies without a restart.

function RelayLocationCard() {
  const { addToast } = useContext(Ctx);
  const [cfg, setCfg] = useState(null);
  const [urlInput, setUrlInput] = useState('');
  const [keyInput, setKeyInput] = useState('');
  const [testing, setTesting] = useState(false);

  const reload = useCallback(() => {
    fetch(`${API}/relay/config`)
      .then(r => r.json())
      .then(d => { setCfg(d); setUrlInput(d.url); })
      .catch(() => setCfg({
        url: 'https://gpu-relay.dias.now',
        enabled: false, api_key_set: false, api_key_preview: '',
      }));
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const post = async (body, okMsg) => {
    try {
      const r = await fetch(`${API}/relay/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setCfg(d);
      setKeyInput('');
      if (okMsg) addToast(okMsg, 'ok');
    } catch (e) {
      addToast(`Save failed: ${e.message}`, 'error');
    }
  };

  const setEnabled = (enabled) =>
    post(
      { enabled, url: urlInput, api_key: keyInput },
      enabled ? 'Cloud GPU enabled' : 'Local mode',
    );

  const saveFields = () =>
    post({ enabled: cfg.enabled, url: urlInput, api_key: keyInput }, 'Saved');

  const testConn = async () => {
    setTesting(true);
    try {
      const r = await fetch(`${API}/relay/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: urlInput, api_key: keyInput || undefined }),
      });
      const d = await r.json();
      if (d.ok) {
        const parts = [`${d.latency_ms}ms`];
        if (d.ollama_reachable !== undefined) parts.push(d.ollama_reachable ? 'Ollama ✓' : 'Ollama down');
        if (d.auth_ok) parts.push('auth ✓');
        addToast(`Relay reachable — ${parts.join(' · ')}`, 'ok');
      } else {
        addToast(`Relay test failed: ${d.error || 'unknown'}`, 'error');
      }
    } catch (e) {
      addToast(`Test failed: ${e.message}`, 'error');
    } finally {
      setTesting(false);
    }
  };

  if (!cfg) return null;

  const tabBtn = (active, label, sub, onClick) => (
    <button
      onClick={onClick}
      style={{
        flex: 1,
        background: active ? T.bg2 : T.bg1,
        border: 'none',
        padding: '14px',
        textAlign: 'left',
        borderLeft: `2px solid ${active ? T.cyan : 'transparent'}`,
        cursor: 'pointer',
      }}
    >
      <div className="mono" style={{
        fontSize: 11, fontWeight: 600,
        color: active ? T.cyan : T.text, marginBottom: 4,
      }}>
        {label}
      </div>
      <div className="mono" style={{ fontSize: 10, color: T.dim }}>{sub}</div>
    </button>
  );

  const inputStyle = {
    width: '100%', padding: '7px 10px',
    background: T.bg2, border: `1px solid ${T.border}`,
    color: T.text, fontFamily: T.mono, fontSize: 11, outline: 'none',
  };

  return (
    <Card title="Inference location" n="GPU">
      <div style={{
        display: 'flex',
        border: `1px solid ${T.border}`,
        borderRight: 'none',
      }}>
        {tabBtn(!cfg.enabled, 'LOCAL', 'Ollama on this PC', () => setEnabled(false))}
        <div style={{ width: 1, background: T.border }} />
        {tabBtn(cfg.enabled, 'CLOUD GPU', 'Relay · Cloud-Assisted tier', () => setEnabled(true))}
        <div style={{ width: 1, background: T.border }} />
      </div>

      {cfg.enabled && (
        <div style={{ marginTop: 14, padding: 14, border: `1px solid ${T.border}`, background: T.bg1 }}>
          <Row label="Relay URL" sub="Default: https://gpu-relay.dias.now (KZ data residency)">
            <input
              value={urlInput}
              onChange={e => setUrlInput(e.target.value)}
              placeholder="https://gpu-relay.dias.now"
              style={inputStyle}
            />
          </Row>
          <Row
            label="API key"
            sub={cfg.api_key_set
              ? `current: ${cfg.api_key_preview} — paste a new one to rotate`
              : 'paste the dlk_relay_… key issued by your tenant admin'}
          >
            <input
              type="password"
              value={keyInput}
              onChange={e => setKeyInput(e.target.value)}
              placeholder={cfg.api_key_set ? '••••••••••' : 'dlk_relay_…'}
              style={inputStyle}
            />
          </Row>
          <Row label="Connection" sub="Save persists fields; Test verifies reachability + Bearer" last>
            <div style={{ display: 'flex', gap: 8 }}>
              <button className="dlk-btn ghost" onClick={saveFields}>Save</button>
              <button className="dlk-btn" onClick={testConn} disabled={testing}>
                {testing ? 'Testing…' : 'Test connection'}
              </button>
            </div>
          </Row>
        </div>
      )}
    </Card>
  );
}


// ── Section: Models ───────────────────────────────────────────────────────────

function ModelsSection() {
  const { settings, update, addToast } = useContext(Ctx);
  const [models, setModels] = useState([]);
  const [search, setSearch] = useState('');
  const [pullOpen, setPullOpen] = useState(false);
  const [pullState, setPullState] = useState(null); // { model, statusText, pct, gb } | null
  const abortRef = useRef(null);

  const load = () =>
    fetch(`${API}/health`).then(r => r.json()).then(d => { if (d.models?.length) setModels(d.models); }).catch(() => {});

  useEffect(() => { load(); }, []);

  const startPull = async (modelName) => {
    if (abortRef.current) abortRef.current.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setPullState({ model: modelName, statusText: 'connecting…', pct: 0, gb: '' });
    try {
      const res = await fetch(`${API}/ollama/pull/stream?model=${encodeURIComponent(modelName)}`, { signal: ctrl.signal });
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split('\n'); buf = lines.pop();
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice(6).trim(); if (!raw) continue;
          try {
            const ev = JSON.parse(raw);
            if (ev.error) { addToast(`Pull failed: ${ev.error}`, 'error'); setPullState(null); return; }
            if (ev.status === 'success') {
              addToast(`✓ ${modelName} downloaded`, 'ok');
              load();
              setPullState(null);
              return;
            }
            const pct = ev.total ? Math.min(100, Math.round((ev.completed || 0) / ev.total * 100)) : 0;
            const gb = ev.total ? `${((ev.completed || 0) / 1e9).toFixed(1)} / ${(ev.total / 1e9).toFixed(1)} GB` : '';
            setPullState({ model: modelName, statusText: ev.status || '', pct, gb });
          } catch { /* ignore */ }
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') { addToast(`Pull error: ${err.message}`, 'error'); setPullState(null); }
    }
  };

  const short = (m) => m.replace(/:latest$/, '');
  const filtered = models.filter(m => !search || short(m).toLowerCase().includes(search.toLowerCase()));
  const activeModel = settings.model || 'gemma3-12b';

  return (
    <BodyShell crumb="01 / SETUP → MODELS" title="Installed models"
      desc="Active model applies to new and running conversations. Pull downloads in the background.">
      <RelayLocationCard />
      <div style={{ height: 18 }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px', background: T.bg1, border: `1px solid ${T.border}`, flex: 1 }}>
          <Icon name="search" size={12} color={T.dim} />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="search models…"
            style={{ flex: 1, background: 'transparent', border: 'none', outline: 'none', fontFamily: T.mono, fontSize: 11, color: T.text, caretColor: T.cyan }} />
        </div>
        <button className="dlk-btn" onClick={() => setPullOpen(true)}><Icon name="plus" size={11} color={T.cyan} />Pull model…</button>
      </div>

      {models.length === 0 ? (
        <div style={{ border: `1px solid ${T.border}`, background: T.bg1, padding: '32px', textAlign: 'center' }}>
          <div className="mono" style={{ fontSize: 11, color: T.dim }}>No models found — is ollama running?</div>
        </div>
      ) : (
        <div style={{ border: `1px solid ${T.border}`, marginBottom: 18 }}>
          {filtered.map((m, i) => {
            const s = short(m);
            const isActive = s === short(activeModel) || m === activeModel;
            return (
              <div key={m} style={{
                display: 'grid', gridTemplateColumns: '24px 1fr auto auto auto', gap: 14, alignItems: 'center',
                padding: '12px 14px', borderBottom: i < filtered.length - 1 ? `1px solid ${T.border}` : 'none',
                background: isActive ? T.bg2 : T.bg1,
                borderLeft: `2px solid ${isActive ? T.cyan : 'transparent'}`,
              }}>
                <span className="mono" style={{ fontSize: 10, color: T.dim }}>{String(i + 1).padStart(2, '0')}</span>
                <div>
                  <div className="mono" style={{ fontSize: 13, fontWeight: 600, color: T.text }}>{s}</div>
                  <div className="mono" style={{ fontSize: 10, color: T.dim, marginTop: 2 }}>ollama · local</div>
                </div>
                <span className="mono" style={{ fontSize: 10, color: isActive ? T.cyan : T.dim, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  <span className={`dlk-dot${isActive ? ' cyan live' : ''}`} style={{ background: isActive ? undefined : T.borderHi }} />
                  {isActive ? 'ACTIVE' : 'LOADED'}
                </span>
                <button className="dlk-btn ghost" style={{ padding: '3px 8px', fontSize: 10 }} onClick={() => {
                  update({ model: s });
                  addToast(`Model → ${s}`, 'ok');
                }}>
                  {isActive ? <Icon name="check" size={11} color={T.cyan} /> : 'Use'}
                </button>
                <button className="dlk-btn ghost" style={{ padding: 4 }}><Icon name="ham" size={11} color={T.muted} /></button>
              </div>
            );
          })}
        </div>
      )}

      <Card title="Default parameters" n="P">
        <Row label="Context window" sub="Max tokens fed to the model per request">
          <Select value={settings.context_window || '8192'} onChange={v => update({ context_window: v })} options={[
            { v: '4096', l: '4 096' }, { v: '8192', l: '8 192 — default' }, { v: '16384', l: '16 384' }, { v: '32768', l: '32 768' },
          ]} />
        </Row>
        <Row label="Max output tokens" sub="Hard cap on generated response length">
          <Select value={settings.max_tokens || '4096'} onChange={v => update({ max_tokens: v })} options={[
            { v: '2048', l: '2 048' }, { v: '4096', l: '4 096 — default' }, { v: '8192', l: '8 192' },
          ]} />
        </Row>
        <Row label="Temperature" sub="0 = deterministic, 1 = creative" last>
          <Select value={settings.temperature || '0.7'} onChange={v => update({ temperature: v })} options={[
            { v: '0', l: '0.0 · precise' }, { v: '0.3', l: '0.3' }, { v: '0.7', l: '0.7 · balanced' }, { v: '1', l: '1.0 · creative' },
          ]} />
        </Row>
      </Card>

      {pullState && (
        <div style={{
          border: `1px solid ${T.cyan}44`, background: T.bg1,
          padding: '10px 14px', marginBottom: 4,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 7 }}>
            <span className="mono" style={{ fontSize: 11, color: T.amber }}>
              ↓ <strong style={{ color: T.text }}>{pullState.model}</strong> · {pullState.statusText}
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              {pullState.gb && <span className="mono" style={{ fontSize: 10, color: T.dim }}>{pullState.gb} · {pullState.pct}%</span>}
              <button className="dlk-btn ghost" style={{ padding: '2px 6px', fontSize: 10 }}
                onClick={() => { abortRef.current?.abort(); setPullState(null); addToast('Pull cancelled', 'warn'); }}>
                Cancel
              </button>
            </div>
          </div>
          <div style={{ height: 3, background: T.bg0, border: `1px solid ${T.border}` }}>
            <div style={{
              height: '100%', background: T.cyan,
              width: pullState.pct > 0 ? `${pullState.pct}%` : '100%',
              transition: 'width 0.4s ease',
              opacity: pullState.pct > 0 ? 1 : 0.35,
              animation: pullState.pct === 0 ? 'dlk-pulse 1.4s ease-in-out infinite' : 'none',
            }} />
          </div>
        </div>
      )}

      {pullOpen && <PullModelModal onClose={() => setPullOpen(false)} onPull={startPull} />}
    </BodyShell>
  );
}

// ── Section: Personality ──────────────────────────────────────────────────────

function PersonalitySection() {
  const { settings, update, addToast } = useContext(Ctx);
  const [draftPrompt, setDraftPrompt] = useState(null);
  const promptValue = draftPrompt ?? settings.system_prompt ?? DEFAULTS.system_prompt;

  return (
    <BodyShell crumb="01 / SETUP → PERSONALITY" title="Personality"
      desc="Shape how dialekt communicates. System prompt changes apply immediately to all running sessions.">
      <Card title="Tone" n="A">
        <div style={{ padding: '14px 16px' }}>
          <div style={{ fontSize: 12, color: T.muted, marginBottom: 12 }}>How should dialekt sound?</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {['concise', 'technical', 'detailed', 'conversational', 'formal'].map(t => (
              <Chip key={t} label={t} active={settings.tone === t} onClick={() => update({ tone: t })} />
            ))}
          </div>
        </div>
      </Card>
      <Card title="Verbosity" n="B">
        <div style={{ padding: '14px 16px' }}>
          <div style={{ display: 'flex', gap: 8 }}>
            {[
              { k: 'brief', l: 'Brief', s: 'key points only' },
              { k: 'balanced', l: 'Balanced', s: 'default' },
              { k: 'thorough', l: 'Thorough', s: 'full explanation' },
            ].map(v => (
              <div key={v.k} onClick={() => update({ verbosity: v.k })} style={{
                flex: 1, padding: '10px 12px', border: `1px solid ${settings.verbosity === v.k ? T.cyan + '66' : T.border}`,
                background: settings.verbosity === v.k ? T.bg2 : T.bg0, cursor: 'pointer', textAlign: 'center',
              }}>
                <div className="mono" style={{ fontSize: 11, color: settings.verbosity === v.k ? T.cyan : T.text, letterSpacing: '.06em', textTransform: 'uppercase' }}>{v.l}</div>
                <div style={{ fontSize: 10, color: T.dim, marginTop: 3 }}>{v.s}</div>
              </div>
            ))}
          </div>
        </div>
      </Card>
      <Card title="Behaviour" n="C">
        <Row label="Response language" sub="auto follows the user's input language">
          <Select value={settings.response_language || 'auto'} onChange={v => update({ response_language: v })} options={[
            { v: 'auto', l: 'Auto-detect' }, { v: 'en', l: 'English' }, { v: 'ru', l: 'Russian' }, { v: 'kz', l: 'Kazakh' },
          ]} />
        </Row>
        <Row label="Add comments to generated code" sub="inline // explanations on non-obvious lines">
          <Toggle value={!!settings.code_comments} onChange={v => update({ code_comments: v })} />
        </Row>
        <Row label="Use emoji" sub="allow occasional emoji in responses" last>
          <Toggle value={!!settings.emoji} onChange={v => update({ emoji: v })} />
        </Row>
      </Card>
      <Card title="System prompt" n="D" right={<span className="mono" style={{ fontSize: 10, color: T.dim }}>applied to every new session + live sessions</span>}>
        <div style={{ padding: 14 }}>
          <textarea value={promptValue} onChange={e => setDraftPrompt(e.target.value)} rows={8} style={{
            display: 'block', width: '100%', boxSizing: 'border-box',
            background: T.bg0, border: `1px solid ${T.border}`, outline: 'none',
            fontFamily: T.mono, fontSize: 11, color: T.text, padding: '10px 12px',
            resize: 'vertical', lineHeight: 1.65, caretColor: T.cyan,
          }} />
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 10 }}>
            <button className="dlk-btn" onClick={() => setDraftPrompt(DEFAULTS.system_prompt)}>Reset</button>
            <button className="dlk-btn" onClick={() => setDraftPrompt('')}>Clear</button>
            <button className="dlk-btn primary" onClick={() => {
              update({ system_prompt: promptValue });
              setDraftPrompt(null);
              addToast('System prompt saved', 'ok');
            }}>Save</button>
          </div>
        </div>
      </Card>
    </BodyShell>
  );
}

// ── Section: Appearance ───────────────────────────────────────────────────────

function AppearanceSection() {
  const { settings, update } = useContext(Ctx);
  const themes = [
    { name: 'Void',    bg: '#05080c', accent: T.cyan    },
    { name: 'Obsidian',bg: '#0d0f12', accent: '#a78bfa' },
    { name: 'Carbon',  bg: '#161616', accent: '#f4a261' },
    { name: 'Pitch',   bg: '#000000', accent: '#22d3ee' },
  ];
  return (
    <BodyShell crumb="01 / SETUP → APPEARANCE" title="Appearance"
      desc="Visual preferences. Theme is always dark — dialekt is a terminal-first tool.">
      <Card title="Typography" n="A">
        <Row label="Chat font size" sub="base size for message text">
          <Select value={settings.font_size || '13'} onChange={v => update({ font_size: v })} options={[
            { v: '12', l: '12px' }, { v: '13', l: '13px — default' }, { v: '14', l: '14px' }, { v: '15', l: '15px' },
          ]} />
        </Row>
        <Row label="Monospace font" sub="used in code blocks and composer" last>
          <Select value={settings.code_font || 'JetBrains Mono'} onChange={v => update({ code_font: v })} options={[
            { v: 'JetBrains Mono', l: 'JetBrains Mono' }, { v: 'Fira Code', l: 'Fira Code' },
            { v: 'IBM Plex Mono', l: 'IBM Plex Mono' }, { v: 'monospace', l: 'System mono' },
          ]} />
        </Row>
      </Card>
      <Card title="Layout" n="B">
        <Row label="Message density" sub="vertical spacing between messages">
          <div style={{ display: 'flex', gap: 8 }}>
            {['compact', 'comfortable', 'spacious'].map(d => (
              <Chip key={d} label={d} active={settings.density === d} onClick={() => update({ density: d })} />
            ))}
          </div>
        </Row>
        <Row label="Left panel width" sub="pixels">
          <Select value={settings.sidebar_width || '240'} onChange={v => update({ sidebar_width: v })} options={[
            { v: '200', l: '200px' }, { v: '220', l: '220px' }, { v: '240', l: '240px — default' }, { v: '280', l: '280px' },
          ]} />
        </Row>
        <Row label="Timestamps" sub="how message times are shown" last>
          <Select value={settings.timestamps_fmt || 'relative'} onChange={v => update({ timestamps_fmt: v })} options={[
            { v: 'relative', l: '5m ago' }, { v: 'time', l: '14:32' }, { v: 'full', l: '14:32:07' }, { v: 'hidden', l: 'hidden' },
          ]} />
        </Row>
      </Card>
      <Card title="Theme" n="C">
        <div style={{ padding: 16 }}>
          <div style={{ display: 'flex', gap: 10 }}>
            {themes.map(th => {
              const on = (settings.theme || 'Void') === th.name;
              return (
                <div key={th.name} onClick={() => update({ theme: th.name })} style={{
                  flex: 1, cursor: 'pointer', border: `2px solid ${on ? T.cyan : T.border}`,
                  overflow: 'hidden', transition: 'border-color .15s',
                }}>
                  <div style={{ height: 52, background: th.bg, padding: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
                    <div style={{ height: 4, width: '70%', background: th.accent, opacity: 0.8 }} />
                    <div style={{ height: 3, width: '90%', background: '#ffffff22' }} />
                    <div style={{ height: 3, width: '55%', background: '#ffffff14' }} />
                    <div style={{ height: 4, width: '40%', background: th.accent, opacity: 0.5, alignSelf: 'flex-end' }} />
                  </div>
                  <div style={{ padding: '5px 8px', background: T.bg1, borderTop: `1px solid ${T.border}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span className="mono" style={{ fontSize: 10, color: on ? T.cyan : T.muted }}>{th.name}</span>
                    {on && <Icon name="check" size={10} color={T.cyan} />}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </Card>
    </BodyShell>
  );
}

// ── Section: Shortcuts ────────────────────────────────────────────────────────

function ShortcutsSection() {
  const groups = [
    { title: 'Global', items: [
      { action: 'New conversation',    keys: ['⌘', 'N'] },
      { action: 'Command palette',     keys: ['⌘', 'K'] },
      { action: 'Toggle settings',     keys: ['⌘', ','] },
      { action: 'Focus composer',      keys: ['⌘', '/'] },
    ]},
    { title: 'Composer', items: [
      { action: 'Send message',        keys: ['↵'] },
      { action: 'Newline',             keys: ['⇧', '↵'] },
      { action: 'Attach file',         keys: ['⌘', 'U'] },
      { action: 'Stop generation',     keys: ['⎋'] },
      { action: 'Clear composer',      keys: ['⌘', 'Del'] },
    ]},
    { title: 'Navigation', items: [
      { action: 'Previous session',    keys: ['⌘', '['] },
      { action: 'Next session',        keys: ['⌘', ']'] },
      { action: 'Go to chat',          keys: ['⌘', '1'] },
      { action: 'Go to settings',      keys: ['⌘', '2'] },
      { action: 'Search sessions',     keys: ['⌘', 'F'] },
    ]},
    { title: 'Messages', items: [
      { action: 'Copy last response',  keys: ['⌘', '⇧', 'C'] },
      { action: 'Regenerate response', keys: ['⌘', 'R'] },
      { action: 'Context menu',        keys: ['right-click'] },
    ]},
  ];
  return (
    <BodyShell crumb="01 / SETUP → SHORTCUTS" title="Keyboard shortcuts"
      desc="All keybindings. Reassignment coming in a future release.">
      {groups.map((g, gi) => (
        <Card key={gi} title={g.title} n={String.fromCharCode(65 + gi)}>
          {g.items.map((it, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', padding: '9px 14px', borderBottom: i < g.items.length - 1 ? `1px solid ${T.border}` : 'none' }}>
              <span style={{ flex: 1, fontSize: 13, color: T.text }}>{it.action}</span>
              <div style={{ display: 'flex', gap: 4 }}>
                {it.keys.map((k, ki) => (
                  <span key={ki} className="mono" style={{ fontSize: 11, color: T.cyan, background: T.bg0, border: `1px solid ${T.border}`, padding: '2px 7px', borderRadius: 3 }}>{k}</span>
                ))}
              </div>
            </div>
          ))}
        </Card>
      ))}
    </BodyShell>
  );
}

// ── Section: Filesystem ───────────────────────────────────────────────────────

function FilesystemSection() {
  const { settings, update } = useContext(Ctx);
  return (
    <BodyShell crumb="02 / CAPABILITIES → FILESYSTEM" title="Filesystem"
      desc="Control which paths dialekt can touch and how it interacts with files on disk.">
      <Card title="Access rules" n="A" right={<ScopeChip label={`${(settings.allowed_paths || []).length} paths`} />}>
        <PermRow cap="Read files"        stateKey="perm_fs_read"    detail="within allow-listed paths" />
        <PermRow cap="Write & modify"    stateKey="perm_fs_write"   detail="requires confirmation for each edit" />
        <PermRow cap="Delete files"      stateKey="perm_fs_delete"  detail="blocked globally" />
        <PermRow cap="Read ~/.ssh, secrets, keychain" stateKey="perm_fs_secrets" detail="sealed" locked />
        <PathsList />
      </Card>
      <Card title="Behaviour" n="B">
        <Row label="Watch for file changes" sub="dialekt detects if a watched file changes externally">
          <Toggle value={!!settings.watch_changes} onChange={v => update({ watch_changes: v })} />
        </Row>
        <Row label="Show hidden files (dotfiles)" sub="include .files and .dirs in directory listings">
          <Toggle value={!!settings.hidden_files} onChange={v => update({ hidden_files: v })} />
        </Row>
        <Row label="Auto-read @file: attachments" sub="inject file contents into context automatically">
          <Toggle value={settings.auto_read !== false} onChange={v => update({ auto_read: v })} />
        </Row>
        <Row label="Max single file size for injection" sub="larger files are summarised or skipped" last>
          <Select value={settings.max_file_size || '10'} onChange={v => update({ max_file_size: v })} options={[
            { v: '1', l: '1 MB' }, { v: '5', l: '5 MB' }, { v: '10', l: '10 MB — default' }, { v: '50', l: '50 MB' },
          ]} />
        </Row>
      </Card>
      <Card title="Sealed paths" n="C">
        <div style={{ padding: '12px 14px' }}>
          <div style={{ fontSize: 12, color: T.muted, marginBottom: 12 }}>These paths are always sealed regardless of allow-list rules.</div>
          <div style={{ border: `1px solid ${T.border}` }}>
            {['~/.ssh', '~/.gnupg', '~/.aws/credentials', '/etc/passwd', '/etc/shadow', '/proc', '/sys'].map((p, i, arr) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 10px', borderBottom: i < arr.length - 1 ? `1px solid ${T.border}` : 'none' }}>
                <Icon name="shield" size={12} color={T.red} />
                <span className="mono" style={{ fontSize: 11, color: T.muted }}>{p}</span>
                <div style={{ flex: 1 }} />
                <span className="mono" style={{ fontSize: 10, color: T.red }}>sealed</span>
              </div>
            ))}
          </div>
        </div>
      </Card>
    </BodyShell>
  );
}

// ── Section: Terminal & shell ─────────────────────────────────────────────────

function TerminalSection() {
  const { settings, update } = useContext(Ctx);
  const [addingEnv, setAddingEnv] = useState(false);
  const [newKey, setNewKey] = useState('');
  const [newVal, setNewVal] = useState('');

  const envVars = settings.env_vars || [];
  const allowedCmds = settings.allowed_cmds || [];

  const addEnv = () => {
    if (newKey.trim()) update({ env_vars: [...envVars, { k: newKey.trim(), v: newVal }] });
    setNewKey(''); setNewVal(''); setAddingEnv(false);
  };
  const removeEnv = (i) => update({ env_vars: envVars.filter((_, j) => j !== i) });
  const removeCmd = (i) => update({ allowed_cmds: allowedCmds.filter((_, j) => j !== i) });
  const addCmd = (cmd) => { if (cmd) update({ allowed_cmds: [...allowedCmds, cmd] }); };

  return (
    <BodyShell crumb="02 / CAPABILITIES → TERMINAL" title="Terminal & shell"
      desc="How dialekt runs commands on this machine. All execution happens locally, in your user context.">
      <Card title="Execution settings" n="A">
        <Row label="Default shell">
          <Select value={settings.shell || '/bin/bash'} onChange={v => update({ shell: v })} options={[
            { v: '/bin/bash', l: '/bin/bash' }, { v: '/bin/zsh', l: '/bin/zsh' }, { v: '/bin/sh', l: '/bin/sh' },
          ]} />
        </Row>
        <Row label="Command timeout" sub="kill a command if it runs longer than this">
          <Select value={settings.cmd_timeout || '60'} onChange={v => update({ cmd_timeout: v })} options={[
            { v: '10', l: '10s' }, { v: '30', l: '30s' }, { v: '60', l: '60s — default' }, { v: '300', l: '5 min' }, { v: '0', l: 'no limit' },
          ]} />
        </Row>
        <Row label="Outbound network from shell" sub="allow curl, wget, etc.">
          <Toggle value={settings.network_from_shell !== false} onChange={v => update({ network_from_shell: v })} />
        </Row>
        <Row label="Privilege escalation (sudo)" sub="never allow — sealed unless explicitly unlocked" last>
          <Toggle value={!!settings.sudo} onChange={v => update({ sudo: v })} />
        </Row>
      </Card>
      <Card title="Auto-approve commands" n="B" right={<span className="mono" style={{ fontSize: 10, color: T.dim }}>{allowedCmds.length} commands</span>}>
        <div style={{ padding: '12px 14px' }}>
          <div style={{ fontSize: 12, color: T.muted, marginBottom: 10 }}>dialekt runs these without asking. All others trigger a confirmation prompt.</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {allowedCmds.map((c, i) => (
              <span key={i} className="mono" style={{ fontSize: 11, padding: '3px 8px', background: T.bg0, border: `1px solid ${T.border}`, color: T.cyan, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                {c}
                <span onClick={() => removeCmd(i)} style={{ cursor: 'pointer', opacity: 0.5 }}>×</span>
              </span>
            ))}
            <span className="mono" onClick={() => { const c = window.prompt('Command:'); addCmd(c?.trim()); }}
              style={{ fontSize: 11, padding: '3px 8px', border: `1px dashed ${T.border}`, color: T.cyan, cursor: 'pointer' }}>
              + add
            </span>
          </div>
        </div>
      </Card>
      <Card title="Environment variables" n="C">
        {envVars.map((e, i) => (
          <div key={i} style={{ display: 'grid', gridTemplateColumns: '140px 1fr auto', gap: 10, alignItems: 'center', padding: '7px 14px', borderBottom: `1px solid ${T.border}` }}>
            <span className="mono" style={{ fontSize: 11, color: T.cyan }}>{e.k}</span>
            <span className="mono" style={{ fontSize: 10, color: T.muted, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.v}</span>
            <div onClick={() => removeEnv(i)} style={{ cursor: 'pointer', padding: '2px 4px' }}><Icon name="x" size={11} color={T.dim} /></div>
          </div>
        ))}
        {addingEnv ? (
          <div style={{ display: 'grid', gridTemplateColumns: '140px 1fr auto auto', gap: 8, alignItems: 'center', padding: '7px 14px' }}>
            <input autoFocus value={newKey} onChange={e => setNewKey(e.target.value)} placeholder="KEY"
              style={{ background: T.bg0, border: `1px solid ${T.cyan}55`, outline: 'none', fontFamily: T.mono, fontSize: 11, color: T.cyan, padding: '4px 6px', caretColor: T.cyan }} />
            <input value={newVal} onChange={e => setNewVal(e.target.value)} placeholder="value"
              onKeyDown={e => { if (e.key === 'Enter') addEnv(); if (e.key === 'Escape') { setAddingEnv(false); setNewKey(''); setNewVal(''); } }}
              style={{ background: T.bg0, border: `1px solid ${T.border}`, outline: 'none', fontFamily: T.mono, fontSize: 11, color: T.text, padding: '4px 6px' }} />
            <button className="dlk-btn" style={{ fontSize: 10, padding: '2px 8px' }} onClick={addEnv}>Add</button>
            <div onClick={() => { setAddingEnv(false); setNewKey(''); setNewVal(''); }} style={{ cursor: 'pointer' }}><Icon name="x" size={11} color={T.dim} /></div>
          </div>
        ) : (
          <div onClick={() => setAddingEnv(true)} style={{ padding: '7px 14px', display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
            <Icon name="plus" size={12} color={T.cyan} /><span className="mono" style={{ fontSize: 11, color: T.cyan }}>add variable…</span>
          </div>
        )}
      </Card>
    </BodyShell>
  );
}

// ── Section: Browser ──────────────────────────────────────────────────────────

function BrowserSection() {
  const { settings, update } = useContext(Ctx);
  return (
    <BodyShell crumb="02 / CAPABILITIES → BROWSER" title="Browser control"
      desc="Settings for dialekt's browser automation via the claude-in-chrome extension.">
      <ComingSoonBanner label="Browser automation is not yet implemented. These settings will take effect in v1.1." />
      <Card title="Access rules" n="A">
        <PermRow cap="Navigate & read pages"     stateKey="perm_browser_navigate" detail="public web only" />
        <PermRow cap="Fill forms & click"        stateKey="perm_browser_fill"     detail="confirms destructive actions" />
        <PermRow cap="Access logged-in sessions" stateKey="perm_browser_sessions" detail="disabled by default" />
        <PermRow cap="Download files"            stateKey="perm_browser_download" detail="explicit confirmation per file" />
      </Card>
      <Card title="Behaviour" n="B">
        <Row label="Headless mode" sub="run browser without visible window">
          <Toggle value={!!settings.browser_headless} onChange={v => update({ browser_headless: v })} />
        </Row>
        <Row label="Cookie banner policy" sub="auto-action on cookie consent popups">
          <Select value={settings.cookie_policy || 'decline'} onChange={v => update({ cookie_policy: v })} options={[
            { v: 'decline', l: 'Always decline' }, { v: 'accept', l: 'Always accept' }, { v: 'ask', l: 'Ask me' }, { v: 'ignore', l: 'Ignore' },
          ]} />
        </Row>
        <Row label="Ad & tracker block" sub="block known ad/tracking domains during automation">
          <Toggle value={settings.adblock !== false} onChange={v => update({ adblock: v })} />
        </Row>
        <Row label="Session isolation" sub="each browser task starts a clean profile">
          <Toggle value={settings.session_isolation !== false} onChange={v => update({ session_isolation: v })} />
        </Row>
        <Row label="Screenshot on error" sub="auto-capture page on navigation failure" last>
          <Toggle value={settings.screenshot_on_error !== false} onChange={v => update({ screenshot_on_error: v })} />
        </Row>
      </Card>
    </BodyShell>
  );
}

// ── Section: Screen control ───────────────────────────────────────────────────

function ScreenSection() {
  const { settings, update } = useContext(Ctx);
  return (
    <BodyShell crumb="02 / CAPABILITIES → SCREEN" title="Screen & input control"
      desc="Screen capture is used to attach context. Mouse/keyboard control is disabled by default.">
      <ComingSoonBanner label="Screen capture and input control are not yet implemented. These settings will take effect in v1.1." />
      <Card title="Screen capture" n="A">
        <PermRow cap="Screen capture" stateKey="perm_screen_capture" detail="flashes overlay while capturing" />
        <Row label="Show capture overlay" sub="flash a visible indicator when dialekt captures your screen">
          <Toggle value={settings.capture_overlay !== false} onChange={v => update({ capture_overlay: v })} />
        </Row>
        <Row label="Capture quality" sub="resolution for getDisplayMedia frames" last>
          <Select value={settings.capture_quality || 'high'} onChange={v => update({ capture_quality: v })} options={[
            { v: 'low', l: 'Low (720p)' }, { v: 'high', l: 'High (1080p) — default' }, { v: 'native', l: 'Native' },
          ]} />
        </Row>
      </Card>
      <Card title="Vision model" n="B">
        <Row label="Image analysis model" sub="used when @screenshot is attached — picks best available if auto" last>
          <Select value={settings.vision_model || 'auto'} onChange={v => update({ vision_model: v })} options={[
            { v: 'auto', l: 'Auto (best available)' }, { v: 'gemma3', l: 'gemma3 (multimodal)' },
            { v: 'llava', l: 'llava:latest' }, { v: 'moondream', l: 'moondream:latest' },
          ]} />
        </Row>
      </Card>
      <Card title="Input control" n="C">
        <div style={{ padding: '10px 14px', borderBottom: `1px solid ${T.border}` }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px', background: '#2a1f0a', border: `1px solid ${T.amber}44` }}>
            <Icon name="stop" size={12} color={T.amber} />
            <span className="mono" style={{ fontSize: 10, color: T.amber }}>Mouse & keyboard control gives dialekt full desktop access. Off by default.</span>
          </div>
        </div>
        <Row label="Mouse control" sub="dialekt can move cursor and click">
          <Toggle value={!!settings.mouse_control} onChange={v => update({ mouse_control: v })} />
        </Row>
        <Row label="Keyboard control" sub="dialekt can type keystrokes and hotkeys" last>
          <Toggle value={!!settings.keyboard_control} onChange={v => update({ keyboard_control: v })} />
        </Row>
      </Card>
    </BodyShell>
  );
}

// ── Section: Instagram ───────────────────────────────────────────────────────
//
// Native publisher (no MCP) for Instagram Graph API. Two modes:
//
//  • Setup Wizard — shown when /social/instagram/status reports
//    configured=false. Walks the user through creating their own
//    Facebook App (we never proxy a shared dialekt App), pasting in
//    App ID + App Secret, and clicking Connect to open the FB OAuth
//    consent dialog in the system browser.
//
//  • Connected panel — shows linked @username, token expiry, manual
//    publish form (feed_post / story / reel) and Disconnect button.
//
// Every publish goes through ConfirmModal because the action is
// destructive (visible to followers, only deletable through Instagram
// itself). The backend additionally requires confirmed=true on the
// POST body — defence in depth against an MCP-driven agent reaching
// the endpoint without a human in the loop.

const IG_SETUP_STEPS = [
  { i: 1, t: 'Open Meta for Developers',
    d: 'Go to developers.facebook.com and sign in with the Facebook account that owns the Page linked to your Instagram.' },
  { i: 2, t: 'Create a new App',
    d: 'Click "Create App" → choose use case "Other" → app type "Business".' },
  { i: 3, t: 'Add the Instagram product',
    d: 'In the App dashboard sidebar: "Add product" → "Instagram" → "Set up". This enables the Graph API permissions dialekt needs.' },
  { i: 4, t: 'Configure OAuth redirect',
    d: 'Under App Settings → Basic, add the redirect URI shown below to "Valid OAuth Redirect URIs" — without it, Facebook rejects the login.' },
  { i: 5, t: 'Copy App ID and App Secret',
    d: 'Both shown in App Settings → Basic. Click "Show" to reveal the secret. dias.now stores them in your OS keychain — never in plaintext.' },
  { i: 6, t: 'Paste them below and click Connect',
    d: 'A browser tab opens to facebook.com. Approve the permissions, then return here.' },
  { i: 7, t: 'Auto-renewal',
    d: 'Tokens last 60 days. dias.now refreshes within the last week before expiry — no action needed from you.' },
];

function InstagramSection() {
  const { addToast, showConfirm } = useContext(Ctx);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [appId, setAppId] = useState('');
  const [appSecret, setAppSecret] = useState('');
  const [connecting, setConnecting] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [pubKind, setPubKind] = useState('feed_post');
  const [pubMedia, setPubMedia] = useState('');
  const [pubCaption, setPubCaption] = useState('');

  const reload = useCallback(async () => {
    try {
      const r = await fetch(`${API}/social/instagram/status`);
      const j = await r.json();
      setStatus(j);
    } catch {
      setStatus(null);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { reload(); }, [reload]);

  const startConnect = async () => {
    if (!appId.trim() || !appSecret.trim()) {
      addToast('App ID and App Secret are required', 'error');
      return;
    }
    setConnecting(true);
    try {
      const r = await fetch(`${API}/social/instagram/setup/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ app_id: appId.trim(), app_secret: appSecret.trim() }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || 'setup failed');
      window.open(j.auth_url, '_blank', 'noopener,noreferrer');
      addToast('Opened Facebook in a browser tab — return here when done', 'ok');
      const id = setInterval(async () => {
        const s = await fetch(`${API}/social/instagram/status`).then(x => x.json()).catch(() => null);
        if (s?.has_token) {
          clearInterval(id);
          setStatus(s);
          setAppId(''); setAppSecret('');
          addToast(`Connected as @${s.username || s.ig_user_id}`, 'ok');
        }
      }, 2500);
      setTimeout(() => clearInterval(id), 5 * 60 * 1000);
    } catch (e) {
      addToast(`Connect failed: ${e.message}`, 'error');
    } finally {
      setConnecting(false);
    }
  };

  const disconnect = () => showConfirm({
    title: 'Disconnect Instagram?',
    body: 'Removes App ID, App Secret, and access token from the keychain. Posts already published stay live on Instagram. You can revoke the token from facebook.com → Settings → Apps separately.',
    action: 'Disconnect', danger: true,
    onConfirm: async () => {
      try {
        await fetch(`${API}/social/instagram`, { method: 'DELETE' });
        await reload();
        addToast('Disconnected', 'ok');
      } catch (e) {
        addToast(`Disconnect failed: ${e.message}`, 'error');
      }
    },
  });

  const requestPublish = () => {
    if (!pubMedia.trim()) {
      addToast('Media URL is required', 'error');
      return;
    }
    if (!/^https?:\/\//i.test(pubMedia.trim())) {
      addToast('Media must be an HTTPS URL — local file paths are not accepted by Instagram', 'error');
      return;
    }
    const labels = { feed_post: 'feed post', story: 'story', reel: 'Reel' };
    const summary = pubCaption.trim()
      ? `Caption: "${pubCaption.length > 80 ? pubCaption.slice(0, 77) + '…' : pubCaption}"`
      : 'No caption.';
    showConfirm({
      title: `Publish ${labels[pubKind]} to @${status?.username || 'Instagram'}?`,
      body: `${summary} Once published, the post is visible to your followers and can only be deleted from Instagram itself.`,
      action: 'Publish', danger: true,
      onConfirm: async () => {
        setPublishing(true);
        try {
          const r = await fetch(`${API}/social/instagram/publish`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              kind: pubKind,
              media: [pubMedia.trim()],
              caption: pubCaption,
              confirmed: true,
            }),
          });
          const j = await r.json();
          if (!r.ok) throw new Error(j.detail || 'publish failed');
          addToast(`Published — media id ${j.media_id}`, 'ok');
          setPubMedia(''); setPubCaption('');
        } catch (e) {
          addToast(`Publish failed: ${e.message}`, 'error');
        } finally {
          setPublishing(false);
        }
      },
    });
  };

  const formatExpiry = (iso) => {
    if (!iso) return '—';
    try {
      const d = new Date(iso);
      const days = Math.round((d - Date.now()) / (24 * 3600 * 1000));
      return `${d.toLocaleDateString()} (${days >= 0 ? `in ${days}d` : `${-days}d ago`})`;
    } catch { return iso; }
  };

  return (
    <BodyShell crumb="02 / CAPABILITIES → INSTAGRAM" title="Instagram"
      desc="Publish feed posts, stories, and Reels to your Instagram Business or Creator account through the Meta Graph API. You bring your own Facebook App — dias.now never proxies credentials.">

      {/* Account requirements — always visible */}
      <Card title="Account requirements" n="A">
        <div style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          {[
            'Instagram Business or Creator account (a personal account cannot publish via Graph API).',
            'The Instagram account must be linked to a Facebook Page you administer.',
            'You must hold ownership of (or admin access to) the Facebook App used for OAuth.',
          ].map((line, i) => (
            <div key={i} style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
              <Icon name="stop" size={11} color={T.amber} />
              <span style={{ fontSize: 12, color: T.muted, lineHeight: 1.55 }}>{line}</span>
            </div>
          ))}
        </div>
      </Card>

      {loading ? (
        <div style={{ color: T.dim, fontSize: 13, padding: '24px 0' }}>Loading…</div>
      ) : status?.has_token ? (
        <>
          <Card title={`Connected · @${status.username || status.ig_user_id}`} n="B"
            right={
              <span className="mono" style={{ fontSize: 10, color: T.green, letterSpacing: '.08em' }}>
                ACTIVE
              </span>
            }>
            <Row label="Instagram username" sub="from the linked FB Page">
              <span className="mono" style={{ fontSize: 12, color: T.text }}>
                @{status.username || '—'}
              </span>
            </Row>
            <Row label="IG user ID" sub="numeric Graph API id">
              <span className="mono" style={{ fontSize: 11, color: T.dim }}>{status.ig_user_id}</span>
            </Row>
            <Row label="App ID" sub="kept in OS keychain (never in config.json)">
              <span className="mono" style={{ fontSize: 11, color: T.dim }}>
                {status.app_id_prefix || '—'}
              </span>
            </Row>
            <Row label="Token expires" sub="dias.now refreshes within 7 days of expiry">
              <span className="mono" style={{ fontSize: 11,
                color: status.needs_refresh ? T.amber : T.dim }}>
                {formatExpiry(status.expires)}
              </span>
            </Row>
            <Row label="Disconnect" sub="removes credentials from this machine" last>
              <button className="dlk-btn"
                style={{ borderColor: T.red + '66', color: T.red }}
                onClick={disconnect}>
                Disconnect
              </button>
            </Row>
          </Card>

          <Card title="Publish" n="C">
            <div style={{
              padding: '10px 14px', borderBottom: `1px solid ${T.border}`,
              display: 'flex', gap: 8, alignItems: 'center',
              background: '#2a1f0a', color: T.amber,
            }}>
              <Icon name="stop" size={11} color={T.amber} />
              <span className="mono" style={{ fontSize: 10, letterSpacing: '.06em' }}>
                Each publish requires explicit confirmation — once live, deletion only on Instagram.
              </span>
            </div>
            <Row label="Kind" sub="feed post · story · reel">
              <Select value={pubKind} onChange={setPubKind} options={[
                { v: 'feed_post', l: 'Feed post (image)' },
                { v: 'story',     l: 'Story (image, 24h)' },
                { v: 'reel',      l: 'Reel (video)' },
              ]} />
            </Row>
            <Row label="Media URL" sub="must be HTTPS — Instagram does not accept local paths">
              <input
                type="url"
                value={pubMedia}
                onChange={e => setPubMedia(e.target.value)}
                placeholder="https://…/photo.jpg"
                style={{
                  width: 360, background: T.bg0, border: `1px solid ${T.border}`,
                  outline: 'none', fontFamily: T.mono, fontSize: 11, color: T.text,
                  padding: '6px 10px', caretColor: T.cyan,
                }}
              />
            </Row>
            <Row label="Caption" sub="ignored for stories" last>
              <textarea
                value={pubCaption}
                onChange={e => setPubCaption(e.target.value)}
                rows={3}
                placeholder="What's the post about?"
                style={{
                  width: 360, background: T.bg0, border: `1px solid ${T.border}`,
                  outline: 'none', fontFamily: T.mono, fontSize: 11, color: T.text,
                  padding: '6px 10px', resize: 'vertical', caretColor: T.cyan,
                }}
              />
            </Row>
            <div style={{ padding: '12px 14px', display: 'flex', justifyContent: 'flex-end' }}>
              <button className="dlk-btn primary"
                disabled={publishing || !pubMedia.trim()}
                onClick={requestPublish}
                style={{ opacity: publishing || !pubMedia.trim() ? 0.5 : 1 }}>
                {publishing ? 'Publishing…' : 'Publish'}
              </button>
            </div>
          </Card>
        </>
      ) : (
        <>
          <Card title="Setup wizard" n="B">
            {IG_SETUP_STEPS.map((s, i) => (
              <div key={s.i} style={{
                display: 'flex', gap: 14, padding: '14px 16px',
                borderBottom: i < IG_SETUP_STEPS.length - 1 ? `1px solid ${T.border}` : 'none',
              }}>
                <span className="mono" style={{
                  width: 22, height: 22, lineHeight: '22px', textAlign: 'center',
                  border: `1px solid ${T.cyan}66`, color: T.cyan, fontSize: 11,
                  flexShrink: 0,
                }}>{s.i}</span>
                <div>
                  <div style={{ fontSize: 13, color: T.text, marginBottom: 4 }}>{s.t}</div>
                  <div style={{ fontSize: 11, color: T.muted, lineHeight: 1.55 }}>{s.d}</div>
                </div>
              </div>
            ))}
          </Card>

          <Card title="OAuth redirect URI" n="C">
            <div style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 8 }}>
              <span style={{ fontSize: 12, color: T.muted, lineHeight: 1.55 }}>
                Add this exact URL to your FB App under{' '}
                <span className="mono" style={{ color: T.text }}>App Settings → Basic → Valid OAuth Redirect URIs</span>:
              </span>
              <div className="mono" style={{
                background: T.bg0, border: `1px solid ${T.border}`,
                padding: '8px 10px', fontSize: 11, color: T.cyan,
                userSelect: 'all',
              }}>
                {status?.redirect_uri || `http://localhost:8765/social/instagram/setup/callback`}
              </div>
            </div>
          </Card>

          <Card title="Credentials" n="D">
            <Row label="App ID" sub="from App Settings → Basic">
              <input
                value={appId}
                onChange={e => setAppId(e.target.value)}
                placeholder="123456789012345"
                style={{
                  width: 280, background: T.bg0, border: `1px solid ${T.border}`,
                  outline: 'none', fontFamily: T.mono, fontSize: 11, color: T.text,
                  padding: '6px 10px', caretColor: T.cyan,
                }}
              />
            </Row>
            <Row label="App Secret" sub="kept in OS keychain — never returned to the UI" last>
              <input
                type="password"
                value={appSecret}
                onChange={e => setAppSecret(e.target.value)}
                placeholder="••••••••••••••••"
                style={{
                  width: 280, background: T.bg0, border: `1px solid ${T.border}`,
                  outline: 'none', fontFamily: T.mono, fontSize: 11, color: T.text,
                  padding: '6px 10px', caretColor: T.cyan,
                }}
              />
            </Row>
            <div style={{ padding: '12px 14px', display: 'flex', justifyContent: 'flex-end' }}>
              <button className="dlk-btn primary"
                disabled={connecting || !appId.trim() || !appSecret.trim()}
                onClick={startConnect}
                style={{ opacity: connecting || !appId.trim() || !appSecret.trim() ? 0.5 : 1 }}>
                {connecting ? 'Opening browser…' : 'Connect'}
              </button>
            </div>
          </Card>
        </>
      )}
    </BodyShell>
  );
}

// ── Section: MCP tools ────────────────────────────────────────────────────────

const MCP_TOOLS = [
  { name: 'github',     source: 'npm:@modelcontextprotocol/server-github', n: 12, state: 'connected', desc: 'repos, issues, PRs, code search' },
  { name: 'postgres',   source: 'local binary',                            n: 6,  state: 'connected', desc: 'query prod-readonly · dialekt_db' },
  { name: 'slack',      source: 'npm:@mcp/slack',                          n: 8,  state: 'connected', desc: 'send messages, read channels' },
  { name: 'linear',     source: 'npm:@mcp/linear',                         n: 9,  state: 'ask',       desc: 'issues, projects, triage' },
  { name: 'figma',      source: 'npm:@mcp/figma',                          n: 4,  state: 'connected', desc: 'read frames, export assets' },
  { name: 'playwright', source: 'local binary',                            n: 22, state: 'disabled',  desc: 'browser automation' },
];

// ── Section: MCP Servers (Phase 1.3) ──────────────────────────────────────────
//
// CRUD surface over /mcp-servers. Mirrors ConnectionsSection structure:
// inline form (no modal), fetch-direct, showConfirm for destructive actions,
// per-row [TEST] with inline result. Secrets never round-trip — backend
// returns has_auth_token: bool and never the plaintext.

const EMPTY_MCP_FORM = {
  name: '',
  transport: 'stdio',
  command_text: '',
  cwd: '',
  url: '',
  auth_type: '',
  auth_token: '',
  replace_token: false,
  env_refs: [],          // [{env_name, ref_name}]
  env_secrets: [],       // [{ref, value}] — plaintext going to keyring
  timeout_seconds: '30',
};

const MCP_NAME_RE = /^[a-z][a-z0-9-]{0,63}$/;

function MCPSection() {
  const { addToast, showConfirm } = useContext(Ctx);
  const [servers, setServers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [testStatus, setTestStatus] = useState({});
  const [form, setForm] = useState(EMPTY_MCP_FORM);
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);
  // v0.21: Quick Add catalog + which template tile is open in the modal
  const [templates, setTemplates] = useState([]);
  const [openTemplate, setOpenTemplate] = useState(null);
  const [openImport, setOpenImport] = useState(false);
  // v0.22: per-row tool inspector. inspectIds = which rows are
  // expanded; toolsByServer = {[server.id]: {loading, tools, error}}.
  // Read-only — allow/deny scoping is per-agent, not per-server.
  const [inspectIds, setInspectIds] = useState(new Set());
  const [toolsByServer, setToolsByServer] = useState({});

  const inspectTools = async (s) => {
    setInspectIds(prev => {
      const next = new Set(prev);
      if (next.has(s.id)) {
        next.delete(s.id);
        return next;
      }
      next.add(s.id);
      return next;
    });
    if (toolsByServer[s.id]) return; // already fetched
    setToolsByServer(prev => ({ ...prev, [s.id]: { loading: true } }));
    try {
      const r = await fetch(`${API}/mcp-servers/${s.id}/tools`);
      const body = await r.json();
      setToolsByServer(prev => ({
        ...prev,
        [s.id]: { loading: false, tools: body.tools || [], error: body.error || '' },
      }));
    } catch (e) {
      setToolsByServer(prev => ({
        ...prev, [s.id]: { loading: false, tools: [], error: String(e) },
      }));
    }
  };

  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`${API}/mcp-servers`);
      const data = await r.json();
      setServers(Array.isArray(data) ? data : []);
    } catch (e) {
      addToast('Failed to load MCP servers', 'error');
    } finally {
      setLoading(false);
    }
  }, [addToast]);

  useEffect(() => { refresh(); }, [refresh]);

  // Load the Quick Add catalog once. Failure is non-fatal — Quick Add
  // hides itself and the freeform form path stays available.
  useEffect(() => {
    fetch(`${API}/mcp-templates`)
      .then((r) => r.ok ? r.json() : Promise.reject())
      .then((data) => {
        if (Array.isArray(data?.templates)) setTemplates(data.templates);
      })
      .catch(() => { /* Quick Add unavailable; freeform CRUD still works */ });
  }, []);

  const fset = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const resetForm = () => {
    setForm(EMPTY_MCP_FORM);
    setAdding(false);
    setEditingId(null);
    setFormError('');
  };

  const beginEdit = (s) => {
    setForm({
      name: s.name,
      transport: s.transport,
      command_text: (s.command || []).join('\n'),
      cwd: s.cwd || '',
      url: s.url || '',
      auth_type: s.auth_type || '',
      auth_token: '',
      replace_token: false,
      env_refs: Object.entries(s.env_refs || {}).map(([env_name, ref_name]) => ({ env_name, ref_name })),
      env_secrets: [],
      timeout_seconds: String(s.timeout_seconds || 30),
    });
    setEditingId(s.id);
    setAdding(false);
    setFormError('');
  };

  const addEnvRef = () => setForm(f => ({ ...f, env_refs: [...f.env_refs, { env_name: '', ref_name: '' }] }));
  const removeEnvRef = (i) => setForm(f => ({ ...f, env_refs: f.env_refs.filter((_, j) => j !== i) }));
  const setEnvRef = (i, k, v) => setForm(f => ({
    ...f,
    env_refs: f.env_refs.map((r, j) => j === i ? { ...r, [k]: v } : r),
  }));

  const addEnvSecret = () => setForm(f => ({ ...f, env_secrets: [...f.env_secrets, { ref: '', value: '' }] }));
  const removeEnvSecret = (i) => setForm(f => ({ ...f, env_secrets: f.env_secrets.filter((_, j) => j !== i) }));
  const setEnvSecret = (i, k, v) => setForm(f => ({
    ...f,
    env_secrets: f.env_secrets.map((s, j) => j === i ? { ...s, [k]: v } : s),
  }));

  const validate = () => {
    if (!MCP_NAME_RE.test(form.name)) return 'Name must be kebab-case (a-z, 0-9, -), start with a letter.';
    if (editingId == null && servers.some(s => s.name === form.name)) return `Server named "${form.name}" already exists.`;
    if (form.transport === 'stdio' && !form.command_text.trim()) return 'stdio transport requires a command.';
    if (form.transport === 'http' && !/^https?:\/\//.test(form.url.trim())) return 'http transport requires a valid URL.';
    const isCreating = editingId == null;
    if (form.auth_type === 'bearer' && isCreating && !form.auth_token) return 'Bearer auth requires a token.';
    const ts = parseFloat(form.timeout_seconds);
    if (!Number.isFinite(ts) || ts < 5 || ts > 300) return 'Timeout must be between 5 and 300 seconds.';
    return '';
  };

  const submit = async () => {
    const err = validate();
    if (err) { setFormError(err); return; }
    setFormError('');
    setSaving(true);

    const env_refs = Object.fromEntries(form.env_refs.filter(r => r.env_name && r.ref_name).map(r => [r.env_name, r.ref_name]));
    const env_secrets = form.env_secrets.filter(s => s.ref && s.value);

    const payload = {
      name: form.name,
      transport: form.transport,
      timeout_seconds: parseFloat(form.timeout_seconds),
      cwd: form.cwd || null,
      env_refs,
      env_secrets,
    };
    if (form.transport === 'stdio') {
      payload.command = form.command_text.split('\n').map(s => s.trim()).filter(Boolean);
    } else {
      payload.url = form.url.trim();
      if (form.auth_type) payload.auth_type = form.auth_type;
      if (form.auth_token && (editingId == null || form.replace_token)) payload.auth_token = form.auth_token;
    }

    try {
      const url = editingId ? `${API}/mcp-servers/${editingId}` : `${API}/mcp-servers`;
      const method = editingId ? 'PATCH' : 'POST';
      const r = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!r.ok) {
        const msg = (await r.json().catch(() => ({})))?.detail || `HTTP ${r.status}`;
        setFormError(typeof msg === 'string' ? msg : JSON.stringify(msg));
        return;
      }
      await refresh();
      addToast(editingId ? 'Server updated' : 'Server added', 'ok');
      resetForm();
    } catch (e) {
      setFormError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const remove = (s) => {
    showConfirm({
      title: `Delete "${s.name}"?`,
      body: 'The server config and its keyring entries will be removed. Agents using this server will fail until you add it again.',
      confirmLabel: 'Delete',
      onConfirm: async () => {
        try {
          const r = await fetch(`${API}/mcp-servers/${s.id}`, { method: 'DELETE' });
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          setServers(prev => prev.filter(x => x.id !== s.id));
          addToast(`"${s.name}" deleted`, 'ok');
        } catch (e) {
          addToast(`Delete failed: ${e}`, 'error');
          refresh();
        }
      },
    });
  };

  const runTest = async (s) => {
    setTestStatus(prev => ({ ...prev, [s.id]: { phase: 'testing' } }));
    try {
      const r = await fetch(`${API}/mcp-servers/${s.id}/test`, { method: 'POST' });
      const data = await r.json();
      if (data.success) {
        setTestStatus(prev => ({ ...prev, [s.id]: { phase: 'ok', tool_count: data.tool_count } }));
      } else {
        setTestStatus(prev => ({ ...prev, [s.id]: { phase: 'error', error: data.error } }));
      }
      refresh();
    } catch (e) {
      setTestStatus(prev => ({ ...prev, [s.id]: { phase: 'error', error: String(e) } }));
    }
  };

  const FInput = ({ label, k, type = 'text', placeholder, style: s }) => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, ...s }}>
      <label style={{ fontSize: 11, color: T.dim }}>{label}</label>
      <input type={type} value={form[k]} onChange={e => fset(k, e.target.value)}
        placeholder={placeholder} style={{
          background: T.bg2, border: `1px solid ${T.border}`, color: T.text,
          padding: '7px 10px', fontSize: 12, outline: 'none', width: '100%', boxSizing: 'border-box',
        }} />
    </div>
  );

  const statusDot = (s) => {
    const st = testStatus[s.id];
    const live = st?.phase;
    if (live === 'testing') return { color: T.amber, label: 'testing…' };
    if (live === 'ok') return { color: T.green, label: `${st.tool_count} tool${st.tool_count === 1 ? '' : 's'}` };
    if (live === 'error') return { color: T.red, label: 'error' };
    if (s.last_test_ok === true) return { color: T.green, label: `${s.tool_count || 0} tool${s.tool_count === 1 ? '' : 's'}` };
    if (s.last_test_ok === false) return { color: T.red, label: 'error' };
    return { color: T.dim, label: 'untested' };
  };

  const MCPRow = ({ s, i }) => {
    const dot = statusDot(s);
    const st = testStatus[s.id];
    const transportLine = s.transport === 'stdio'
      ? `stdio · ${(s.command || []).slice(0, 2).join(' ')}${(s.command || []).length > 2 ? ' …' : ''}`
      : `http · ${s.url}`;
    return (
      <Card key={s.id} title={s.name} n={String(i + 1).padStart(2, '0')} right={
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className="mono" style={{ color: dot.color, fontSize: 11 }} aria-label={dot.label}>● {dot.label}</span>
        </div>
      }>
        <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div className="mono" style={{ fontSize: 11, color: T.muted }}>{transportLine}</div>
          {s.has_auth_token && (
            <div style={{ fontSize: 11, color: T.dim }}>Bearer: <span className="mono" style={{ color: T.muted }}>••••••••</span></div>
          )}
          {s.auth_type === 'bearer' && !s.has_auth_token && (
            <div style={{ fontSize: 11, color: T.amber }}>⚠ auth_type=bearer but no token set</div>
          )}
          {st?.phase === 'error' && st.error && (
            <div style={{ fontSize: 11, color: T.red, border: `1px solid ${T.red}33`, padding: '6px 10px', background: `${T.red}0a` }}>{st.error}</div>
          )}
          {st?.phase === 'ok' && (
            <div style={{ fontSize: 11, color: T.green }}>✓ {st.tool_count} tool{st.tool_count === 1 ? '' : 's'} discovered</div>
          )}
          {s.last_test_at && !st && (
            <div style={{ fontSize: 10, color: T.dim }}>last tested {s.last_test_at}{s.last_test_error ? ` — ${s.last_test_error}` : ''}</div>
          )}
          <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
            <button onClick={() => runTest(s)} disabled={st?.phase === 'testing'} style={{
              background: 'transparent', border: `1px solid ${T.border}`, color: T.text,
              padding: '5px 12px', fontSize: 11, cursor: st?.phase === 'testing' ? 'default' : 'pointer',
            }}>{st?.phase === 'testing' ? 'TESTING…' : 'TEST'}</button>
            <button onClick={() => inspectTools(s)} disabled={s.last_test_ok !== true} style={{
              background: 'transparent', border: `1px solid ${T.border}`,
              color: s.last_test_ok === true ? T.text : T.dim,
              padding: '5px 12px', fontSize: 11,
              cursor: s.last_test_ok === true ? 'pointer' : 'not-allowed',
            }}>{inspectIds.has(s.id) ? 'HIDE TOOLS' : 'INSPECT TOOLS ▾'}</button>
            <button onClick={() => beginEdit(s)} style={{
              background: 'transparent', border: `1px solid ${T.border}`, color: T.text,
              padding: '5px 12px', fontSize: 11, cursor: 'pointer',
            }}>EDIT</button>
            <button onClick={() => remove(s)} style={{
              background: 'transparent', border: `1px solid ${T.red}66`, color: T.red,
              padding: '5px 12px', fontSize: 11, cursor: 'pointer',
            }}>DELETE</button>
          </div>
          {inspectIds.has(s.id) && (() => {
            const ts = toolsByServer[s.id] || { loading: true };
            const destCount = (ts.tools || []).filter(t => t.destructive).length;
            return (
              <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
                {!ts.loading && !ts.error && destCount > 0 && (
                  <div style={{ fontSize: 11, color: T.muted, padding: '6px 10px',
                    border: `1px solid ${T.border}`, background: T.bg2 }}>
                    This server exposes {destCount} destructive tool{destCount === 1 ? '' : 's'}. Per-agent scoping in agent settings.
                  </div>
                )}
                <McpToolList
                  tools={ts.tools}
                  loading={ts.loading}
                  error={ts.error}
                  mode="readonly"
                />
              </div>
            );
          })()}
        </div>
      </Card>
    );
  };

  const isFormOpen = adding || editingId != null;
  const formTitle = editingId ? 'Edit MCP server' : 'New MCP server';

  // v0.21: Quick Add tile row, rendered above the configured-servers list.
  const QuickAddRow = () => {
    if (!templates.length) return null;
    return (
      <Card title="Quick add from template" n="01">
        <div style={{ padding: '12px 14px', display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {templates.map((t) => {
            const badge = t.validated
              ? { color: T.green, mark: '✓' }
              : { color: T.amber, mark: '⚠' };
            return (
              <button key={t.id} onClick={() => setOpenTemplate(t)} style={{
                background: T.bg2, border: `1px solid ${T.border}`, color: T.text,
                padding: '8px 12px', fontSize: 12, cursor: 'pointer',
                display: 'flex', alignItems: 'center', gap: 8,
              }}>
                <span className="mono" style={{ fontSize: 10, color: badge.color }}>{badge.mark}</span>
                <span>{t.label}</span>
              </button>
            );
          })}
        </div>
        <div style={{ padding: '0 14px 12px', fontSize: 10, color: T.dim }}>
          ✓ validated · ⚠ untested community package — verify with [Test] before pilot rollout
        </div>
      </Card>
    );
  };

  return (
    <BodyShell crumb="02 / CAPABILITIES → MCP SERVERS" title="MCP Servers"
      desc="External MCP servers agents can call. Credentials are stored in your OS keychain — never in config files or logs.">

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginBottom: 8 }}>
        <button onClick={() => setOpenImport(true)} style={{
          background: 'transparent', border: `1px solid ${T.border}`, color: T.text,
          padding: '6px 14px', fontSize: 11, cursor: 'pointer', letterSpacing: '.04em',
        }}>IMPORT BUNDLE</button>
        <button onClick={async () => {
          const r = await fetch(`${API}/mcp-servers/export`);
          const blob = await r.blob();
          const u = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = u; a.download = 'dialekt-mcp-servers.json'; a.click();
          URL.revokeObjectURL(u);
        }} disabled={servers.length === 0} style={{
          background: 'transparent', border: `1px solid ${T.border}`, color: servers.length ? T.text : T.dim,
          padding: '6px 14px', fontSize: 11, cursor: servers.length ? 'pointer' : 'default', letterSpacing: '.04em',
        }}>EXPORT JSON</button>
      </div>
      <QuickAddRow />

      {loading ? (
        <div style={{ color: T.dim, fontSize: 13, padding: '24px 0' }}>Loading…</div>
      ) : servers.length === 0 && !isFormOpen ? (
        <Card>
          <div style={{ padding: '40px 0', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
            <Icon name="cog" size={28} color={T.dim} />
            <div style={{ color: T.dim, fontSize: 13 }}>No MCP servers yet. Pick a template above or add a custom server.</div>
            <button onClick={() => setAdding(true)} style={{
              background: T.cyan, color: '#000', border: 'none', padding: '8px 18px',
              fontSize: 12, fontWeight: 600, cursor: 'pointer', letterSpacing: '.04em',
            }}>+ ADD CUSTOM SERVER</button>
          </div>
        </Card>
      ) : (
        <>
          {servers.map((s, i) => <MCPRow key={s.id} s={s} i={i} />)}
          {!isFormOpen && (
            <button onClick={() => setAdding(true)} style={{
              background: 'transparent', border: `1px dashed ${T.border}`, color: T.muted,
              padding: '10px', width: '100%', fontSize: 12, cursor: 'pointer', marginTop: 8, letterSpacing: '.04em',
            }}>+ ADD CUSTOM SERVER</button>
          )}
        </>
      )}

      <McpTemplateModal
        template={openTemplate}
        onClose={() => setOpenTemplate(null)}
        onSaved={(created) => {
          addToast(`Server "${created.name}" added`, 'ok');
          refresh();
        }}
      />
      {openImport && (
        <McpBulkImportModal existingNames={servers.map((s) => s.name)}
          onClose={() => setOpenImport(false)}
          onImported={(body) => {
            const n = (body?.imported || []).length, m = (body?.secrets_needed || []).length;
            addToast(`Imported ${n} server${n === 1 ? '' : 's'}` + (m > 0 ? `. ${m} credential${m === 1 ? '' : 's'} required — open each server to add them.` : '.'), 'ok');
            refresh();
          }} />
      )}


      {isFormOpen && (
        <Card title={formTitle} n={editingId ? 'EDIT' : 'NEW'}>
          <div style={{ padding: '16px 14px', display: 'flex', flexDirection: 'column', gap: 14 }}>
            <FInput label="Name *" k="name" placeholder="github" />
            <div style={{ fontSize: 10, color: T.dim, marginTop: -8 }}>kebab-case, unique</div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <label style={{ fontSize: 11, color: T.dim }}>Transport *</label>
              <div style={{ display: 'flex', gap: 16 }}>
                {['stdio', 'http'].map(t => (
                  <label key={t} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, cursor: 'pointer' }}>
                    <input type="radio" name="mcp-transport" value={t} checked={form.transport === t}
                      onChange={e => fset('transport', e.target.value)} />
                    <span className="mono" style={{ color: T.text }}>{t}</span>
                  </label>
                ))}
              </div>
            </div>

            {form.transport === 'stdio' ? (
              <>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <label style={{ fontSize: 11, color: T.dim }}>Command * <span style={{ color: T.dim }}>(one argv token per line)</span></label>
                  <textarea value={form.command_text} onChange={e => fset('command_text', e.target.value)}
                    placeholder={'npx\n-y\n@modelcontextprotocol/server-github'} rows={4} style={{
                      background: T.bg2, border: `1px solid ${T.border}`, color: T.text,
                      padding: '8px 10px', fontSize: 12, fontFamily: 'var(--code-font, monospace)', outline: 'none',
                      width: '100%', boxSizing: 'border-box', resize: 'vertical',
                    }} />
                </div>
                <FInput label="Working directory (optional)" k="cwd" placeholder="/path/to/cwd" />
              </>
            ) : (
              <>
                <FInput label="URL *" k="url" placeholder="https://example.com/mcp" />
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <label style={{ fontSize: 11, color: T.dim }}>Auth</label>
                  <select value={form.auth_type} onChange={e => fset('auth_type', e.target.value)} style={{
                    background: T.bg2, border: `1px solid ${T.border}`, color: T.text,
                    padding: '7px 10px', fontSize: 12, outline: 'none', width: '100%',
                  }}>
                    <option value="">None</option>
                    <option value="bearer">Bearer token</option>
                  </select>
                </div>
                {form.auth_type === 'bearer' && (
                  <>
                    {editingId && !form.replace_token ? (
                      <div style={{ fontSize: 11, color: T.dim, display: 'flex', gap: 10, alignItems: 'center' }}>
                        <span>Token: <span className="mono">••••••••</span></span>
                        <button type="button" onClick={() => fset('replace_token', true)} style={{
                          background: 'transparent', border: `1px solid ${T.border}`, color: T.text,
                          padding: '3px 10px', fontSize: 10, cursor: 'pointer',
                        }}>REPLACE</button>
                      </div>
                    ) : (
                      <FInput label={editingId ? 'New bearer token *' : 'Bearer token *'} k="auth_token" type="password" placeholder="ghp_…" />
                    )}
                  </>
                )}
              </>
            )}

            {/* Env refs + secrets — only meaningful for stdio but harmless for http */}
            {form.transport === 'stdio' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div style={{ fontSize: 11, color: T.dim }}>Environment variables (mapped to secret refs)</div>
                {form.env_refs.map((r, i) => (
                  <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto', gap: 8 }}>
                    <input placeholder="GITHUB_TOKEN" value={r.env_name}
                      onChange={e => setEnvRef(i, 'env_name', e.target.value)} style={{
                        background: T.bg2, border: `1px solid ${T.border}`, color: T.text,
                        padding: '6px 10px', fontSize: 12, fontFamily: 'var(--code-font, monospace)',
                      }} />
                    <input placeholder="github_token (secret ref)" value={r.ref_name}
                      onChange={e => setEnvRef(i, 'ref_name', e.target.value)} style={{
                        background: T.bg2, border: `1px solid ${T.border}`, color: T.text,
                        padding: '6px 10px', fontSize: 12, fontFamily: 'var(--code-font, monospace)',
                      }} />
                    <button onClick={() => removeEnvRef(i)} style={{
                      background: 'transparent', border: `1px solid ${T.border}`, color: T.dim,
                      padding: '4px 10px', fontSize: 11, cursor: 'pointer',
                    }}>−</button>
                  </div>
                ))}
                <button type="button" onClick={addEnvRef} style={{
                  background: 'transparent', border: `1px dashed ${T.border}`, color: T.muted,
                  padding: '6px 10px', fontSize: 11, cursor: 'pointer', alignSelf: 'flex-start',
                }}>+ add variable</button>

                <div style={{ fontSize: 11, color: T.dim, marginTop: 4 }}>
                  Credential values (plaintext → keyring)
                </div>
                {form.env_secrets.map((sec, i) => (
                  <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto', gap: 8 }}>
                    <input placeholder="github_token (matches ref)" value={sec.ref}
                      onChange={e => setEnvSecret(i, 'ref', e.target.value)} style={{
                        background: T.bg2, border: `1px solid ${T.border}`, color: T.text,
                        padding: '6px 10px', fontSize: 12, fontFamily: 'var(--code-font, monospace)',
                      }} />
                    <input type="password" placeholder="ghp_…" value={sec.value}
                      onChange={e => setEnvSecret(i, 'value', e.target.value)} style={{
                        background: T.bg2, border: `1px solid ${T.border}`, color: T.text,
                        padding: '6px 10px', fontSize: 12,
                      }} />
                    <button onClick={() => removeEnvSecret(i)} style={{
                      background: 'transparent', border: `1px solid ${T.border}`, color: T.dim,
                      padding: '4px 10px', fontSize: 11, cursor: 'pointer',
                    }}>−</button>
                  </div>
                ))}
                <button type="button" onClick={addEnvSecret} style={{
                  background: 'transparent', border: `1px dashed ${T.border}`, color: T.muted,
                  padding: '6px 10px', fontSize: 11, cursor: 'pointer', alignSelf: 'flex-start',
                }}>+ add credential</button>
                {editingId && (
                  <div style={{ fontSize: 10, color: T.dim }}>
                    Existing credentials stay in the keyring unless a new value is provided here.
                  </div>
                )}
              </div>
            )}

            <FInput label="Timeout (seconds)" k="timeout_seconds" placeholder="30" />

            {formError && (
              <div style={{ fontSize: 11, color: T.red, border: `1px solid ${T.red}44`, padding: '8px 12px', background: `${T.red}0a` }}>
                {formError}
              </div>
            )}

            <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
              <button onClick={submit} disabled={saving} style={{
                background: T.cyan, color: '#000', border: 'none', padding: '8px 20px',
                fontSize: 12, fontWeight: 600, cursor: saving ? 'default' : 'pointer', letterSpacing: '.04em',
              }}>{saving ? 'SAVING…' : (editingId ? 'SAVE' : 'ADD')}</button>
              <button onClick={resetForm} disabled={saving} style={{
                background: 'transparent', border: `1px solid ${T.border}`, color: T.text,
                padding: '8px 20px', fontSize: 12, cursor: 'pointer',
              }}>CANCEL</button>
            </div>
          </div>
        </Card>
      )}
    </BodyShell>
  );
}

// ── Section: Storage & memory ─────────────────────────────────────────────────

function StorageSection() {
  const { settings, update, addToast, showConfirm } = useContext(Ctx);
  const facts = settings.facts || [];
  const [sessionStats, setSessionStats] = useState({ sessions: 0, msgs: 0 });
  const [addingFact, setAddingFact] = useState(false);
  const [newFact, setNewFact] = useState('');

  useEffect(() => {
    fetch(`${API}/sessions`).then(r => r.json()).then(d => {
      setSessionStats({ sessions: d.length, msgs: d.reduce((s, x) => s + (x.message_count || 0), 0) });
    }).catch(() => {});
  }, []);

  const wipe = () => showConfirm({
    title: 'Wipe all conversations',
    body: `This will permanently delete ${sessionStats.sessions} sessions and ${sessionStats.msgs} messages. Models are kept. This cannot be undone.`,
    action: 'Wipe conversations',
    danger: true,
    onConfirm: async () => {
      try {
        await fetch(`${API}/sessions`, { method: 'DELETE' });
        setSessionStats({ sessions: 0, msgs: 0 });
        addToast('All conversations wiped', 'warn');
      } catch {
        addToast('Wipe failed', 'error');
      }
    },
  });

  const reset = () => showConfirm({
    title: 'Reset dialekt',
    body: 'Wipes all conversations and resets all settings to factory defaults. Models are kept. This cannot be undone.',
    action: 'Reset everything',
    danger: true,
    onConfirm: async () => {
      try {
        await fetch(`${API}/sessions`, { method: 'DELETE' });
        await fetch(`${API}/settings`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(DEFAULTS) });
        setSessionStats({ sessions: 0, msgs: 0 });
        addToast('dialekt reset to defaults', 'warn');
      } catch {
        addToast('Reset failed', 'error');
      }
    },
  });

  const exportData = async () => {
    try {
      const sessions = await fetch(`${API}/sessions`).then(r => r.json());
      const blob = new Blob([JSON.stringify({ settings, sessions }, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url; a.download = 'dialekt-export.json'; a.click();
      URL.revokeObjectURL(url);
      addToast('Export downloaded', 'ok');
    } catch {
      addToast('Export failed', 'error');
    }
  };

  const addFact = () => {
    if (newFact.trim()) {
      update({ facts: [...facts, { t: newFact.trim(), src: 'added manually' }] });
      setNewFact(''); setAddingFact(false);
    }
  };

  return (
    <BodyShell crumb="03 / SYSTEM → STORAGE & MEMORY" title="Storage & memory"
      desc="All data is on this machine. Nothing is synced to a cloud account.">
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', border: `1px solid ${T.border}`, marginBottom: 18 }}>
        {[
          { k: 'Sessions',   v: sessionStats.sessions || '0' },
          { k: 'Messages',   v: sessionStats.msgs || '0'     },
          { k: 'Memory facts', v: facts.length              },
          { k: 'Cloud sync', v: 'never', accent: true       },
        ].map((s, i) => (
          <div key={i} style={{ padding: '14px 16px', borderRight: i < 3 ? `1px solid ${T.border}` : 'none', background: s.accent ? T.bg2 : T.bg1 }}>
            <div className="upper" style={{ color: T.dim, marginBottom: 6 }}>{s.k}</div>
            <div className="mono" style={{ fontSize: 20, fontWeight: 600, color: s.accent ? T.green : T.text }}>{s.v}</div>
          </div>
        ))}
      </div>

      <Card title="Long-term memory" n="A"
        right={
          <button className="dlk-btn" style={{ padding: '3px 8px', fontSize: 10 }} onClick={() => setAddingFact(true)}>
            Add fact
          </button>
        }>
        <div style={{ padding: '4px 14px 8px', borderBottom: `1px solid ${T.border}` }}>
          <span className="mono" style={{ fontSize: 10, color: T.dim }}>things dialekt remembers about you · survives across sessions</span>
        </div>
        {addingFact && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px', borderBottom: `1px solid ${T.border}` }}>
            <input autoFocus value={newFact} onChange={e => setNewFact(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') addFact(); if (e.key === 'Escape') { setAddingFact(false); setNewFact(''); } }}
              placeholder="Type a fact dialekt should remember…"
              style={{ flex: 1, background: T.bg0, border: `1px solid ${T.cyan}55`, outline: 'none', fontFamily: 'inherit', fontSize: 12, color: T.text, padding: '6px 10px', caretColor: T.cyan }} />
            <button className="dlk-btn" style={{ padding: '2px 10px', fontSize: 10 }} onClick={addFact}>Add</button>
            <div onClick={() => { setAddingFact(false); setNewFact(''); }} style={{ cursor: 'pointer' }}><Icon name="x" size={11} color={T.dim} /></div>
          </div>
        )}
        {facts.map((f, i) => (
          <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 14, alignItems: 'center', padding: '10px 14px', borderBottom: i < facts.length - 1 ? `1px solid ${T.border}` : 'none' }}>
            <div>
              <div style={{ fontSize: 12, color: T.text }}>{f.t}</div>
              <div className="mono" style={{ fontSize: 10, color: T.dim, marginTop: 2 }}>{f.src}</div>
            </div>
            <button className="dlk-btn ghost" style={{ padding: 3 }} onClick={() => update({ facts: facts.filter((_, j) => j !== i) })}>
              <Icon name="x" size={11} color={T.dim} />
            </button>
          </div>
        ))}
        {facts.length === 0 && !addingFact && (
          <div className="mono" style={{ padding: '18px 14px', fontSize: 11, color: T.dim }}>No facts yet — add something you'd like dialekt to always remember.</div>
        )}
      </Card>

      <div style={{ border: `1px solid ${T.red}44`, background: '#1a0c0e' }}>
        <div style={{ padding: '10px 14px', borderBottom: `1px solid ${T.red}33` }}>
          <span className="mono" style={{ fontSize: 10, color: T.red, letterSpacing: '.14em' }}>DANGER ZONE</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '10px 14px', borderBottom: `1px solid ${T.red}33` }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 12, color: T.text }}>Export all data</div>
            <div style={{ fontSize: 11, color: T.dim, marginTop: 2 }}>JSON download · sessions + settings</div>
          </div>
          <button className="dlk-btn" onClick={exportData}>Export</button>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '10px 14px', borderBottom: `1px solid ${T.red}33` }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 12, color: T.text }}>Wipe conversations</div>
            <div style={{ fontSize: 11, color: T.dim, marginTop: 2 }}>removes {sessionStats.sessions} sessions · keeps models + settings</div>
          </div>
          <button className="dlk-btn" style={{ borderColor: T.red + '55', color: T.red }} onClick={wipe}>Wipe</button>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '10px 14px' }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 12, color: T.text }}>Reset dialekt</div>
            <div style={{ fontSize: 11, color: T.dim, marginTop: 2 }}>wipe conversations + reset all settings to defaults · models kept</div>
          </div>
          <button className="dlk-btn" style={{ borderColor: T.red + '55', color: T.red }} onClick={reset}>Reset</button>
        </div>
      </div>
    </BodyShell>
  );
}

// ── Section: Performance ──────────────────────────────────────────────────────

function PerformanceSection() {
  const { settings, update } = useContext(Ctx);
  return (
    <BodyShell crumb="03 / SYSTEM → PERFORMANCE" title="Performance"
      desc="LLM inference settings. Changes apply immediately to active and future sessions.">
      <Card title="LLM parameters" n="A">
        <Row label="Context window" sub="max tokens fed to the model per request">
          <Select value={settings.context_window || '8192'} onChange={v => update({ context_window: v })} options={[
            { v: '4096', l: '4 096' }, { v: '8192', l: '8 192 — default' }, { v: '16384', l: '16 384' }, { v: '32768', l: '32 768' }, { v: '128000', l: '128k' },
          ]} />
        </Row>
        <Row label="Max output tokens" sub="hard cap on generated response length">
          <Select value={settings.max_tokens || '4096'} onChange={v => update({ max_tokens: v })} options={[
            { v: '1024', l: '1 024' }, { v: '2048', l: '2 048' }, { v: '4096', l: '4 096 — default' }, { v: '8192', l: '8 192' },
          ]} />
        </Row>
        <Row label="Temperature">
          <Select value={settings.temperature || '0.7'} onChange={v => update({ temperature: v })} options={[
            { v: '0', l: '0.0 · deterministic' }, { v: '0.3', l: '0.3 · focused' }, { v: '0.7', l: '0.7 · balanced' }, { v: '1', l: '1.0 · creative' },
          ]} />
        </Row>
        <Row label="Streaming output" sub="show tokens as they arrive" last>
          <Toggle value={settings.streaming !== false} onChange={v => update({ streaming: v })} />
        </Row>
      </Card>
      <Card title="Concurrency" n="B">
        <Row label="Max concurrent sessions" sub="parallel OI threads — more sessions = more RAM" last>
          <Select value={settings.concurrent_sessions || '1'} onChange={v => update({ concurrent_sessions: v })} options={[
            { v: '1', l: '1 — default' }, { v: '2', l: '2' }, { v: '4', l: '4' },
          ]} />
        </Row>
      </Card>
      <Card title="System resources" n="C">
        <div style={{ padding: '12px 14px' }}>
          {[
            { k: 'CPU cores',      v: '12 cores · x86_64' },
            { k: 'RAM',            v: '32 GB' },
            { k: 'Storage',        v: '915 GB NVMe' },
            { k: 'GPU',            v: 'NVIDIA (NVENC)' },
            { k: 'Ollama',         v: 'localhost:11434' },
          ].map((r, i) => (
            <div key={i} style={{ display: 'flex', padding: '6px 0', borderBottom: i < 4 ? `1px solid ${T.border}` : 'none' }}>
              <span className="mono" style={{ fontSize: 11, color: T.dim, width: 140 }}>{r.k}</span>
              <span className="mono" style={{ fontSize: 11, color: T.text }}>{r.v}</span>
            </div>
          ))}
        </div>
      </Card>
    </BodyShell>
  );
}

// ── Section: Privacy & telemetry ──────────────────────────────────────────────

function PrivacySection() {
  const { settings, update } = useContext(Ctx);
  return (
    <BodyShell crumb="03 / SYSTEM → PRIVACY" title="Privacy & telemetry"
      desc="dialekt is 100% local. These controls exist to make that auditable.">
      <Card title="Data leaving this machine" n="A">
        <div style={{ padding: '12px 14px', borderBottom: `1px solid ${T.border}` }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', background: '#0c2a1f', border: `1px solid ${T.green}33` }}>
            <Icon name="shield" size={14} color={T.green} />
            <div>
              <div style={{ fontSize: 13, color: T.green, fontWeight: 500 }}>0 bytes sent to the cloud by dialekt</div>
              <div style={{ fontSize: 11, color: T.dim, marginTop: 2 }}>All inference runs on Ollama (localhost:11434). No API keys. No accounts.</div>
            </div>
          </div>
        </div>
        <Row label="Crash reports" sub="send anonymised crash logs to dialekt dev team">
          <Toggle value={!!settings.crash_reports} onChange={v => update({ crash_reports: v })} />
        </Row>
        <Row label="Usage statistics" sub="anonymous feature-usage counts (no content)" last>
          <Toggle value={!!settings.usage_stats} onChange={v => update({ usage_stats: v })} />
        </Row>
      </Card>
      <Card title="Data retention" n="B">
        <Row label="Session history" sub="how long to keep conversation history on disk" last>
          <Select value={settings.session_retention || 'forever'} onChange={v => update({ session_retention: v })} options={[
            { v: '7d', l: '7 days' }, { v: '30d', l: '30 days' }, { v: '90d', l: '90 days' }, { v: 'forever', l: 'Forever — default' },
          ]} />
        </Row>
      </Card>
      <Card title="What is stored locally" n="C">
        <div style={{ padding: '12px 14px' }}>
          {[
            { t: 'Conversation messages', v: 'SQLite · ~/.dialekt/dialekt.db',        stored: true  },
            { t: 'Uploaded files',        v: '/tmp/dialekt_files/ · session-scoped', stored: true  },
            { t: 'Settings',              v: '~/.dialekt/config.json',               stored: true  },
            { t: 'Prompts sent to LLM',   v: 'Ollama, localhost only',               stored: false },
            { t: 'Your IP / identity',    v: 'never collected',                      stored: false },
          ].map((r, i, arr) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 0', borderBottom: i < arr.length - 1 ? `1px solid ${T.border}` : 'none' }}>
              <Icon name={r.stored ? 'file' : 'shield'} size={12} color={r.stored ? T.muted : T.green} />
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 12, color: T.text }}>{r.t}</div>
                <div className="mono" style={{ fontSize: 10, color: T.dim, marginTop: 1 }}>{r.v}</div>
              </div>
              <span className="mono" style={{ fontSize: 10, color: r.stored ? T.amber : T.green }}>{r.stored ? 'on disk' : 'never stored'}</span>
            </div>
          ))}
        </div>
      </Card>
    </BodyShell>
  );
}

// ── Section: License & Account ───────────────────────────────────────────────
//
// Re-entry surface for the license key + 30-day trial + onboarding restart.
// Pilot feedback in 04-2026: users couldn't find where to enter their key
// after the first-launch LicenseScreen was dismissed and had no way to
// re-trigger the onboarding flow. This section is the durable home.

function fmtMaskedKey(key) {
  if (!key) return '—';
  if (key.length <= 8) return '••••' + key.slice(-2);
  return key.slice(0, 4) + '••••••••' + key.slice(-4);
}

function fmtExpiry(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleDateString();
  } catch { return iso; }
}

function fmtTrialDaysLeft(trialStartedAt) {
  if (!trialStartedAt) return null;
  const started = typeof trialStartedAt === 'number' ? trialStartedAt * 1000 : new Date(trialStartedAt).getTime();
  if (!Number.isFinite(started)) return null;
  const elapsedDays = (Date.now() - started) / 86400000;
  return Math.max(0, Math.ceil(30 - elapsedDays));
}

function LicenseSection() {
  const { addToast, showConfirm } = useContext(Ctx);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [key, setKey] = useState('');
  const [reveal, setReveal] = useState(false);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`${API}/license/status`).then(r => r.json());
      setStatus(r);
    } catch (e) {
      addToast('Failed to load license status', 'error');
    } finally {
      setLoading(false);
    }
  }, [addToast]);

  useEffect(() => { refresh(); }, [refresh]);

  const submitKey = async () => {
    const trimmed = key.trim();
    if (!trimmed) return;
    setBusy(true);
    try {
      // Match LicenseScreen.jsx validation flow exactly: cloud-validate
      // first, fall through to local cache if cloud is unreachable.
      let data;
      try {
        const cloudApi = await getCloudApi();
        const r = await fetch(`${cloudApi}/auth/validate-license`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ license_key: trimmed }),
        });
        data = await r.json();
      } catch {
        addToast('Cloud unreachable. Check your internet connection.', 'error');
        return;
      }
      if (!data?.valid) {
        addToast(data?.message || 'License key not found or expired. Contact hello@dias.now', 'error');
        return;
      }
      const tenant = {
        company_name: data.company_name || null,
        plan: data.plan,
        seats_limit: data.seats_limit,
        expires_at: data.expires_at,
      };
      await fetch(`${API}/license/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ license_key: trimmed, tenant, bearer_token: data.bearer_token }),
      });
      fetch(`${API}/sync/pull`, { method: 'POST' }).catch(() => {});
      addToast('License activated', 'ok');
      setKey('');
      setEditing(false);
      await refresh();
    } catch (e) {
      addToast(`Validation failed: ${e}`, 'error');
    } finally {
      setBusy(false);
    }
  };

  const startTrial = async () => {
    setBusy(true);
    try {
      const r = await fetch(`${API}/license/trial`, { method: 'POST' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      addToast('Trial started — 30 days', 'ok');
      await refresh();
    } catch (e) {
      addToast(`Trial start failed: ${e}`, 'error');
    } finally {
      setBusy(false);
    }
  };

  const refreshFromCloud = async () => {
    setBusy(true);
    try {
      const r = await fetch(`${API}/license/refresh`, { method: 'POST' });
      const data = await r.json().catch(() => ({}));
      if (data?.status === 'ok' || data?.valid) {
        addToast('License revalidated', 'ok');
      } else {
        addToast(data?.reason || 'Revalidation failed', 'error');
      }
      await refresh();
    } catch (e) {
      addToast(`Revalidation failed: ${e}`, 'error');
    } finally {
      setBusy(false);
    }
  };

  const restartOnboarding = () => {
    showConfirm({
      title: 'Restart onboarding?',
      body: 'The first-launch flow (license check, mode pick, Ollama install, model download, permissions) will be shown again on next reload. Your data is not touched.',
      confirmLabel: 'Restart',
      onConfirm: async () => {
        try {
          await fetch(`${API}/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ onboarding_completed: false }),
          });
          window.location.reload();
        } catch (e) {
          addToast(`Failed: ${e}`, 'error');
        }
      },
    });
  };

  const trialDaysLeft = status?.trial ? fmtTrialDaysLeft(status?.trial_started || status?.last_validated_at) : null;

  return (
    <BodyShell crumb="03 / SYSTEM → LICENSE" title="License & account"
      desc="Enter or change your dialekt license key, start a trial, or restart the first-launch onboarding flow.">

      {loading ? (
        <div style={{ color: T.dim, fontSize: 13, padding: '24px 0' }}>Loading…</div>
      ) : (
        <>
          {/* Current state ─────────────────────────────────────── */}
          <Card title="Current state" n="01">
            <div style={{ padding: '14px 16px', display: 'grid', gridTemplateColumns: '160px 1fr', gap: '10px 18px', fontSize: 12 }}>
              <span style={{ color: T.dim }}>Status</span>
              <span className="mono" style={{ color: status?.valid ? T.green : T.amber }}>
                {status?.valid ? (status?.trial ? '● TRIAL' : '● ACTIVE') : '○ NO LICENSE'}
              </span>

              <span style={{ color: T.dim }}>License key</span>
              <span className="mono" style={{ color: T.text, display: 'flex', alignItems: 'center', gap: 8 }}>
                {status?.license_key ? (reveal ? status.license_key : fmtMaskedKey(status.license_key)) : '—'}
                {status?.license_key && (
                  <button onClick={() => setReveal(v => !v)} style={{
                    background: 'transparent', border: `1px solid ${T.border}`, color: T.dim,
                    padding: '2px 8px', fontSize: 10, cursor: 'pointer',
                  }}>{reveal ? 'HIDE' : 'REVEAL'}</button>
                )}
              </span>

              <span style={{ color: T.dim }}>Plan</span>
              <span className="mono" style={{ color: T.text }}>{status?.tenant?.plan || (status?.trial ? 'trial' : '—')}</span>

              <span style={{ color: T.dim }}>Company</span>
              <span style={{ color: T.text }}>{status?.tenant?.company_name || '—'}</span>

              <span style={{ color: T.dim }}>Seats</span>
              <span className="mono" style={{ color: T.text }}>{status?.tenant?.seats_limit || '—'}</span>

              <span style={{ color: T.dim }}>Expires</span>
              <span className="mono" style={{ color: T.text }}>
                {status?.trial ? `trial · ${trialDaysLeft ?? '?'} day${trialDaysLeft === 1 ? '' : 's'} left` : fmtExpiry(status?.tenant?.expires_at)}
              </span>

              <span style={{ color: T.dim }}>Last revalidated</span>
              <span className="mono" style={{ color: T.dim, fontSize: 11 }}>
                {status?.last_validated_at ? new Date(status.last_validated_at * 1000).toLocaleString() : 'never'}
              </span>

              {status?.revocation_reason && (
                <>
                  <span style={{ color: T.red }}>Revocation</span>
                  <span style={{ color: T.red, fontSize: 11 }}>{status.revocation_reason}</span>
                </>
              )}
            </div>
            <div style={{ display: 'flex', gap: 8, padding: '0 16px 14px' }}>
              {status?.license_key && (
                <button onClick={refreshFromCloud} disabled={busy} style={{
                  background: 'transparent', border: `1px solid ${T.border}`, color: T.text,
                  padding: '6px 14px', fontSize: 11, cursor: busy ? 'default' : 'pointer',
                }}>{busy ? '…' : 'REVALIDATE'}</button>
              )}
            </div>
          </Card>

          {/* Enter / change key ───────────────────────────────── */}
          <Card title={status?.license_key ? 'Replace license key' : 'Enter license key'} n="02">
            <div style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 12 }}>
              {status?.license_key && !editing ? (
                <div style={{ display: 'flex', gap: 10, alignItems: 'center', fontSize: 12, color: T.muted }}>
                  <span>A key is currently set.</span>
                  <button onClick={() => setEditing(true)} style={{
                    background: 'transparent', border: `1px solid ${T.border}`, color: T.text,
                    padding: '5px 14px', fontSize: 11, cursor: 'pointer',
                  }}>REPLACE KEY</button>
                </div>
              ) : (
                <>
                  <input
                    type={reveal ? 'text' : 'password'}
                    value={key}
                    onChange={e => setKey(e.target.value)}
                    placeholder="lic_…"
                    style={{
                      background: T.bg2, border: `1px solid ${T.border}`, color: T.text,
                      padding: '8px 12px', fontSize: 13, fontFamily: 'var(--code-font, monospace)',
                      outline: 'none',
                    }}
                  />
                  <div style={{ fontSize: 11, color: T.dim }}>
                    Validated against <span className="mono">api.dias.now</span>. License + bearer token are stored in your OS keychain.
                  </div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button onClick={submitKey} disabled={busy || !key.trim()} style={{
                      background: T.cyan, color: '#000', border: 'none', padding: '7px 18px',
                      fontSize: 12, fontWeight: 600, cursor: busy || !key.trim() ? 'default' : 'pointer', letterSpacing: '.04em',
                    }}>{busy ? 'CHECKING…' : 'ACTIVATE'}</button>
                    {editing && (
                      <button onClick={() => { setEditing(false); setKey(''); }} disabled={busy} style={{
                        background: 'transparent', border: `1px solid ${T.border}`, color: T.text,
                        padding: '7px 18px', fontSize: 12, cursor: 'pointer',
                      }}>CANCEL</button>
                    )}
                  </div>
                </>
              )}
              {!status?.license_key && !status?.trial_valid && (
                <div style={{ paddingTop: 12, borderTop: `1px solid ${T.border}`, marginTop: 4, fontSize: 12, color: T.muted, display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span>No key yet?</span>
                  <button onClick={startTrial} disabled={busy} style={{
                    background: 'transparent', border: `1px solid ${T.cyan}66`, color: T.cyan,
                    padding: '5px 14px', fontSize: 11, cursor: busy ? 'default' : 'pointer', letterSpacing: '.04em',
                  }}>START 30-DAY TRIAL</button>
                </div>
              )}
            </div>
          </Card>

          {/* Restart onboarding ────────────────────────────────── */}
          <Card title="Onboarding" n="03">
            <div style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 10, fontSize: 12 }}>
              <div style={{ color: T.muted }}>
                Replay the first-launch flow: license check → mode pick → Ollama install → model download → permissions.
              </div>
              <div style={{ color: T.dim, fontSize: 11 }}>
                Your data, agents, and connections are not affected.
              </div>
              <div>
                <button onClick={restartOnboarding} style={{
                  background: 'transparent', border: `1px solid ${T.border}`, color: T.text,
                  padding: '7px 18px', fontSize: 12, cursor: 'pointer', letterSpacing: '.04em',
                }}>RESTART ONBOARDING</button>
              </div>
            </div>
          </Card>

          <div style={{ fontSize: 11, color: T.dim, marginTop: 4 }}>
            Need a license key? Email <span className="mono" style={{ color: T.muted }}>hello@dias.now</span> with your company name and seat count.
          </div>
        </>
      )}
    </BodyShell>
  );
}

// ── Section: About ────────────────────────────────────────────────────────────

function AboutSection() {
  const [about, setAbout] = useState(null);
  useEffect(() => {
    fetch(`${API}/about`).then(r => r.json()).then(setAbout).catch(() => {});
  }, []);
  const rows = [
    { k: 'Version',     v: about?.version ? `v${about.version}` : 'v0.8.2' },
    { k: 'Frontend',    v: 'Vite 8 + React 19' },
    { k: 'Backend',     v: 'FastAPI + Open Interpreter 0.4.3' },
    { k: 'LLM runtime', v: 'Ollama (localhost:11434)' },
    { k: 'Database',    v: about?.db ? about.db.replace(about?.home || '', '~') : 'SQLite · ~/.dialekt/dialekt.db' },
    { k: 'Config',      v: about?.config ? about.config.replace(about?.home || '', '~') : '~/.dialekt/config.json' },
    { k: 'Platform',    v: about?.platform || 'detecting…' },
    { k: 'User',        v: about?.username || '…' },
  ];
  return (
    <BodyShell crumb="03 / SYSTEM → ABOUT" title="About dialekt"
      desc="Local AI agent. All compute stays on this machine.">
      <Card title="Build info" n="A">
        {rows.map((r, i, arr) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', padding: '10px 14px', borderBottom: i < arr.length - 1 ? `1px solid ${T.border}` : 'none' }}>
            <span className="mono" style={{ fontSize: 11, color: T.dim, width: 150 }}>{r.k}</span>
            <span className="mono" style={{ fontSize: 11, color: T.text }}>{r.v}</span>
          </div>
        ))}
      </Card>
      <Card title="Privacy guarantee" n="B">
        <div style={{ padding: '16px 14px', display: 'flex', gap: 12 }}>
          <Icon name="shield" size={16} color={T.green} />
          <div style={{ fontSize: 13, color: T.muted, lineHeight: 1.7 }}>
            No telemetry. No cloud account. No token counting by a third party.{' '}
            <span style={{ color: T.cyan }}>0 bytes</span> sent outside this machine by dialekt itself.
            Your conversations never leave your hardware.
          </div>
        </div>
      </Card>
      <Card title="Licenses" n="C">
        <div style={{ padding: '12px 14px' }}>
          {[
            ['dialekt',          'Proprietary · local use'],
            ['Open Interpreter', 'MIT License'],
            ['FastAPI',          'MIT License'],
            ['React',            'MIT License'],
            ['Ollama',           'MIT License'],
            ['aiosqlite',        'MIT License'],
          ].map(([pkg, lic], i, arr) => (
            <div key={i} style={{ display: 'flex', padding: '6px 0', borderBottom: i < arr.length - 1 ? `1px solid ${T.border}` : 'none' }}>
              <span className="mono" style={{ fontSize: 11, color: T.text, width: 180 }}>{pkg}</span>
              <span className="mono" style={{ fontSize: 11, color: T.dim }}>{lic}</span>
            </div>
          ))}
        </div>
      </Card>
    </BodyShell>
  );
}

// ── Section: Connections ──────────────────────────────────────────────────────

// Driver metadata for the connection picker. Each entry maps to the
// backend router for that database type. Default port is applied when
// the user switches drivers in the Add form.
const DRIVERS = {
  postgres:   { label: 'PostgreSQL', prefix: '/connections',        defaultPort: '5432' },
  mysql:      { label: 'MySQL',      prefix: '/mysql-connections',  defaultPort: '3306' },
  clickhouse: { label: 'ClickHouse', prefix: '/ch-connections',     defaultPort: '8123' },
};

function ConnectionsSection() {
  const { addToast, showConfirm } = useContext(Ctx);
  const [conns, setConns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [testStatus, setTestStatus] = useState({});
  const [reindexStatus, setReindexStatus] = useState({});
  const [modelStatus, setModelStatus] = useState(null);
  const [pulling, setPulling] = useState(false);
  const [nomicPendingId, setNomicPendingId] = useState(null);
  const EMPTY_FORM = { driver: 'postgres', name: '', host: 'localhost', port: '5432', database: '', username: '', password: '', row_limit: '500', ssl: 'prefer' };
  const [form, setForm] = useState(EMPTY_FORM);

  // Route backend calls through the per-driver prefix. Each connection
  // row we render carries `_driver` (added in load()) so tests / reindex /
  // delete hit the correct router.
  const prefixFor = (c) => (DRIVERS[c?._driver || 'postgres']?.prefix) || '/connections';

  useEffect(() => {
    fetch(`${API}/schema-rag/model-status`)
      .then(r => r.json())
      .then(d => setModelStatus(d))
      .catch(() => {});
  }, []);

  const pullModel = async () => {
    setPulling(true);
    addToast(`Pulling ${modelStatus?.model ?? 'embedding model'}… this may take a few minutes`, 'ok');
    try {
      const r = await fetch(`${API}/schema-rag/pull-model`, { method: 'POST' });
      const d = await r.json();
      if (d.ok) {
        setModelStatus(m => ({ ...m, available: true, pull_command: null }));
        addToast('Embedding model ready — you can now reindex connections', 'ok');
      } else {
        addToast('Pull failed — check Ollama is running', 'error');
      }
    } catch { addToast('Pull failed', 'error'); }
    setPulling(false);
  };

  const load = async () => {
    setLoading(true);
    const all = [];
    for (const [driver, meta] of Object.entries(DRIVERS)) {
      try {
        const r = await fetch(`${API}${meta.prefix}`);
        if (r.ok) {
          const rows = await r.json();
          if (Array.isArray(rows)) rows.forEach(c => all.push({ ...c, _driver: driver }));
        }
      } catch {
        // individual driver offline — skip, don't break the whole page
      }
    }
    setConns(all);
    setLoading(false);
  };
  useEffect(() => { load(); }, []);

  const fset = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const create = async () => {
    const driverMeta = DRIVERS[form.driver] || DRIVERS.postgres;
    const body = {
      name: form.name.trim(), host: form.host.trim(),
      port: parseInt(form.port) || parseInt(driverMeta.defaultPort), database: form.database.trim(),
      username: form.username.trim(), password: form.password,
      row_limit: parseInt(form.row_limit) || 500,
      // SSL is a PostgreSQL-specific concept (sslmode). MySQL/ClickHouse
      // backends currently ignore it — sending anyway is harmless.
      ssl: form.ssl,
    };
    // ClickHouse's POST handler doesn't require password; the other two do.
    const required = ['name', 'database', 'username'];
    for (const f of required) {
      if (!body[f]) { addToast(`${f} is required`, 'error'); return; }
    }
    try {
      const r = await fetch(`${API}${driverMeta.prefix}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      if (!r.ok) {
        const detail = await r.text().catch(() => '');
        addToast(`Failed to save connection${detail ? `: ${detail.slice(0, 140)}` : ''}`, 'error');
        return;
      }
      addToast(`${driverMeta.label} connection saved`, 'ok');
      setAdding(false); setForm(EMPTY_FORM); load();
    } catch { addToast('Network error', 'error'); }
  };

  const reindexConn = async (conn) => {
    const id = conn.id;
    // Goal 1.5: intercept when embedding model not available
    if (modelStatus && !modelStatus.available) {
      setNomicPendingId(id);
      return;
    }
    setReindexStatus(s => ({ ...s, [id]: 'indexing' }));
    try {
      const r = await fetch(`${API}${prefixFor(conn)}/${id}/reindex`, { method: 'POST' });
      const data = await r.json();
      setReindexStatus(s => ({ ...s, [id]: 'done' }));
      const msg = data.error
        ? `Indexed ${data.indexed ?? 0}, skipped ${data.skipped ?? 0}: ${data.error}`
        : `Indexed ${data.indexed ?? 0} tables${data.skipped ? ` (${data.skipped} skipped — Ollama unavailable)` : ''}`;
      addToast(msg, data.error ? 'warn' : 'ok');
    } catch { setReindexStatus(s => ({ ...s, [id]: 'error' })); addToast('Reindex failed', 'error'); }
  };

  const handleNomicDownload = async () => {
    const pendingId = nomicPendingId;
    setNomicPendingId(null);
    setPulling(true);
    addToast('Pulling nomic-embed-text:v1.5 (274 MB)…', 'ok');
    try {
      const r = await fetch(`${API}/schema-rag/pull-model`, { method: 'POST' });
      const d = await r.json();
      if (d.ok) {
        setModelStatus(m => ({ ...m, available: true }));
        addToast('Embedding model ready', 'ok');
        if (pendingId) {
          const c = conns.find(x => x.id === pendingId);
          if (c) reindexConn(c);
        }
      } else {
        addToast('Pull failed — check Ollama is running', 'error');
      }
    } catch { addToast('Pull failed', 'error'); }
    setPulling(false);
  };

  const testConn = async (conn) => {
    const id = conn.id;
    setTestStatus(s => ({ ...s, [id]: 'testing' }));
    try {
      const r = await fetch(`${API}${prefixFor(conn)}/${id}/test`, { method: 'POST' });
      const data = await r.json();
      const ok = r.ok && data.ok !== false;
      setTestStatus(s => ({ ...s, [id]: ok ? 'ok' : 'error' }));
      addToast(ok ? 'Connection successful' : `Connection failed${data.error ? ': ' + data.error : ''}`, ok ? 'ok' : 'error');
    } catch { setTestStatus(s => ({ ...s, [id]: 'error' })); addToast('Test failed', 'error'); }
  };

  const remove = (conn) => showConfirm({
    title: `Remove "${conn.name}"?`,
    body: 'The connection and its stored credentials will be deleted. This cannot be undone.',
    action: 'Remove connection', danger: true,
    onConfirm: async () => {
      try {
        await fetch(`${API}${prefixFor(conn)}/${conn.id}`, { method: 'DELETE' });
        setConns(c => c.filter(x => x.id !== conn.id));
        addToast('Connection removed', 'ok');
      } catch { addToast('Delete failed', 'error'); }
    },
  });

  const FInput = ({ label, k, type = 'text', placeholder, style: s }) => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, ...s }}>
      <label style={{ fontSize: 11, color: T.dim }}>{label}</label>
      <input type={type} value={form[k]} onChange={e => fset(k, e.target.value)}
        placeholder={placeholder} style={{
          background: T.bg2, border: `1px solid ${T.border}`, color: T.text,
          padding: '7px 10px', fontSize: 12, outline: 'none', width: '100%', boxSizing: 'border-box',
        }} />
    </div>
  );

  const ConnRow = ({ c, i }) => {
    const st = testStatus[c.id];
    const dot = st === 'ok' ? T.green : st === 'error' ? T.red : st === 'testing' ? T.amber : T.dim;
    const label = st === 'ok' ? 'connected' : st === 'error' ? 'failed' : st === 'testing' ? '…' : 'untested';
    const driverLabel = DRIVERS[c._driver]?.label || c._driver || 'postgres';
    return (
      <Card key={c.id} title={c.name} n={String(i + 1).padStart(2, '0')} right={
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className="mono" style={{
            fontSize: 9, color: T.cyan, border: `1px solid ${T.cyan}55`,
            padding: '2px 6px', letterSpacing: '.08em', textTransform: 'uppercase',
          }}>{driverLabel}</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <div style={{ width: 7, height: 7, borderRadius: '50%', background: dot, flexShrink: 0 }} />
            <span className="mono" style={{ fontSize: 10, color: dot }}>{label}</span>
          </div>
          <button onClick={() => testConn(c)} style={{
            background: T.bg2, border: `1px solid ${T.border}`, color: T.muted,
            padding: '4px 10px', fontSize: 11, cursor: 'pointer',
          }}>TEST</button>
          <button onClick={() => reindexConn(c)} disabled={reindexStatus[c.id] === 'indexing'} style={{
            background: T.bg2, border: `1px solid ${T.border}`,
            color: reindexStatus[c.id] === 'indexing' ? T.dim : T.muted,
            padding: '4px 10px', fontSize: 11, cursor: reindexStatus[c.id] === 'indexing' ? 'default' : 'pointer',
          }}>{reindexStatus[c.id] === 'indexing' ? '…' : 'REINDEX'}</button>
          <button onClick={() => remove(c)} style={{
            background: 'transparent', border: `1px solid ${T.border}`, color: T.red,
            padding: '4px 10px', fontSize: 11, cursor: 'pointer',
          }}>REMOVE</button>
        </div>
      }>
        <div style={{ padding: '10px 14px', display: 'flex', flexWrap: 'wrap', gap: 20 }}>
          {[['host', c.host], ['port', c.port], ['database', c.database], ['user', c.username], ['rows', c.row_limit], ['ssl', c.ssl || 'prefer']].map(([k, v]) => (
            <div key={k} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <span className="mono" style={{ fontSize: 9, color: T.dim, letterSpacing: '.1em' }}>{k.toUpperCase()}</span>
              <span className="mono" style={{ fontSize: 12, color: T.text }}>{v}</span>
            </div>
          ))}
        </div>
      </Card>
    );
  };

  return (
    <BodyShell crumb="02 / CAPABILITIES → CONNECTIONS" title="Database Connections"
      desc="Connect to PostgreSQL, MySQL, and ClickHouse databases for SQL analytics. Credentials are stored in your OS keychain — never in config files or logs.">

      {modelStatus && !modelStatus.available && (
        <div style={{ border: `1px solid ${T.amber}44`, background: `${T.amber}0a`, padding: '10px 14px', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 7, height: 7, borderRadius: '50%', background: T.amber, flexShrink: 0 }} />
          <div style={{ flex: 1, fontSize: 12, color: T.muted }}>
            Schema RAG: <span className="mono" style={{ color: T.amber }}>{modelStatus.model}</span> not pulled.
            REINDEX will skip until the model is available.
          </div>
          <button onClick={pullModel} disabled={pulling} style={{
            background: T.amber, color: '#000', border: 'none', padding: '5px 12px',
            fontSize: 11, fontWeight: 600, cursor: pulling ? 'default' : 'pointer', letterSpacing: '.04em', flexShrink: 0,
          }}>{pulling ? 'PULLING…' : 'PULL MODEL'}</button>
        </div>
      )}
      {modelStatus?.available && (
        <div style={{ border: `1px solid ${T.green}33`, background: `${T.green}08`, padding: '8px 14px', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ width: 7, height: 7, borderRadius: '50%', background: T.green, flexShrink: 0 }} />
          <span className="mono" style={{ fontSize: 11, color: T.green }}>{modelStatus.model} ready</span>
        </div>
      )}

      {loading ? (
        <div style={{ color: T.dim, fontSize: 13, padding: '24px 0' }}>Loading…</div>
      ) : conns.length === 0 && !adding ? (
        <Card>
          <div style={{ padding: '40px 0', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
            <Icon name="folder" size={28} color={T.dim} />
            <div style={{ color: T.dim, fontSize: 13 }}>No connections yet. Add one to start querying databases.</div>
            <button onClick={() => setAdding(true)} style={{
              background: T.cyan, color: '#000', border: 'none', padding: '8px 18px',
              fontSize: 12, fontWeight: 600, cursor: 'pointer', letterSpacing: '.04em',
            }}>+ ADD CONNECTION</button>
          </div>
        </Card>
      ) : (
        <>
          {conns.map((c, i) => <ConnRow key={c.id} c={c} i={i} />)}
          {!adding && (
            <button onClick={() => setAdding(true)} style={{
              background: 'transparent', border: `1px dashed ${T.border}`, color: T.muted,
              width: '100%', padding: '11px', fontSize: 12, cursor: 'pointer', marginBottom: 16,
              letterSpacing: '.04em', boxSizing: 'border-box',
            }}>+ ADD CONNECTION</button>
          )}
        </>
      )}

      {adding && (
        <Card title="New connection" n="NEW">
          <div style={{ padding: '16px 14px', display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <label style={{ fontSize: 11, color: T.dim }}>Driver</label>
              <select
                value={form.driver}
                onChange={e => {
                  const newDriver = e.target.value;
                  const meta = DRIVERS[newDriver];
                  // Only overwrite port if the user hasn't customised it — compare
                  // against the previous default; if it still matches, snap to the
                  // new default. Keeps accidental driver toggles cheap.
                  const prevDefault = DRIVERS[form.driver]?.defaultPort || '';
                  const nextPort = (form.port === prevDefault || !form.port) ? meta.defaultPort : form.port;
                  setForm(f => ({ ...f, driver: newDriver, port: nextPort }));
                }}
                style={{
                  background: T.bg2, border: `1px solid ${T.border}`, color: T.text,
                  padding: '7px 10px', fontSize: 12, outline: 'none', width: '100%',
                }}
              >
                {Object.entries(DRIVERS).map(([k, meta]) => (
                  <option key={k} value={k}>{meta.label}</option>
                ))}
              </select>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <FInput label="Name *" k="name" placeholder="My Analytics DB" style={{ gridColumn: '1 / -1' }} />
              <FInput label="Host *" k="host" placeholder="localhost" />
              <FInput label="Port" k="port" placeholder={DRIVERS[form.driver]?.defaultPort} />
              <FInput label="Database *" k="database" placeholder={form.driver === 'clickhouse' ? 'default' : 'analytics'} />
              <FInput label="Username *" k="username" placeholder={form.driver === 'mysql' ? 'root' : form.driver === 'clickhouse' ? 'default' : 'readonly'} />
              <FInput label="Password" k="password" type="password" placeholder="••••••••" style={{ gridColumn: '1 / -1' }} />
              <FInput label="Row limit" k="row_limit" placeholder="500" />
              {form.driver === 'postgres' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <label style={{ fontSize: 11, color: T.dim }}>SSL</label>
                  <select value={form.ssl} onChange={e => fset('ssl', e.target.value)} style={{
                    background: T.bg2, border: `1px solid ${T.border}`, color: T.text,
                    padding: '7px 10px', fontSize: 12, outline: 'none', width: '100%',
                  }}>
                    {['prefer', 'require', 'disable', 'verify-full'].map(m => <option key={m} value={m}>{m}</option>)}
                  </select>
                </div>
              )}
            </div>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', paddingTop: 4 }}>
              <button onClick={() => { setAdding(false); setForm(EMPTY_FORM); }} style={{
                background: 'transparent', border: `1px solid ${T.border}`, color: T.muted,
                padding: '7px 16px', fontSize: 12, cursor: 'pointer',
              }}>CANCEL</button>
              <button onClick={create} style={{
                background: T.cyan, color: '#000', border: 'none',
                padding: '7px 20px', fontSize: 12, fontWeight: 600, cursor: 'pointer', letterSpacing: '.04em',
              }}>SAVE</button>
            </div>
          </div>
        </Card>
      )}

      <Card title="Security" n="i">
        <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 8 }}>
          {[
            'Passwords are stored in your OS keychain (Keyring / Secret Service). They never appear in config files or logs.',
            'Only SELECT queries are allowed. DDL and DML statements are rejected before any database connection is made.',
            'Each query runs inside a read-only transaction. The row limit protects against accidental full-table scans.',
          ].map((note, i) => (
            <div key={i} style={{ display: 'flex', gap: 10, fontSize: 12, color: T.muted, lineHeight: 1.6 }}>
              <span style={{ color: T.cyan, flexShrink: 0 }}>—</span>
              <span>{note}</span>
            </div>
          ))}
        </div>
      </Card>

      {nomicPendingId && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.72)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 999,
        }}>
          <div style={{
            background: T.bg1, border: `1px solid ${T.border}`,
            padding: '28px 32px', maxWidth: 440, width: '100%',
          }}>
            <div className="mono" style={{ fontSize: 10, color: T.cyan, letterSpacing: '.12em', marginBottom: 10 }}>SCHEMA RAG · MODEL REQUIRED</div>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 10 }}>nomic-embed-text not found</div>
            <div style={{ fontSize: 13, color: T.muted, lineHeight: 1.6, marginBottom: 24 }}>
              Schema indexing requires <span className="mono" style={{ color: T.text }}>nomic-embed-text:v1.5</span> (274 MB).
              This model runs locally and enables semantic search over your database schema. Download now?
            </div>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button onClick={() => setNomicPendingId(null)} style={{
                background: 'transparent', border: `1px solid ${T.border}`, color: T.muted,
                padding: '7px 18px', fontSize: 12, cursor: 'pointer',
              }}>Cancel</button>
              <button onClick={handleNomicDownload} disabled={pulling} style={{
                background: T.cyan, color: '#000', border: 'none',
                padding: '7px 22px', fontSize: 12, fontWeight: 600,
                cursor: pulling ? 'default' : 'pointer', letterSpacing: '.04em',
              }}>{pulling ? 'Downloading…' : 'Download & index'}</button>
            </div>
          </div>
        </div>
      )}
    </BodyShell>
  );
}

// ── Section: Agents ──────────────────────────────────────────────────────────

// Map agent manifest connection type aliases → backend endpoint.
const AGENT_CONN_ENDPOINT = {
  postgres: '/connections',
  postgresql: '/connections',
  pg: '/connections',
  mysql: '/mysql-connections',
  clickhouse: '/ch-connections',
  ch: '/ch-connections',
};

function normaliseType(t) {
  const s = String(t || '').toLowerCase();
  if (s === 'postgresql' || s === 'pg') return 'postgres';
  if (s === 'ch') return 'clickhouse';
  return s;
}

// Extract required DB types from a manifest YAML. Manifest spec allows
//   connections:
//     required:
//       - type: postgres
// We parse defensively since not every agent declares the field.
function parseRequiredConnTypes(manifestYaml) {
  if (!manifestYaml) return [];
  const types = new Set();
  // Very light YAML parse — look for 'type: <value>' lines within the
  // connections block. Full YAML parse would need a library.
  const connIdx = manifestYaml.indexOf('connections:');
  if (connIdx < 0) return [];
  const tail = manifestYaml.slice(connIdx);
  const nextTopLevel = tail.search(/\n[a-z_][\w]*:/);
  const block = nextTopLevel > 0 ? tail.slice(0, nextTopLevel) : tail;
  const re = /^\s*-?\s*type:\s*["']?([a-zA-Z_][\w-]*)["']?\s*$/gm;
  let m;
  while ((m = re.exec(block)) !== null) {
    const t = normaliseType(m[1]);
    if (t) types.add(t);
  }
  return Array.from(types);
}

function AgentsSection() {
  const { addToast, focusAgentId } = useContext(Ctx);
  const [agents, setAgents] = useState([]);
  const [connsByType, setConnsByType] = useState({});
  const [bindings, setBindings] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState({});
  const rowRefs = useRef({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const agentsResp = await fetch(`${API}/agents`);
      const agentsList = agentsResp.ok ? await agentsResp.json() : [];
      setAgents(agentsList);

      // Load connections per type, deduping requests.
      const endpoints = [...new Set(
        agentsList
          .flatMap(a => parseRequiredConnTypes(a.manifest_yaml))
          .map(t => AGENT_CONN_ENDPOINT[t])
          .filter(Boolean)
      )];
      const connsMap = {};
      await Promise.all(endpoints.map(async (ep) => {
        try {
          const r = await fetch(`${API}${ep}`);
          if (r.ok) connsMap[ep] = await r.json();
        } catch {}
      }));
      setConnsByType(connsMap);

      // Current bindings (one request per agent — small N).
      const bindMap = {};
      await Promise.all(agentsList.map(async (a) => {
        try {
          const r = await fetch(`${API}/agents/${a.id}/binding`);
          if (r.ok) {
            const b = await r.json();
            if (b.connection_id) {
              bindMap[a.id] = { connection_id: b.connection_id, connection_type: b.connection_type };
            }
          }
        } catch {}
      }));
      setBindings(bindMap);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Scroll to focused agent (from Part 3 chat nudge).
  useEffect(() => {
    if (!focusAgentId || loading) return;
    const el = rowRefs.current[focusAgentId];
    if (el && el.scrollIntoView) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [focusAgentId, loading]);

  const saveBinding = async (agent, connectionId, connectionType) => {
    setSaving(s => ({ ...s, [agent.id]: true }));
    try {
      if (!connectionId) {
        const r = await fetch(`${API}/agents/${agent.id}/binding`, { method: 'DELETE' });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        setBindings(b => { const n = { ...b }; delete n[agent.id]; return n; });
        addToast(`${agent.name}: connection cleared`, 'ok');
      } else {
        const r = await fetch(`${API}/agents/${agent.id}/binding`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ connection_id: connectionId, connection_type: connectionType }),
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        setBindings(b => ({ ...b, [agent.id]: { connection_id: connectionId, connection_type: connectionType } }));
        addToast(`${agent.name}: connection saved`, 'ok');
      }
    } catch (e) {
      addToast(`Failed to save binding: ${e.message}`, 'error');
    } finally {
      setSaving(s => ({ ...s, [agent.id]: false }));
    }
  };

  const renderAgent = (agent) => {
    const reqTypes = parseRequiredConnTypes(agent.manifest_yaml);
    const current = bindings[agent.id];
    const focused = focusAgentId === agent.id;

    if (reqTypes.length === 0) {
      // Agents with no DB requirement — show a muted row so users see
      // them exist here too, but no connection picker.
      return (
        <div
          key={agent.id}
          ref={(el) => { if (el) rowRefs.current[agent.id] = el; }}
          style={{
            display: 'flex', alignItems: 'center', gap: 14, padding: '12px 14px',
            borderBottom: `1px solid ${T.border}`,
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, color: T.text, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {agent.name}
            </div>
            <div className="mono" style={{ fontSize: 10, color: T.dim, marginTop: 2 }}>
              no database required
            </div>
          </div>
          <span className="mono" style={{ fontSize: 10, color: T.dim }}>—</span>
        </div>
      );
    }

    // Build the list of candidate connections across required types.
    const candidates = [];
    reqTypes.forEach((t) => {
      const ep = AGENT_CONN_ENDPOINT[t];
      if (!ep) return;
      (connsByType[ep] || []).forEach((c) => {
        candidates.push({ id: c.id, name: c.name || c.id, type: t });
      });
    });

    const selectedValue = current?.connection_id || '';
    const selectedType = current?.connection_type || reqTypes[0];

    return (
      <div
        key={agent.id}
        ref={(el) => { if (el) rowRefs.current[agent.id] = el; }}
        style={{
          display: 'flex', alignItems: 'center', gap: 14, padding: '12px 14px',
          borderBottom: `1px solid ${T.border}`,
          background: focused ? `${T.cyan}0a` : 'transparent',
          transition: 'background .2s',
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, color: T.text, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {agent.name}
          </div>
          <div className="mono" style={{ fontSize: 10, color: T.dim, marginTop: 2, display: 'flex', gap: 8 }}>
            <span>requires {reqTypes.join(', ')}</span>
            {current ? (
              <span style={{ color: T.green }}>● connected</span>
            ) : (
              <span style={{ color: T.amber }}>● not connected</span>
            )}
          </div>
        </div>
        {candidates.length === 0 ? (
          <div className="mono" style={{ fontSize: 11, color: T.amber }}>
            no matching connection — add one in Connections
          </div>
        ) : (
          <select
            value={selectedValue}
            disabled={!!saving[agent.id]}
            onChange={(e) => {
              const cid = e.target.value;
              if (!cid) {
                saveBinding(agent, null, null);
                return;
              }
              const cand = candidates.find(c => c.id === cid);
              saveBinding(agent, cid, cand?.type || selectedType);
            }}
            style={{
              minWidth: 220,
              background: T.bg0, border: `1px solid ${T.border}`, color: T.text,
              fontFamily: T.mono, fontSize: 12, padding: '6px 10px',
              cursor: 'pointer',
            }}
          >
            <option value="">— no connection —</option>
            {candidates.map(c => (
              <option key={c.id} value={c.id}>{c.name} ({c.type})</option>
            ))}
          </select>
        )}
      </div>
    );
  };

  return (
    <BodyShell crumb="02 / CAPABILITIES → AGENTS" title="Agent Connections"
      desc="Bind each agent to a default database connection. SQL Analyst and any other agent that declares a required connection type needs this set before it can run queries.">
      {loading ? (
        <div style={{ color: T.dim, fontSize: 13, padding: '24px 0' }}>Loading…</div>
      ) : agents.length === 0 ? (
        <Card>
          <div style={{ padding: '40px 0', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
            <Icon name="diamond" size={28} color={T.dim} />
            <div style={{ color: T.dim, fontSize: 13 }}>No agents yet. Create one from the chat sidebar (WIZARD).</div>
          </div>
        </Card>
      ) : (
        <Card title="All agents" n="A">
          {agents.map(renderAgent)}
        </Card>
      )}
    </BodyShell>
  );
}

// ── Section: Scheduled (v0.27 §3.2) ──────────────────────────────────────────
//
// Lists every agent whose manifest declares trigger.type=scheduled and
// renders a card per agent: schedule line, next/last run, Run-now,
// History (collapsible), Disconnect-style "Skip-on-startup" toggle is
// deliberately absent — that's per-manifest, not per-session.

const CRON_FIELD_LABELS = ['minute', 'hour', 'day', 'month', 'weekday'];
const WEEKDAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function describeCron(expr) {
  // Best-effort humanisation. Catches the common cases the IBA agents
  // use; falls back to the raw expression when shape doesn't match.
  if (!expr || typeof expr !== 'string') return expr || '';
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return expr;
  const [m, h, dom, mon, dow] = parts;
  const numeric = (s) => /^\d+$/.test(s);
  const time = numeric(m) && numeric(h)
    ? `${h.padStart(2, '0')}:${m.padStart(2, '0')}`
    : null;
  if (!time) return expr;
  if (dom === '*' && mon === '*' && dow === '*') return `every day at ${time}`;
  if (dom === '*' && mon === '*' && /^[A-Z]+$/i.test(dow)) {
    return `${dow.slice(0, 3)} at ${time}`;
  }
  if (dom === '*' && mon === '*' && numeric(dow)) {
    const idx = parseInt(dow, 10) % 7;
    return `${WEEKDAY_NAMES[idx]} at ${time}`;
  }
  if (numeric(dom) && numeric(mon)) {
    return `${MONTH_NAMES[parseInt(mon, 10) - 1] || mon} ${dom} at ${time}`;
  }
  return expr;
}

function parseScheduledManifest(yamlStr) {
  // Tiny manual parser — we only need trigger.{type,schedule,timezone,
  // missed_run_policy} and output.destination.type. Importing js-yaml
  // for this is overkill (and SettingsScreen is already a chunky
  // bundle). Caller falls back to "this isn't a scheduled agent" when
  // anything looks off.
  if (!yamlStr || typeof yamlStr !== 'string') return null;
  const lines = yamlStr.split('\n');
  const out = { type: null, schedule: null, timezone: null, policy: null, destination: null };
  let inTrigger = false, inOutput = false, inDest = false, indentTrigger = -1, indentOutput = -1;
  for (const raw of lines) {
    const line = raw.replace(/\r$/, '');
    if (/^[a-z_]+:\s*$/i.test(line) || /^[a-z_]+:/i.test(line)) {
      if (line.startsWith('trigger:')) { inTrigger = true; inOutput = false; inDest = false; indentTrigger = 0; continue; }
      if (line.startsWith('output:')) { inOutput = true; inTrigger = false; inDest = false; indentOutput = 0; continue; }
      if (!line.startsWith(' ') && !line.startsWith('\t')) { inTrigger = false; inOutput = false; inDest = false; }
    }
    const m = line.match(/^(\s+)([a-z_]+):\s*['"]?([^'"#]*?)['"]?\s*(#.*)?$/i);
    if (!m) continue;
    const [, indent, key, value] = m;
    const ind = indent.length;
    if (inTrigger && ind === 2) {
      if (key === 'type') out.type = value;
      else if (key === 'schedule' || key === 'cron') out.schedule = value;
      else if (key === 'timezone') out.timezone = value;
      else if (key === 'missed_run_policy') out.policy = value;
    }
    if (inOutput) {
      if (ind === 2 && key === 'destination') { inDest = true; continue; }
      if (inDest && ind === 4 && key === 'type') { out.destination = value; inDest = false; }
    }
  }
  return out.type === 'scheduled' ? out : null;
}

function formatRelative(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    const delta = (d - Date.now()) / 1000;
    const abs = Math.abs(delta);
    if (abs < 60) return delta >= 0 ? 'in <1 min' : '<1 min ago';
    if (abs < 3600) return delta >= 0 ? `in ${Math.round(delta / 60)} min` : `${Math.round(abs / 60)} min ago`;
    if (abs < 86400) return delta >= 0 ? `in ${Math.round(delta / 3600)} h` : `${Math.round(abs / 3600)} h ago`;
    return delta >= 0
      ? `in ${Math.round(delta / 86400)}d (${d.toLocaleDateString()})`
      : `${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
  } catch { return iso; }
}

function ScheduledStatusBadge({ status }) {
  const palette = {
    success: { bg: '#0c2a1f', fg: T.green, label: 'OK' },
    failed: { bg: '#2a0f12', fg: T.red, label: 'FAIL' },
    timeout: { bg: '#2a1f0a', fg: T.amber, label: 'TIMEOUT' },
    running: { bg: '#0a1d2a', fg: T.cyan, label: 'RUNNING' },
  };
  const p = palette[status] || { bg: T.bg2, fg: T.dim, label: (status || '—').toUpperCase() };
  return (
    <span className="mono" style={{
      fontSize: 9, padding: '2px 6px', letterSpacing: '.08em',
      background: p.bg, color: p.fg, border: `1px solid ${p.fg}33`,
    }}>{p.label}</span>
  );
}

function ScheduledAgentCard({ agent, schedSpec, schedulerJob, onChanged }) {
  const { addToast, showConfirm } = useContext(Ctx);
  const [running, setRunning] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [runs, setRuns] = useState(null);
  const [loadingRuns, setLoadingRuns] = useState(false);

  const reloadRuns = useCallback(async () => {
    setLoadingRuns(true);
    try {
      const r = await fetch(`${API}/agents/${agent.id}/runs`);
      const j = r.ok ? await r.json() : { rows: [] };
      setRuns(j.rows || []);
    } finally {
      setLoadingRuns(false);
    }
  }, [agent.id]);

  const runNow = () => showConfirm({
    title: `Run "${agent.name}" now?`,
    body: `Fires the agent's trigger.message immediately, just like a scheduled tick. Output goes to ${schedSpec?.destination || 'the manifest destination'} and the run shows up in the history below.`,
    action: 'Run now', danger: false,
    onConfirm: async () => {
      setRunning(true);
      try {
        const r = await fetch(`${API}/agents/${agent.id}/run-now`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: null }),
        });
        const j = await r.json();
        if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
        addToast(`Run ${j.status} (${j.duration_ms} ms)`, j.status === 'success' ? 'ok' : 'error');
        if (showHistory) reloadRuns();
        onChanged?.();
      } catch (e) {
        addToast(`Run failed: ${e.message}`, 'error');
      } finally {
        setRunning(false);
      }
    },
  });

  const toggleHistory = () => {
    const next = !showHistory;
    setShowHistory(next);
    if (next && runs === null) reloadRuns();
  };

  const deleteRun = (runId) => showConfirm({
    title: 'Delete run from history?',
    body: 'This only removes the entry from the history panel. The output (if delivered) is unaffected.',
    action: 'Delete', danger: true,
    onConfirm: async () => {
      try {
        const r = await fetch(`${API}/agents/${agent.id}/runs/${runId}`, { method: 'DELETE' });
        if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
        setRuns(rs => (rs || []).filter(x => x.id !== runId));
      } catch (e) {
        addToast(`Delete failed: ${e.message}`, 'error');
      }
    },
  });

  const lastRun = schedulerJob?.last_run_at;
  const lastStatus = schedulerJob?.last_status;
  const nextRun = schedulerJob?.next_run;

  return (
    <div style={{
      border: `1px solid ${T.border}`, background: T.bg1, marginBottom: 14,
    }}>
      <div style={{
        padding: '12px 16px', borderBottom: `1px solid ${T.border}`,
        display: 'flex', alignItems: 'center', gap: 10,
      }}>
        <Icon name="sparkle" size={14} color={T.cyan} />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, color: T.text, fontWeight: 500 }}>{agent.name}</div>
          {agent.description && (
            <div style={{ fontSize: 11, color: T.dim, marginTop: 2 }}>{agent.description}</div>
          )}
        </div>
        <span className="mono" style={{
          fontSize: 10, color: T.green, letterSpacing: '.08em',
          padding: '2px 8px', background: '#0c2a1f', border: `1px solid ${T.green}33`,
        }}>● ACTIVE</span>
      </div>

      <div style={{
        display: 'grid', gridTemplateColumns: '110px 1fr', gap: '8px 14px',
        padding: '12px 16px', fontSize: 12,
      }}>
        <span style={{ color: T.dim }}>Schedule</span>
        <span style={{ color: T.text }}>
          <span className="mono" style={{ color: T.cyan }}>{schedSpec?.schedule}</span>
          {schedSpec?.schedule && (
            <span style={{ color: T.muted, marginLeft: 8 }}>
              ({describeCron(schedSpec.schedule)}{schedSpec.timezone ? `, ${schedSpec.timezone}` : ''})
            </span>
          )}
        </span>
        <span style={{ color: T.dim }}>Next run</span>
        <span style={{ color: T.text }} className="mono">
          {nextRun
            ? <>{new Date(nextRun).toLocaleString()} <span style={{ color: T.muted }}>· {formatRelative(nextRun)}</span></>
            : <span style={{ color: T.dim }}>—</span>}
        </span>
        <span style={{ color: T.dim }}>Last run</span>
        <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {lastRun ? (
            <>
              <span className="mono" style={{ color: T.text }}>
                {new Date(lastRun).toLocaleString()}
              </span>
              <ScheduledStatusBadge status={lastStatus} />
              <span style={{ color: T.muted, fontSize: 11 }}>{formatRelative(lastRun)}</span>
            </>
          ) : (
            <span style={{ color: T.dim, fontSize: 11 }}>never run</span>
          )}
        </span>
        <span style={{ color: T.dim }}>Delivery</span>
        <span className="mono" style={{ color: T.muted, fontSize: 11 }}>
          {schedSpec?.destination || 'unspecified'}
          {schedSpec?.policy && (
            <span style={{ marginLeft: 12 }}>
              missed: <span style={{ color: T.text }}>{schedSpec.policy}</span>
            </span>
          )}
        </span>
      </div>

      <div style={{
        padding: '10px 14px', borderTop: `1px solid ${T.border}`,
        display: 'flex', gap: 8, justifyContent: 'flex-end', alignItems: 'center',
      }}>
        <button className="dlk-btn" onClick={toggleHistory}
          style={{ borderColor: T.border, color: T.text }}>
          {showHistory ? 'Hide history' : 'History'}
        </button>
        <button className="dlk-btn primary" disabled={running} onClick={runNow}
          style={{ opacity: running ? 0.5 : 1 }}>
          {running ? 'Running…' : 'Run now'}
        </button>
      </div>

      {showHistory && (
        <RunsHistoryPanel
          runs={runs}
          loading={loadingRuns}
          onReload={reloadRuns}
          onDelete={deleteRun}
        />
      )}
    </div>
  );
}

function RunsHistoryPanel({ runs, loading, onReload, onDelete }) {
  const [expanded, setExpanded] = useState(null);
  if (loading && runs === null) {
    return (
      <div style={{ padding: '14px 16px', color: T.dim, fontSize: 12, borderTop: `1px solid ${T.border}` }}>
        Loading runs…
      </div>
    );
  }
  if (!runs || runs.length === 0) {
    return (
      <div style={{ padding: '14px 16px', color: T.dim, fontSize: 12, borderTop: `1px solid ${T.border}` }}>
        No runs yet.
      </div>
    );
  }
  return (
    <div style={{ borderTop: `1px solid ${T.border}`, background: T.bg2 }}>
      <div style={{
        padding: '8px 14px', display: 'flex', alignItems: 'center', gap: 10,
        fontSize: 11, color: T.dim, borderBottom: `1px solid ${T.border}`,
      }}>
        <span className="mono" style={{ letterSpacing: '.08em' }}>RUNS · {runs.length}</span>
        <div style={{ flex: 1 }} />
        <span onClick={onReload} style={{ cursor: 'pointer', color: T.muted, userSelect: 'none' }}>
          ↻ refresh
        </span>
      </div>
      {runs.map(run => {
        const isOpen = expanded === run.id;
        return (
          <div key={run.id} style={{ borderBottom: `1px solid ${T.border}` }}>
            <div onClick={() => setExpanded(isOpen ? null : run.id)} style={{
              padding: '8px 14px', display: 'flex', alignItems: 'center', gap: 10,
              cursor: 'pointer', fontSize: 12,
            }}>
              <span className="mono" style={{ color: T.muted, fontSize: 11, minWidth: 150 }}>
                {new Date(run.triggered_at).toLocaleString()}
              </span>
              <ScheduledStatusBadge status={run.status} />
              {run.duration_ms != null && (
                <span className="mono" style={{ color: T.dim, fontSize: 10 }}>
                  {run.duration_ms} ms
                </span>
              )}
              {run.delivery_status && (
                <span className="mono" style={{
                  color: run.delivery_status === 'sent' ? T.green : T.amber,
                  fontSize: 10, letterSpacing: '.04em',
                }}>
                  · {run.delivery_status}
                </span>
              )}
              <span style={{ flex: 1, color: T.muted, fontSize: 11, overflow: 'hidden',
                whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>
                {run.error || (run.output || '').slice(0, 120)}
              </span>
              <span className="mono" style={{ color: T.dim, fontSize: 10 }}>{isOpen ? '▾' : '▸'}</span>
            </div>
            {isOpen && (
              <div style={{ padding: '10px 14px 14px', background: T.bg0 }}>
                {run.error && (
                  <div style={{ marginBottom: 10 }}>
                    <div className="mono" style={{ fontSize: 10, color: T.red, marginBottom: 4 }}>
                      ERROR
                    </div>
                    <pre className="mono" style={{
                      margin: 0, padding: '8px 10px', background: '#2a0f12',
                      border: `1px solid ${T.red}33`, color: T.text, fontSize: 11,
                      whiteSpace: 'pre-wrap',
                    }}>{run.error}</pre>
                  </div>
                )}
                {run.output && (
                  <div style={{ marginBottom: 10 }}>
                    <div className="mono" style={{ fontSize: 10, color: T.dim, marginBottom: 4 }}>
                      OUTPUT
                    </div>
                    <pre className="mono" style={{
                      margin: 0, padding: '8px 10px', background: T.bg1,
                      border: `1px solid ${T.border}`, color: T.text, fontSize: 11,
                      whiteSpace: 'pre-wrap', maxHeight: 320, overflowY: 'auto',
                    }}>{run.output}</pre>
                  </div>
                )}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span className="mono" style={{ fontSize: 10, color: T.dim }}>
                    delivery: {run.delivery_status || '—'}
                    {run.delivery_status_detail && <> · {run.delivery_status_detail}</>}
                    {run.delivery_target && <> · {run.delivery_target}</>}
                  </span>
                  <button className="dlk-btn" onClick={() => onDelete(run.id)}
                    style={{ borderColor: T.red + '66', color: T.red }}>
                    Delete
                  </button>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function ScheduledSection() {
  const { addToast } = useContext(Ctx);
  const [scheduled, setScheduled] = useState(null);
  const [status, setStatus] = useState(null);
  const [reloading, setReloading] = useState(false);

  const reload = useCallback(async () => {
    try {
      const [aResp, sResp] = await Promise.all([
        fetch(`${API}/agents`),
        fetch(`${API}/scheduler/status`),
      ]);
      const agents = aResp.ok ? await aResp.json() : [];
      const scheduledList = agents.flatMap(a => {
        const spec = parseScheduledManifest(a.manifest_yaml);
        return spec ? [{ agent: a, spec }] : [];
      });
      setScheduled(scheduledList);
      setStatus(sResp.ok ? await sResp.json() : null);
    } catch {
      setScheduled([]);
      setStatus(null);
    }
  }, []);
  useEffect(() => { reload(); }, [reload]);

  const jobByAgent = (() => {
    const map = {};
    (status?.jobs || []).forEach(j => { if (j.agent_id) map[j.agent_id] = j; });
    return map;
  })();

  const reloadScheduler = async () => {
    setReloading(true);
    try {
      const r = await fetch(`${API}/scheduler/reload`, { method: 'POST' });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
      addToast(`Reloaded · +${j.added} / ~${j.updated} / -${j.removed}`, 'ok');
      reload();
    } catch (e) {
      addToast(`Reload failed: ${e.message}`, 'error');
    } finally {
      setReloading(false);
    }
  };

  return (
    <BodyShell crumb="02 / CAPABILITIES → SCHEDULED" title="Scheduled agents"
      desc="Agents whose manifest declares trigger.type=scheduled. The scheduler fires their trigger.message on a cron schedule and routes the result to the configured destination — Telegram, filesystem, or in-app notifications.">

      <Card title="Scheduler" n="A"
        right={
          status?.disabled ? (
            <span className="mono" style={{ fontSize: 10, color: T.amber, letterSpacing: '.08em' }}>
              DISABLED (DIALEKT_DISABLE_SCHEDULER=1)
            </span>
          ) : status?.running ? (
            <span className="mono" style={{ fontSize: 10, color: T.green, letterSpacing: '.08em' }}>
              ● RUNNING · {(status.jobs || []).length} job(s)
            </span>
          ) : (
            <span className="mono" style={{ fontSize: 10, color: T.dim, letterSpacing: '.08em' }}>
              not started
            </span>
          )
        }>
        <Row label="Reload jobs from manifests"
          sub="re-syncs APScheduler against the agents table" last>
          <button className="dlk-btn" disabled={reloading} onClick={reloadScheduler}
            style={{ opacity: reloading ? 0.5 : 1 }}>
            {reloading ? 'Reloading…' : 'Reload'}
          </button>
        </Row>
      </Card>

      {scheduled === null ? (
        <div style={{ color: T.dim, fontSize: 13, padding: '24px 0' }}>Loading…</div>
      ) : scheduled.length === 0 ? (
        <Card>
          <div style={{ padding: '40px 0', display: 'flex', flexDirection: 'column',
            alignItems: 'center', gap: 12 }}>
            <Icon name="sparkle" size={28} color={T.dim} />
            <div style={{ color: T.dim, fontSize: 13, textAlign: 'center' }}>
              No scheduled agents yet.<br />
              Import a manifest with{' '}
              <span className="mono" style={{ color: T.cyan }}>trigger.type: scheduled</span>{' '}
              from the Builder Wizard or the YAML import endpoint.
            </div>
          </div>
        </Card>
      ) : (
        <div>
          {scheduled.map(({ agent, spec }) => (
            <ScheduledAgentCard
              key={agent.id}
              agent={agent}
              schedSpec={spec}
              schedulerJob={jobByAgent[agent.id]}
              onChanged={reload}
            />
          ))}
        </div>
      )}
    </BodyShell>
  );
}

// ── Section: Admin ───────────────────────────────────────────────────────────

function AdminSection() {
  const { addToast, showConfirm } = useContext(Ctx);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [reloadingSchema, setReloadingSchema] = useState(false);
  const [schemaInfo, setSchemaInfo] = useState(null);
  const [tab, setTab] = useState('stats'); // 'stats' | 'usage'

  const load = () => {
    setLoading(true);
    fetch(`${API}/admin/stats`)
      .then(r => r.json())
      .then(d => { setStats(d); setLoading(false); })
      .catch(() => setLoading(false));
  };
  useEffect(load, []);

  const reloadSchema = async () => {
    setReloadingSchema(true);
    try {
      const r = await fetch(`${API}/admin/reload-schema`, { method: 'POST' });
      const body = await r.json();
      if (r.ok && body.ok) {
        setSchemaInfo(body);
        const v = body.package_version ? `v${body.package_version}` : 'installed';
        const n = body.constants?.autonomy_levels?.length ?? '?';
        addToast(`Schema reloaded (${v}, ${n} autonomy levels)`, 'ok');
      } else {
        addToast(`Reload failed: ${(body.errors || []).join('; ') || 'unknown error'}`, 'error');
      }
    } catch (e) {
      addToast(`Reload failed: ${e.message || 'network error'}`, 'error');
    } finally {
      setReloadingSchema(false);
    }
  };

  const wipeAll = () => showConfirm({
    title: 'Wipe all conversations?',
    body: `Delete ${stats?.sessions ?? '?'} sessions and ${stats?.messages ?? '?'} messages. Models and agents are kept.`,
    action: 'Wipe conversations', danger: true,
    onConfirm: async () => {
      try {
        await fetch(`${API}/sessions`, { method: 'DELETE' });
        addToast('Conversations wiped', 'warn');
        load();
      } catch { addToast('Failed', 'error'); }
    },
  });

  const StatCard = ({ label, value, color }) => (
    <div style={{ flex: 1, border: `1px solid ${T.border}`, background: T.bg1, padding: '18px 20px', display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span className="mono" style={{ fontSize: 10, color: T.dim, letterSpacing: '.12em' }}>{label}</span>
      <span style={{ fontSize: 28, fontWeight: 700, letterSpacing: '-0.03em', color: color || T.text }}>{value ?? '—'}</span>
    </div>
  );

  const fmtBytes = (b) => b > 1e6 ? `${(b/1e6).toFixed(1)} MB` : b > 1e3 ? `${(b/1e3).toFixed(0)} KB` : `${b} B`;

  return (
    <BodyShell crumb="03 / SYSTEM → ADMIN" title="Admin Panel"
      desc="System-wide usage statistics, agent breakdown, and maintenance actions.">

      {/* Tabs: Stats (default) | Usage (MCP audit dashboard, v0.25). */}
      <div style={{
        display: 'flex', gap: 0, marginBottom: 18,
        borderBottom: `1px solid ${T.border}`,
      }}>
        {[['stats', 'Stats'], ['usage', 'Usage']].map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)} style={{
            background: 'transparent',
            border: 'none',
            borderBottom: `2px solid ${tab === k ? T.cyan : 'transparent'}`,
            color: tab === k ? T.text : T.muted,
            padding: '8px 16px', fontSize: 11, fontFamily: T.mono,
            letterSpacing: '.06em', cursor: 'pointer', marginBottom: -1,
          }}>{label.toUpperCase()}</button>
        ))}
      </div>

      {tab === 'usage' ? (
        <MCPAuditDashboard />
      ) : loading ? (
        <div style={{ color: T.dim, fontSize: 13, padding: '16px 0' }}>Loading…</div>
      ) : stats ? (
        <>
          <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
            <StatCard label="SESSIONS"    value={stats.sessions}    color={T.cyan}  />
            <StatCard label="MESSAGES"    value={stats.messages}    color={T.muted} />
            <StatCard label="AGENTS"      value={stats.agents}      color={T.amber} />
            <StatCard label="CONNECTIONS" value={stats.connections}  color={T.green} />
          </div>
          <Card title="Database" n="A" right={<span className="mono" style={{ fontSize: 11, color: T.dim }}>{fmtBytes(stats.db_size_bytes)}</span>}>
            <div style={{ padding: '10px 14px', display: 'flex', gap: 6 }}>
              <span className="mono" style={{ fontSize: 11, color: T.muted }}>{`${API.replace('http://', '')}/admin/stats`}</span>
            </div>
          </Card>
          <Card title="Agents breakdown" n="B">
            {(stats.agents_detail || []).length === 0 ? (
              <div style={{ padding: '16px 14px', color: T.dim, fontSize: 12 }}>No agents.</div>
            ) : (
              stats.agents_detail.map((a, i, arr) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', padding: '9px 14px', borderBottom: i < arr.length - 1 ? `1px solid ${T.border}` : 'none', gap: 12 }}>
                  <div style={{ width: 7, height: 7, borderRadius: '50%', background: a.status === 'published' ? T.green : a.status === 'draft' ? T.amber : T.dim, flexShrink: 0 }} />
                  <span style={{ flex: 1, fontSize: 12, color: T.text }}>{a.name}</span>
                  <span className="mono" style={{ fontSize: 10, color: T.dim }}>{a.status}</span>
                  <span className="mono" style={{ fontSize: 11, color: T.muted }}>{a.session_count} sessions</span>
                </div>
              ))
            )}
          </Card>
          <Card title="Maintenance" n="C">
            <Row
              label="Reload validation schema"
              sub={
                schemaInfo
                  ? `dialekt-manifest-validator${schemaInfo.package_version ? ` v${schemaInfo.package_version}` : ''} · ${schemaInfo.constants?.autonomy_levels?.length ?? '?'} autonomy levels, ${schemaInfo.constants?.connection_types?.length ?? '?'} connection types`
                  : 'Re-import the manifest validator so a pip-upgrade takes effect without restarting.'
              }
            >
              <button onClick={reloadSchema} disabled={reloadingSchema} style={{
                background: 'transparent', border: `1px solid ${T.cyan}`, color: T.cyan,
                padding: '6px 14px', fontSize: 11, cursor: reloadingSchema ? 'wait' : 'pointer',
                letterSpacing: '.04em', opacity: reloadingSchema ? 0.5 : 1,
              }}>{reloadingSchema ? 'RELOADING…' : 'RELOAD'}</button>
            </Row>
            <Row label="Wipe conversations" sub="Delete all sessions and messages. Models and agents are kept." last>
              <button onClick={wipeAll} style={{
                background: 'transparent', border: `1px solid ${T.red}`, color: T.red,
                padding: '6px 14px', fontSize: 11, cursor: 'pointer', letterSpacing: '.04em',
              }}>WIPE</button>
            </Row>
          </Card>
          <Card title="Cloud Sync" n="D">
            <Row label="Cloud API key" sub="Connect to dialekt Cloud for sync, licensing, and pilot management." last>
              <button onClick={() => addToast('Cloud sync coming in Week 8–9', 'ok')} style={{
                background: T.bg2, border: `1px solid ${T.border}`, color: T.muted,
                padding: '6px 14px', fontSize: 11, cursor: 'pointer',
              }}>CONFIGURE</button>
            </Row>
          </Card>
        </>
      ) : (
        <div style={{ color: T.red, fontSize: 13 }}>Failed to load stats — backend offline?</div>
      )}
    </BodyShell>
  );
}

// ── Nav + routing ─────────────────────────────────────────────────────────────

const NAV_GROUPS = [
  { title: 'Setup', items: [
    { k: 'Models',      icon: 'sparkle' },
    { k: 'Personality', icon: 'chat'    },
    { k: 'Branding',    icon: 'diamond' },
    { k: 'Appearance',  icon: 'diamond' },
    { k: 'Shortcuts',   icon: 'terminal'},
  ]},
  { title: 'Capabilities', items: [
    { k: 'Permissions',     icon: 'shield'  },
    { k: 'Filesystem',      icon: 'folder'  },
    { k: 'Terminal & shell',icon: 'terminal'},
    { k: 'Browser',         icon: 'globe'   },
    { k: 'Screen control',  icon: 'screen'  },
    { k: 'MCP Servers',     icon: 'cog' },
    { k: 'Connections',     icon: 'folder'  },
    { k: 'Agents',          icon: 'diamond' },
    { k: 'Instagram',       icon: 'sparkle' },
    { k: 'Scheduled',       icon: 'sparkle' },
  ]},
  { title: 'System', items: [
    { k: 'Storage & memory',   icon: 'file'   },
    { k: 'Performance',        icon: 'cpu'    },
    { k: 'Privacy & telemetry',icon: 'shield' },
    { k: 'License',            icon: 'shield' },
    { k: 'Admin',              icon: 'cog'    },
    { k: 'About',              icon: 'diamond'},
  ]},
];

function renderSection(s) {
  switch (s) {
    case 'Permissions':        return <PermissionsSection />;
    case 'Models':             return <ModelsSection />;
    case 'Personality':        return <PersonalitySection />;
    case 'Branding':           return <BrandingSection />;
    case 'Appearance':         return <AppearanceSection />;
    case 'Shortcuts':          return <ShortcutsSection />;
    case 'Filesystem':         return <FilesystemSection />;
    case 'Terminal & shell':   return <TerminalSection />;
    case 'Browser':            return <BrowserSection />;
    case 'Screen control':     return <ScreenSection />;
    case 'MCP Servers':        return <MCPSection />;
    case 'Connections':        return <ConnectionsSection />;
    case 'Agents':             return <AgentsSection />;
    case 'Instagram':          return <InstagramSection />;
    case 'Scheduled':          return <ScheduledSection />;
    case 'Storage & memory':   return <StorageSection />;
    case 'Performance':        return <PerformanceSection />;
    case 'Privacy & telemetry':return <PrivacySection />;
    case 'License':            return <LicenseSection />;
    case 'Admin':              return <AdminSection />;
    case 'About':              return <AboutSection />;
    default:                   return <PermissionsSection />;
  }
}

function SettingsNav({ active, onSelect }) {
  return (
    <nav style={{ width: 240, borderRight: `1px solid ${T.border}`, background: T.bg1, padding: '18px 0', flexShrink: 0 }}>
      <div style={{ padding: '0 18px 14px', display: 'flex', alignItems: 'center', gap: 10 }}>
        <Icon name="cog" size={14} color={T.cyan} />
        <span style={{ fontSize: 14, fontWeight: 600, letterSpacing: '-0.01em' }}>Settings</span>
      </div>
      {NAV_GROUPS.map((g, i) => (
        <div key={i} style={{ marginTop: 14 }}>
          <div className="upper" style={{ color: T.dim, padding: '4px 18px 6px' }}>{g.title}</div>
          {g.items.map((it, j) => {
            const on = it.k === active;
            return (
              <div key={j} onClick={() => onSelect(it.k)} style={{
                display: 'flex', alignItems: 'center', gap: 10, padding: '7px 18px',
                background: on ? T.bg2 : 'transparent',
                borderLeft: `2px solid ${on ? T.cyan : 'transparent'}`,
                paddingLeft: on ? 16 : 18,
                cursor: 'pointer', fontSize: 12,
                color: on ? T.text : T.muted, transition: 'background .1s',
              }}>
                <Icon name={it.icon} size={13} color={on ? T.cyan : T.dim} />
                <span style={{ flex: 1 }}>{it.k}</span>
                {it.n && <span className="mono" style={{ fontSize: 10, color: T.dim }}>{it.n}</span>}
              </div>
            );
          })}
        </div>
      ))}
    </nav>
  );
}

// ── Root ──────────────────────────────────────────────────────────────────────

export default function SettingsScreen({ onNav, initialSection, focusAgentId }) {
  const [settings, setSettings] = useState(DEFAULTS);
  const [loaded, setLoaded] = useState(false);
  const [section, setSection] = useState(initialSection || 'Permissions');
  const [toasts, setToasts] = useState([]);
  const [confirm, setConfirm] = useState(null);
  const saveTimer = useRef(null);
  const pendingRef = useRef(null);

  useEffect(() => {
    fetch(`${API}/settings`)
      .then(r => r.json())
      .then(data => { setSettings({ ...DEFAULTS, ...data }); setLoaded(true); })
      .catch(() => setLoaded(true));
  }, []);

  const addToast = useCallback((msg, type = 'ok') => {
    const id = Date.now() + Math.random();
    setToasts(t => [...t, { id, msg, type }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 3500);
  }, []);

  const showConfirm = useCallback((opts) => setConfirm(opts), []);

  const update = useCallback((patch) => {
    setSettings(prev => {
      const next = { ...prev, ...patch };
      pendingRef.current = next;
      clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(async () => {
        try {
          await fetch(`${API}/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(pendingRef.current),
          });
          addToast('Saved', 'ok');
        } catch {
          addToast('Save failed — is the backend running?', 'error');
        }
      }, 800);
      return next;
    });
  }, [addToast]);

  const ctx = { settings, update, addToast, showConfirm, focusAgentId, onNav };

  return (
    <Ctx.Provider value={ctx}>
      <AppFrame title={`dias.now — ${section.toLowerCase()}`}>
        <LeftPanel active={-1} onNav={onNav} />
        <main style={{ flex: 1, display: 'flex', minWidth: 0, background: T.bg0 }}>
          <SettingsNav active={section} onSelect={setSection} />
          {loaded ? renderSection(section) : (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <span className="mono" style={{ fontSize: 11, color: T.dim }}>Loading settings…</span>
            </div>
          )}
        </main>
      </AppFrame>
      <ToastStack toasts={toasts} />
      {confirm && (
        <ConfirmModal
          {...confirm}
          onConfirm={() => { confirm.onConfirm?.(); setConfirm(null); }}
          onCancel={() => setConfirm(null)}
        />
      )}
    </Ctx.Provider>
  );
}
