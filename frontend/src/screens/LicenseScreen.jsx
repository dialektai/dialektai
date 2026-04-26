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
  // Trial is the default path now; the license-key input is a secondary flow
  // revealed by clicking "I already have a license key →".
  const [showKeyInput, setShowKeyInput] = useState(false);

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
                  Welcome to dialekt
                </div>
                <div style={{ fontSize: 14, color: T.muted, lineHeight: 1.6 }}>
                  Start with a 30-day free trial — no key needed. Already paid? Use your license key instead.
                </div>
              </div>

              <button
                onClick={startTrial}
                disabled={status === 'checking'}
                style={{
                  width: '100%', padding: '16px 24px', marginBottom: 14,
                  background: T.cyan, color: T.bg0, border: 'none',
                  fontSize: 14, fontWeight: 800, letterSpacing: '.04em',
                  cursor: status === 'checking' ? 'wait' : 'pointer',
                  opacity: status === 'checking' ? 0.6 : 1,
                }}>
                START 30-DAY FREE TRIAL →
              </button>
              <div style={{ fontSize: 11, color: T.dim, textAlign: 'center', marginBottom: 24, letterSpacing: '.04em' }}>
                3 seats · all features · no credit card · no email signup required
              </div>

              {!showKeyInput ? (
                <div style={{ borderTop: `1px solid ${T.border}`, paddingTop: 20, textAlign: 'center' }}>
                  <button
                    onClick={() => setShowKeyInput(true)}
                    style={{ background: 'none', border: 'none', color: T.muted, fontSize: 12, cursor: 'pointer', letterSpacing: '.04em' }}>
                    I already have a license key →
                  </button>
                </div>
              ) : (
                <div style={{ borderTop: `1px solid ${T.border}`, paddingTop: 24 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 12 }}>
                    <label style={{ fontSize: 11, letterSpacing: '.1em', color: T.dim }}>LICENSE KEY</label>
                    <button onClick={() => setShowKeyInput(false)}
                      style={{ background: 'none', border: 'none', color: T.dim, fontSize: 11, cursor: 'pointer' }}>
                      ← back to trial
                    </button>
                  </div>
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
                      fontFamily: T.mono, outline: 'none', marginBottom: 12,
                    }}
                  />
                  {status === 'error' && (
                    <div style={{ color: T.red, fontSize: 12, marginBottom: 10 }}>{errorMsg}</div>
                  )}
                  <button
                    onClick={validate}
                    disabled={!key.trim() || status === 'checking'}
                    style={{
                      width: '100%', padding: '11px 24px',
                      background: (!key.trim() || status === 'checking') ? T.bg3 : T.cyan,
                      color: (!key.trim() || status === 'checking') ? T.dim : T.bg0,
                      border: 'none', fontSize: 13, fontWeight: 700,
                      cursor: (!key.trim() || status === 'checking') ? 'not-allowed' : 'pointer',
                      letterSpacing: '.06em',
                    }}>
                    {status === 'checking' ? 'VALIDATING…' : 'ACTIVATE LICENSE'}
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </AppFrame>
  );
}
