import { useState, useRef, useCallback, useEffect } from 'react';

const WS_URL = 'ws://localhost:8765/ws';
const API_URL = 'http://localhost:8765';

export function useChat() {
  const [messages, setMessages] = useState([]);
  const [streaming, setStreaming] = useState(false);
  const [connected, setConnected] = useState(false);
  const [ollamaOnline, setOllamaOnline] = useState(true);
  const [sessionId, setSessionId] = useState(null);
  const [sessionTitle, setSessionTitle] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [models, setModels] = useState([]);
  const [activeModel, setActiveModel] = useState('gemma3-12b');
  const [autonomy, setAutonomy] = useState('ask-write');
  const [consentQueue, setConsentQueue] = useState([]);     // pending mcp_consent_request payloads
  const [mcpSetupErrors, setMcpSetupErrors] = useState([]); // soft-fail messages from join

  const wsRef = useRef(null);
  const streamingMsgRef = useRef(null);
  const sessionIdRef = useRef(null);  // sync ref for use inside WS callbacks
  // Debounce ollamaOnline flips: a single failed /health (transient
  // sidecar latency, Ollama loading a model, macOS WebKit jitter) used
  // to flip the indicator and trigger a MainScreen→OfflineScreen→empty
  // bounce loop. Require 2 consecutive misses before going offline; any
  // success resets the counter and flips back to online immediately.
  const healthFailRef = useRef(0);

  // Keep ref in sync
  useEffect(() => { sessionIdRef.current = sessionId; }, [sessionId]);

  // ── REST helpers ──────────────────────────────────────────────────

  const fetchSessions = useCallback(async () => {
    try {
      const r = await fetch(`${API_URL}/sessions`);
      const data = await r.json();
      setSessions(data);
      // Keep title in sync for current session
      const cur = data.find(s => s.id === sessionIdRef.current);
      if (cur) setSessionTitle(cur.title);
    } catch {}
  }, []);

  const deleteSession = useCallback(async (id) => {
    try {
      await fetch(`${API_URL}/sessions/${id}`, { method: 'DELETE' });
      setSessions(prev => prev.filter(s => s.id !== id));
      if (sessionIdRef.current === id) {
        setSessionId(null);
        setMessages([]);
      }
    } catch {}
  }, []);

  const loadSessionMessages = useCallback(async (id) => {
    try {
      const r = await fetch(`${API_URL}/sessions/${id}/messages`);
      const data = await r.json();
      setMessages(data.map(m => ({
        id: m.id,
        role: m.role,
        type: m.type,
        format: m.format,
        content: m.content,
        ts: m.ts,
      })));
    } catch {}
  }, []);

  // Switch to an existing session
  const switchSession = useCallback(async (id) => {
    setSessionId(id);
    sessionIdRef.current = id;
    await loadSessionMessages(id);
    // Sync title
    try {
      const r = await fetch(`${API_URL}/sessions`);
      const list = await r.json();
      const s = list.find(x => x.id === id);
      if (s) { setSessions(list); setSessionTitle(s.title); }
    } catch {}
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'join', session_id: id }));
    }
  }, [loadSessionMessages]);

  // ── Health check ──────────────────────────────────────────────────

  const checkHealth = useCallback(async () => {
    try {
      const r = await fetch(`${API_URL}/health`);
      const d = await r.json();
      if (d.ollama) {
        healthFailRef.current = 0;
        setOllamaOnline(true);
      } else {
        healthFailRef.current += 1;
        if (healthFailRef.current >= 2) setOllamaOnline(false);
      }
      const list = Array.isArray(d.models) ? d.models : [];
      if (list.length) setModels(list);
      // Self-heal the active model. If the currently selected model isn't
      // actually installed (e.g. the hardcoded "gemma3-12b" default on a
      // machine that has different tags), fall back to the first installed
      // model. Without this, the sidebar dropdown shows a model name that
      // doesn't exist anywhere in Ollama and chat fails on first send.
      setActiveModel(prev => {
        const short = (s) => String(s || '').replace(/:latest$/, '');
        const installed = new Set(list.map(short));
        if (installed.has(short(prev))) return prev;
        return list[0] || prev;
      });
      return d;
    } catch {
      healthFailRef.current += 1;
      if (healthFailRef.current >= 2) setOllamaOnline(false);
      return { ollama: false };
    }
  }, []);

  // Pull the user's saved model from /settings so the sidebar dropdown
  // reflects what was picked during onboarding instead of the hardcoded
  // initial value. checkHealth's self-heal still kicks in if /settings
  // points at a model that's no longer installed.
  const loadSavedModel = useCallback(async () => {
    try {
      const r = await fetch(`${API_URL}/settings`);
      if (!r.ok) return;
      const s = await r.json();
      if (s?.model) setActiveModel(s.model);
    } catch { /* offline — checkHealth retries */ }
  }, []);

  useEffect(() => {
    loadSavedModel();
    checkHealth();
    fetchSessions();
    // Goal 1.7: 30-second Ollama heartbeat
    const hb = setInterval(checkHealth, 30_000);
    return () => clearInterval(hb);
  }, [loadSavedModel, checkHealth, fetchSessions]);

  // ── Chunk assembler ───────────────────────────────────────────────

  const applyChunk = useCallback((chunk) => {
    const { role, type, format, content, start, end } = chunk;

    if (type === 'message' && role === 'assistant') {
      if (start) {
        const id = `msg-${Date.now()}-${Math.random()}`;
        streamingMsgRef.current = id;
        setMessages(prev => [...prev, { id, role: 'assistant', type: 'message', content: '' }]);
      } else if (content !== undefined && streamingMsgRef.current) {
        setMessages(prev => prev.map(m =>
          m.id === streamingMsgRef.current ? { ...m, content: m.content + content } : m
        ));
      } else if (end) {
        streamingMsgRef.current = null;
      }
    } else if (type === 'code' && role === 'assistant') {
      if (start) {
        const id = `code-${Date.now()}-${Math.random()}`;
        streamingMsgRef.current = id;
        setMessages(prev => [...prev, { id, role: 'assistant', type: 'code', format: format || 'python', content: '' }]);
      } else if (content !== undefined && streamingMsgRef.current) {
        setMessages(prev => prev.map(m =>
          m.id === streamingMsgRef.current ? { ...m, content: m.content + content } : m
        ));
      } else if (end) {
        streamingMsgRef.current = null;
      }
    } else if (type === 'console' && role === 'tool') {
      if (start) {
        const id = `out-${Date.now()}-${Math.random()}`;
        streamingMsgRef.current = id;
        setMessages(prev => [...prev, { id, role: 'tool', type: 'console', content: '' }]);
      } else if (content !== undefined && streamingMsgRef.current) {
        setMessages(prev => prev.map(m =>
          m.id === streamingMsgRef.current ? { ...m, content: m.content + content } : m
        ));
      } else if (end) {
        streamingMsgRef.current = null;
      }
    } else if (type === 'confirmation') {
      setMessages(prev => [...prev, {
        id: `conf-${Date.now()}`,
        role: 'assistant',
        type: 'confirmation',
        content: chunk.content || 'Run this code?',
        code: chunk.code,
      }]);
    } else if (type === 'error') {
      setMessages(prev => [...prev, {
        id: `err-${Date.now()}`,
        role: 'system',
        type: 'error',
        content,
      }]);
    }
  }, []);

  // ── WebSocket ─────────────────────────────────────────────────────

  useEffect(() => {
    let ws;
    let dead = false;

    const connect = () => {
      if (dead) return;
      ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (!dead) setTimeout(connect, 3000);
      };
      ws.onerror = () => ws.close();

      ws.onmessage = (e) => {
        const chunk = JSON.parse(e.data);
        if (chunk.type === 'start') {
          setStreaming(true);
          // Backend tells us the session_id for this conversation
          if (chunk.session_id && !sessionIdRef.current) {
            setSessionId(chunk.session_id);
            sessionIdRef.current = chunk.session_id;
            // Refresh sessions list so LeftPanel shows it
            fetchSessions();
          }
        } else if (chunk.type === 'done') {
          setStreaming(false);
          streamingMsgRef.current = null;
          fetchSessions();  // refresh list after AI reply saved
        } else if (chunk.type === 'joined') {
          // session join ack
        } else if (chunk.type === 'autonomy_ok') {
          setAutonomy(chunk.level);
        } else if (chunk.type === 'mcp_consent_request') {
          // Backend asks the user to approve a destructive MCP tool call.
          // Modal renders the head of the queue; concurrent requests
          // stack and resolve one at a time.
          setConsentQueue(prev => [...prev, { ...chunk, status: 'pending' }]);
        } else if (chunk.type === 'mcp_consent_timeout') {
          // Backend timed out waiting for a response (30s). The
          // backend already returned DENIED to the runtime; the modal
          // swaps to an error banner so the user knows what happened.
          setConsentQueue(prev => prev.map(r =>
            r.request_id === chunk.request_id ? { ...r, status: 'timed_out' } : r
          ));
        } else if (chunk.type === 'mcp_setup_error') {
          // Soft-fail at session join — agent's mcp_servers couldn't
          // be wired (missing secret, bad transport spec, etc). Chat
          // still works, just without MCP. Surface inline.
          setMcpSetupErrors(prev => [...prev, chunk.error || 'unknown MCP setup error']);
        } else {
          applyChunk(chunk);
        }
      };
    };

    connect();
    return () => { dead = true; ws?.close(); };
  }, [applyChunk, fetchSessions]);

  // ── Send ──────────────────────────────────────────────────────────

  const send = useCallback((text, agentId = null) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    const id = `user-${Date.now()}`;
    setMessages(prev => [...prev, { id, role: 'user', type: 'message', content: text }]);
    setStreaming(true);
    const payload = {
      type: 'chat',
      content: text,
      session_id: sessionIdRef.current || null,
    };
    // Always forward agent_id when supplied — backend decides whether it's
    // a first-message bind or an explicit mid-session switch.
    if (agentId) payload.agent_id = agentId;
    wsRef.current.send(JSON.stringify(payload));
  }, []);

  const stop = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'stop' }));
    }
    setStreaming(false);
  }, []);

  const clear = useCallback(() => {
    setMessages([]);
    setSessionId(null);
    setSessionTitle(null);
    sessionIdRef.current = null;
  }, []);

  const newSession = useCallback(() => {
    clear();
  }, [clear]);

  const switchModel = useCallback((model) => {
    setActiveModel(model);
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'model', model }));
    }
  }, []);

  const setAutonomyLevel = useCallback((level) => {
    setAutonomy(level);
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'autonomy', level }));
    }
  }, []);

  const confirm = useCallback((msgId, approved) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'confirm', approved }));
    }
    // Dismiss the confirmation bubble after responding
    setMessages(prev => prev.filter(m => m.id !== msgId));
  }, []);

  // ── MCP consent ────────────────────────────────────────────────────
  // Decisions map to backend ConsentDecision enum + v0.24 wire shorthand:
  //   "approved"          — single tool call only
  //   "approved_session"  — cache (server, tool) for this WS session
  //   "approved_all"      — v0.24: head + all currently-queued resolve as
  //                         APPROVED on the backend; FE clears its queue
  //                         to match. Snapshot semantics — future
  //                         requests in the same turn re-prompt normally.
  //   "denied"            — refuse, runtime raises MCPConsentDenied
  const respondConsent = useCallback((decision) => {
    setConsentQueue(prev => {
      const head = prev[0];
      if (!head || head.status !== 'pending') return prev;
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({
          type: 'mcp_consent_response',
          request_id: head.request_id,
          decision,
        }));
      }
      // approved_all: backend resolves head + all siblings, so FE
      // queue must drop everything (not just the head). Other
      // decisions only pop the head; remaining items re-render in
      // the modal one-by-one.
      return decision === 'approved_all' ? [] : prev.slice(1);
    });
  }, []);

  // User dismissing the timeout banner — backend already returned
  // DENIED to the runtime, so we just pop the head from the local queue.
  const ackConsentTimeout = useCallback(() => {
    setConsentQueue(prev => prev[0]?.status === 'timed_out' ? prev.slice(1) : prev);
  }, []);

  const dismissMcpSetupError = useCallback((idx) => {
    setMcpSetupErrors(prev => prev.filter((_, i) => i !== idx));
  }, []);

  return {
    messages, streaming, connected, ollamaOnline,
    sessionId, sessionTitle, sessions,
    models, activeModel, autonomy,
    send, stop, clear, newSession, switchModel, setAutonomyLevel, checkHealth,
    fetchSessions, deleteSession, switchSession, confirm,
    consentQueue, respondConsent, ackConsentTimeout,
    mcpSetupErrors, dismissMcpSetupError,
  };
}
