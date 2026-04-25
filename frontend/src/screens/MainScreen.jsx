import { useEffect, useRef, useState } from 'react';
import { AppFrame } from '../components/Shell.jsx';
import LeftPanel from '../components/LeftPanel.jsx';
import ChatColumn from '../components/ChatColumn.jsx';
import RightPanel from '../components/RightPanel.jsx';
import ConsentModal from '../components/ConsentModal.jsx';
import { useChat } from '../hooks/useChat.js';
import { T } from '../tokens.js';

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
    consentQueue, respondConsent, ackConsentTimeout,
    mcpSetupErrors, dismissMcpSetupError,
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
      <ConsentModal
        request={consentQueue[0] || null}
        queueLength={consentQueue.length}
        onApprove={() => respondConsent('approved')}
        onApproveSession={() => respondConsent('approved_session')}
        onApproveAll={() => respondConsent('approved_all')}
        onDeny={() => respondConsent('denied')}
        onTimeoutAck={ackConsentTimeout}
      />
      {mcpSetupErrors.length > 0 && (
        <div style={{
          position: 'fixed', top: 16, left: '50%', transform: 'translateX(-50%)',
          zIndex: 9998, display: 'flex', flexDirection: 'column', gap: 6,
          maxWidth: 'min(640px, calc(100vw - 32px))',
        }}>
          {mcpSetupErrors.map((err, i) => (
            <div key={i} style={{
              padding: '8px 12px', background: T.bg2,
              border: `1px solid ${T.amber}88`,
              display: 'flex', alignItems: 'center', gap: 10,
              boxShadow: '0 4px 16px rgba(0,0,0,0.5)',
            }}>
              <span className="mono" style={{ fontSize: 10, color: T.amber, letterSpacing: '.08em' }}>⚠ MCP SETUP</span>
              <span style={{ fontSize: 11, color: T.muted, flex: 1 }}>{err}</span>
              <button onClick={() => dismissMcpSetupError(i)} style={{
                background: 'transparent', border: 'none', color: T.dim,
                fontSize: 14, cursor: 'pointer', padding: '0 4px',
              }} aria-label="dismiss">×</button>
            </div>
          ))}
        </div>
      )}
      <RightPanel
        messages={messages}
        streaming={streaming}
        collapsed={rightCollapsed}
        onToggle={() => setRightCollapsed(c => !c)}
      />
    </AppFrame>
  );
}
