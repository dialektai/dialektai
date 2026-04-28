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
  // Per-session streaming buffer. The OI sidecar only persists the
  // final answer to DB in its `finally` block — partial chunks live
  // only in React state. When the user switches sessions mid-stream
  // we wipe `messages` via loadSessionMessages, losing every chunk
  // that arrived before the switch. This ref accumulates assistant
  // text per session_id, lives across switchSession calls, and lets
  // us replay the in-progress message into `messages` when the user
  // returns to a session that's still streaming. Cleared on `end`.
  const streamBuffersRef = useRef({});
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
    // If a stream is active for this session, replay the buffered
    // partial message so the user sees what the agent generated
    // before they switched away. The buffer continues to accumulate
    // from the WS, and applyChunk's "create-if-missing" branch
    // appends new chunks under this same id going forward.
    const buf = streamBuffersRef.current[id];
    if (buf && buf.content) {
      const resumeId = `resume-${id}-${Date.now()}`;
      streamingMsgRef.current = resumeId;
      setMessages(prev => [
        ...prev,
        {
          id: resumeId,
          role: 'assistant',
          type: buf.type,
          format: buf.format,
          content: buf.content,
        },
      ]);
      setStreaming(true);
    }
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
      // CHAT-CAPABLE model. Without this, the sidebar dropdown shows a
      // model name that doesn't exist anywhere in Ollama and chat fails on
      // first send. The catalog isn't reachable from the FE, so embedding
      // families are listed by prefix here; matches the catalog's
      // "embedding"-only category in Python.
      const EMBEDDING_PREFIXES = ['nomic-embed', 'mxbai-embed', 'bge-m3', 'bge-large', 'all-minilm'];
      const isEmbedding = (name) => {
        const lc = String(name || '').toLowerCase();
        return EMBEDDING_PREFIXES.some(p => lc.startsWith(p));
      };
      setActiveModel(prev => {
        const short = (s) => String(s || '').replace(/:latest$/, '');
        const installed = new Set(list.map(short));
        if (installed.has(short(prev))) return prev;
        const chatCapable = list.find(m => !isEmbedding(m));
        return chatCapable || list[0] || prev;
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
        // If the user switched away and back during a stream, the ref
        // still points at the placeholder ID we created at `start`,
        // but `loadSessionMessages` wiped it out of `messages` state.
        // Treat that case as "create the placeholder now and append" so
        // late chunks land somewhere visible instead of silently being
        // dropped (Bug C live-chunk recovery).
        setMessages(prev => {
          if (prev.some(m => m.id === streamingMsgRef.current)) {
            return prev.map(m =>
              m.id === streamingMsgRef.current ? { ...m, content: m.content + content } : m
            );
          }
          return [...prev, { id: streamingMsgRef.current, role: 'assistant', type: 'message', content }];
        });
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
    let pingTimer = null;

    const connect = () => {
      if (dead) return;
      ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        // Application-level keepalive. macOS closes idle TCP after a few
        // minutes (lid sleep / network change kills it sooner) and the
        // sidecar's WS handler has no native ping, so without this the
        // connection silently dies and the user sees a "backend offline"
        // badge until the 3s reconnect kicks in. 20s cadence is well
        // under any common idle-close threshold.
        if (pingTimer) clearInterval(pingTimer);
        pingTimer = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            try { ws.send(JSON.stringify({ type: 'ping' })); } catch {}
          }
        }, 20_000);
      };
      ws.onclose = () => {
        setConnected(false);
        if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
        if (!dead) setTimeout(connect, 3000);
      };
      ws.onerror = () => ws.close();

      ws.onmessage = (e) => {
        const chunk = JSON.parse(e.data);

        // ── Per-session streaming buffer ─────────────────────────────
        // Run BEFORE the session-filter so we accumulate the
        // assistant message even when the user is viewing a different
        // chat. switchSession reads this buffer to reconstruct the
        // in-progress message when returning to the streaming session.
        if (chunk.session_id && chunk.role === 'assistant'
            && (chunk.type === 'message' || chunk.type === 'code')) {
          const sid = chunk.session_id;
          if (chunk.start) {
            streamBuffersRef.current[sid] = {
              content: '',
              type: chunk.type,
              format: chunk.format,
            };
          } else if (chunk.content !== undefined && streamBuffersRef.current[sid]) {
            streamBuffersRef.current[sid].content += chunk.content;
          } else if (chunk.end) {
            delete streamBuffersRef.current[sid];
          }
        }

        // Bug C: drop chunks not for the currently visible session so
        // they don't bleed into the wrong chat. Buffer above already
        // captured them for replay on switch-back.
        if (chunk.session_id && chunk.session_id !== sessionIdRef.current) {
          return;
        }
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
          // Bug C — if the user switched away mid-stream and came
          // back, the streaming placeholder message no longer exists
          // in the local `messages` state (loadSessionMessages reset
          // it on switch). Subsequent content chunks tried to update
          // a non-existent ID and silently no-op'd. Pulling the full
          // session from DB on done guarantees the final answer is
          // visible without making the user re-click the chat.
          if (chunk.session_id && chunk.session_id === sessionIdRef.current) {
            loadSessionMessages(chunk.session_id);
          }
        } else if (chunk.type === 'joined') {
          // session join ack
        } else if (chunk.type === 'pong') {
          // keepalive ack — nothing to do, presence alone is the signal
        } else if (chunk.type === 'model_ok') {
          // Backend tells us the actual chosen model on connect / agent
          // bind / session join. May differ from what the FE picked
          // because the default-model guard swapped a not-installed or
          // embedding-only model. Updating activeModel here keeps the
          // dropdown honest without a manual flip.
          if (chunk.model) setActiveModel(chunk.model);
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
    return () => { dead = true; if (pingTimer) clearInterval(pingTimer); ws?.close(); };
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
    // Persist as session default so the next WS (new chat, restart,
    // session switch) reads this model from /settings instead of the
    // stale onboarding pick. Without this, switching the dropdown
    // only affects the current connection — every new chat reverts
    // to whatever was saved at onboarding (often nomic-embed-text on
    // a fresh install).
    fetch(`${API_URL}/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model }),
    }).catch(() => { /* best-effort; the WS message already covered the live session */ });
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
