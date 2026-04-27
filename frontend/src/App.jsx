import { useState, useEffect } from 'react';
import { T } from './tokens.js';
import MainScreen from './screens/MainScreen.jsx';
import SettingsScreen from './screens/SettingsScreen.jsx';
import OnboardingScreen from './screens/OnboardingScreen.jsx';
import DownloadScreen from './screens/DownloadScreen.jsx';
import EmptyChatScreen from './screens/EmptyChatScreen.jsx';
import CommandPaletteScreen from './screens/CommandPaletteScreen.jsx';
import OfflineScreen from './screens/OfflineScreen.jsx';
import OnboardingPermsScreen from './screens/OnboardingPermsScreen.jsx';
import OnboardingIndexScreen from './screens/OnboardingIndexScreen.jsx';
import OnboardingFirstChatScreen from './screens/OnboardingFirstChatScreen.jsx';
import ModeSetupScreen from './screens/ModeSetupScreen.jsx';
import AgentWizardScreen from './screens/AgentWizardScreen.jsx';
import OllamaInstallScreen from './screens/OllamaInstallScreen.jsx';
import LicenseScreen from './screens/LicenseScreen.jsx';
import InviteRedemptionScreen from './screens/InviteRedemptionScreen.jsx';
import AdminDashboardScreen from './screens/AdminDashboardScreen.jsx';
import LibraryScreen from './screens/LibraryScreen.jsx';

const API = 'http://localhost:8765';

// ── Backend boot gate ──────────────────────────────────────────────────────
// PyInstaller-frozen Python sidecar takes 5-20s to boot (cold start +
// FastAPI startup + SQLite migrations). Until /health responds, fetches
// from screens silently fail and components like the onboarding model
// picker render with empty data — the Continue button stays disabled
// because the catalog never loaded. Gate the whole app on /health so
// nothing renders until the sidecar is reachable.
function BackendBootGate({ children }) {
  const [ready, setReady] = useState(false);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    let timer = null;
    const start = Date.now();
    const poll = async () => {
      try {
        const ctrl = new AbortController();
        const t = setTimeout(() => ctrl.abort(), 2000);
        const r = await fetch(`${API}/health`, { signal: ctrl.signal });
        clearTimeout(t);
        if (r.ok && !cancelled) { setReady(true); return; }
      } catch { /* keep polling */ }
      if (cancelled) return;
      const now = Date.now() - start;
      setElapsedMs(now);
      if (now > 60_000) { setError('Backend did not start within 60 seconds.'); return; }
      timer = setTimeout(poll, 500);
    };
    poll();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, []);

  if (ready) return children;

  // First 1.5s show nothing — most boots finish before the user notices.
  // After that, surface the loading state so the window doesn't look frozen.
  if (!error && elapsedMs < 1500) {
    return <div style={{ width: '100%', height: '100%', background: '#0a0d12' }} />;
  }

  const hint =
    error                  ? error :
    elapsedMs < 5000       ? 'Starting local agent…' :
    elapsedMs < 12000      ? 'Loading models…' :
    elapsedMs < 25000      ? 'Running first-launch migrations…' :
                             'Still working — first launch can take a while.';

  return (
    <div style={{
      width: '100%', height: '100%', background: '#0a0d12',
      display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 22,
    }}>
      <div style={{
        width: 56, height: 56, borderRadius: '50%',
        border: '1px solid #1f2a37',
        background: 'radial-gradient(circle at 50% 40%, #38bdf8 0%, #0a0d12 70%)',
        boxShadow: '0 0 30px rgba(56,189,248,0.25)',
        animation: error ? 'none' : 'dlk-boot-pulse 1.6s ease-in-out infinite',
      }} />
      <div style={{
        fontFamily: 'ui-monospace, SF Mono, Consolas, monospace',
        fontSize: 11, color: '#94a3b8', letterSpacing: '.14em', textTransform: 'uppercase',
      }}>
        DIALEKT · LOCAL AGENT
      </div>
      <div style={{ fontSize: 13, color: error ? '#f87171' : '#cbd5e1', maxWidth: 360, textAlign: 'center', lineHeight: 1.5 }}>
        {hint}
      </div>
      <div style={{ fontFamily: 'ui-monospace, monospace', fontSize: 10, color: '#475569', letterSpacing: '.08em' }}>
        {error ? 'CHECK ~/.dialekt/server.log' : `${(elapsedMs / 1000).toFixed(1)}s`}
      </div>
      {error && (
        <button
          onClick={() => location.reload()}
          style={{
            marginTop: 4, padding: '8px 18px', background: 'transparent',
            border: '1px solid #38bdf8', color: '#38bdf8',
            fontFamily: 'ui-monospace, monospace', fontSize: 11, letterSpacing: '.12em',
            cursor: 'pointer',
          }}>RETRY</button>
      )}
      <style>{`@keyframes dlk-boot-pulse { 0%,100% { opacity: .55; transform: scale(.94); } 50% { opacity: 1; transform: scale(1); } }`}</style>
    </div>
  );
}

export default function App() {
  return (
    <BackendBootGate>
      <AppRoutes />
    </BackendBootGate>
  );
}

function AppRoutes() {
  // null until first-launch routing resolves — prevents MainScreen
  // (chat) from flashing for a frame before /settings comes back and
  // we redirect to license / mode-setup / onboarding.
  const [screen, setScreen] = useState(null);
  const [screenProps, setScreenProps] = useState({});

  const nav = (s, props = {}) => {
    setScreen(s);
    setScreenProps(props);
  };

  // Auto-start Ollama on every launch if installed but not yet running.
  // BackendBootGate already confirmed the sidecar is up, so this is safe.
  useEffect(() => {
    fetch(`${API}/ollama/check`)
      .then(r => r.json())
      .then(d => { if (d.installed && !d.running) fetch(`${API}/ollama/start`, { method: 'POST' }).catch(() => {}); })
      .catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // First-launch detection: run the onboarding flow if not completed
  useEffect(() => {
    (async () => {
      try {
        const s = await fetch(`${API}/settings`).then(r => r.json());

        // License gate runs UNCONDITIONALLY — even if a previous session
        // marked onboarding_completed, a missing license must still route
        // to the LicenseScreen. Pilots with corrupted/preseeded settings
        // (no key + onboarding_completed=true) used to fall through to
        // MainScreen → OfflineScreen and have no way to reach the
        // license entry surface.
        const hasLicense = !!s.license_key || !!s.trial_started;
        if (!hasLicense) {
          nav('license');
          return;
        }

        // Already completed onboarding past the license gate — done.
        if (s.onboarding_completed) { nav('main'); return; }

        // Mode not set → show mode selection
        if (!('mode' in s)) {
          nav('mode-setup');
          return;
        }

        // Mode set but Ollama not checked yet → check Ollama
        nav('onboarding-ollama');
      } catch {
        // backend offline — fall back to main; OfflineScreen surfaces
        // diagnostics from there.
        nav('main');
      }
    })();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Keyboard shortcuts
  useEffect(() => {
    const onKey = (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key === 'k') { e.preventDefault(); nav('palette'); }
      if (mod && e.key === 'n') { e.preventDefault(); nav('empty'); }
      if (mod && e.key === ',') { e.preventDefault(); nav('settings'); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Routing not resolved yet — keep the boot-gate background visible
  // instead of flashing MainScreen.
  if (screen === null) {
    return <div style={{ width: '100%', height: '100%', background: '#0a0d12' }} />;
  }

  return (
    <div style={{ width: '100%', height: '100%' }}>
      {screen === 'main'               && <MainScreen onNav={nav} {...screenProps} />}
      {screen === 'settings'           && <SettingsScreen onNav={nav} {...screenProps} />}
      {screen === 'onboarding'         && <OnboardingScreen onNav={nav} />}
      {screen === 'download'           && <DownloadScreen onNav={nav} {...screenProps} />}
      {screen === 'empty'              && <EmptyChatScreen onNav={nav} />}
      {screen === 'palette'            && <CommandPaletteScreen onNav={nav} />}
      {screen === 'offline'            && <OfflineScreen onNav={nav} />}
      {screen === 'onboarding-step3'   && <OnboardingScreen onNav={nav} />}
      {screen === 'onboarding-step4'   && <OnboardingPermsScreen onNav={nav} onComplete={async () => {
          // Mark onboarding complete (fire-and-forget — don't block nav)
          fetch(`${API}/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ onboarding_completed: true }),
          }).catch(() => {});
          // User mode → first chat; builder mode → main. Await so the
          // child can keep its loading state on while we resolve the mode.
          try {
            const d = await fetch(`${API}/config/mode`).then(r => r.json());
            nav(d.mode === 'user' ? 'onboarding-step5' : 'main');
          } catch {
            nav('main');
          }
        }} />}
      {screen === 'onboarding-step5'   && <OnboardingFirstChatScreen onNav={nav} />}
      {screen === 'mode-setup'         && <ModeSetupScreen onNav={nav} />}
      {screen === 'wizard'             && <AgentWizardScreen onNav={nav} />}
      {screen === 'license'            && <LicenseScreen onNav={nav} />}
      {screen === 'invite'             && <InviteRedemptionScreen onNav={nav} />}
      {screen === 'admin'              && <AdminDashboardScreen onNav={nav} />}
      {screen === 'library'            && <LibraryScreen onNav={nav} />}

      {/* Ollama install guidance */}
      {screen === 'onboarding-install-ollama' && <OllamaInstallScreen onNav={nav} checkInfo={screenProps} />}
      {/* Ollama detection step: check Ollama, route to install or model download */}
      {screen === 'onboarding-ollama'  && <OllamaGateway onNav={nav} />}
    </div>
  );
}

/**
 * Transient gate: checks Ollama, routes to OllamaInstallScreen or model download.
 * Not a full screen — renders nothing visible, just redirects.
 */
function OllamaGateway({ onNav }) {
  useEffect(() => {
    fetch(`${API}/ollama/check`)
      .then(r => r.json())
      .then(d => {
        if (d.installed && d.running) {
          // Ollama ready — go straight to model download step
          onNav('onboarding-step3');
        } else {
          // Need to install or start Ollama
          onNav('onboarding-install-ollama', d);
        }
      })
      .catch(() => {
        // backend offline — skip to main
        onNav('main');
      });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div style={{ width: '100%', height: '100%', background: T.bg0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ fontFamily: T.mono, fontSize: 12, color: T.dim, letterSpacing: '.1em' }}>CHECKING OLLAMA…</div>
    </div>
  );
}
