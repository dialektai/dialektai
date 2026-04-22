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

  const wsRef = useRef(null);
  const streamingMsgRef = useRef(null);
  const sessionIdRef = useRef(null);  // sync ref for use inside WS callbacks

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
      setOllamaOnline(d.ollama);
      if (d.models?.length) setModels(d.models);
      return d;
    } catch {
      setOllamaOnline(false);
      return { ollama: false };
    }
  }, []);

  useEffect(() => {
    checkHealth();
    fetchSessions();
  }, [checkHealth, fetchSessions]);

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
    if (!sessionIdRef.current && agentId) {
      payload.agent_id = agentId;
    }
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

  return {
    messages, streaming, connected, ollamaOnline,
    sessionId, sessionTitle, sessions,
    models, activeModel, autonomy,
    send, stop, clear, newSession, switchModel, setAutonomyLevel, checkHealth,
    fetchSessions, deleteSession, switchSession, confirm,
  };
}
