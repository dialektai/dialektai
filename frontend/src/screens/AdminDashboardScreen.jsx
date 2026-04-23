import { useState, useEffect } from 'react';
import { T } from '../tokens.js';
import { AppFrame } from '../components/Shell.jsx';
import { getCloudApi } from '../lib/cloud.js';

const API = 'http://localhost:8765';

// ── Shared components ─────────────────────────────────────────────────────────

function StatCard({ label, value, sub, accent }) {
  return (
    <div style={{ background: T.bg1, border: `1px solid ${T.border}`, padding: '20px 24px' }}>
      <div style={{ fontSize: 10, letterSpacing: '.12em', color: T.dim, marginBottom: 8 }}>{label.toUpperCase()}</div>
      <div style={{ fontSize: 28, fontWeight: 800, color: accent || T.text, letterSpacing: '-0.03em' }}>{value ?? '—'}</div>
      {sub && <div style={{ fontSize: 11, color: T.muted, marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

function Badge({ text, color }) {
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, letterSpacing: '.08em',
      color: color, border: `1px solid ${color}`,
      padding: '2px 7px', borderRadius: 2,
    }}>{text.toUpperCase()}</span>
  );
}

function Tab({ label, active, onClick }) {
  return (
    <button onClick={onClick} style={{
      background: 'none', border: 'none',
      borderBottom: `2px solid ${active ? T.cyan : 'transparent'}`,
      color: active ? T.cyan : T.muted, fontSize: 12, fontWeight: active ? 700 : 400,
      padding: '10px 18px', cursor: 'pointer', letterSpacing: '.06em', transition: 'color .15s',
    }}>{label}</button>
  );
}

// ── Tab: Users ────────────────────────────────────────────────────────────────

function UsersTab() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState('user');
  const [inviting, setInviting] = useState(false);
  const [inviteResult, setInviteResult] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const license = await fetch(`${API}/license/status`).then(r => r.json());
        if (!license.bearer_token) { setLoading(false); return; }
        const cloudApi = await getCloudApi();
        const r = await fetch(`${cloudApi}/auth/me`, {
          headers: { Authorization: `Bearer ${license.bearer_token}` },
        });
        // In production: fetch users from cloud API. For now use local admin stats.
        const stats = await fetch(`${API}/admin/stats`).then(r => r.json());
        setUsers(stats.agents_detail || []);
      } catch { /* ignore */ }
      setLoading(false);
    })();
  }, []);

  const sendInvite = async () => {
    if (!inviteEmail.trim()) return;
    setInviting(true);
    setInviteResult(null);
    try {
      const license = await fetch(`${API}/license/status`).then(r => r.json());
      if (!license.bearer_token) throw new Error('No active license');
      const cloudApi = await getCloudApi();
      const r = await fetch(`${cloudApi}/auth/invite`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${license.bearer_token}` },
        body: JSON.stringify({ email: inviteEmail.trim(), role: inviteRole }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Failed to send invite');
      setInviteResult({ ok: true, msg: `Invite sent to ${inviteEmail}` });
      setInviteEmail('');
    } catch (e) {
      setInviteResult({ ok: false, msg: String(e).replace('Error: ', '') });
    }
    setInviting(false);
  };

  return (
    <div>
      {/* Invite form */}
      <div style={{ background: T.bg1, border: `1px solid ${T.border}`, padding: 24, marginBottom: 28 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: T.text, marginBottom: 16 }}>Invite Colleague</div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <input
            value={inviteEmail}
            onChange={e => setInviteEmail(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && sendInvite()}
            placeholder="colleague@company.com"
            style={{ flex: 2, minWidth: 200, background: T.bg0, border: `1px solid ${T.border}`, color: T.text, padding: '9px 12px', fontSize: 13, outline: 'none' }}
          />
          <select
            value={inviteRole}
            onChange={e => setInviteRole(e.target.value)}
            style={{ flex: 1, minWidth: 130, background: T.bg0, border: `1px solid ${T.border}`, color: T.text, padding: '9px 12px', fontSize: 13 }}
          >
            <option value="user">User</option>
            <option value="developer">Developer</option>
            <option value="admin">Admin</option>
          </select>
          <button
            onClick={sendInvite}
            disabled={!inviteEmail.trim() || inviting}
            style={{ padding: '9px 20px', background: inviteEmail.trim() ? T.cyan : T.bg3, color: inviteEmail.trim() ? T.bg0 : T.dim, border: 'none', fontSize: 12, fontWeight: 700, cursor: inviteEmail.trim() ? 'pointer' : 'not-allowed', letterSpacing: '.06em' }}
          >{inviting ? 'SENDING…' : 'SEND INVITE'}</button>
        </div>
        {inviteResult && (
          <div style={{ marginTop: 10, fontSize: 12, color: inviteResult.ok ? T.green : T.red }}>
            {inviteResult.ok ? '✓ ' : '✗ '}{inviteResult.msg}
          </div>
        )}
      </div>

      {/* User list — from local stats */}
      {loading ? (
        <div style={{ color: T.dim, fontSize: 12 }}>Loading…</div>
      ) : users.length === 0 ? (
        <div style={{ color: T.muted, fontSize: 13 }}>No team members yet. Invite a colleague above.</div>
      ) : (
        <div style={{ border: `1px solid ${T.border}` }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr auto auto', gap: 16, padding: '8px 16px', background: T.bg2, borderBottom: `1px solid ${T.border}` }}>
            {['Name', 'Status', 'Sessions'].map(h => (
              <span key={h} style={{ fontSize: 10, letterSpacing: '.1em', color: T.dim }}>{h.toUpperCase()}</span>
            ))}
          </div>
          {users.map((u, i) => (
            <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr auto auto', gap: 16, padding: '12px 16px', borderBottom: i < users.length - 1 ? `1px solid ${T.border}` : 'none', alignItems: 'center' }}>
              <span style={{ fontSize: 13, color: T.text }}>{u.name}</span>
              <Badge text={u.status} color={u.status === 'published' ? T.green : T.amber} />
              <span className="mono" style={{ fontSize: 12, color: T.muted }}>{u.session_count}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Tab: Agents ───────────────────────────────────────────────────────────────

function AgentsTab() {
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API}/agents`)
      .then(r => r.json())
      .then(setAgents)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div style={{ color: T.dim, fontSize: 12 }}>Loading…</div>;

  return (
    <div style={{ border: `1px solid ${T.border}` }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr auto auto auto', gap: 16, padding: '8px 16px', background: T.bg2, borderBottom: `1px solid ${T.border}` }}>
        {['Agent', 'Version', 'Status', 'Actions'].map(h => (
          <span key={h} style={{ fontSize: 10, letterSpacing: '.1em', color: T.dim }}>{h.toUpperCase()}</span>
        ))}
      </div>
      {agents.map((a, i) => (
        <div key={a.id} style={{ display: 'grid', gridTemplateColumns: '1fr auto auto auto', gap: 16, padding: '12px 16px', borderBottom: i < agents.length - 1 ? `1px solid ${T.border}` : 'none', alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: 13, color: T.text, fontWeight: 600 }}>{a.name}</div>
            <div style={{ fontSize: 11, color: T.dim }}>{a.description || '—'}</div>
          </div>
          <span className="mono" style={{ fontSize: 11, color: T.muted }}>{a.version}</span>
          <Badge text={a.status} color={a.status === 'published' ? T.green : T.amber} />
          <div style={{ display: 'flex', gap: 6 }}>
            <button style={{ background: 'none', border: `1px solid ${T.border}`, color: T.muted, padding: '4px 10px', fontSize: 10, cursor: 'pointer' }}>
              EXPORT
            </button>
          </div>
        </div>
      ))}
      {agents.length === 0 && (
        <div style={{ padding: '24px 16px', color: T.muted, fontSize: 13 }}>No agents yet. Use the Builder Wizard to create one.</div>
      )}
    </div>
  );
}

// ── Tab: Usage ────────────────────────────────────────────────────────────────

function UsageTab() {
  const [stats, setStats] = useState(null);

  useEffect(() => {
    fetch(`${API}/admin/stats`).then(r => r.json()).then(setStats).catch(() => {});
  }, []);

  if (!stats) return <div style={{ color: T.dim, fontSize: 12 }}>Loading…</div>;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
        <StatCard label="Sessions" value={stats.sessions} />
        <StatCard label="Messages" value={stats.messages} />
        <StatCard label="Agents" value={stats.agents} accent={T.cyan} />
        <StatCard label="Connections" value={stats.connections} />
      </div>

      {stats.agents_detail && stats.agents_detail.length > 0 && (
        <div>
          <div style={{ fontSize: 11, letterSpacing: '.1em', color: T.dim, marginBottom: 12 }}>AGENT USAGE BREAKDOWN</div>
          <div style={{ border: `1px solid ${T.border}` }}>
            {stats.agents_detail.map((a, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '12px 16px', borderBottom: i < stats.agents_detail.length - 1 ? `1px solid ${T.border}` : 'none' }}>
                <div style={{ flex: 1 }}>
                  <span style={{ fontSize: 13, color: T.text }}>{a.name}</span>
                </div>
                <Badge text={a.status} color={a.status === 'published' ? T.green : T.amber} />
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 160 }}>
                  <div style={{ flex: 1, height: 4, background: T.bg3 }}>
                    <div style={{ width: `${Math.min(100, (a.session_count / Math.max(1, stats.sessions)) * 100)}%`, height: '100%', background: T.cyan }} />
                  </div>
                  <span className="mono" style={{ fontSize: 11, color: T.muted, minWidth: 30, textAlign: 'right' }}>{a.session_count}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{ background: T.bg1, border: `1px solid ${T.border}`, padding: '14px 18px' }}>
        <div style={{ fontSize: 11, color: T.dim }}>
          Database size: <span className="mono" style={{ color: T.muted }}>{(stats.db_size_bytes / 1024 / 1024).toFixed(2)} MB</span>
        </div>
      </div>
    </div>
  );
}

// ── Tab: Subscription ─────────────────────────────────────────────────────────

function SubscriptionTab() {
  const [license, setLicense] = useState(null);

  useEffect(() => {
    fetch(`${API}/license/status`).then(r => r.json()).then(setLicense).catch(() => {});
  }, []);

  const tenant = license?.tenant;

  return (
    <div style={{ maxWidth: 600 }}>
      <div style={{ background: T.bg1, border: `1px solid ${T.border}`, padding: 24, marginBottom: 20 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: T.text, marginBottom: 16 }}>Current Plan</div>
        {!license?.valid ? (
          <div style={{ color: T.amber, fontSize: 13 }}>No active license. <a href="mailto:hello@dialekt.ai" style={{ color: T.cyan }}>Contact us</a></div>
        ) : license?.trial ? (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
              <Badge text="Trial" color={T.amber} />
              <span style={{ fontSize: 13, color: T.muted }}>30-day free trial</span>
            </div>
            <div style={{ fontSize: 12, color: T.dim }}>3 seats · all features. To activate a paid plan, contact <a href="mailto:hello@dialekt.ai" style={{ color: T.cyan }}>hello@dialekt.ai</a></div>
          </div>
        ) : (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
              <Badge text={tenant?.plan || 'team'} color={T.cyan} />
              <span style={{ fontSize: 13, color: T.text }}>{tenant?.company_name}</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
              <div>
                <div style={{ fontSize: 10, letterSpacing: '.1em', color: T.dim, marginBottom: 4 }}>SEATS</div>
                <div style={{ fontSize: 20, fontWeight: 700, color: T.text }}>{tenant?.seats_limit ?? '—'}</div>
              </div>
            </div>
          </div>
        )}
      </div>

      <div style={{ background: T.bg1, border: `1px solid ${T.border}`, padding: 24 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: T.text, marginBottom: 12 }}>Upgrade or change plan</div>
        <div style={{ fontSize: 13, color: T.muted, lineHeight: 1.6, marginBottom: 16 }}>
          dialekt uses invoice-based billing. To upgrade, add seats, or extend your subscription,
          contact the founder directly.
        </div>
        <a href="mailto:hello@dialekt.ai?subject=dialekt%20subscription"
          style={{ display: 'inline-block', padding: '9px 20px', background: T.bg2, border: `1px solid ${T.border}`, color: T.text, fontSize: 12, fontWeight: 600, textDecoration: 'none', letterSpacing: '.04em' }}>
          CONTACT → hello@dialekt.ai
        </a>
      </div>
    </div>
  );
}

// ── Main screen ───────────────────────────────────────────────────────────────

const TABS = ['Users', 'Agents', 'Usage', 'Subscription'];

export default function AdminDashboardScreen({ onNav }) {
  const [activeTab, setActiveTab] = useState('Users');

  return (
    <AppFrame title="dialekt.ai — Admin">
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: T.bg0, minWidth: 0, overflowY: 'auto' }}>
        {/* Header */}
        <div style={{ background: T.bg1, borderBottom: `1px solid ${T.border}`, padding: '16px 32px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 800, letterSpacing: '-0.02em', color: T.text }}>Admin Dashboard</div>
            <div style={{ fontSize: 11, color: T.dim, marginTop: 2 }}>Manage team, agents, and subscription</div>
          </div>
          <button onClick={() => onNav?.('settings')} style={{ background: 'none', border: `1px solid ${T.border}`, color: T.muted, padding: '7px 14px', fontSize: 11, cursor: 'pointer' }}>
            ← BACK TO SETTINGS
          </button>
        </div>

        {/* Tabs */}
        <div style={{ background: T.bg1, borderBottom: `1px solid ${T.border}`, padding: '0 32px', display: 'flex' }}>
          {TABS.map(t => <Tab key={t} label={t} active={activeTab === t} onClick={() => setActiveTab(t)} />)}
        </div>

        {/* Content */}
        <div style={{ flex: 1, padding: '32px 32px', overflowY: 'auto' }}>
          {activeTab === 'Users'        && <UsersTab />}
          {activeTab === 'Agents'       && <AgentsTab />}
          {activeTab === 'Usage'        && <UsageTab />}
          {activeTab === 'Subscription' && <SubscriptionTab />}
        </div>
      </div>
    </AppFrame>
  );
}
