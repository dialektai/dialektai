import { T } from '../tokens.js';
import { AppFrame, Logo } from '../components/Shell.jsx';
import { APP_VERSION } from '../version.js';

const steps = [
  { n: '01', t: 'License & privacy' },
  { n: '02', t: 'Choose your model' },
  { n: '03', t: 'Grant permissions' },
  { n: '04', t: 'Index your workspace' },
  { n: '05', t: 'First conversation' },
];

export default function OnboardingShell({ step, title, blurb, cta = 'Continue', loading = false, onCtaClick, onNav, children }) {
  return (
    <AppFrame title={`dias.now — onboarding · step ${step}`}>
      <div style={{ flex: 1, display: 'flex', background: T.bg0, minWidth: 0 }}>
        <div style={{ width: 320, background: T.bg1, borderRight: `1px solid ${T.border}`, padding: '36px 32px', display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 40 }}>
            <Logo />
            <div>
              <div style={{ fontSize: 15, fontWeight: 600 }}>dialekt<span style={{ color: T.cyan }}>.ai</span></div>
              <div className="mono" style={{ fontSize: 10, color: T.dim, letterSpacing: '.1em' }}>LOCAL-FIRST · v{APP_VERSION}</div>
            </div>
          </div>
          <div className="mono" style={{ fontSize: 10, color: T.cyan, letterSpacing: '.14em', marginBottom: 10 }}>
            {String(step).padStart(2, '0')} / 05
          </div>
          <div style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.02em', lineHeight: 1.18, marginBottom: 10 }}>
            {title}
          </div>
          <div style={{ fontSize: 12, color: T.muted, lineHeight: 1.55 }}>{blurb}</div>

          <div style={{ flex: 1 }} />

          <div style={{ marginTop: 24, display: 'flex', flexDirection: 'column', gap: 2 }}>
            {steps.map((s, i) => {
              const n = i + 1;
              const done = n < step;
              const active = n === step;
              return (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', color: active ? T.text : done ? T.muted : T.dim }}>
                  <span className="mono" style={{ fontSize: 10, color: active ? T.cyan : done ? T.green : T.dim, width: 22 }}>{done ? '✓' : s.n}</span>
                  <span style={{ fontSize: 12, fontWeight: active ? 500 : 400 }}>{s.t}</span>
                  {active && <div style={{ flex: 1, height: 1, marginLeft: 6, background: `linear-gradient(90deg, ${T.cyan}, transparent)` }} />}
                </div>
              );
            })}
          </div>
        </div>

        <div className="dlk-scroll" style={{ flex: 1, overflowY: 'auto', padding: '36px 44px' }}>
          {children}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 28, borderTop: `1px solid ${T.border}`, paddingTop: 16 }}>
            <div style={{ flex: 1 }} className="mono">
              <span style={{ fontSize: 11, color: T.dim }}>step {step} of 5 · </span>
              <span style={{ fontSize: 11, color: T.muted }}>you can change all of this later</span>
            </div>
            <button className="dlk-btn" onClick={() => onNav?.(`onboarding-step${step - 1}`)} disabled={loading}>Back</button>
            <button className="dlk-btn" onClick={() => step < 5 ? onNav?.(`onboarding-step${step + 1}`) : onNav?.('main')} disabled={loading}>Skip</button>
            <button className="dlk-btn primary"
              style={{ padding: '7px 16px', opacity: loading ? 0.6 : 1, cursor: loading ? 'wait' : 'pointer' }}
              disabled={loading}
              onClick={onCtaClick || (() => step < 5 ? onNav?.(`onboarding-step${step + 1}`) : onNav?.('main'))}>
              {loading ? 'Saving…' : cta}
              {!loading && <span className="mono" style={{ fontSize: 10, opacity: .7, marginLeft: 4 }}>⏎</span>}
            </button>
          </div>
        </div>
      </div>
    </AppFrame>
  );
}
