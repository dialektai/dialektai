import { useState, useEffect, useCallback } from 'react';

const API = 'http://localhost:8765';

export function useAgents() {
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedAgentId, setSelectedAgentId] = useState(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch(`${API}/agents`);
      if (!r.ok) return;
      setAgents(await r.json());
    } catch {
      // backend not ready
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const createAgent = useCallback(async (fields) => {
    const r = await fetch(`${API}/agents`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(fields),
    });
    if (!r.ok) throw new Error(await r.text());
    const agent = await r.json();
    await load();
    return agent;
  }, [load]);

  const updateAgent = useCallback(async (id, fields) => {
    const r = await fetch(`${API}/agents/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(fields),
    });
    if (!r.ok) throw new Error(await r.text());
    await load();
  }, [load]);

  const deleteAgent = useCallback(async (id) => {
    await fetch(`${API}/agents/${id}`, { method: 'DELETE' });
    setAgents(prev => prev.filter(a => a.id !== id));
    if (selectedAgentId === id) setSelectedAgentId(null);
  }, [selectedAgentId]);

  const selectAgent = useCallback((id) => {
    setSelectedAgentId(id === selectedAgentId ? null : id);
  }, [selectedAgentId]);

  const selectedAgent = agents.find(a => a.id === selectedAgentId) ?? null;

  return {
    agents,
    loading,
    selectedAgentId,
    selectedAgent,
    selectAgent,
    createAgent,
    updateAgent,
    deleteAgent,
    reload: load,
  };
}
