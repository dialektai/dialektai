import { T } from '../tokens.js';
import Icon from '../components/Icon.jsx';
import { AppFrame, Logo } from '../components/Shell.jsx';

function Stat({ k, v, mono, accent, last }) {
  return (
    <div style={{ padding: '10px 14px', borderRight: last ? 'none' : `1px solid ${T.border}` }}>
      <div className="upper" style={{ color: T.dim, fontSize: 9 }}>{k}</div>
      <div className={mono || accent ? 'mono' : ''} style={{ fontSize: 14, fontWeight: 500, marginTop: 4, color: accent ? T.cyan : T.text }}>{v}</div>
    </div>
  );
}

function Sparkline() {
  const pts = [40,58,72,65,80,92,88,74,96,110,124,118,132,120,140,168,150,124,112,124,138,124,118,124,132,124];
  const max = 180;
  const w = 800, h = 56;
  const step = w / (pts.length - 1);
  const d = pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${i * step} ${h - (p / max) * h}`).join(' ');
  const area = `${d} L ${w} ${h} L 0 ${h} Z`;
  return (
    <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ display: 'block' }}>
      <defs>
        <linearGradient id="sp" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={T.cyan} stopOpacity=".35" />
          <stop offset="100%" stopColor={T.cyan} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill="url(#sp)" />
      <path d={d} stroke={T.cyan} strokeWidth="1.2" fill="none" />
    </svg>
  );
}

const layers = [
  { id: 'sha256:a1f3…', size: '4.2 GB', status: 'done' },
  { id: 'sha256:82ae…', size: '4.2 GB', status: 'done' },
  { id: 'sha256:b74c…', size: '4.2 GB', status: 'done' },
  { id: 'sha256:dd10…', size: '4.2 GB', status: 'active', pct: 58 },
  { id: 'sha256:e3cb…', size: '4.2 GB', status: 'queue' },
  { id: 'sha256:5fba…', size: '4.2 GB', status: 'queue' },
  { id: 'sha256:9c11…', size: '4.2 GB', status: 'queue' },
  { id: 'sha256:2a48…', size: '4.1 GB', status: 'queue' },
  { id: 'sha256:3f92…', size: '2.0 GB', status: 'queue' },
  { id: 'manifest.json', size: '1.8 KB', status: 'queue' },
];
const overall = 36;

export default function DownloadScreen({ onNav }) {
  return (
    <AppFrame title="dialekt.ai — pulling llama3.1:70b">
      <div style={{ flex: 1, display: 'flex', background: T.bg0, minWidth: 0 }}>
        <div style={{ width: 320, background: T.bg1, borderRight: `1px solid ${T.border}`, padding: '36px 32px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 40 }}>
            <Logo />
            <div>
              <div style={{ fontSize: 15, fontWeight: 600 }}>dialekt<span style={{ color: T.cyan }}>.ai</span></div>
              <div className="mono" style={{ fontSize: 10, color: T.dim, letterSpacing: '.1em' }}>LOCAL-FIRST · v0.8.2</div>
            </div>
          </div>
          <div className="mono" style={{ fontSize: 10, color: T.cyan, letterSpacing: '.14em', marginBottom: 10 }}>02 / 05 · DOWNLOAD</div>
          <div style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.02em', lineHeight: 1.18, marginBottom: 10 }}>
            Pulling weights<br />to <span style={{ color: T.cyan }}>this machine.</span>
          </div>
          <div style={{ fontSize: 12, color: T.muted, lineHeight: 1.55 }}>
            Downloaded once, runs forever. Safe to close — we'll resume on the next launch.
          </div>
          <div style={{ marginTop: 28, padding: 12, border: `1px solid ${T.border}`, background: T.bg0 }}>
            <div className="upper" style={{ color: T.dim, marginBottom: 8 }}>Destination</div>
            <div className="mono" style={{ fontSize: 11, color: T.text }}>~/Library/dialekt/models</div>
            <div className="mono" style={{ fontSize: 10, color: T.dim, marginTop: 2 }}>612 GB free · verified with SHA-256</div>
          </div>
        </div>

        <div className="dlk-scroll" style={{ flex: 1, overflowY: 'auto', padding: '36px 44px' }}>
          <div style={{ border: `1px solid ${T.border}`, background: T.bg1, padding: 22, marginBottom: 18 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 4 }}>
              <span className="mono" style={{ fontSize: 10, color: T.cyan, letterSpacing: '.14em' }}>DOWNLOADING</span>
              <span className="dlk-dot cyan live" />
            </div>
            <div className="mono" style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.01em', marginBottom: 18 }}>
              llama3.1:<span style={{ color: T.cyan }}>70b-instruct-q4_K_M</span>
            </div>

            <div style={{ position: 'relative', height: 28, background: T.bg0, border: `1px solid ${T.border}` }}>
              <div style={{ position: 'absolute', inset: 0, width: `${overall}%`, background: T.cyan }} className="dlk-scan" />
              <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <span className="mono" style={{ fontSize: 12, fontWeight: 600, color: T.text, letterSpacing: '.08em' }}>
                  15.2 / 42.1 GB · <span style={{ color: T.cyan }}>{overall}%</span>
                </span>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', marginTop: 18, border: `1px solid ${T.border}` }}>
              <Stat k="Speed"    v="124 MB/s" accent />
              <Stat k="ETA"      v="03:42"    mono />
              <Stat k="Layer"    v="4 / 10"   mono />
              <Stat k="Verified" v="12 / 42 GB" mono last />
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', marginBottom: 10 }}>
            <span className="upper" style={{ color: T.dim }}>Layers</span>
            <div style={{ flex: 1, height: 1, margin: '0 10px', background: `repeating-linear-gradient(90deg, ${T.border} 0 4px, transparent 4px 8px)` }} />
            <span className="mono" style={{ fontSize: 10, color: T.dim }}>3 done · 1 active · 6 queued</span>
          </div>

          <div style={{ border: `1px solid ${T.border}`, background: T.bg1 }}>
            {layers.map((l, i) => (
              <div key={i} style={{
                display: 'grid', gridTemplateColumns: '20px 1fr auto auto', gap: 12, alignItems: 'center',
                padding: '8px 12px', borderBottom: i < layers.length - 1 ? `1px solid ${T.border}` : 'none',
                background: l.status === 'active' ? T.bg2 : 'transparent',
              }}>
                {l.status === 'done'   && <Icon name="check" size={13} color={T.green} />}
                {l.status === 'active' && <span className="dlk-dot cyan live" />}
                {l.status === 'queue'  && <span style={{ width: 6, height: 6, border: `1px solid ${T.dim}`, borderRadius: '50%', display: 'inline-block' }} />}
                <span className="mono" style={{ fontSize: 11, color: l.status === 'queue' ? T.dim : T.text }}>{l.id}</span>
                {l.status === 'active' ? (
                  <div style={{ width: 180, height: 4, background: T.bg0, border: `1px solid ${T.border}` }}>
                    <div style={{ width: `${l.pct}%`, height: '100%', background: T.cyan }} />
                  </div>
                ) : <span />}
                <span className="mono" style={{ fontSize: 11, color: l.status === 'done' ? T.green : l.status === 'active' ? T.cyan : T.dim, minWidth: 70, textAlign: 'right' }}>
                  {l.status === 'done' ? `✓ ${l.size}` : l.status === 'active' ? `${l.pct}% · ${l.size}` : l.size}
                </span>
              </div>
            ))}
          </div>

          <div style={{ marginTop: 18, padding: 14, border: `1px solid ${T.border}`, background: T.bg1 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 10 }}>
              <span className="upper" style={{ color: T.dim }}>Bandwidth · last 60s</span>
              <span className="mono" style={{ fontSize: 11, color: T.cyan }}>124 MB/s</span>
              <span className="mono" style={{ fontSize: 10, color: T.dim }}>peak 168 · avg 112</span>
            </div>
            <Sparkline />
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 22 }}>
            <div style={{ flex: 1 }} className="mono">
              <span style={{ fontSize: 11, color: T.dim }}>downloading from </span>
              <span style={{ fontSize: 11, color: T.muted }}>registry.ollama.ai</span>
              <span style={{ fontSize: 11, color: T.dim }}> · resumable</span>
            </div>
            <button className="dlk-btn"><Icon name="stop" size={11} color={T.amber} />Pause</button>
            <button className="dlk-btn">Cancel</button>
            <button className="dlk-btn primary" style={{ padding: '7px 14px' }} onClick={() => onNav?.('main')}>Continue in background</button>
          </div>
        </div>
      </div>
    </AppFrame>
  );
}
