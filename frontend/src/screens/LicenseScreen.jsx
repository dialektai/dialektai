import { useState } from 'react';
import { T } from '../tokens.js';
import { AppFrame, Logo } from '../components/Shell.jsx';
import { getCloudApi } from '../lib/cloud.js';

const API = 'http://localhost:8765';

export default function LicenseScreen({ onNav }) {
  const [key, setKey] = useState('');
  const [status, setStatus] = useState('idle'); // idle | checking | ok | error | trial
  const [errorMsg, setErrorMsg] = useState('');
  const [tenantInfo, setTenantInfo] = useState(null);

  const validate = async () => {
    const trimmed = key.trim();
    if (!trimmed) return;
    setStatus('checking');
    setErrorMsg('');
    try {
      // Validate against cloud API; fallback to local offline check
      let data;
      try {
        const cloudApi = await getCloudApi();
        const r = await fetch(`${cloudApi}/auth/validate-license`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ license_key: trimmed }),
        });
        data = await r.json();
      } catch {
        // Cloud unreachable — check local cache
        const cached = await fetch(`${API}/license/status`).then(r => r.json()).catch(() => null);
        if (cached?.valid && cached?.license_key === trimmed) {
          data = { valid: true, ...cached };
        } else {
          throw new Error('Cloud API unreachable. Please check your internet connection and try again.');
        }
      }

      if (!data.valid) {
        setStatus('error');
        setErrorMsg(data.message || 'License key not found or expired. Contact hello@dialekt.ai');
        return;
      }

      // Save license + bearer token locally, then pull assigned agents
      const tenant = {
        company_name: data.company_name || null,
        plan: data.plan,
        seats_limit: data.seats_limit,
        expires_at: data.expires_at,
      };
      await fetch(`${API}/license/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ license_key: trimmed, tenant, bearer_token: data.bearer_token }),
      }).catch(() => {});
      fetch(`${API}/sync/pull`, { method: 'POST' }).catch(() => {});

      setTenantInfo(tenant);
      setStatus('ok');
    } catch (e) {
      setStatus('error');
      setErrorMsg(String(e).replace('Error: ', ''));
    }
  };

  const startTrial = async () => {
    setStatus('trial');
    // Generate a local trial marker valid for 30 days
    await fetch(`${API}/license/trial`, { method: 'POST' }).catch(() => {});
    setTimeout(() => onNav('mode-setup'), 1500);
  };

  return (
    <AppFrame title="dialekt.ai — License">
      <div style={{ flex: 1, display: 'flex', background: T.bg0, alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ width: 480 }}>
          {/* Logo */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 48 }}>
            <Logo />
            <div>
              <div style={{ fontSize: 18, fontWeight: 800, letterSpacing: '-0.02em' }}>
                dialekt<span style={{ color: T.cyan }}>.ai</span>
              </div>
              <div className="mono" style={{ fontSize: 10, color: T.dim, letterSpacing: '.1em' }}>LOCAL-FIRST AGENT PLATFORM</div>
            </div>
          </div>

          {status === 'ok' ? (
            <div style={{ border: `1px solid ${T.green}`, background: T.bg1, padding: 28 }}>
              <div style={{ color: T.green, fontWeight: 700, fontSize: 16, marginBottom: 8 }}>
                ✓ License activated
              </div>
              {tenantInfo && (
                <div style={{ color: T.muted, fontSize: 13, marginBottom: 4 }}>
                  {tenantInfo.company_name} — {tenantInfo.plan} plan · {tenantInfo.seats_limit} seats
                </div>
              )}
              <div style={{ color: T.dim, fontSize: 12, marginBottom: 20 }}>
                Your license has been saved. It will be verified automatically in the background.
              </div>
              <button
                onClick={() => onNav('mode-setup')}
                style={{ padding: '10px 28px', background: T.cyan, color: T.bg0, border: 'none', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}
              >
                CONTINUE SETUP →
              </button>
            </div>
          ) : status === 'trial' ? (
            <div style={{ border: `1px solid ${T.amber}`, background: T.bg1, padding: 28 }}>
              <div style={{ color: T.amber, fontWeight: 700, fontSize: 16, marginBottom: 8 }}>
                30-day trial started
              </div>
              <div style={{ color: T.muted, fontSize: 13 }}>
                3 seats · all features · expires in 30 days. Continuing to setup…
              </div>
            </div>
          ) : (
            <>
              <div style={{ marginBottom: 32 }}>
                <div style={{ fontSize: 26, fontWeight: 800, letterSpacing: '-0.02em', color: T.text, marginBottom: 8 }}>
                  Enter your license key
                </div>
                <div style={{ fontSize: 14, color: T.muted, lineHeight: 1.6 }}>
                  Received your license via email? Paste it below.
                  To purchase, contact <span style={{ color: T.cyan }}>hello@dialekt.ai</span>
                </div>
              </div>

              <div style={{ background: T.bg1, border: `1px solid ${T.border}`, padding: 24, marginBottom: 16 }}>
                <label style={{ fontSize: 11, letterSpacing: '.1em', color: T.dim, display: 'block', marginBottom: 8 }}>
                  LICENSE KEY
                </label>
                <input
                  value={key}
                  onChange={e => setKey(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && validate()}
                  placeholder="dialekt_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
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

              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 32 }}>
                <button
                  onClick={validate}
                  disabled={!key.trim() || status === 'checking'}
                  style={{
                    flex: 1, padding: '11px 24px',
                    background: (!key.trim() || status === 'checking') ? T.bg3 : T.cyan,
                    color: (!key.trim() || status === 'checking') ? T.dim : T.bg0,
                    border: 'none', fontSize: 13, fontWeight: 700,
                    cursor: (!key.trim() || status === 'checking') ? 'not-allowed' : 'pointer',
                    letterSpacing: '.06em',
                  }}
                >
                  {status === 'checking' ? 'VALIDATING…' : 'ACTIVATE LICENSE'}
                </button>
              </div>

              <div style={{ borderTop: `1px solid ${T.border}`, paddingTop: 24, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ fontSize: 12, color: T.dim }}>
                  Don't have a license yet?
                </div>
                <button
                  onClick={startTrial}
                  style={{ background: 'none', border: `1px solid ${T.border}`, color: T.muted, padding: '8px 18px', fontSize: 12, cursor: 'pointer' }}
                >
                  Start 30-day free trial
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </AppFrame>
  );
}
