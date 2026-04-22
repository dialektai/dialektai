import { useState } from 'react';
import { T } from '../tokens.js';

const API = 'http://localhost:8765';

function ModeCard({ chosen, title, subtitle, bullets, badge, onClick }) {
  const active = chosen;
  return (
    <div
      onClick={onClick}
      style={{
        flex: 1,
        border: `1px solid ${active ? T.cyan : T.border}`,
        background: active ? `${T.cyan}08` : T.bg1,
        padding: '28px 24px',
        cursor: 'pointer',
        position: 'relative',
        transition: 'border-color .15s, background .15s',
      }}
    >
      {active && (
        <div style={{
          position: 'absolute', top: 12, right: 12,
          width: 8, height: 8, background: T.cyan, borderRadius: '50%',
        }} />
      )}
      <div className="mono" style={{ fontSize: 9, letterSpacing: '.14em', color: T.cyan, marginBottom: 10 }}>
        {badge}
      </div>
      <div style={{ fontSize: 18, fontWeight: 700, letterSpacing: '-0.02em', marginBottom: 8, color: T.text }}>
        {title}
      </div>
      <div style={{ fontSize: 12, color: T.muted, lineHeight: 1.7, marginBottom: 20 }}>
        {subtitle}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {bullets.map((b, i) => (
          <div key={i} style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
            <span style={{ color: T.cyan, fontSize: 10, marginTop: 2 }}>◆</span>
            <span style={{ fontSize: 11, color: T.muted, lineHeight: 1.5 }}>{b}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function ModeSetupScreen({ onNav }) {
  const [mode, setMode] = useState(null);
  const [saving, setSaving] = useState(false);

  const confirm = async () => {
    if (!mode || saving) return;
    setSaving(true);
    try {
      await fetch(`${API}/config/mode`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode }),
      });
      onNav('main');
    } catch {
      setSaving(false);
    }
  };

  return (
    <div style={{
      width: '100%', height: '100%',
      background: T.bg0,
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      padding: '0 40px',
    }}>
      <div style={{ maxWidth: 780, width: '100%' }}>
        {/* Header */}
        <div style={{ marginBottom: 40, textAlign: 'center' }}>
          <div className="mono" style={{ fontSize: 10, color: T.cyan, letterSpacing: '.14em', marginBottom: 12 }}>
            DIALEKT · FIRST LAUNCH
          </div>
          <div style={{ fontSize: 30, fontWeight: 800, letterSpacing: '-0.03em', color: T.text, marginBottom: 12 }}>
            How are you using dialekt?
          </div>
          <div style={{ fontSize: 13, color: T.muted, lineHeight: 1.7, maxWidth: 480, margin: '0 auto' }}>
            This sets your default view. You can switch anytime in Settings.
          </div>
        </div>

        {/* Mode cards */}
        <div style={{ display: 'flex', gap: 16, marginBottom: 32 }}>
          <ModeCard
            chosen={mode === 'builder'}
            badge="MODE 01 · BUILDER"
            title="I'm building agents"
            subtitle="Create, test, and publish agents for your team or yourself."
            bullets={[
              'Visual agent editor with 9-step wizard',
              'Import & export manifest YAML files',
              'Manage connections, permissions, and schedules',
              'Publish agents to team members',
            ]}
            onClick={() => setMode('builder')}
          />
          <ModeCard
            chosen={mode === 'user'}
            badge="MODE 02 · USER"
            title="Someone shared an agent"
            subtitle="Run agents assigned to you. No configuration required."
            bullets={[
              'Clean interface — no technical settings',
              'Agents appear automatically when assigned',
              'Fill in forms, see results, download outputs',
              'Switch to builder mode later if needed',
            ]}
            onClick={() => setMode('user')}
          />
        </div>

        {/* Confirm */}
        <div style={{ display: 'flex', justifyContent: 'center', gap: 12 }}>
          <button
            onClick={confirm}
            disabled={!mode || saving}
            style={{
              padding: '11px 32px',
              background: mode ? T.cyan : T.bg2,
              color: mode ? T.bg0 : T.dim,
              border: 'none', fontFamily: T.ui, fontWeight: 700,
              fontSize: 13, letterSpacing: '-0.01em',
              cursor: mode ? 'pointer' : 'not-allowed',
              transition: 'background .15s, color .15s',
            }}
          >
            {saving ? 'Setting up…' : mode ? `Continue as ${mode === 'builder' ? 'Builder' : 'User'}` : 'Select a mode'}
          </button>
        </div>

        <div className="mono" style={{ textAlign: 'center', marginTop: 20, fontSize: 10, color: T.dim }}>
          Settings → App Mode to change later
        </div>
      </div>
    </div>
  );
}
