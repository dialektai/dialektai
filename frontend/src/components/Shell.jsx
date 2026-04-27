import { T } from '../tokens.js';
import Icon from './Icon.jsx';
import UpdateBanner from './UpdateBanner.jsx';

async function tauriWin(fn) {
  if (!window.__TAURI_INTERNALS__) return;
  const { getCurrentWindow } = await import('@tauri-apps/api/window');
  fn(getCurrentWindow());
}

export function Logo() {
  return (
    <div style={{
      width: 28, height: 28, position: 'relative',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      border: `1px solid ${T.cyan}`, background: T.bg0, flexShrink: 0,
    }}>
      <svg width="18" height="18" viewBox="0 0 18 18">
        <path d="M2 9 L9 2 L16 9 L9 16 Z" fill="none" stroke={T.cyan} strokeWidth="1.2" />
        <path d="M9 2 L9 16 M2 9 L16 9" stroke={T.cyan} strokeWidth="1" opacity="0.5" />
        <circle cx="9" cy="9" r="1.6" fill={T.cyan} />
      </svg>
    </div>
  );
}

export function Meter({ label, value, unit = '%', warn = 80, crit = 92 }) {
  const color = value >= crit ? T.red : value >= warn ? T.amber : T.cyan;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 10, fontFamily: T.mono, color: T.muted }}>
      <span style={{ width: 28, letterSpacing: '.08em' }}>{label}</span>
      <div style={{ flex: 1, height: 4, background: T.bg0, position: 'relative', border: `1px solid ${T.border}` }}>
        <div style={{ position: 'absolute', inset: 0, width: `${value}%`, background: color }} />
      </div>
      <span className="mono" style={{ width: 32, textAlign: 'right', color: T.text, fontVariantNumeric: 'tabular-nums' }}>
        {value}{unit}
      </span>
    </div>
  );
}

export function SectionLabel({ n, children, right }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10,
      padding: '10px 14px', borderBottom: `1px solid ${T.border}`, background: T.bg1,
    }}>
      <span className="mono" style={{ color: T.cyan, fontSize: 10, letterSpacing: '.12em' }}>{n}</span>
      <span className="upper" style={{ color: T.text }}>{children}</span>
      <div style={{ flex: 1, height: 1, background: `repeating-linear-gradient(90deg, ${T.border} 0 4px, transparent 4px 8px)` }} />
      {right}
    </div>
  );
}

// Window-control style per OS. macOS uses left-aligned traffic-light dots;
// Windows + Linux (GNOME/KDE both default to right-aligned controls) get
// the right-aligned hairline button set. Detection is UA-based — Tauri's
// platform plugin isn't bundled, and the UA is reliable enough for this
// purely cosmetic decision.
function detectControlsStyle() {
  if (typeof navigator === 'undefined') return 'macos';
  const ua = (navigator.userAgent || navigator.platform || '').toLowerCase();
  if (ua.includes('mac')) return 'macos';
  return 'win-linux';
}

function MacControls() {
  return (
    <div style={{ display: 'flex', gap: 6 }} data-tauri-drag-region={false}>
      <div
        onClick={() => tauriWin(w => w.close())}
        title="Close"
        style={{ width: 12, height: 12, borderRadius: '50%', background: '#ff5f56', cursor: 'pointer' }}
      />
      <div
        onClick={() => tauriWin(w => w.minimize())}
        title="Minimize"
        style={{ width: 12, height: 12, borderRadius: '50%', background: '#ffbd2e', cursor: 'pointer' }}
      />
      <div
        onClick={() => tauriWin(w => w.toggleMaximize())}
        title="Toggle full size"
        style={{ width: 12, height: 12, borderRadius: '50%', background: '#27c93f', cursor: 'pointer' }}
      />
    </div>
  );
}

function WinLinuxControls() {
  // Three minimal buttons aligned to the right edge of the title bar:
  // minimize · maximize · close. Hairline borders + the close button
  // turning red on hover follow the modern Windows / GNOME convention.
  const baseBtn = {
    width: 36, height: 32, display: 'flex', alignItems: 'center', justifyContent: 'center',
    cursor: 'pointer', background: 'transparent',
    border: 'none', color: T.muted, transition: 'background .12s, color .12s',
  };
  const stroke = 'currentColor';
  const Btn = ({ onClick, title, children, hoverBg = T.bg2, hoverColor = T.text }) => {
    return (
      <button
        type="button"
        onClick={onClick}
        title={title}
        onMouseEnter={(e) => { e.currentTarget.style.background = hoverBg; e.currentTarget.style.color = hoverColor; }}
        onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = T.muted; }}
        style={baseBtn}
      >{children}</button>
    );
  };
  return (
    <div style={{ display: 'flex', alignSelf: 'stretch' }} data-tauri-drag-region={false}>
      <Btn onClick={() => tauriWin(w => w.minimize())} title="Minimize">
        <svg width="11" height="11" viewBox="0 0 11 11"><path d="M2 6h7" stroke={stroke} strokeWidth="1" /></svg>
      </Btn>
      <Btn onClick={() => tauriWin(w => w.toggleMaximize())} title="Maximize">
        <svg width="11" height="11" viewBox="0 0 11 11"><rect x="2" y="2" width="7" height="7" stroke={stroke} fill="none" strokeWidth="1" /></svg>
      </Btn>
      <Btn onClick={() => tauriWin(w => w.close())} title="Close" hoverBg="#e81123" hoverColor="#fff">
        <svg width="11" height="11" viewBox="0 0 11 11">
          <path d="M2 2l7 7M9 2l-7 7" stroke={stroke} strokeWidth="1" />
        </svg>
      </Btn>
    </div>
  );
}

export function AppFrame({ children, title = 'dias.now', ollamaOnline }) {
  const showOllama = ollamaOnline !== undefined;
  const dotColor = ollamaOnline ? '#27c93f' : '#ff5f56';
  const dotTitle = ollamaOnline ? 'Ollama running' : 'Ollama offline';
  const controlsStyle = detectControlsStyle();
  const isMac = controlsStyle === 'macos';
  return (
    <div style={{ width: '100%', height: '100%', background: T.bg0, display: 'flex', flexDirection: 'column' }}>
      <div
        data-tauri-drag-region
        style={{
          height: 32, display: 'flex', alignItems: 'center', gap: 10,
          paddingLeft: isMac ? 12 : 14, paddingRight: isMac ? 12 : 0,
          background: T.bg1, borderBottom: `1px solid ${T.border}`, flexShrink: 0,
          userSelect: 'none', cursor: 'default',
        }}
      >
        {isMac && <MacControls />}
        <div
          data-tauri-drag-region
          style={{
            flex: 1, fontSize: 11, color: T.muted,
            fontFamily: T.mono, letterSpacing: '.08em',
            textAlign: isMac ? 'center' : 'left',
          }}
        >
          {title}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: isMac ? 0 : 10, paddingRight: isMac ? 0 : 8 }}>
          {showOllama && (
            <div
              title={dotTitle}
              style={{
                width: 7, height: 7, borderRadius: '50%',
                background: dotColor,
                boxShadow: `0 0 4px ${dotColor}`,
                transition: 'background 0.4s, box-shadow 0.4s',
              }}
            />
          )}
        </div>
        {!isMac && <WinLinuxControls />}
      </div>
      <UpdateBanner />
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        {children}
      </div>
    </div>
  );
}
