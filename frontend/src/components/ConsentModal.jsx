import { useEffect } from 'react';
import { T } from '../tokens.js';

/**
 * Consent modal for destructive MCP tool calls.
 *
 * Rendered above the chat column when the backend emits an
 * `mcp_consent_request` frame. Three decisions map directly to
 * `dialekt.mcp.consent.ConsentDecision`:
 *
 *   Approve once             → "approved"
 *   Approve for this session → "approved_session"  (cached on (server,tool))
 *   Deny                     → "denied"
 *
 * Keyboard:
 *   Enter         → Approve once
 *   Shift+Enter   → Approve for this session
 *   Esc           → Deny
 *
 * If `request.status === "timed_out"`, the action row swaps for an OK
 * button — the backend already returned DENIED to the runtime.
 *
 * Styled to match the SettingsScreen token system; no new tokens.
 * Always centered; at <600px wide the dialog shrinks via
 * `calc(100vw - 32px)`. Non-dismissible by clicking the scrim — the
 * user must explicitly choose. Matches design doc §4.
 */
export default function ConsentModal({
  request,
  queueLength,
  onApprove,
  onApproveSession,
  onApproveAll,
  onDeny,
  onTimeoutAck,
}) {
  useEffect(() => {
    if (!request) return;
    const onKey = (e) => {
      // Don't hijack typing in inputs/textareas — the user might be
      // mid-edit when the prompt arrives.
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      if (request.status === 'timed_out') {
        if (e.key === 'Enter' || e.key === 'Escape') {
          e.preventDefault();
          onTimeoutAck?.();
        }
        return;
      }
      if (e.key === 'Enter' && e.shiftKey) {
        e.preventDefault();
        onApproveSession?.();
      } else if (e.key === 'Enter') {
        e.preventDefault();
        onApprove?.();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        onDeny?.();
      } else if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === 'a' && queueLength > 1) {
        // v0.24: Shift+Cmd/Ctrl+A approves the entire visible burst.
        // Mentor-ruled key choice: 'A' carries select-all-pending
        // semantic; modifier guard avoids ambient typing collision.
        e.preventDefault();
        onApproveAll?.();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [request, onApprove, onApproveSession, onApproveAll, onDeny, onTimeoutAck, queueLength]);

  if (!request) return null;

  const timedOut = request.status === 'timed_out';
  const argsPretty = (() => {
    try { return JSON.stringify(request.arguments || {}, null, 2); }
    catch { return String(request.arguments); }
  })();

  return (
    <div
      role="alertdialog"
      aria-labelledby="consent-modal-title"
      aria-describedby="consent-modal-args"
      style={{
        position: 'fixed', inset: 0, zIndex: 10000,
        background: 'rgba(0,0,0,0.6)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 16,
      }}
    >
      <div style={{
        width: 'min(560px, calc(100vw - 32px))',
        maxHeight: 'calc(100vh - 32px)',
        overflowY: 'auto',
        background: T.bg1,
        border: `1px solid ${T.border}`,
        boxShadow: '0 12px 48px rgba(0,0,0,0.7)',
        display: 'flex', flexDirection: 'column',
      }}>
        {/* Header */}
        <div style={{
          padding: '14px 18px',
          borderBottom: `1px solid ${T.border}`,
          background: T.bg2,
          display: 'flex', alignItems: 'center', gap: 10,
        }}>
          <span style={{ fontSize: 16 }}>🔐</span>
          <div id="consent-modal-title" style={{ fontSize: 13, color: T.text, letterSpacing: '.04em' }}>
            Permission required
          </div>
          {queueLength > 1 && (
            <span className="mono" style={{ marginLeft: 'auto', fontSize: 10, color: T.dim }}>
              1 of {queueLength}
            </span>
          )}
        </div>

        {/* Body */}
        <div style={{ padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ fontSize: 12, color: T.muted }}>
            {timedOut
              ? 'The agent waited too long for a response. The tool call has been denied; you can resend the message to retry.'
              : 'An agent wants to call an MCP tool. Approve only if the action is safe.'}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '90px 1fr', gap: '6px 14px', fontSize: 12 }}>
            <span style={{ color: T.dim }}>Server</span>
            <span className="mono" style={{ color: T.text }}>{request.server_name}</span>
            <span style={{ color: T.dim }}>Tool</span>
            <span style={{ color: T.text, display: 'flex', alignItems: 'center', gap: 8 }}>
              <span className="mono">{request.tool_name}</span>
              {request.destructive && (
                <span className="mono" style={{
                  fontSize: 10, color: T.red,
                  border: `1px solid ${T.red}66`, padding: '1px 6px',
                  letterSpacing: '.04em',
                }}>
                  destructive · {request.destructive_source}
                </span>
              )}
            </span>
          </div>

          <div>
            <div style={{ fontSize: 11, color: T.dim, marginBottom: 4 }}>Arguments</div>
            <pre id="consent-modal-args" className="mono" style={{
              margin: 0, padding: '10px 12px',
              background: T.bg2, border: `1px solid ${T.border}`,
              fontSize: 11, color: T.text, lineHeight: 1.5,
              maxHeight: 240, overflow: 'auto', whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}>{argsPretty}</pre>
          </div>
        </div>

        {/* Actions */}
        <div style={{
          padding: '12px 18px',
          borderTop: `1px solid ${T.border}`,
          display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap',
        }}>
          {timedOut ? (
            <button
              autoFocus
              onClick={onTimeoutAck}
              style={{
                background: T.cyan, color: '#000', border: 'none',
                padding: '8px 22px', fontSize: 12, fontWeight: 600,
                cursor: 'pointer', letterSpacing: '.04em',
              }}>OK</button>
          ) : (
            <>
              <button
                onClick={onDeny}
                style={{
                  background: 'transparent', border: `1px solid ${T.red}66`,
                  color: T.red, padding: '8px 16px', fontSize: 12,
                  cursor: 'pointer', letterSpacing: '.04em',
                }}>Deny (Esc)</button>
              <button
                onClick={onApproveSession}
                style={{
                  background: 'transparent', border: `1px solid ${T.border}`,
                  color: T.text, padding: '8px 16px', fontSize: 12,
                  cursor: 'pointer', letterSpacing: '.04em',
                }}>Approve for session (⇧⏎)</button>
              {queueLength > 1 && (
                <button
                  onClick={onApproveAll}
                  style={{
                    background: 'transparent', border: `1px solid ${T.cyan}66`,
                    color: T.cyan, padding: '8px 16px', fontSize: 12,
                    cursor: 'pointer', letterSpacing: '.04em',
                  }}>Approve all {queueLength} pending (⇧⌘A)</button>
              )}
              <button
                autoFocus
                onClick={onApprove}
                style={{
                  background: T.cyan, color: '#000', border: 'none',
                  padding: '8px 22px', fontSize: 12, fontWeight: 600,
                  cursor: 'pointer', letterSpacing: '.04em',
                }}>Approve once (⏎)</button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
