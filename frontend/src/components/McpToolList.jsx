import { T } from '../tokens.js';

/**
 * Shared rendering of an MCP server's tool catalog.
 * - Wizard step 5 expander: mode="checklist", drives allow_tools/deny_tools
 * - Settings → MCP Servers tool inspector (commit 5): mode="readonly"
 *
 * Tool shape (from GET /mcp-servers/{id}/tools):
 *   { name, description, destructive, destructive_source }
 * destructive_source: "explicit" (MCP-annotated) | "heuristic" (name match)
 */
export default function McpToolList({
  tools, mode = 'readonly',
  selectedNames, onToggle,
  loading, error,
}) {
  const isCheck = mode === 'checklist';
  const selectedSet = new Set(selectedNames || []);
  const status = loading ? 'loading' : error ? 'error' : !tools?.length ? 'empty' : 'ok';

  if (status !== 'ok') {
    return (
      <div style={{
        padding: status === 'error' ? '10px 14px' : '14px',
        fontSize: 11,
        color: status === 'error' ? T.red : T.dim,
        border: status === 'error' ? `1px solid ${T.red}44` : 'none',
        background: status === 'error' ? `${T.red}08` : 'transparent',
      }}>
        {status === 'loading' && 'Loading tools…'}
        {status === 'error' && `Couldn't list tools: ${error}`}
        {status === 'empty' && 'No tools advertised by this server.'}
      </div>
    );
  }

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: 1,
      maxHeight: 280, overflowY: 'auto',
      border: `1px solid ${T.border}`, background: T.bg2,
    }}>
      {tools.map(t => {
        const checked = selectedSet.has(t.name);
        return (
          <div key={t.name} style={{
            display: 'flex', alignItems: 'center', gap: 10,
            padding: '7px 12px',
            background: isCheck && checked ? `${T.cyan}08` : 'transparent',
            borderBottom: `1px solid ${T.bg1}`,
          }}>
            {isCheck && (
              <input type="checkbox" checked={checked}
                onChange={e => onToggle?.(t.name, e.target.checked)}
                style={{ cursor: 'pointer' }} />
            )}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="mono" style={{ fontSize: 11, color: T.text }}>{t.name}</div>
              {t.description && (
                <div style={{ fontSize: 10, color: T.dim, marginTop: 1,
                  whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {t.description}
                </div>
              )}
            </div>
            {t.destructive ? (
              <span className="mono" title={`destructive · ${t.destructive_source}`} style={{
                fontSize: 9, color: T.red,
                border: `1px solid ${T.red}66`, padding: '1px 6px',
                letterSpacing: '.04em', flexShrink: 0,
              }}>⚠ {t.destructive_source === 'explicit' ? 'destructive' : 'dest. (heur)'}</span>
            ) : (
              <span className="mono" style={{
                fontSize: 9, color: T.dim, flexShrink: 0,
              }}>read</span>
            )}
          </div>
        );
      })}
    </div>
  );
}
