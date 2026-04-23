import { useEffect, useRef, useState } from 'react';
import { AppFrame } from '../components/Shell.jsx';
import LeftPanel from '../components/LeftPanel.jsx';
import ChatColumn from '../components/ChatColumn.jsx';
import RightPanel from '../components/RightPanel.jsx';
import { useChat } from '../hooks/useChat.js';

const API = 'http://localhost:8765';

// Extract required connection types from a manifest YAML. Matches the
// server-side parsing — light regex instead of a YAML library.
function parseRequiredConnTypes(manifestYaml) {
  if (!manifestYaml) return [];
  const connIdx = manifestYaml.indexOf('connections:');
  if (connIdx < 0) return [];
  const tail = manifestYaml.slice(connIdx);
  const nextTopLevel = tail.search(/\n[a-z_][\w]*:/);
  const block = nextTopLevel > 0 ? tail.slice(0, nextTopLevel) : tail;
  const re = /^\s*-?\s*type:\s*["']?([a-zA-Z_][\w-]*)["']?\s*$/gm;
  const types = new Set();
  let m;
  while ((m = re.exec(block)) !== null) {
    const t = m[1].toLowerCase();
    types.add(t === 'postgresql' || t === 'pg' ? 'postgres' : t);
  }
  return Array.from(types);
}

export default function MainScreen({ onNav, initialMessage, sessionId: initSessionId }) {
  const {
    messages, streaming, connected, ollamaOnline,
    sessionId, sessionTitle, models, activeModel, autonomy,
    send, stop, newSession, switchSession, switchModel, setAutonomyLevel, fetchSessions, confirm,
  } = useChat();

  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [localTitle, setLocalTitle] = useState(null);
  const [selectedAgentId, setSelectedAgentId] = useState(null);
  const [agentDetails, setAgentDetails] = useState(null); // {id, name, requiredTypes}
  const [hasBinding, setHasBinding] = useState(null); // null=unknown, true/false when checked
  const didInit = useRef(false);

  // Whenever the user picks a different agent, refresh its manifest
  // summary + current binding. This drives the empty-state nudge.
  useEffect(() => {
    if (!selectedAgentId) {
      setAgentDetails(null);
      setHasBinding(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const [a, b] = await Promise.all([
          fetch(`${API}/agents/${selectedAgentId}`).then(r => r.ok ? r.json() : null),
          fetch(`${API}/agents/${selectedAgentId}/binding`).then(r => r.ok ? r.json() : null),
        ]);
        if (cancelled) return;
        if (!a) { setAgentDetails(null); setHasBinding(null); return; }
        setAgentDetails({
          id: a.id,
          name: a.name,
          requiredTypes: parseRequiredConnTypes(a.manifest_yaml),
        });
        setHasBinding(!!(b && b.connection_id));
      } catch {
        if (!cancelled) { setAgentDetails(null); setHasBinding(null); }
      }
    })();
    return () => { cancelled = true; };
  }, [selectedAgentId]);

  const missingBinding =
    !!agentDetails &&
    agentDetails.requiredTypes.length > 0 &&
    hasBinding === false;

  const handleSend = (text) => {
    if (missingBinding) return; // disabled path; guard anyway
    send(text, selectedAgentId);
  };

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
        bindingNotice={missingBinding ? {
          agentName: agentDetails.name,
          requiredTypes: agentDetails.requiredTypes,
          onPickConnection: () => onNav?.('settings', { initialSection: 'Agents', focusAgentId: selectedAgentId }),
          onAddConnection: () => onNav?.('settings', { initialSection: 'Connections' }),
        } : null}
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
