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

export default function App() {
  const [screen, setScreen] = useState('main');
  const [screenProps, setScreenProps] = useState({});

  const nav = (s, props = {}) => {
    setScreen(s);
    setScreenProps(props);
  };

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
      {screen === 'download'           && <DownloadScreen onNav={nav} />}
      {screen === 'empty'              && <EmptyChatScreen onNav={nav} />}
      {screen === 'palette'            && <CommandPaletteScreen onNav={nav} />}
      {screen === 'offline'            && <OfflineScreen onNav={nav} />}
      {screen === 'onboarding-step3'   && <OnboardingPermsScreen onNav={nav} />}
      {screen === 'onboarding-step4'   && <OnboardingIndexScreen onNav={nav} />}
      {screen === 'onboarding-step5'   && <OnboardingFirstChatScreen onNav={nav} />}
    </div>
  );
}
