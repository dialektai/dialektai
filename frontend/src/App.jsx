import { useState, useEffect } from 'react';
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

const API = 'http://localhost:8765';

export default function App() {
  const [screen, setScreen] = useState('main');
  const [screenProps, setScreenProps] = useState({});

  const nav = (s, props = {}) => {
    setScreen(s);
    setScreenProps(props);
  };

  // First-launch detection: run the onboarding flow if not completed
  useEffect(() => {
    (async () => {
      try {
        const s = await fetch(`${API}/settings`).then(r => r.json());

        // Already completed onboarding — do nothing
        if (s.onboarding_completed) return;

        // Check license first (Builder mode flow)
        // Trial or license accepted → proceed; no license → show LicenseScreen
        const hasLicense = !!s.license_key || !!s.trial_started;
        if (!hasLicense) {
          nav('license');
          return;
        }

        // Mode not set → show mode selection
        if (!('mode' in s)) {
          nav('mode-setup');
          return;
        }

        // Mode set but Ollama not checked yet → check Ollama
        nav('onboarding-ollama');
      } catch {
        // backend offline — stay on main
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

  return (
    <div style={{ width: '100%', height: '100%' }}>
      {screen === 'main'               && <MainScreen onNav={nav} {...screenProps} />}
      {screen === 'settings'           && <SettingsScreen onNav={nav} />}
      {screen === 'onboarding'         && <OnboardingScreen onNav={nav} />}
      {screen === 'download'           && <DownloadScreen onNav={nav} {...screenProps} />}
      {screen === 'empty'              && <EmptyChatScreen onNav={nav} />}
      {screen === 'palette'            && <CommandPaletteScreen onNav={nav} />}
      {screen === 'offline'            && <OfflineScreen onNav={nav} />}
      {screen === 'onboarding-step3'   && <OnboardingScreen onNav={nav} />}
      {screen === 'onboarding-step4'   && <OnboardingPermsScreen onNav={nav} onComplete={() => {
          // Mark onboarding complete
          fetch(`${API}/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ onboarding_completed: true }),
          }).catch(() => {});
          // User mode → first chat; builder mode → main
          fetch(`${API}/config/mode`).then(r => r.json()).then(d => {
            nav(d.mode === 'user' ? 'onboarding-step5' : 'main');
          }).catch(() => nav('main'));
        }} />}
      {screen === 'onboarding-step5'   && <OnboardingFirstChatScreen onNav={nav} />}
      {screen === 'mode-setup'         && <ModeSetupScreen onNav={nav} />}
      {screen === 'wizard'             && <AgentWizardScreen onNav={nav} />}
      {screen === 'license'            && <LicenseScreen onNav={nav} />}
      {screen === 'invite'             && <InviteRedemptionScreen onNav={nav} />}
      {screen === 'admin'              && <AdminDashboardScreen onNav={nav} />}

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
    <div style={{ width: '100%', height: '100%', background: '#0a0d12', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ fontFamily: 'monospace', fontSize: 12, color: '#64748b', letterSpacing: '.1em' }}>CHECKING OLLAMA…</div>
    </div>
  );
}
