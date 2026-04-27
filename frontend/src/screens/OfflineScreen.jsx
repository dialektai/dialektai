import { useState, useEffect, useCallback, useRef } from 'react';
import { T } from '../tokens.js';
import Icon from '../components/Icon.jsx';
import { AppFrame } from '../components/Shell.jsx';
import LeftPanel from '../components/LeftPanel.jsx';

const API = 'http://localhost:8765';
const RETRY_INTERVAL = 5;

function DiagRow({ label, state, detail, last }) {
  const map = {
    ok:   { c: T.green, m: '✓ OK'   },
    warn: { c: T.amber, m: '△ INFO' },
    fail: { c: T.red,   m: '✕ FAIL' },
  }[state];
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '90px 1fr auto', gap: 14, alignItems: 'center',
      padding: '10px 14px', borderBottom: last ? 'none' : `1px solid ${T.border}`,
      background: state === 'fail' ? T.errorBg : 'transparent',
    }}>
      <span className="mono" style={{ fontSize: 10, color: map.c, letterSpacing: '.08em' }}>{map.m}</span>
      <div>
        <div style={{ fontSize: 12, color: T.text }}>{label}</div>
        <div className="mono" style={{ fontSize: 10, color: T.dim, marginTop: 2 }}>{detail}</div>
      </div>
      <span className="mono" style={{ fontSize: 10, color: T.dim }}>re-run</span>
    </div>
  );
}

function ActionTile({ icon, title, sub, primary, onClick, loading }) {
  return (
    <div onClick={onClick} style={{
      padding: 14, border: `1px solid ${primary ? T.cyan : T.border}`,
      background: primary ? T.bg2 : T.bg1, cursor: 'pointer',
      borderLeft: `2px solid ${primary ? T.cyan : T.border}`,
      opacity: loading ? 0.7 : 1,
    }}>
      <Icon name={loading ? 'cpu' : icon} size={16} color={primary ? T.cyan : T.muted} />
      <div style={{ fontSize: 13, color: T.text, marginTop: 10 }}>{loading ? 'Working…' : title}</div>
      <div style={{ fontSize: 11, color: T.dim, marginTop: 2 }}>{sub}</div>
    </div>
  );
}

export default function OfflineScreen({ onNav }) {
  const [countdown, setCountdown] = useState(RETRY_INTERVAL);
  const [attempt, setAttempt] = useState(1);
  const [checking, setChecking] = useState(false);
  const [starting, setStarting] = useState(false);
  const [lastChecked, setLastChecked] = useState('just now');
  const [hasLicense, setHasLicense] = useState(null);   // null = unknown
  // Live diagnostic state (replaces hardcoded mockup rows pre-v0.26.x).
  const [diag, setDiag] = useState({
    backend: 'unknown',
    backend_detail: 'pinging…',
    ollama: 'unknown',
    ollama_detail: 'pinging…',
    models: 'unknown',
    models_detail: '—',
  });
  const timerRef = useRef(null);

  // Probe license status so the "first-time pilot" banner can decide
  // whether to push toward Settings → License, or just trust they
  // already have a key and the issue is purely Ollama.
  useEffect(() => {
    fetch(`${API}/license/status`)
      .then(r => r.json())
      .then(d => setHasLicense(!!(d?.license_key || d?.trial_valid)))
      .catch(() => setHasLicense(null));
  }, []);

  const check = useCallback(async () => {
    setChecking(true);
    setLastChecked('checking…');
    try {
      const r = await fetch(`${API}/health`, { signal: AbortSignal.timeout(3000) });
      const d = await r.json();
      const models = Array.isArray(d.models) ? d.models : [];
      setDiag({
        backend: 'ok',
        backend_detail: `localhost:8765 (${d.status || 'ok'})`,
        ollama: d.ollama ? 'ok' : 'fail',
        ollama_detail: d.ollama ? 'localhost:11434 reachable' : 'localhost:11434 unreachable from backend',
        models: models.length > 0 ? 'ok' : 'warn',
        models_detail: models.length > 0
          ? `${models.length} model(s): ${models.slice(0, 2).join(', ')}${models.length > 2 ? ', …' : ''}`
          : 'no models — run `ollama pull <name>`',
      });
      if (d.ollama) {
        onNav?.('empty');
        return;
      }
    } catch {
      setDiag(prev => ({
        ...prev,
        backend: 'fail',
        backend_detail: 'localhost:8765 unreachable',
        ollama: 'unknown',
        ollama_detail: 'cannot probe — backend offline',
      }));
    }
    setChecking(false);
    setLastChecked('just now');
    setAttempt(a => a + 1);
    setCountdown(RETRY_INTERVAL);
  }, [onNav]);

  const startOllama = useCallback(async () => {
    setStarting(true);
    try {
      await fetch(`${API}/ollama/start`, { method: 'POST', signal: AbortSignal.timeout(5000) });
    } catch {}
    setTimeout(() => { setStarting(false); check(); }, 2000);
  }, [check]);

  // Auto-retry countdown
  useEffect(() => {
    timerRef.current = setInterval(() => {
      setCountdown(c => {
        if (c <= 1) { check(); return RETRY_INTERVAL; }
        return c - 1;
      });
    }, 1000);
    return () => clearInterval(timerRef.current);
  }, [check]);

  return (
    <AppFrame title="dias.now — connection error">
      <LeftPanel active={-1} running={false} model="— no model —" onNav={onNav} />
      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', background: T.bg0, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 18px', background: T.errorBg, borderBottom: `1px solid ${T.amber}55` }}>
          <span className="dlk-dot amber live" />
          <span className="mono" style={{ fontSize: 11, color: T.amber, letterSpacing: '.1em' }}>OLLAMA OFFLINE</span>
          <span className="mono" style={{ fontSize: 11, color: T.muted }}>· can't reach localhost:11434</span>
          <div style={{ flex: 1 }} />
          <span className="mono" style={{ fontSize: 10, color: T.dim }}>
            {checking ? 'checking…' : `retry in ${countdown}s · attempt ${attempt}`}
          </span>
        </div>

        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', padding: '0 44px', minHeight: 0 }}>
          <div style={{ maxWidth: 780, margin: '0 auto', width: '100%' }}>
            <div className="mono" style={{ fontSize: 10, color: T.amber, letterSpacing: '.16em', marginBottom: 10 }}>ERROR · E_OLLAMA_UNREACHABLE</div>
            <div style={{ fontSize: 26, fontWeight: 600, letterSpacing: '-0.02em', lineHeight: 1.15, marginBottom: 10 }}>
              Can't reach the local inference server.
            </div>
            <div style={{ fontSize: 13, color: T.muted, lineHeight: 1.6, maxWidth: 560, marginBottom: 24 }}>
              dialekt runs on a local Ollama instance at <span className="mono" style={{ color: T.text }}>http://127.0.0.1:11434</span>.
              It looks like the process isn't running, or something is blocking the port.
            </div>

            {/* First-time-pilot escape hatch. Pilots without a license
                used to dead-end here because MainScreen redirected before
                LicenseScreen had a chance — now the gate in App.jsx catches
                that, and this banner offers the same path explicitly so
                returning pilots also see it. */}
            {hasLicense === false && (
              <div style={{
                border: `1px solid ${T.cyan}66`, background: `${T.cyan}0a`,
                padding: '12px 16px', marginBottom: 20,
                display: 'flex', alignItems: 'center', gap: 14,
              }}>
                <Icon name="diamond" size={18} color={T.cyan} />
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, color: T.text }}>First time using dialekt?</div>
                  <div style={{ fontSize: 11, color: T.muted, marginTop: 2 }}>
                    Set up your license or start a 30-day trial — you don't need Ollama running for that.
                  </div>
                </div>
                <button onClick={() => onNav?.('license')} style={{
                  background: T.cyan, color: '#000', border: 'none',
                  padding: '7px 16px', fontSize: 12, fontWeight: 600,
                  cursor: 'pointer', letterSpacing: '.04em',
                }}>OPEN LICENSE</button>
              </div>
            )}

            <div style={{ border: `1px solid ${T.border}`, background: T.bg1, marginBottom: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', borderBottom: `1px solid ${T.border}`, background: T.bg2 }}>
                <span className="mono" style={{ fontSize: 10, color: T.cyan, letterSpacing: '.14em' }}>A //</span>
                <span style={{ fontSize: 12, fontWeight: 500 }}>Diagnostics</span>
                <div style={{ flex: 1 }} />
                <span className="mono" style={{ fontSize: 10, color: T.dim }}>{lastChecked}</span>
              </div>
              <DiagRow label="dialekt backend reachable"      state={diag.backend === 'unknown' ? 'warn' : diag.backend} detail={diag.backend_detail} />
              <DiagRow label="Ollama reachable from backend"  state={diag.ollama === 'unknown' ? 'warn' : diag.ollama}   detail={diag.ollama_detail} />
              <DiagRow label="Models available"               state={diag.models === 'unknown' ? 'warn' : diag.models}   detail={diag.models_detail} />
              <DiagRow label="Network (outbound)"             state="warn" detail="not required — local only" last />
            </div>

            <div style={{ border: `1px solid ${T.border}`, background: T.surfaceDeep, marginBottom: 20 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 10px', borderBottom: `1px solid ${T.border}`, background: T.bg2 }}>
                <Icon name="terminal" size={12} color={T.green} />
                <span className="mono" style={{ fontSize: 10, color: T.text }}>dialekt backend log · latest</span>
                <div style={{ flex: 1 }} />
                <Icon name="copy" size={12} color={T.dim} />
              </div>
              <div className="mono" style={{ padding: '10px 12px', fontSize: 11, lineHeight: 1.65 }}>
                <div style={{ color: T.dim }}>[–] <span style={{ color: T.muted }}>dialekt-api</span> probe :11434 …</div>
                <div style={{ color: T.textError }}>[–] fetch error: ECONNREFUSED 127.0.0.1:11434</div>
                <div style={{ color: T.amber }}>[–] ollama offline · attempt {attempt}</div>
                <div style={{ color: T.muted }}>[–] hint: run <span style={{ color: T.cyan }}>ollama serve</span> to start the daemon</div>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
              <ActionTile
                icon="refresh"
                title="Retry now"
                sub="re-probe :11434"
                primary
                loading={checking}
                onClick={check}
              />
              <ActionTile
                icon="terminal"
                title="Start Ollama"
                sub="runs `ollama serve` in a sandbox"
                loading={starting}
                onClick={startOllama}
              />
              <ActionTile
                icon="cog"
                title="Point to remote"
                sub="use a machine on your network"
                onClick={() => onNav?.('settings')}
              />
            </div>

            <div style={{
              marginTop: 18, padding: 14, display: 'flex', alignItems: 'center', gap: 14,
              border: `1px dashed ${T.border}`,
            }}>
              <Icon name="shield" size={18} color={T.cyan} />
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 12, color: T.text }}>Keep browsing offline</div>
                <div style={{ fontSize: 11, color: T.dim, marginTop: 2 }}>All past sessions, files and memory are still available — you just can't send new messages.</div>
              </div>
              <button className="dlk-btn" onClick={() => onNav?.('empty')}>Open past sessions</button>
            </div>

            {/* Always-visible link to Settings → License so returning
                pilots (license=true but Ollama dead) can still find the
                License section to swap a key, or hit Restart Onboarding. */}
            <div style={{
              marginTop: 12, padding: '10px 14px',
              display: 'flex', alignItems: 'center', gap: 10, justifyContent: 'flex-end',
              fontSize: 11, color: T.dim,
            }}>
              <span>Need to enter or change a license key, or restart onboarding?</span>
              <button onClick={() => onNav?.('settings', { initialSection: 'License' })} style={{
                background: 'transparent', border: `1px solid ${T.border}`, color: T.text,
                padding: '4px 12px', fontSize: 11, cursor: 'pointer', letterSpacing: '.04em',
              }}>OPEN SETTINGS → LICENSE</button>
            </div>
          </div>
        </div>
      </main>
    </AppFrame>
  );
}
