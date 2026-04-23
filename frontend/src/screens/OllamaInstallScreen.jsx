import { useState, useEffect, useCallback } from 'react';
import { T } from '../tokens.js';
import { AppFrame, Logo } from '../components/Shell.jsx';

const API = 'http://localhost:8765';

function Step({ n, label, done }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0' }}>
      <div style={{
        width: 24, height: 24, borderRadius: '50%', flexShrink: 0,
        background: done ? T.green : T.bg3,
        border: `1px solid ${done ? T.green : T.border}`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 11, fontWeight: 700,
        color: done ? T.bg0 : T.dim,
      }}>{done ? '✓' : n}</div>
      <span style={{ fontSize: 13, color: done ? T.green : T.muted }}>{label}</span>
    </div>
  );
}

export default function OllamaInstallScreen({ onNav, checkInfo }) {
  const [status, setStatus] = useState(checkInfo || null);
  const [polling, setPolling] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState(null);

  const check = useCallback(async () => {
    try {
      const r = await fetch(`${API}/ollama/check`);
      const d = await r.json();
      setStatus(d);
      return d;
    } catch {
      return null;
    }
  }, []);

  // poll every 3s while waiting for user to install
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

  // re-check on window focus (user may have installed Ollama in browser)
  useEffect(() => {
    const onFocus = async () => {
      const d = await check();
      if (d?.installed && d?.running) onNav('onboarding-step3');
    };
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [check, onNav]);

  const handleStart = async () => {
    setStarting(true);
    setError(null);
    try {
      await fetch(`${API}/ollama/start`, { method: 'POST' });
      await new Promise(r => setTimeout(r, 2000));
      const d = await check();
      if (d?.running) {
        onNav('onboarding-step3');
      } else {
        setError('Ollama started but not responding yet. Please wait a moment and click "Check again".');
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setStarting(false);
    }
  };

  const installed = status?.installed;
  const running = status?.running;
  const platform = status?.platform || 'darwin';
  const installUrl = status?.install_url || 'https://ollama.com/download/Mac';

  const platformLabel = { darwin: 'Mac', linux: 'Linux', windows: 'Windows' }[platform] || 'Mac';

  return (
    <AppFrame title="dialekt.ai — Setup">
      <div style={{ flex: 1, display: 'flex', background: T.bg0, minWidth: 0 }}>
        {/* Sidebar */}
        <div style={{ width: 280, background: T.bg1, borderRight: `1px solid ${T.border}`, padding: '40px 32px', display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 48 }}>
            <Logo />
            <div>
              <div style={{ fontSize: 15, fontWeight: 700 }}>dialekt<span style={{ color: T.cyan }}>.ai</span></div>
              <div className="mono" style={{ fontSize: 10, color: T.dim, letterSpacing: '.1em' }}>SETUP · STEP 2/5</div>
            </div>
          </div>

          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.12em', color: T.dim, marginBottom: 16 }}>SETUP PROGRESS</div>
          <Step n="1" label="Choose mode" done />
          <Step n="2" label="Install Ollama" done={false} />
          <Step n="3" label="Download models" done={false} />
          <Step n="4" label="Permissions" done={false} />
          <Step n="5" label="First chat" done={false} />

          <div style={{ flex: 1 }} />
          <button
            onClick={() => onNav('main')}
            style={{ background: 'none', border: `1px solid ${T.border}`, color: T.dim, padding: '8px 16px', fontSize: 11, cursor: 'pointer', letterSpacing: '.08em' }}
          >SKIP SETUP</button>
        </div>

        {/* Main */}
        <div style={{ flex: 1, padding: '60px 80px', overflowY: 'auto' }}>
          <div className="mono" style={{ fontSize: 10, color: T.cyan, letterSpacing: '.14em', marginBottom: 12 }}>STEP 2 OF 5</div>
          <h1 style={{ fontSize: 32, fontWeight: 800, color: T.text, margin: '0 0 8px', letterSpacing: '-0.02em' }}>
            {installed ? 'Start Ollama' : 'Install Ollama'}
          </h1>
          <p style={{ fontSize: 14, color: T.muted, margin: '0 0 48px', lineHeight: 1.6 }}>
            {installed
              ? 'Ollama is installed but not running. Start it to continue.'
              : 'dialekt uses Ollama to run AI models locally on your machine. No data leaves your computer.'}
          </p>

          {!installed && (
            <>
              <div style={{ background: T.bg1, border: `1px solid ${T.border}`, padding: 28, marginBottom: 32 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: T.text, marginBottom: 16 }}>
                  Download Ollama for {platformLabel}
                </div>
                <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                  <a
                    href={installUrl}
                    target="_blank"
                    rel="noreferrer"
                    style={{
                      display: 'inline-block', padding: '10px 24px',
                      background: T.cyan, color: T.bg0, fontSize: 13, fontWeight: 700,
                      textDecoration: 'none', letterSpacing: '.06em',
                    }}
                    onClick={() => setPolling(true)}
                  >
                    DOWNLOAD OLLAMA →
                  </a>
                  <button
                    onClick={async () => { const d = await check(); if (d?.installed && d?.running) onNav('onboarding-step3'); }}
                    style={{ padding: '10px 24px', background: 'none', border: `1px solid ${T.border}`, color: T.text, fontSize: 13, cursor: 'pointer' }}
                  >
                    Check again
                  </button>
                </div>

                <div style={{ marginTop: 24, fontSize: 12, color: T.dim, lineHeight: 1.7 }}>
                  <div style={{ marginBottom: 4, fontWeight: 600, color: T.muted }}>After downloading:</div>
                  <div className="mono" style={{ background: T.bg2, padding: '12px 16px', fontSize: 12, color: T.text }}>
                    {platform === 'darwin' && '1. Open the .dmg and drag Ollama to Applications\n2. Launch Ollama from Applications or Spotlight'}
                    {platform === 'linux' && '1. Run: curl -fsSL https://ollama.com/install.sh | sh\n2. Ollama starts automatically as a service'}
                    {platform === 'windows' && '1. Run the OllamaSetup.exe installer\n2. Ollama starts automatically on login'}
                  </div>
                </div>
              </div>

              {polling && (
                <div style={{ color: T.cyan, fontSize: 13, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span className="mono" style={{ fontSize: 11 }}>⟳</span>
                  Waiting for Ollama to start… (checking every 3 seconds)
                </div>
              )}
            </>
          )}

          {installed && !running && (
            <div style={{ background: T.bg1, border: `1px solid ${T.border}`, padding: 28 }}>
              <div style={{ fontSize: 13, color: T.text, marginBottom: 20 }}>
                Ollama {status?.version && <span className="mono" style={{ color: T.cyan }}>v{status.version}</span>} is installed but not running.
              </div>
              <div style={{ display: 'flex', gap: 12 }}>
                <button
                  onClick={handleStart}
                  disabled={starting}
                  style={{
                    padding: '10px 24px', background: starting ? T.bg3 : T.cyan,
                    color: starting ? T.muted : T.bg0, border: 'none',
                    fontSize: 13, fontWeight: 700, cursor: starting ? 'not-allowed' : 'pointer',
                  }}
                >
                  {starting ? 'STARTING…' : 'START OLLAMA'}
                </button>
                <button
                  onClick={async () => { const d = await check(); if (d?.running) onNav('onboarding-step3'); }}
                  style={{ padding: '10px 24px', background: 'none', border: `1px solid ${T.border}`, color: T.text, fontSize: 13, cursor: 'pointer' }}
                >
                  Check again
                </button>
              </div>
            </div>
          )}

          {installed && running && (
            <div style={{ background: T.bg1, border: `1px solid ${T.green}`, padding: 28 }}>
              <div style={{ color: T.green, fontWeight: 700, fontSize: 14, marginBottom: 8 }}>✓ Ollama is running</div>
              <div style={{ color: T.muted, fontSize: 13, marginBottom: 20 }}>Version: {status?.version || 'unknown'}</div>
              <button
                onClick={() => onNav('onboarding-step3')}
                style={{ padding: '10px 24px', background: T.cyan, color: T.bg0, border: 'none', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}
              >
                CONTINUE →
              </button>
            </div>
          )}

          {error && (
            <div style={{ marginTop: 16, padding: '12px 16px', background: T.bg1, border: `1px solid ${T.red}`, color: T.red, fontSize: 12 }}>
              {error}
            </div>
          )}
        </div>
      </div>
    </AppFrame>
  );
}
