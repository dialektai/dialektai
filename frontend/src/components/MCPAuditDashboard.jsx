import { useEffect, useMemo, useState } from 'react';
import { T } from '../tokens.js';

const API = 'http://localhost:8765';

// Mentor pass 3: error + server_unavailable collapse onto ✗ (both
// surface to the LLM as failed; error_kind distinguishes in expand).
function glyph(kind, result) {
  if (kind === 'mcp_consent_requested') return '?';
  if (kind === 'mcp_tool_blocked') return '⊘';
  if (kind === 'mcp_consent_decision') {
    if (result === 'approved') return '✓';
    if (result === 'approved_session') return '△';
    return '⊘';
  }
  if (result === 'success') return '✓';
  if (result === 'rate_limited' || result === 'timeout') return '⏱';
  return '✗';
}
const fmtTs = iso => new Date(iso.replace(' ', 'T') + 'Z').toLocaleTimeString('en-GB');
const fmtMs = ms => ms == null ? '—' : ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
const LEGEND = '? asked  ✓ approved/success  △ session  ⊘ blocked/denied  ✗ error  ⏱ rate-limited/timeout  [!] destructive';
const KIND_FILTERS = { all: 'mcp_*', consent: 'mcp_consent_*', tool: 'mcp_tool_call', blocked: 'mcp_tool_blocked' };

export default function MCPAuditDashboard() {
  const [rows, setRows] = useState([]);
  const [truncated, setTruncated] = useState(false);
  const [days, setDays] = useState(7);
  const [kindKey, setKindKey] = useState('all');
  const [expanded, setExpanded] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const since = new Date(Date.now() - days * 86400_000).toISOString();
    const params = new URLSearchParams({ kind: KIND_FILTERS[kindKey], since, limit: '500' });
    fetch(`${API}/audit/log?${params}`)
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(d => {
        if (cancelled) return;
        setRows(d.rows || []);
        setTruncated(!!d.truncated);
        setLoading(false);
      })
      .catch(e => { if (!cancelled) { setError(String(e)); setLoading(false); } });
    return () => { cancelled = true; };
  }, [days, kindKey]);

  // Group rows that share consent_id under the decision row's expand.
  // Rows without consent_id stand alone (auto-approved non-destructive
  // calls — the majority case in normal pilot use).
  const grouped = useMemo(() => {
    const decisionById = new Map();
    for (const r of rows) if (r.kind === 'mcp_consent_decision') decisionById.set(r.id, []);
    for (const r of rows) {
      const cid = r.extra?.consent_id;
      if (cid != null && decisionById.has(cid) && r.id !== cid) decisionById.get(cid).push(r);
    }
    const consumed = new Set();
    for (const list of decisionById.values()) for (const r of list) consumed.add(r.id);
    return rows.filter(r => !consumed.has(r.id)).map(r => ({
      head: r,
      kids: r.kind === 'mcp_consent_decision' ? (decisionById.get(r.id) || []) : [],
    }));
  }, [rows]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

      {/* Filter strip */}
      <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: 4 }}>
          {[1, 7, 30].map(d => (
            <button key={d} onClick={() => setDays(d)} style={{
              border: `1px solid ${days === d ? T.cyan : T.border}`,
              color: days === d ? T.cyan : T.muted,
              background: 'transparent', padding: '4px 12px',
              fontSize: 11, fontFamily: T.mono, cursor: 'pointer',
              letterSpacing: '.04em',
            }}>{d}d</button>
          ))}
        </div>
        <select value={kindKey} onChange={e => setKindKey(e.target.value)} style={{
          background: T.bg1, border: `1px solid ${T.border}`,
          color: T.text, padding: '5px 10px', fontSize: 11, fontFamily: T.mono,
        }}>
          <option value="all">All MCP events</option>
          <option value="consent">Consent only</option>
          <option value="tool">Tool calls only</option>
          <option value="blocked">Blocked only</option>
        </select>
        <span className="mono" style={{ fontSize: 10, color: T.dim, marginLeft: 'auto' }}>
          showing last 30 days max — older rows are clipped server-side
        </span>
      </div>

      <div style={{
        padding: '6px 10px', background: T.bg1, border: `1px solid ${T.border}`,
        fontSize: 10, fontFamily: T.mono, color: T.dim, whiteSpace: 'nowrap', overflow: 'auto',
      }}>{LEGEND}</div>

      {/* Rows */}
      {loading && <div style={{ color: T.dim, fontSize: 12 }}>Loading…</div>}
      {error && <div style={{ color: T.red, fontSize: 12 }}>Error: {error}</div>}
      {!loading && !error && grouped.length === 0 && (
        <div style={{ color: T.dim, fontSize: 12, padding: '20px 0', textAlign: 'center' }}>
          No MCP activity in the selected window.
        </div>
      )}
      {!loading && !error && grouped.length > 0 && (
        <div style={{ border: `1px solid ${T.border}`, background: T.bg1 }}>
          {grouped.map(({ head, kids }, i) => (
            <Row key={head.id} row={head} kids={kids}
                 expanded={expanded === head.id}
                 onToggle={() => setExpanded(expanded === head.id ? null : head.id)}
                 last={i === grouped.length - 1} />
          ))}
        </div>
      )}

      {truncated && (
        <div style={{ fontSize: 10, color: T.amber, fontFamily: T.mono }}>
          Showing newest 500 of more rows in this window — narrow time range to see more.
        </div>
      )}
    </div>
  );
}

function Row({ row, kids, expanded, onToggle, last }) {
  const destructive = !!row.extra?.destructive;
  const hasGroup = kids.length > 0;
  return (
    <>
      <div onClick={onToggle} style={{
        display: 'flex', alignItems: 'center', gap: 12,
        padding: '8px 12px', cursor: 'pointer',
        borderBottom: !last && !expanded ? `1px solid ${T.border}` : 'none',
        fontSize: 11, fontFamily: T.mono,
      }}>
        <span style={{ color: T.dim, width: 64 }}>{fmtTs(row.ts)}</span>
        <span style={{ color: T.text, flex: 1 }}>
          {row.target} · {row.action}
          {destructive && <span style={{ color: T.red, marginLeft: 8 }}>[!]</span>}
          {hasGroup && <span style={{ color: T.dim, marginLeft: 8 }}>(+{kids.length})</span>}
        </span>
        <span style={{ width: 18, color: T.text }}>{glyph(row.kind, row.result)}</span>
        <span style={{ width: 80, color: T.muted, textAlign: 'right' }}>{row.result}</span>
        <span style={{ width: 56, color: T.dim, textAlign: 'right' }}>{fmtMs(row.duration_ms)}</span>
      </div>
      {expanded && (
        <div style={{
          padding: '10px 14px', background: T.bg2,
          borderBottom: !last ? `1px solid ${T.border}` : 'none',
          fontSize: 11, fontFamily: T.mono, color: T.muted,
        }}>
          <div>agent_id: <span style={{ color: T.text }}>{row.agent_id || '—'}</span></div>
          <div>error_kind: <span style={{ color: T.text }}>{row.error_kind || '—'}</span></div>
          <pre style={{ margin: '8px 0 0', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
{JSON.stringify(row.extra || {}, null, 2)}
          </pre>
          {kids.map(k => (
            <div key={k.id} style={{ marginTop: 6, paddingTop: 6, borderTop: `1px dashed ${T.border}` }}>
              <span style={{ color: T.dim }}>↳ {fmtTs(k.ts)} · {k.kind} · </span>
              <span style={{ color: T.text }}>{k.result}</span>
              <span style={{ color: T.dim }}> · {fmtMs(k.duration_ms)}</span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
