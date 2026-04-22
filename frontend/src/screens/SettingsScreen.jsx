import { useState, useEffect, useRef, useCallback, createContext, useContext } from 'react';
import { T } from '../tokens.js';
import Icon from '../components/Icon.jsx';
import { AppFrame } from '../components/Shell.jsx';
import LeftPanel from '../components/LeftPanel.jsx';

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

// ── Section: MCP tools ────────────────────────────────────────────────────────

const MCP_TOOLS = [
  { name: 'github',     source: 'npm:@modelcontextprotocol/server-github', n: 12, state: 'connected', desc: 'repos, issues, PRs, code search' },
  { name: 'postgres',   source: 'local binary',                            n: 6,  state: 'connected', desc: 'query prod-readonly · dialekt_db' },
  { name: 'slack',      source: 'npm:@mcp/slack',                          n: 8,  state: 'connected', desc: 'send messages, read channels' },
  { name: 'linear',     source: 'npm:@mcp/linear',                         n: 9,  state: 'ask',       desc: 'issues, projects, triage' },
  { name: 'figma',      source: 'npm:@mcp/figma',                          n: 4,  state: 'connected', desc: 'read frames, export assets' },
  { name: 'playwright', source: 'local binary',                            n: 22, state: 'disabled',  desc: 'browser automation' },
];

function MCPSection() {
  return (
    <BodyShell crumb="02 / CAPABILITIES → MCP TOOLS" title="Model Context Protocol"
      desc="External capabilities dialekt can call. Each tool's permissions inherit your global policy.">
      <ComingSoonBanner version="v1.1" label="MCP tool integration is not yet implemented. Connect external tools like GitHub, Slack, Linear, and Figma in v1.1." />
      <div style={{ padding: '32px 0', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14, border: `1px solid ${T.border}`, background: T.bg1 }}>
        <Icon name="cog" size={32} color={T.dim} />
        <div style={{ fontSize: 13, color: T.dim, textAlign: 'center', maxWidth: 340, lineHeight: 1.6 }}>
          MCP support will let dialekt call external tools — GitHub, Slack, Linear, Figma, Playwright, and more.
          Each tool inherits your permission policy (allow / ask / deny).
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'center', marginTop: 4 }}>
          {['github', 'slack', 'linear', 'figma', 'playwright', 'postgres'].map(name => (
            <span key={name} className="mono" style={{ fontSize: 10, color: T.dim, border: `1px solid ${T.border}`, padding: '3px 8px' }}>{name}</span>
          ))}
        </div>
      </div>
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

// ── Nav + routing ─────────────────────────────────────────────────────────────

const NAV_GROUPS = [
  { title: 'Setup', items: [
    { k: 'Models',      icon: 'sparkle' },
    { k: 'Personality', icon: 'chat'    },
    { k: 'Appearance',  icon: 'diamond' },
    { k: 'Shortcuts',   icon: 'terminal'},
  ]},
  { title: 'Capabilities', items: [
    { k: 'Permissions',     icon: 'shield'  },
    { k: 'Filesystem',      icon: 'folder'  },
    { k: 'Terminal & shell',icon: 'terminal'},
    { k: 'Browser',         icon: 'globe'   },
    { k: 'Screen control',  icon: 'screen'  },
    { k: 'MCP tools',       icon: 'cog', n: 6 },
  ]},
  { title: 'System', items: [
    { k: 'Storage & memory',   icon: 'file'   },
    { k: 'Performance',        icon: 'cpu'    },
    { k: 'Privacy & telemetry',icon: 'shield' },
    { k: 'About',              icon: 'diamond'},
  ]},
];

function renderSection(s) {
  switch (s) {
    case 'Permissions':        return <PermissionsSection />;
    case 'Models':             return <ModelsSection />;
    case 'Personality':        return <PersonalitySection />;
    case 'Appearance':         return <AppearanceSection />;
    case 'Shortcuts':          return <ShortcutsSection />;
    case 'Filesystem':         return <FilesystemSection />;
    case 'Terminal & shell':   return <TerminalSection />;
    case 'Browser':            return <BrowserSection />;
    case 'Screen control':     return <ScreenSection />;
    case 'MCP tools':          return <MCPSection />;
    case 'Storage & memory':   return <StorageSection />;
    case 'Performance':        return <PerformanceSection />;
    case 'Privacy & telemetry':return <PrivacySection />;
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

export default function SettingsScreen({ onNav }) {
  const [settings, setSettings] = useState(DEFAULTS);
  const [loaded, setLoaded] = useState(false);
  const [section, setSection] = useState('Permissions');
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

  const ctx = { settings, update, addToast, showConfirm };

  return (
    <Ctx.Provider value={ctx}>
      <AppFrame title={`dialekt.ai — ${section.toLowerCase()}`}>
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
