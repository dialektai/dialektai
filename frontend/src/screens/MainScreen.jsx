import { useEffect, useRef, useState } from 'react';
import { AppFrame } from '../components/Shell.jsx';
import LeftPanel from '../components/LeftPanel.jsx';
import ChatColumn from '../components/ChatColumn.jsx';
import RightPanel from '../components/RightPanel.jsx';
import { useChat } from '../hooks/useChat.js';

export default function MainScreen({ onNav, initialMessage, sessionId: initSessionId }) {
  const {
    messages, streaming, connected, ollamaOnline,
    sessionId, sessionTitle, models, activeModel, autonomy,
    send, stop, newSession, switchSession, switchModel, setAutonomyLevel, fetchSessions, confirm,
  } = useChat();

  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [localTitle, setLocalTitle] = useState(null);
  const [selectedAgentId, setSelectedAgentId] = useState(null);
  const didInit = useRef(false);

  const handleSend = (text) => send(text, selectedAgentId);

  const displayTitle = localTitle || sessionTitle;

  useEffect(() => {
    if (!connected || didInit.current) return;
    didInit.current = true;
    if (initialMessage) send(initialMessage);
    else if (initSessionId) switchSession(initSessionId);
  }, [connected]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setLocalTitle(null);
  }, [sessionId]);

  useEffect(() => {
    if (!ollamaOnline) onNav?.('offline');
  }, [ollamaOnline, onNav]);

  const handleNewSession = () => {
    newSession();
    onNav?.('empty');
  };

  const handleTitleChange = (title) => {
    setLocalTitle(title);
    fetchSessions();
  };

  return (
    <AppFrame title={displayTitle ? `dialekt.ai — ${displayTitle}` : 'dialekt.ai'} ollamaOnline={ollamaOnline}>
      <LeftPanel
        onNav={onNav}
        currentSessionId={sessionId}
        model={activeModel}
        models={models}
        running={connected}
        onSessionSwitch={switchSession}
        onNewSession={handleNewSession}
        onModelSwitch={switchModel}
        selectedAgentId={selectedAgentId}
        onAgentSelect={setSelectedAgentId}
      />
      <ChatColumn
        messages={messages}
        streaming={streaming}
        connected={connected}
        sessionTitle={displayTitle}
        sessionId={sessionId}
        autonomy={autonomy}
        activeModel={activeModel}
        onSend={handleSend}
        onStop={stop}
        onNewSession={handleNewSession}
        onSessionTitleChange={handleTitleChange}
        onAutonomyChange={setAutonomyLevel}
        onConfirm={confirm}
      />
      <RightPanel
        messages={messages}
        streaming={streaming}
        collapsed={rightCollapsed}
        onToggle={() => setRightCollapsed(c => !c)}
      />
    </AppFrame>
  );
}
