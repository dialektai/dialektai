import { useState, useEffect, useCallback, useRef } from 'react';
import { T } from '../tokens.js';
import { AppFrame, Logo } from '../components/Shell.jsx';

const API = 'http://localhost:8765';

const PHASES = [
  { id: 'idle',        label: 'Awaiting consent' },
  { id: 'downloading', label: 'Downloading install script' },
  { id: 'verified',    label: 'Verified hash' },
  { id: 'running',     label: 'Running installer' },
  { id: 'starting',    label: 'Starting Ollama service' },
  { id: 'done',        label: 'Ready' },
];

function PhasePill({ phase, current, doneSet }) {
  const done = doneSet.has(phase.id);
  const active = current === phase.id;
  const color = done ? T.green : active ? T.cyan : T.dim;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0' }}>
      <div style={{
        width: 18, height: 18, borderRadius: '50%', flexShrink: 0,
        background: done ? T.green : active ? `${T.cyan}33` : 'transparent',
        border: `1px solid ${color}`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 9, fontWeight: 700, color: done ? T.bg0 : color,
      }}>
        {done ? '✓' : active ? '·' : ''}
      </div>
      <span style={{ fontSize: 12, color, fontWeight: active ? 600 : 400 }}>{phase.label}</span>
      {active && <span className="dlk-dot cyan live" style={{ marginLeft: 'auto' }} />}
    </div>
  );
}

function StepBadge({ n, label, done }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 0' }}>
      <div style={{
        width: 22, height: 22, borderRadius: '50%', flexShrink: 0,
        background: done ? T.green : T.bg3,
        border: `1px solid ${done ? T.green : T.border}`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 10, fontWeight: 700,
        color: done ? T.bg0 : T.dim,
      }}>{done ? '✓' : n}</div>
      <span style={{ fontSize: 12, color: done ? T.green : T.muted }}>{label}</span>
    </div>
  );
}

export default function OllamaInstallScreen({ onNav, checkInfo }) {
  const [status, setStatus] = useState(checkInfo || null);
  const [polling, setPolling] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState(null);

  // Auto-install state (Linux only)
  const [preview, setPreview] = useState(null); // { sha256, command, preview, supported }
  const [consent, setConsent] = useState(false);
  const [phase, setPhase] = useState('idle');
  const [doneSet, setDoneSet] = useState(() => new Set());
  const [logLines, setLogLines] = useState([]);
  const [installing, setInstalling] = useState(false);
  const [installError, setInstallError] = useState(null);
  const abortRef = useRef(null);
  const logBoxRef = useRef(null);

  const check = useCallback(async () => {
    try {
      const r = await fetch(`${API}/ollama/check`);
      const d = await r.json();
      setStatus(d);
      return d;
    } catch { return null; }
  }, []);

  // Poll while waiting (browser-driven install on Mac/Windows)
  useEffect(() => {
    if (!polling) return;
    const id = setInterval(async () => {
      const d = await check();
      if (d?.installed && d?.running) {
        setPolling(false);
        onNav('onboarding-step3');
      }
    }, 3000);
    return () => clearInterval(id);
  }, [polling, check, onNav]);

  useEffect(() => {
    const onFocus = async () => {
      const d = await check();
      if (d?.installed && d?.running) onNav('onboarding-step3');
    };
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [check, onNav]);

  // Fetch install preview on mount (linux only — server tells us)
  useEffect(() => {
    fetch(`${API}/ollama/install/preview`).then(r => r.json()).then(d => {
      setPreview(d);
    }).catch(() => {});
  }, []);

  // Auto-scroll log
  useEffect(() => {
    if (logBoxRef.current) {
      logBoxRef.current.scrollTop = logBoxRef.current.scrollHeight;
    }
  }, [logLines]);

  const startAutoInstall = async () => {
    if (!preview?.supported || !preview?.sha256) return;
    setInstalling(true);
    setInstallError(null);
    setLogLines([]);
    setDoneSet(new Set(['idle']));
    setPhase('downloading');

    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const url = `${API}/ollama/install/stream?sha256=${encodeURIComponent(preview.sha256)}`;
      const resp = await fetch(url, { signal: ctrl.signal });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop();
        for (const line of lines) {
          if (!line.startsWith('data:')) continue;
          const raw = line.slice(5).trim();
          if (!raw) continue;
          try {
            const ev = JSON.parse(raw);
            if (ev.phase === 'log') {
              setLogLines(prev => [...prev.slice(-200), ev.line]);
            } else if (ev.phase === 'abort') {
              setInstallError(ev.error || 'install aborted');
              setPhase('idle');
            } else if (ev.phase) {
              setPhase(ev.phase);
              setDoneSet(prev => {
                const next = new Set(prev);
                // Mark prior phases as done
                const order = ['idle', 'downloading', 'verified', 'running', 'starting', 'done'];
                const idx = order.indexOf(ev.phase);
                for (let i = 0; i < idx; i++) next.add(order[i]);
                if (ev.phase === 'done') next.add('done').add('starting');
                return next;
              });
            }
          } catch { /* malformed */ }
        }
      }

      // After SSE stream ends, give Ollama a moment to start the service then check
      setPhase('starting');
      await new Promise(r => setTimeout(r, 2500));
      const d = await check();
      if (d?.installed && d?.running) {
        setPhase('done');
        setDoneSet(new Set(['idle', 'downloading', 'verified', 'running', 'starting', 'done']));
        setTimeout(() => onNav('onboarding-step3'), 800);
      } else if (d?.installed) {
        // Installed but service not up — try to start it
        await fetch(`${API}/ollama/start`, { method: 'POST' }).catch(() => {});
        await new Promise(r => setTimeout(r, 2000));
        const d2 = await check();
        if (d2?.running) {
          setPhase('done');
          setDoneSet(new Set(['idle', 'downloading', 'verified', 'running', 'starting', 'done']));
          setTimeout(() => onNav('onboarding-step3'), 800);
        } else {
          setInstallError('Installed but service did not start. Try the "Start Ollama" button below.');
        }
      } else if (!installError) {
        setInstallError('Install completed but Ollama not detected. Check the log.');
      }
    } catch (e) {
      if (e.name !== 'AbortError') {
        setInstallError(String(e));
      }
    } finally {
      setInstalling(false);
    }
  };

  const cancelAutoInstall = async () => {
    abortRef.current?.abort();
    await fetch(`${API}/ollama/install/cancel`, { method: 'POST' }).catch(() => {});
    setInstalling(false);
  };

  const handleManualStart = async () => {
    setStarting(true);
    setError(null);
    try {
      await fetch(`${API}/ollama/start`, { method: 'POST' });
      await new Promise(r => setTimeout(r, 2000));
      const d = await check();
      if (d?.running) onNav('onboarding-step3');
      else setError('Ollama started but not responding yet. Wait a moment and click "Check again".');
    } catch (e) { setError(String(e)); }
    finally { setStarting(false); }
  };

  const installed = status?.installed;
  const running = status?.running;
  const platform = status?.platform || preview?.supported ? 'linux' : (status?.platform || 'darwin');
  const installUrl = status?.install_url || 'https://ollama.com/download';
  const platformLabel = { darwin: 'Mac', linux: 'Linux', windows: 'Windows' }[platform] || 'Mac';
  const isLinux = (status?.platform === 'linux') || (preview?.supported === true);
  const canAutoInstall = isLinux && preview?.supported && preview?.sha256 && !installed;

  return (
    <AppFrame title="dialekt.ai — Setup">
      <div style={{ flex: 1, display: 'flex', background: T.bg0, minWidth: 0 }}>
        {/* Sidebar */}
        <div style={{ width: 300, background: T.bg1, borderRight: `1px solid ${T.border}`, padding: '40px 28px', display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 40 }}>
            <Logo />
            <div>
              <div style={{ fontSize: 15, fontWeight: 700 }}>dialekt<span style={{ color: T.cyan }}>.ai</span></div>
              <div className="mono" style={{ fontSize: 10, color: T.dim, letterSpacing: '.1em' }}>SETUP · STEP 2/5</div>
            </div>
          </div>

          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.12em', color: T.dim, marginBottom: 12 }}>SETUP PROGRESS</div>
          <StepBadge n="1" label="Choose mode" done />
          <StepBadge n="2" label="Install Ollama" done={!!(installed && running)} />
          <StepBadge n="3" label="Download models" done={false} />
          <StepBadge n="4" label="Permissions" done={false} />
          <StepBadge n="5" label="First chat" done={false} />

          {installing && (
            <div style={{ marginTop: 24, padding: 12, background: T.bg0, border: `1px solid ${T.border}` }}>
              <div className="mono" style={{ fontSize: 10, color: T.cyan, letterSpacing: '.1em', marginBottom: 8 }}>LIVE PHASES</div>
              {PHASES.map(p => (
                <PhasePill key={p.id} phase={p} current={phase} doneSet={doneSet} />
              ))}
            </div>
          )}

          <div style={{ flex: 1 }} />
          <button
            onClick={() => onNav('main')}
            style={{ background: 'none', border: `1px solid ${T.border}`, color: T.dim, padding: '8px 16px', fontSize: 11, cursor: 'pointer', letterSpacing: '.08em' }}
          >SKIP SETUP</button>
        </div>

        {/* Main */}
        <div style={{ flex: 1, padding: '60px 80px', overflowY: 'auto', minWidth: 0 }}>
          <div className="mono" style={{ fontSize: 10, color: T.cyan, letterSpacing: '.14em', marginBottom: 12 }}>STEP 2 OF 5</div>

          {installed && running ? (
            // ── Already installed ──
            <>
              <h1 style={{ fontSize: 32, fontWeight: 800, color: T.text, margin: '0 0 8px', letterSpacing: '-0.02em' }}>
                Ollama is ready
              </h1>
              <p style={{ fontSize: 14, color: T.muted, margin: '0 0 32px', lineHeight: 1.6 }}>
                Version <span className="mono" style={{ color: T.cyan }}>v{status?.version || '?'}</span> running locally.
              </p>
              <button
                onClick={() => onNav('onboarding-step3')}
                style={{ padding: '11px 28px', background: T.cyan, color: T.bg0, border: 'none', fontSize: 13, fontWeight: 700, cursor: 'pointer', letterSpacing: '.06em' }}
              >CONTINUE →</button>
            </>
          ) : installing || phase !== 'idle' ? (
            // ── Live install in progress ──
            <>
              <h1 style={{ fontSize: 32, fontWeight: 800, color: T.text, margin: '0 0 8px', letterSpacing: '-0.02em' }}>
                Installing Ollama
              </h1>
              <p style={{ fontSize: 14, color: T.muted, margin: '0 0 24px', lineHeight: 1.6 }}>
                Running the install script with your consent. Script SHA-256 verified before exec.
              </p>

              {/* Live log */}
              <div style={{ border: `1px solid ${T.border}`, background: T.bg1, marginBottom: 18 }}>
                <div style={{ padding: '10px 16px', borderBottom: `1px solid ${T.border}`, display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span className="mono" style={{ fontSize: 10, color: T.cyan, letterSpacing: '.14em' }}>STDOUT</span>
                  <div style={{ flex: 1 }} />
                  <span className="mono" style={{ fontSize: 10, color: T.dim }}>{logLines.length} lines</span>
                </div>
                <div ref={logBoxRef} style={{
                  height: 280, overflowY: 'auto', padding: '8px 16px',
                  fontFamily: T.mono, fontSize: 11, color: T.muted, lineHeight: 1.55,
                }}>
                  {logLines.length === 0 ? (
                    <div style={{ color: T.dim, fontStyle: 'italic' }}>Waiting for output…</div>
                  ) : (
                    logLines.map((l, i) => (
                      <div key={i} style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{l}</div>
                    ))
                  )}
                </div>
              </div>

              {installError && (
                <div style={{ padding: '10px 14px', background: T.bg1, border: `1px solid ${T.red}`, color: T.red, fontSize: 12, marginBottom: 16 }}>
                  ✗ {installError}
                </div>
              )}

              <div style={{ display: 'flex', gap: 10 }}>
                {installing ? (
                  <button onClick={cancelAutoInstall}
                    style={{ padding: '9px 20px', background: 'none', border: `1px solid ${T.border}`, color: T.muted, fontSize: 12, cursor: 'pointer' }}>
                    Cancel install
                  </button>
                ) : phase === 'done' ? (
                  <button onClick={() => onNav('onboarding-step3')}
                    style={{ padding: '11px 28px', background: T.cyan, color: T.bg0, border: 'none', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>
                    CONTINUE →
                  </button>
                ) : (
                  <button onClick={() => { setPhase('idle'); setDoneSet(new Set()); setLogLines([]); setInstallError(null); }}
                    style={{ padding: '9px 20px', background: T.bg2, border: `1px solid ${T.border}`, color: T.text, fontSize: 12, cursor: 'pointer' }}>
                    Try again
                  </button>
                )}
              </div>
            </>
          ) : installed && !running ? (
            // ── Installed but not running ──
            <>
              <h1 style={{ fontSize: 32, fontWeight: 800, color: T.text, margin: '0 0 8px', letterSpacing: '-0.02em' }}>
                Start Ollama
              </h1>
              <p style={{ fontSize: 14, color: T.muted, margin: '0 0 32px', lineHeight: 1.6 }}>
                Ollama is installed but not running. Start it to continue.
              </p>
              <div style={{ background: T.bg1, border: `1px solid ${T.border}`, padding: 28, marginBottom: 16 }}>
                <div style={{ fontSize: 13, color: T.text, marginBottom: 20 }}>
                  Ollama {status?.version && <span className="mono" style={{ color: T.cyan }}>v{status.version}</span>} is installed but the service is not running.
                </div>
                <div style={{ display: 'flex', gap: 12 }}>
                  <button onClick={handleManualStart} disabled={starting}
                    style={{
                      padding: '10px 24px', background: starting ? T.bg3 : T.cyan,
                      color: starting ? T.muted : T.bg0, border: 'none',
                      fontSize: 13, fontWeight: 700, cursor: starting ? 'not-allowed' : 'pointer',
                    }}>
                    {starting ? 'STARTING…' : 'START OLLAMA'}
                  </button>
                  <button onClick={async () => { const d = await check(); if (d?.running) onNav('onboarding-step3'); }}
                    style={{ padding: '10px 24px', background: 'none', border: `1px solid ${T.border}`, color: T.text, fontSize: 13, cursor: 'pointer' }}>
                    Check again
                  </button>
                </div>
              </div>
              {error && (
                <div style={{ padding: '10px 14px', background: T.bg1, border: `1px solid ${T.red}`, color: T.red, fontSize: 12 }}>
                  {error}
                </div>
              )}
            </>
          ) : isLinux && preview?.supported ? (
            // ── Linux fresh install — automated path ──
            <>
              <h1 style={{ fontSize: 32, fontWeight: 800, color: T.text, margin: '0 0 8px', letterSpacing: '-0.02em' }}>
                Install Ollama automatically
              </h1>
              <p style={{ fontSize: 14, color: T.muted, margin: '0 0 24px', lineHeight: 1.6 }}>
                dialekt can fetch and run Ollama's official install script for you. The script's SHA-256 hash is verified before execution. You can review it below.
              </p>

              {/* Script info card */}
              <div style={{ background: T.bg1, border: `1px solid ${T.border}`, padding: 22, marginBottom: 18 }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16 }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: T.text, marginBottom: 6 }}>
                      Install script
                    </div>
                    <div className="mono" style={{ fontSize: 11, color: T.muted, marginBottom: 10, wordBreak: 'break-all' }}>
                      {preview.command || `curl -fsSL https://ollama.com/install.sh | sh`}
                    </div>
                    <div style={{ display: 'flex', gap: 16, fontSize: 11, color: T.dim }}>
                      <span><span className="mono" style={{ color: T.cyan }}>SHA-256</span> {preview.sha256?.slice(0, 16)}…</span>
                      <span><span className="mono" style={{ color: T.cyan }}>SIZE</span> {preview.size_bytes ? `${(preview.size_bytes / 1024).toFixed(1)} KB` : '?'}</span>
                      {preview.matches_pin === true && (
                        <span style={{ color: T.green }}>✓ matches pinned hash</span>
                      )}
                      {preview.matches_pin === false && (
                        <span style={{ color: T.amber }}>⚠ hash differs from pinned</span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Collapsible script preview */}
                <details style={{ marginTop: 16, fontSize: 11 }}>
                  <summary style={{ cursor: 'pointer', color: T.cyan, fontFamily: T.mono, fontSize: 11, letterSpacing: '.06em' }}>
                    Show first 2 KB of script ↓
                  </summary>
                  <pre style={{
                    marginTop: 10, padding: 12, background: T.bg0,
                    fontFamily: T.mono, fontSize: 10, color: T.muted,
                    maxHeight: 200, overflowY: 'auto', whiteSpace: 'pre-wrap',
                  }}>{preview.preview}</pre>
                </details>
              </div>

              {/* Consent + button */}
              <div style={{ background: T.bg1, border: `1px solid ${T.border}`, padding: 18, marginBottom: 16 }}>
                <label style={{ display: 'flex', gap: 12, alignItems: 'flex-start', cursor: 'pointer' }}>
                  <input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)}
                    style={{ marginTop: 3, accentColor: T.cyan }} />
                  <div style={{ fontSize: 12, color: T.muted, lineHeight: 1.55 }}>
                    I understand this will execute the script above on my machine. The script may request <span style={{ color: T.text }}>sudo</span> for systemd registration. dialekt will stream the output live and stop on first error.
                  </div>
                </label>
              </div>

              <div style={{ display: 'flex', gap: 12 }}>
                <button onClick={startAutoInstall} disabled={!consent || !canAutoInstall}
                  style={{
                    padding: '11px 28px',
                    background: (consent && canAutoInstall) ? T.cyan : T.bg3,
                    color: (consent && canAutoInstall) ? T.bg0 : T.dim,
                    border: 'none', fontSize: 13, fontWeight: 700,
                    cursor: (consent && canAutoInstall) ? 'pointer' : 'not-allowed',
                    letterSpacing: '.06em',
                  }}>
                  INSTALL AUTOMATICALLY
                </button>
                <a href={installUrl} target="_blank" rel="noreferrer" onClick={() => setPolling(true)}
                  style={{
                    padding: '11px 22px', background: 'none', border: `1px solid ${T.border}`,
                    color: T.muted, fontSize: 12, textDecoration: 'none',
                    display: 'inline-flex', alignItems: 'center',
                  }}>
                  Or download manually →
                </a>
              </div>

              {polling && (
                <div style={{ color: T.cyan, fontSize: 12, marginTop: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span className="dlk-dot cyan live" />
                  Waiting for Ollama to appear (manual install)…
                </div>
              )}
            </>
          ) : (
            // ── Mac/Windows / Linux without preview — manual path ──
            <>
              <h1 style={{ fontSize: 32, fontWeight: 800, color: T.text, margin: '0 0 8px', letterSpacing: '-0.02em' }}>
                Install Ollama
              </h1>
              <p style={{ fontSize: 14, color: T.muted, margin: '0 0 32px', lineHeight: 1.6 }}>
                dialekt uses Ollama to run AI models locally on your machine. No data leaves your computer.
              </p>

              <div style={{ background: T.bg1, border: `1px solid ${T.border}`, padding: 28, marginBottom: 18 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: T.text, marginBottom: 16 }}>
                  Download Ollama for {platformLabel}
                </div>
                <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                  <a href={installUrl} target="_blank" rel="noreferrer"
                    onClick={() => setPolling(true)}
                    style={{
                      display: 'inline-block', padding: '10px 24px',
                      background: T.cyan, color: T.bg0, fontSize: 13, fontWeight: 700,
                      textDecoration: 'none', letterSpacing: '.06em',
                    }}>
                    DOWNLOAD OLLAMA →
                  </a>
                  <button onClick={async () => { const d = await check(); if (d?.installed && d?.running) onNav('onboarding-step3'); }}
                    style={{ padding: '10px 24px', background: 'none', border: `1px solid ${T.border}`, color: T.text, fontSize: 13, cursor: 'pointer' }}>
                    Check again
                  </button>
                </div>
                <div style={{ marginTop: 24, fontSize: 12, color: T.dim, lineHeight: 1.7 }}>
                  <div style={{ marginBottom: 4, fontWeight: 600, color: T.muted }}>After downloading:</div>
                  <div className="mono" style={{ background: T.bg2, padding: '12px 16px', fontSize: 12, color: T.text, whiteSpace: 'pre-line' }}>
                    {platform === 'darwin' && '1. Open the .dmg and drag Ollama to Applications\n2. Launch Ollama from Applications or Spotlight'}
                    {platform === 'linux' && '1. Run: curl -fsSL https://ollama.com/install.sh | sh\n2. Ollama starts automatically as a service'}
                    {platform === 'windows' && '1. Run the OllamaSetup.exe installer\n2. Ollama starts automatically on login'}
                  </div>
                </div>
              </div>

              {polling && (
                <div style={{ color: T.cyan, fontSize: 13, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span className="dlk-dot cyan live" />
                  Waiting for Ollama to start… (checking every 3 seconds)
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </AppFrame>
  );
}
