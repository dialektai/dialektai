import { useState } from 'react';
import { T } from '../tokens.js';
import { AppFrame, Logo } from '../components/Shell.jsx';
import { getCloudApi } from '../lib/cloud.js';

const API = 'http://localhost:8765';

export default function InviteRedemptionScreen({ onNav }) {
  const [token, setToken] = useState('');
  const [status, setStatus] = useState('idle'); // idle | checking | ok | error
  const [errorMsg, setErrorMsg] = useState('');
  const [result, setResult] = useState(null);

  const redeem = async () => {
    const trimmed = token.trim();
    if (!trimmed) return;
    setStatus('checking');
    setErrorMsg('');
    try {
      const cloudApi = await getCloudApi();
      const r = await fetch(`${cloudApi}/auth/accept-invite`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ invite_token: trimmed }),
      });
      const data = await r.json();
      if (!r.ok || data.error) {
        throw new Error(data.detail || data.error || 'Invalid or expired invite token');
      }

      // Save user + bearer token locally, then pull assigned agents
      await fetch(`${API}/license/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bearer_token: data.bearer_token,
          user: { user_id: data.user_id, tenant_id: data.tenant_id, role: data.role },
        }),
      }).catch(() => {});
      fetch(`${API}/sync/pull`, { method: 'POST' }).catch(() => {});

      setResult(data);
      setStatus('ok');
    } catch (e) {
      setStatus('error');
      setErrorMsg(String(e).replace('Error: ', ''));
    }
  };

  return (
    <AppFrame title="dialekt.ai — Accept Invite">
      <div style={{ flex: 1, display: 'flex', background: T.bg0, alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ width: 460 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 48 }}>
            <Logo />
            <div>
              <div style={{ fontSize: 18, fontWeight: 800, letterSpacing: '-0.02em' }}>
                dialekt<span style={{ color: T.cyan }}>.ai</span>
              </div>
              <div className="mono" style={{ fontSize: 10, color: T.dim, letterSpacing: '.1em' }}>YOU WERE INVITED</div>
            </div>
          </div>

          {status === 'ok' ? (
            <div style={{ border: `1px solid ${T.green}`, background: T.bg1, padding: 28 }}>
              <div style={{ color: T.green, fontWeight: 700, fontSize: 16, marginBottom: 8 }}>
                ✓ Invite accepted
              </div>
              <div style={{ color: T.muted, fontSize: 13, marginBottom: 4 }}>
                Your account is ready.
              </div>
              {result?.role && (
                <div style={{ color: T.dim, fontSize: 12, marginBottom: 16 }}>
                  Your role: <span className="mono" style={{ color: T.cyan }}>{result.role}</span>
                </div>
              )}
              <div style={{ color: T.dim, fontSize: 12, marginBottom: 24 }}>
                Your agents will be pulled automatically.
              </div>
              <button
                onClick={() => onNav('mode-setup')}
                style={{ padding: '10px 28px', background: T.cyan, color: T.bg0, border: 'none', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}
              >
                CONTINUE →
              </button>
            </div>
          ) : (
            <>
              <div style={{ marginBottom: 32 }}>
                <div style={{ fontSize: 26, fontWeight: 800, letterSpacing: '-0.02em', color: T.text, marginBottom: 8 }}>
                  Enter your invite code
                </div>
                <div style={{ fontSize: 14, color: T.muted, lineHeight: 1.6 }}>
                  Check the email invitation you received from your team admin.
                  The code looks like: <span className="mono" style={{ color: T.cyan }}>inv_xxxxxxxxxxxx</span>
                </div>
              </div>

              <div style={{ background: T.bg1, border: `1px solid ${T.border}`, padding: 24, marginBottom: 16 }}>
                <label style={{ fontSize: 11, letterSpacing: '.1em', color: T.dim, display: 'block', marginBottom: 8 }}>
                  INVITE CODE
                </label>
                <input
                  value={token}
                  onChange={e => setToken(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && redeem()}
                  placeholder="inv_xxxxxxxxxxxxxxxxxxxx"
                  disabled={status === 'checking'}
                  style={{
                    width: '100%', boxSizing: 'border-box',
                    background: T.bg0, border: `1px solid ${status === 'error' ? T.red : T.border}`,
                    color: T.text, padding: '10px 14px', fontSize: 13,
                    fontFamily: T.mono, outline: 'none',
                  }}
                />
                {status === 'error' && (
                  <div style={{ color: T.red, fontSize: 12, marginTop: 8 }}>{errorMsg}</div>
                )}
              </div>

              <button
                onClick={redeem}
                disabled={!token.trim() || status === 'checking'}
                style={{
                  width: '100%', padding: '12px 24px',
                  background: (!token.trim() || status === 'checking') ? T.bg3 : T.cyan,
                  color: (!token.trim() || status === 'checking') ? T.dim : T.bg0,
                  border: 'none', fontSize: 13, fontWeight: 700,
                  cursor: (!token.trim() || status === 'checking') ? 'not-allowed' : 'pointer',
                  letterSpacing: '.06em', marginBottom: 24,
                }}
              >
                {status === 'checking' ? 'VERIFYING…' : 'ACCEPT INVITE'}
              </button>

              <div style={{ borderTop: `1px solid ${T.border}`, paddingTop: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ fontSize: 12, color: T.dim }}>Have a license key instead?</div>
                <button
                  onClick={() => onNav('license')}
                  style={{ background: 'none', border: `1px solid ${T.border}`, color: T.muted, padding: '6px 14px', fontSize: 12, cursor: 'pointer' }}
                >
                  Enter license
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </AppFrame>
  );
}
