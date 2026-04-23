import { useState, useEffect, useCallback } from 'react';
import { T } from '../tokens.js';
import Icon from '../components/Icon.jsx';
import { AppFrame } from '../components/Shell.jsx';

const API = 'http://localhost:8765';

// ── Steps definition ──────────────────────────────────────────────────────────

const STEPS = [
  { label: 'Identity',      icon: 'diamond'  },
  { label: 'Model',         icon: 'sparkle'  },
  { label: 'System Prompt', icon: 'chat'     },
  { label: 'Capabilities',  icon: 'shield'   },
  { label: 'Connections',   icon: 'folder'   },
  { label: 'Variables',     icon: 'terminal' },
  { label: 'Autonomy',      icon: 'cog'      },
  { label: 'Trigger',       icon: 'screen'   },
  { label: 'Publish',       icon: 'diamond'  },
];

// ── Autonomy level descriptions ───────────────────────────────────────────────

// Values here must match dialekt_manifest.schema.AUTONOMY_LEVELS exactly.
// Before 2026-04-23 the wizard emitted full-auto / ask-before-run / manual
// which the validator rejected — breaking Publish whenever the user
// picked anything except ask-before-write. Labels stay user-friendly;
// only the string value is schema-bound.
const AUTONOMY_OPTS = [
  { value: 'autonomous',       label: 'Full Auto',        desc: 'Agent acts without asking. Reads, writes, executes, and publishes results autonomously. Use only for trusted, well-tested agents.' },
  { value: 'ask-before-write', label: 'Ask Before Write', desc: 'Agent reads and analyzes freely, but asks for approval before writing files, sending messages, or making persistent changes. Recommended default.' },
  { value: 'review-only',      label: 'Ask Before Run',   desc: 'Agent asks before executing any command or writing data. Safer for agents that interact with external systems or run shell commands.' },
  { value: 'manual',           label: 'Manual',           desc: 'Every action requires user confirmation — including reads. Useful for learning, auditing, or sensitive production environments.' },
];

// ── YAML builder ──────────────────────────────────────────────────────────────

function isoWithOffset(d = new Date()) {
  const pad = n => String(Math.floor(Math.abs(n))).padStart(2, '0');
  const tz = -d.getTimezoneOffset();
  const sign = tz >= 0 ? '+' : '-';
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
    + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds())
    + sign + pad(tz / 60) + ':' + pad(tz % 60);
}

function buildManifestYaml(data) {
  const now = isoWithOffset();
  const id = typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `agent-${Date.now()}`;

  const tags = data.tags
    ? data.tags.split(',').map(t => t.trim()).filter(Boolean)
    : [];

  const enabledCaps = Object.entries(data.capabilities)
    .filter(([, v]) => v)
    .map(([k]) => k);

  const acceptableModels = data.model_acceptable
    ? data.model_acceptable.split('\n').map(m => m.trim()).filter(Boolean)
    : [];

  const ctx = parseInt(data.context_window, 10) || 32768;
  const temperature = parseFloat(data.temperature) || 0.7;
  const maxTokens = parseInt(data.max_tokens, 10) || 4096;
  const minRam = parseInt(data.min_ram_gb, 10) || 8;
  const minVram = parseInt(data.min_vram_gb, 10) || 0;
  const recRam = parseInt(data.recommended_ram_gb, 10) || 16;

  const escapeYaml = (s) => String(s || '').replace(/"/g, '\\"');
  const authorName = escapeYaml(data.author_name) || 'dialekt user';
  const authorEmail = escapeYaml(data.author_email) || 'unknown@local';

  let yaml = `spec_version: "1.0.1"
minimum_dialekt_version: "1.0.0"

metadata:
  id: "${id}"
  name: "${data.name || 'Unnamed Agent'}"
  description: "${escapeYaml(data.description)}"
  version: "${data.version}"
  language: "${data.language}"
  tags:
${tags.length ? tags.map(t => `    - "${t}"`).join('\n') : '    []'}
  author:
    name: "${authorName}"
    email: "${authorEmail}"
  created_at: "${now}"
  updated_at: "${now}"

model:
  preferred: "${data.model_preferred}"
  acceptable:
${acceptableModels.length ? acceptableModels.map(m => `    - "${m}"`).join('\n') : '    []'}
  min_context_window: ${ctx}
  requirements:
    min_ram_gb: ${minRam}
    min_vram_gb: ${minVram}
    recommended_ram_gb: ${recRam}
  parameters:
    temperature: ${temperature}
    top_p: 0.95
    max_tokens: ${maxTokens}

system_prompt: |
${(data.system_prompt || '').split('\n').map(l => `  ${l}`).join('\n')}
`;

  // Schema expects a dict keyed by variable name (dialekt_manifest.schema.AgentManifest
  // declares `variables: Optional[dict[str, Variable]]`), not a YAML list.
  // Each Variable has type (string/number/boolean/list) + required + description.
  // We filter out rows with an empty key so an abandoned "Add variable"
  // click doesn't write `: {...}` into the manifest.
  const namedVars = (data.variables || []).filter(v => v.key && v.key.trim());
  if (namedVars.length > 0) {
    yaml += `\nvariables:\n`;
    namedVars.forEach(v => {
      const key = v.key.trim();
      const type = v.type || 'string';
      yaml += `  ${key}:\n`;
      yaml += `    type: "${type}"\n`;
      yaml += `    required: ${v.required ? 'true' : 'false'}\n`;
      yaml += `    description: "${(v.description || '').replace(/"/g, '\\"')}"\n`;
    });
  }

  yaml += `\ncapabilities:\n  groups:\n`;
  if (enabledCaps.length > 0) {
    enabledCaps.forEach(cap => {
      yaml += `    - "${cap}"\n`;
    });
  } else {
    yaml += `    []\n`;
  }

  if (data.connection_type && data.connection_type !== 'none') {
    // Schema shape is {required: [Connection, …]}, not a flat list. Fields
    // are type + role + purpose; the specific connection_id is NOT part
    // of the manifest — binding lives in agent_bindings (POST /agents/{id}/binding,
    // which the wizard does separately on publish). `role` and `purpose`
    // are required strings per dialekt_manifest.schema.Connection.
    const role = data.connection_role || 'readonly';
    const purpose = escapeYaml(data.connection_purpose || 'Database access for this agent');
    yaml += `\nconnections:\n  required:\n    - type: "${data.connection_type}"\n      role: "${role}"\n      purpose: "${purpose}"\n`;
  }

  yaml += `\nautonomy:\n  recommended: "${data.autonomy_recommended}"\n  max_allowed: "${data.autonomy_max}"\n`;

  yaml += `\ninput:\n  type: "chat"\n  placeholder: "${(data.input_placeholder || 'Ask me anything...').replace(/"/g, '\\"')}"\n`;

  yaml += `\noutput:\n  format: "${data.output_format || 'markdown'}"\n  streaming: ${data.streaming ? 'true' : 'false'}\n  destination:\n    type: "notification"\n`;

  yaml += `\ntrigger:\n  type: "${data.trigger_type}"\n`;

  return yaml;
}

// ── Toast ─────────────────────────────────────────────────────────────────────

function ToastStack({ toasts }) {
  if (!toasts.length) return null;
  return (
    <div style={{
      position: 'fixed', bottom: 24, right: 24, zIndex: 9999,
      display: 'flex', flexDirection: 'column-reverse', gap: 8, pointerEvents: 'none',
    }}>
      {toasts.map(t => (
        <div key={t.id} style={{
          padding: '10px 16px', background: T.bg3,
          border: `1px solid ${t.type === 'error' ? T.red : t.type === 'success' ? T.green : T.borderHi}`,
          color: t.type === 'error' ? T.red : t.type === 'success' ? T.green : T.text,
          fontFamily: T.mono, fontSize: 12, letterSpacing: '.04em',
          maxWidth: 360, pointerEvents: 'auto',
          boxShadow: '0 4px 24px rgba(0,0,0,0.5)',
        }}>
          {t.msg}
        </div>
      ))}
    </div>
  );
}

function useToasts() {
  const [toasts, setToasts] = useState([]);
  const add = useCallback((msg, type = 'info') => {
    const id = Date.now() + Math.random();
    setToasts(prev => [...prev, { id, msg, type }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 3500);
  }, []);
  return { toasts, addToast: add };
}

// ── Shared input styles ───────────────────────────────────────────────────────

const INPUT = {
  background: T.bg2,
  border: `1px solid ${T.border}`,
  color: T.text,
  padding: '7px 10px',
  fontSize: 12,
  fontFamily: 'inherit',
  width: '100%',
  boxSizing: 'border-box',
  outline: 'none',
};

const LABEL = {
  display: 'block',
  fontFamily: T.mono,
  fontSize: 11,
  color: T.dim,
  letterSpacing: '.1em',
  textTransform: 'uppercase',
  marginBottom: 5,
};

const FIELD = { marginBottom: 18 };

function Field({ label, children }) {
  return (
    <div style={FIELD}>
      <label style={LABEL}>{label}</label>
      {children}
    </div>
  );
}

function TextInput({ value, onChange, placeholder, style }) {
  return (
    <input
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      style={{ ...INPUT, ...style }}
    />
  );
}

function ErrMsg({ msg }) {
  if (!msg) return null;
  return <div style={{ fontFamily: T.mono, fontSize: 11, color: T.red, marginTop: 4 }}>{msg}</div>;
}

// ── Step 0: Identity ──────────────────────────────────────────────────────────

function StepIdentity({ data, setData, errors }) {
  return (
    <div>
      <Field label="Name *">
        <TextInput
          value={data.name}
          onChange={v => setData(d => ({ ...d, name: v }))}
          placeholder="my-awesome-agent"
        />
        <ErrMsg msg={errors.name} />
      </Field>
      <Field label="Description">
        <textarea
          value={data.description}
          onChange={e => setData(d => ({ ...d, description: e.target.value }))}
          placeholder="What does this agent do?"
          rows={3}
          style={{ ...INPUT, resize: 'vertical', fontFamily: 'inherit' }}
        />
      </Field>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <Field label="Version">
          <TextInput
            value={data.version}
            onChange={v => setData(d => ({ ...d, version: v }))}
            placeholder="1.0.0"
          />
        </Field>
        <Field label="Language">
          <select
            value={data.language}
            onChange={e => setData(d => ({ ...d, language: e.target.value }))}
            style={{ ...INPUT, cursor: 'pointer' }}
          >
            <option value="en">English</option>
            <option value="ru">Russian</option>
            <option value="kk">Kazakh</option>
            <option value="multi">Multilingual</option>
          </select>
        </Field>
      </div>
      <Field label="Tags (comma-separated)">
        <TextInput
          value={data.tags}
          onChange={v => setData(d => ({ ...d, tags: v }))}
          placeholder="coding, automation, research"
        />
      </Field>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <Field label="Author name *">
          <TextInput
            value={data.author_name}
            onChange={v => setData(d => ({ ...d, author_name: v }))}
            placeholder="Ivan Ivanov"
          />
          <ErrMsg msg={errors.author_name} />
        </Field>
        <Field label="Author email *">
          <TextInput
            value={data.author_email}
            onChange={v => setData(d => ({ ...d, author_email: v }))}
            placeholder="ivan@company.com"
          />
          <ErrMsg msg={errors.author_email} />
        </Field>
      </div>
    </div>
  );
}

// ── Step 1: Model ─────────────────────────────────────────────────────────────

function StepModel({ data, setData }) {
  return (
    <div>
      <Field label="Preferred Model">
        <TextInput
          value={data.model_preferred}
          onChange={v => setData(d => ({ ...d, model_preferred: v }))}
          placeholder="llama3.2:3b"
        />
        <div style={{ fontFamily: T.mono, fontSize: 10, color: T.dim, marginTop: 4 }}>
          e.g. qwen2.5-coder:32b, llama3.1:70b, gemma3-12b
        </div>
      </Field>
      <Field label="Acceptable Models (one per line)">
        <textarea
          value={data.model_acceptable}
          onChange={e => setData(d => ({ ...d, model_acceptable: e.target.value }))}
          placeholder={"llama3.2:1b\ngemma3:2b"}
          rows={4}
          style={{ ...INPUT, resize: 'vertical', fontFamily: T.mono }}
        />
        <div style={{ fontFamily: T.mono, fontSize: 10, color: T.dim, marginTop: 4 }}>
          Fallback models if preferred is unavailable
        </div>
      </Field>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <Field label="Context Window (tokens)">
          <TextInput
            value={data.context_window}
            onChange={v => setData(d => ({ ...d, context_window: v }))}
            placeholder="32768"
            style={{ fontFamily: T.mono }}
          />
        </Field>
        <Field label="Max Output Tokens">
          <TextInput
            value={data.max_tokens}
            onChange={v => setData(d => ({ ...d, max_tokens: v }))}
            placeholder="4096"
            style={{ fontFamily: T.mono }}
          />
        </Field>
      </div>
      <Field label={`Temperature: ${parseFloat(data.temperature).toFixed(2)}`}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontFamily: T.mono, fontSize: 10, color: T.dim }}>0.0</span>
          <input
            type="range" min="0" max="1" step="0.05"
            value={data.temperature}
            onChange={e => setData(d => ({ ...d, temperature: e.target.value }))}
            style={{ flex: 1, accentColor: T.cyan, cursor: 'pointer' }}
          />
          <span style={{ fontFamily: T.mono, fontSize: 10, color: T.dim }}>1.0</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: T.mono, fontSize: 10, color: T.dim, marginTop: 4 }}>
          <span>deterministic</span>
          <span style={{ color: T.cyan, fontWeight: 600 }}>{parseFloat(data.temperature).toFixed(2)}</span>
          <span>creative</span>
        </div>
      </Field>
    </div>
  );
}

// ── Step 2: System Prompt ─────────────────────────────────────────────────────

function StepSystemPrompt({ data, setData, errors }) {
  const chars = data.system_prompt.length;
  return (
    <div>
      <Field label="System Prompt *">
        <textarea
          value={data.system_prompt}
          onChange={e => setData(d => ({ ...d, system_prompt: e.target.value }))}
          placeholder={`You are a focused AI agent specialized in...\n\nYour primary responsibilities:\n1. ...\n2. ...\n\nAlways respond with structured, actionable output.`}
          rows={14}
          style={{
            ...INPUT,
            resize: 'vertical',
            fontFamily: T.mono,
            fontSize: 12,
            lineHeight: '1.6',
            minHeight: 280,
          }}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6 }}>
          <ErrMsg msg={errors.system_prompt} />
          <span style={{
            fontFamily: T.mono, fontSize: 10, marginLeft: 'auto',
            color: chars < 20 ? T.red : chars > 8000 ? T.amber : T.dim,
          }}>
            {chars.toLocaleString()} chars
          </span>
        </div>
      </Field>
      <div style={{
        padding: '10px 14px', background: T.bg1,
        border: `1px solid ${T.border}`,
        fontFamily: T.mono, fontSize: 11, color: T.dim, lineHeight: 1.7,
      }}>
        <span style={{ color: T.amber }}>TIP</span>{'  '}
        Be specific about the agent's role, output format, and constraints.
        Use ALL CAPS for critical rules. Define the tone and response style.
      </div>
    </div>
  );
}

// ── Step 3: Capabilities ──────────────────────────────────────────────────────

// Keys here must match the manifest schema's CAPABILITY_GROUPS set
// (dialekt_manifest/schema.py:11). Before this fix the wizard emitted
// `filesystem`, `terminal`, `screen` which the validator rejects with
// 422 on publish. Labels are user-facing and can stay friendly.
const CAP_META = {
  filesystem_read: { label: 'Filesystem',    desc: 'Read and write local files and directories' },
  network:         { label: 'Network',       desc: 'Make HTTP requests and fetch remote resources' },
  browser:         { label: 'Browser',       desc: 'Control a headless browser, scrape pages, interact with web UIs' },
  database_read:   { label: 'Database Read', desc: 'Run read-only SELECT queries on connected databases' },
  shell_execute:   { label: 'Terminal',      desc: 'Execute shell commands and scripts on this machine' },
  screen_capture:  { label: 'Screen',        desc: 'Capture screenshots and observe the current display' },
};

function StepCapabilities({ data, setData }) {
  const toggle = key => setData(d => ({
    ...d,
    capabilities: { ...d.capabilities, [key]: !d.capabilities[key] },
  }));

  return (
    <div>
      <div style={{ fontFamily: T.mono, fontSize: 11, color: T.dim, marginBottom: 6, letterSpacing: '.06em' }}>
        DECLARE CAPABILITIES — tag what this agent uses
      </div>
      <div style={{ fontFamily: T.mono, fontSize: 10, color: T.dim, marginBottom: 16, lineHeight: 1.6 }}>
        These tags describe what the agent needs access to. Currently used for documentation
        and future policy enforcement — runtime gates live in Settings → Permissions (global)
        and the Autonomy slider (per-agent).
      </div>
      {Object.entries(CAP_META).map(([key, meta]) => {
        const active = data.capabilities[key];
        return (
          <div
            key={key}
            onClick={() => toggle(key)}
            style={{
              display: 'flex', alignItems: 'flex-start', gap: 14,
              padding: '12px 14px', marginBottom: 8,
              background: active ? `${T.cyan}11` : T.bg1,
              border: `1px solid ${active ? T.cyan : T.border}`,
              cursor: 'pointer',
              transition: 'background 0.15s, border-color 0.15s',
            }}
          >
            <div style={{
              width: 16, height: 16, border: `1px solid ${active ? T.cyan : T.borderHi}`,
              background: active ? T.cyan : 'transparent',
              flexShrink: 0, marginTop: 1,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              {active && (
                <svg width="10" height="10" viewBox="0 0 20 20" fill="none" stroke={T.bg0} strokeWidth="2.5" strokeLinecap="square">
                  <path d="M4 10l4 4 8-8" />
                </svg>
              )}
            </div>
            <div style={{ flex: 1 }}>
              <div style={{
                fontFamily: T.mono, fontSize: 12,
                color: active ? T.cyan : T.text,
                marginBottom: 3, letterSpacing: '.04em',
              }}>
                {meta.label}
              </div>
              <div style={{ fontFamily: T.mono, fontSize: 11, color: T.dim }}>
                {meta.desc}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Step 4: Connections ───────────────────────────────────────────────────────

const CONN_ENDPOINTS = {
  postgres:   '/connections',
  mysql:      '/mysql-connections',
  clickhouse: '/ch-connections',
};

function StepConnections({ data, setData }) {
  const [connList, setConnList] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (data.connection_type === 'none') {
      setConnList([]);
      return;
    }
    const ep = CONN_ENDPOINTS[data.connection_type];
    if (!ep) return;
    setLoading(true);
    fetch(`${API}${ep}`)
      .then(r => r.ok ? r.json() : [])
      .then(rows => setConnList(Array.isArray(rows) ? rows : []))
      .catch(() => setConnList([]))
      .finally(() => setLoading(false));
  }, [data.connection_type]);

  return (
    <div>
      <Field label="Connection Type">
        <select
          value={data.connection_type}
          onChange={e => setData(d => ({ ...d, connection_type: e.target.value, connection_id: '' }))}
          style={{ ...INPUT, cursor: 'pointer' }}
        >
          <option value="none">None</option>
          <option value="postgres">PostgreSQL</option>
          <option value="mysql">MySQL</option>
          <option value="clickhouse">ClickHouse</option>
        </select>
      </Field>

      {data.connection_type !== 'none' && (
        <>
          <Field label="Connection">
            {loading ? (
              <div style={{ fontFamily: T.mono, fontSize: 11, color: T.dim, padding: '8px 0' }}>
                loading connections...
              </div>
            ) : connList.length === 0 ? (
              <div style={{
                padding: '12px 14px', background: T.bg1,
                border: `1px solid ${T.border}`,
                fontFamily: T.mono, fontSize: 11, color: T.dim,
              }}>
                No connections saved — add one in{' '}
                <span style={{ color: T.cyan }}>Settings → Connections</span>
              </div>
            ) : (
              <select
                value={data.connection_id}
                onChange={e => setData(d => ({ ...d, connection_id: e.target.value }))}
                style={{ ...INPUT, cursor: 'pointer' }}
              >
                <option value="">-- select connection --</option>
                {connList.map(c => (
                  <option key={c.id || c.name} value={c.id || c.name}>
                    {c.name || c.id}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Role">
            <select
              value={data.connection_role}
              onChange={e => setData(d => ({ ...d, connection_role: e.target.value }))}
              style={{ ...INPUT, cursor: 'pointer' }}
            >
              <option value="readonly">Read only — SELECT queries</option>
              <option value="readwrite">Read / write — SELECT + INSERT/UPDATE</option>
              <option value="admin">Admin — DDL + all operations</option>
            </select>
          </Field>
          <Field label="Purpose">
            <TextInput
              value={data.connection_purpose}
              onChange={v => setData(d => ({ ...d, connection_purpose: v }))}
              placeholder="Database access for this agent"
            />
          </Field>
        </>
      )}

      {data.connection_type === 'none' && (
        <div style={{
          padding: '14px', background: T.bg1, border: `1px solid ${T.border}`,
          fontFamily: T.mono, fontSize: 11, color: T.dim, lineHeight: 1.7,
        }}>
          No database connection required. Skip this step or configure one if your agent needs SQL access.
        </div>
      )}
    </div>
  );
}

// ── Step 5: Variables ─────────────────────────────────────────────────────────

function StepVariables({ data, setData }) {
  const addVar = () => setData(d => ({
    ...d,
    variables: [...d.variables, { key: '', type: 'string', description: '', required: true }],
  }));

  const removeVar = idx => setData(d => ({
    ...d,
    variables: d.variables.filter((_, i) => i !== idx),
  }));

  const updateVar = (idx, field, val) => setData(d => ({
    ...d,
    variables: d.variables.map((v, i) => i === idx ? { ...v, [field]: val } : v),
  }));

  return (
    <div>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16,
      }}>
        <div style={{ fontFamily: T.mono, fontSize: 11, color: T.dim }}>
          RUNTIME VARIABLES — injected into the agent context at launch
        </div>
        <button
          onClick={addVar}
          style={{
            display: 'flex', alignItems: 'center', gap: 6,
            padding: '6px 12px', background: 'transparent',
            border: `1px solid ${T.cyan}`, color: T.cyan,
            fontFamily: T.mono, fontSize: 11, cursor: 'pointer',
            letterSpacing: '.06em',
          }}
        >
          <Icon name="plus" size={12} color={T.cyan} />
          ADD VARIABLE
        </button>
      </div>

      {data.variables.length === 0 && (
        <div style={{
          padding: '24px', background: T.bg1, border: `1px solid ${T.border}`,
          textAlign: 'center', fontFamily: T.mono, fontSize: 11, color: T.dim,
        }}>
          No variables defined. Add one to inject dynamic values at agent startup.
        </div>
      )}

      {data.variables.map((v, idx) => (
        <div key={idx} style={{
          padding: '12px 14px', marginBottom: 10,
          background: T.bg1, border: `1px solid ${T.border}`,
          position: 'relative',
        }}>
          <button
            onClick={() => removeVar(idx)}
            style={{
              position: 'absolute', top: 10, right: 10,
              background: 'transparent', border: 'none',
              color: T.dim, cursor: 'pointer', padding: 2,
              display: 'flex', alignItems: 'center',
            }}
            title="Remove variable"
          >
            <Icon name="x" size={13} color={T.dim} />
          </button>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 110px 2fr auto', gap: 10, alignItems: 'end' }}>
            <div>
              <label style={LABEL}>Key</label>
              <input
                value={v.key}
                onChange={e => updateVar(idx, 'key', e.target.value)}
                placeholder="API_KEY"
                style={{ ...INPUT, fontFamily: T.mono }}
              />
            </div>
            <div>
              <label style={LABEL}>Type</label>
              <select
                value={v.type || 'string'}
                onChange={e => updateVar(idx, 'type', e.target.value)}
                style={{ ...INPUT, cursor: 'pointer' }}
              >
                <option value="string">string</option>
                <option value="number">number</option>
                <option value="boolean">boolean</option>
                <option value="list">list</option>
              </select>
            </div>
            <div>
              <label style={LABEL}>Description</label>
              <input
                value={v.description}
                onChange={e => updateVar(idx, 'description', e.target.value)}
                placeholder="e.g. OpenAI API key for embeddings"
                style={{ ...INPUT }}
              />
            </div>
            <div style={{ paddingBottom: 1 }}>
              <label style={LABEL}>Required</label>
              <div
                onClick={() => updateVar(idx, 'required', !v.required)}
                style={{
                  width: 40, height: 22, background: v.required ? T.cyan : T.bg3,
                  border: `1px solid ${v.required ? T.cyan : T.borderHi}`,
                  cursor: 'pointer', position: 'relative',
                  transition: 'background 0.15s',
                }}
              >
                <div style={{
                  position: 'absolute', top: 2,
                  left: v.required ? 20 : 2,
                  width: 16, height: 16,
                  background: v.required ? T.bg0 : T.dim,
                  transition: 'left 0.15s',
                }} />
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Step 6: Autonomy ──────────────────────────────────────────────────────────

function AutonomySelect({ label, value, onChange }) {
  const selected = AUTONOMY_OPTS.find(o => o.value === value);
  return (
    <Field label={label}>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        style={{ ...INPUT, cursor: 'pointer', marginBottom: 8 }}
      >
        {AUTONOMY_OPTS.map(o => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
      {selected && (
        <div style={{
          padding: '10px 12px', background: T.bg1,
          border: `1px solid ${T.border}`,
          fontFamily: T.mono, fontSize: 11, color: T.muted, lineHeight: 1.7,
        }}>
          <span style={{ color: T.cyan }}>{selected.label}</span>{'  '}
          {selected.desc}
        </div>
      )}
    </Field>
  );
}

function StepAutonomy({ data, setData }) {
  return (
    <div>
      <div style={{ fontFamily: T.mono, fontSize: 11, color: T.dim, marginBottom: 20, lineHeight: 1.7 }}>
        AUTONOMY LEVELS — control how much the agent can act without user approval.
        Recommended is shown to users; max_allowed is a hard ceiling.
      </div>
      <AutonomySelect
        label="Recommended Level"
        value={data.autonomy_recommended}
        onChange={v => setData(d => ({ ...d, autonomy_recommended: v }))}
      />
      <AutonomySelect
        label="Max Allowed Level"
        value={data.autonomy_max}
        onChange={v => setData(d => ({ ...d, autonomy_max: v }))}
      />
      <div style={{
        padding: '10px 14px', background: T.bg1,
        border: `1px solid ${T.amber}22`,
        fontFamily: T.mono, fontSize: 11, color: T.dim, lineHeight: 1.7,
      }}>
        <span style={{ color: T.amber }}>NOTE</span>{'  '}
        Max allowed cannot be stricter than recommended. Users may choose any level up to the max.
      </div>
    </div>
  );
}

// ── Step 7: Trigger ───────────────────────────────────────────────────────────

// `comingSoon` flags trigger types that the schema either doesn't accept
// at all (webhook / event) or can't drive end-to-end yet (scheduled —
// no scheduler process exists in the backend). They still render in
// the list so the roadmap signal is visible, but Publish is gated.
const TRIGGER_OPTS = [
  { value: 'interactive', label: 'Interactive',  desc: 'User types a message to start the agent. Standard chat mode.' },
  { value: 'scheduled',   label: 'Scheduled',    desc: 'Agent runs on a cron schedule without user input.', comingSoon: true },
  { value: 'webhook',     label: 'Webhook',      desc: 'Agent is invoked via HTTP POST from an external system.', comingSoon: true },
  { value: 'event',       label: 'Event',        desc: 'Agent responds to system events (file change, DB row, etc.).', comingSoon: true },
];

// Helper consumed by the Publish step to disable the button when the
// chosen trigger can't actually run yet.
function triggerSupported(triggerType) {
  const opt = TRIGGER_OPTS.find(o => o.value === triggerType);
  return !!opt && !opt.comingSoon;
}

function StepTrigger({ data, setData }) {
  const selectedOpt = TRIGGER_OPTS.find(o => o.value === data.trigger_type);
  const selectedUnavailable = selectedOpt && selectedOpt.comingSoon;
  return (
    <div>
      <Field label="Trigger Type">
        {TRIGGER_OPTS.map(opt => {
          const active = data.trigger_type === opt.value;
          return (
            <div
              key={opt.value}
              onClick={() => setData(d => ({ ...d, trigger_type: opt.value }))}
              style={{
                display: 'flex', alignItems: 'flex-start', gap: 12,
                padding: '12px 14px', marginBottom: 8,
                background: active ? `${T.cyan}11` : T.bg1,
                border: `1px solid ${active ? T.cyan : T.border}`,
                cursor: 'pointer',
                opacity: opt.comingSoon ? 0.75 : 1,
              }}
            >
              <div style={{
                width: 14, height: 14, border: `1px solid ${active ? T.cyan : T.borderHi}`,
                marginTop: 2, flexShrink: 0, position: 'relative',
                background: active ? T.cyan : 'transparent',
              }}>
                {active && (
                  <div style={{
                    position: 'absolute', inset: 3,
                    background: T.bg0,
                  }} />
                )}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontFamily: T.mono, fontSize: 12, color: active ? T.cyan : T.text }}>
                    {opt.label}
                  </span>
                  {opt.comingSoon && (
                    <span className="mono" style={{
                      fontSize: 9, color: T.amber,
                      border: `1px solid ${T.amber}66`,
                      padding: '1px 6px', letterSpacing: '.08em',
                      textTransform: 'uppercase',
                    }}>Soon</span>
                  )}
                </div>
                <div style={{ fontFamily: T.mono, fontSize: 11, color: T.dim, marginTop: 2 }}>{opt.desc}</div>
              </div>
            </div>
          );
        })}
      </Field>

      {selectedUnavailable && (
        <div style={{
          padding: '12px 14px', marginTop: -4, marginBottom: 12,
          background: `${T.amber}0a`, border: `1px solid ${T.amber}44`,
          fontFamily: T.mono, fontSize: 11, color: T.muted, lineHeight: 1.7,
        }}>
          <span style={{ color: T.amber }}>NOTE</span>{'  '}
          The <span style={{ color: T.text }}>{selectedOpt.label}</span> trigger
          is coming in a future release — contact{' '}
          <span style={{ color: T.cyan }}>hello@dialekt.ai</span> for early access.
          Publish is disabled until you switch to Interactive.
        </div>
      )}

      <Field label="Input Placeholder">
        <TextInput
          value={data.input_placeholder}
          onChange={v => setData(d => ({ ...d, input_placeholder: v }))}
          placeholder="Ask me anything..."
        />
        <div style={{ fontFamily: T.mono, fontSize: 10, color: T.dim, marginTop: 4 }}>
          Shown in the chat input box when the agent is selected
        </div>
      </Field>

      <Field label="Response Streaming">
        <div
          onClick={() => setData(d => ({ ...d, streaming: !d.streaming }))}
          style={{ display: 'flex', alignItems: 'center', gap: 12, cursor: 'pointer' }}
        >
          <div style={{
            width: 44, height: 24,
            background: data.streaming ? T.cyan : T.bg3,
            border: `1px solid ${data.streaming ? T.cyan : T.borderHi}`,
            position: 'relative', transition: 'background 0.15s',
          }}>
            <div style={{
              position: 'absolute', top: 3,
              left: data.streaming ? 22 : 3,
              width: 16, height: 16,
              background: data.streaming ? T.bg0 : T.dim,
              transition: 'left 0.15s',
            }} />
          </div>
          <span style={{ fontFamily: T.mono, fontSize: 12, color: data.streaming ? T.cyan : T.muted }}>
            {data.streaming ? 'ENABLED' : 'DISABLED'}
          </span>
        </div>
        <div style={{ fontFamily: T.mono, fontSize: 10, color: T.dim, marginTop: 6 }}>
          Stream tokens as they are generated (recommended for interactive agents)
        </div>
      </Field>
    </div>
  );
}

// ── Step 8: Publish ───────────────────────────────────────────────────────────

function StepPublish({ data, saving, onSave }) {
  const yaml = buildManifestYaml(data);
  const enabledCaps = Object.entries(data.capabilities).filter(([, v]) => v).map(([k]) => k);
  const vars = data.variables.filter(v => v.key);

  return (
    <div>
      {/* Summary card */}
      <div style={{
        padding: '16px 20px', background: T.bg1,
        border: `1px solid ${T.cyan}44`,
        marginBottom: 20,
      }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16 }}>
          <div style={{
            width: 42, height: 42, background: `${T.cyan}18`,
            border: `1px solid ${T.cyan}`,
            display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
          }}>
            <Icon name="diamond" size={20} color={T.cyan} />
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontFamily: T.mono, fontSize: 15, color: T.text, letterSpacing: '.04em', marginBottom: 4 }}>
              {data.name || <span style={{ color: T.dim }}>Unnamed Agent</span>}
            </div>
            {data.description && (
              <div style={{ fontFamily: 'inherit', fontSize: 12, color: T.muted, marginBottom: 8 }}>
                {data.description}
              </div>
            )}
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <span style={{ fontFamily: T.mono, fontSize: 10, color: T.dim, padding: '2px 6px', border: `1px solid ${T.border}` }}>
                v{data.version}
              </span>
              <span style={{ fontFamily: T.mono, fontSize: 10, color: T.dim, padding: '2px 6px', border: `1px solid ${T.border}` }}>
                {data.model_preferred}
              </span>
              <span style={{ fontFamily: T.mono, fontSize: 10, color: T.cyan, padding: '2px 6px', border: `1px solid ${T.cyan}44` }}>
                {data.trigger_type}
              </span>
              {enabledCaps.length > 0 && (
                <span style={{ fontFamily: T.mono, fontSize: 10, color: T.amber, padding: '2px 6px', border: `1px solid ${T.amber}44` }}>
                  {enabledCaps.length} cap{enabledCaps.length !== 1 ? 's' : ''}
                </span>
              )}
              {vars.length > 0 && (
                <span style={{ fontFamily: T.mono, fontSize: 10, color: T.muted, padding: '2px 6px', border: `1px solid ${T.border}` }}>
                  {vars.length} var{vars.length !== 1 ? 's' : ''}
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* YAML preview */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ fontFamily: T.mono, fontSize: 11, color: T.dim, marginBottom: 6, letterSpacing: '.1em', textTransform: 'uppercase' }}>
          Generated Manifest YAML
        </div>
        <div style={{
          background: T.bg0, border: `1px solid ${T.border}`,
          padding: '14px 16px', maxHeight: 340, overflowY: 'auto',
        }}>
          <pre className="dlk-scroll" style={{
            margin: 0, fontFamily: T.mono, fontSize: 11,
            color: T.muted, lineHeight: 1.65, whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}>
            {yaml}
          </pre>
        </div>
      </div>

      {/* Trigger gate: Publish blocked when user picked a scheduled/webhook/event
          trigger — those options are in the UI as a roadmap signal but the
          backend has no runtime for them yet (no scheduler, no webhook listener). */}
      {!triggerSupported(data.trigger_type) && (
        <div style={{
          padding: '12px 14px', marginBottom: 12,
          background: `${T.amber}0a`, border: `1px solid ${T.amber}44`,
          fontFamily: T.mono, fontSize: 11, color: T.muted, lineHeight: 1.7,
        }}>
          <span style={{ color: T.amber }}>⚠ PUBLISH BLOCKED</span>{'  '}
          This agent is configured with a trigger that isn't available yet.
          Go back to step 8 and pick <span style={{ color: T.text }}>Interactive</span>,
          or contact <span style={{ color: T.cyan }}>hello@dialekt.ai</span> for
          early access to scheduled / webhook / event triggers.
        </div>
      )}

      {/* Action buttons */}
      <div style={{ display: 'flex', gap: 12 }}>
        <button
          onClick={() => onSave('draft')}
          disabled={saving}
          style={{
            flex: 1, padding: '12px', background: 'transparent',
            border: `1px solid ${T.borderHi}`, color: T.muted,
            fontFamily: T.mono, fontSize: 12, cursor: saving ? 'not-allowed' : 'pointer',
            letterSpacing: '.08em', opacity: saving ? 0.6 : 1,
          }}
        >
          {saving ? 'SAVING...' : 'SAVE AS DRAFT'}
        </button>
        <button
          onClick={() => onSave('published')}
          disabled={saving || !triggerSupported(data.trigger_type)}
          style={{
            flex: 2, padding: '12px', background: T.cyan,
            border: `1px solid ${T.cyan}`, color: T.bg0,
            fontFamily: T.mono, fontSize: 12, fontWeight: 700,
            cursor: (saving || !triggerSupported(data.trigger_type)) ? 'not-allowed' : 'pointer',
            letterSpacing: '.1em',
            opacity: (saving || !triggerSupported(data.trigger_type)) ? 0.4 : 1,
          }}
        >
          {saving ? 'PUBLISHING...' : 'PUBLISH AGENT'}
        </button>
      </div>
    </div>
  );
}

// ── Left sidebar step list ────────────────────────────────────────────────────

function StepList({ current, completed }) {
  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
      {STEPS.map((step, idx) => {
        const isActive = idx === current;
        const isDone = completed.has(idx);
        return (
          <div
            key={idx}
            style={{
              display: 'flex', alignItems: 'center', gap: 10,
              padding: '10px 18px 10px 16px',
              borderLeft: isActive ? `2px solid ${T.cyan}` : '2px solid transparent',
              paddingLeft: isActive ? 14 : 16,
              background: isActive ? `${T.cyan}0d` : 'transparent',
            }}
          >
            <span style={{
              fontFamily: T.mono, fontSize: 9,
              color: isActive ? T.cyan : T.dim,
              width: 14, textAlign: 'right', flexShrink: 0,
            }}>
              {idx + 1}
            </span>
            <Icon
              name={step.icon}
              size={13}
              color={isActive ? T.cyan : isDone ? T.green : T.dim}
            />
            <span style={{
              fontFamily: T.mono, fontSize: 11,
              color: isActive ? T.cyan : isDone ? T.muted : T.dim,
              letterSpacing: '.04em', flex: 1,
            }}>
              {step.label}
            </span>
            {isDone && !isActive && (
              <div style={{
                width: 6, height: 6, background: T.green,
                flexShrink: 0,
              }} />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Main screen ───────────────────────────────────────────────────────────────

export default function AgentWizardScreen({ onNav }) {
  const [step, setStep] = useState(0);
  const [completed, setCompleted] = useState(new Set());
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const { toasts, addToast } = useToasts();

  const [data, setData] = useState({
    name: '',
    description: '',
    version: '1.0.0',
    language: 'en',
    tags: '',
    author_name: '',
    author_email: '',
    model_preferred: 'llama3.2:3b',
    model_acceptable: '',
    context_window: '32768',
    temperature: '0.7',
    max_tokens: '4096',
    min_ram_gb: '8',
    min_vram_gb: '0',
    recommended_ram_gb: '16',
    system_prompt: '',
    capabilities: {
      filesystem_read: false,
      network: false,
      browser: false,
      database_read: false,
      shell_execute: false,
      screen_capture: false,
    },
    connection_type: 'none',
    connection_id: '',
    connection_role: 'readonly',
    connection_purpose: 'Database access for this agent',
    variables: [],
    autonomy_recommended: 'ask-before-write',
    autonomy_max: 'ask-before-write',
    trigger_type: 'interactive',
    input_placeholder: 'Ask me anything...',
    streaming: true,
  });

  const validate = useCallback((stepIdx) => {
    const errs = {};
    if (stepIdx === 0) {
      if (!data.name.trim()) errs.name = 'Name is required';
      if (!data.author_name.trim()) errs.author_name = 'Author name is required';
      const email = data.author_email.trim();
      if (!email) errs.author_email = 'Author email is required';
      else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) errs.author_email = 'Invalid email format';
    }
    if (stepIdx === 2) {
      if (data.system_prompt.trim().length < 20)
        errs.system_prompt = 'System prompt must be at least 20 characters';
    }
    setErrors(errs);
    return Object.keys(errs).length === 0;
  }, [data]);

  const goNext = () => {
    if (!validate(step)) return;
    setCompleted(prev => new Set(prev).add(step));
    setStep(s => Math.min(s + 1, STEPS.length - 1));
    setErrors({});
  };

  const goBack = () => {
    setStep(s => Math.max(s - 1, 0));
    setErrors({});
  };

  const save = async (status) => {
    setSaving(true);
    try {
      const yaml = buildManifestYaml(data);
      const res = await fetch(`${API}/agents/import-yaml`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ manifest_yaml: yaml, status }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        // Validator returns detail.errors = [{code, message}, ...]
        const detail = body?.detail;
        const errs = detail && typeof detail === 'object' && Array.isArray(detail.errors)
          ? detail.errors.map(e => e.message || JSON.stringify(e))
          : [typeof detail === 'string' ? detail : (body.error || `HTTP ${res.status}`)];
        errs.slice(0, 8).forEach(m => addToast(m, 'error'));
        if (errs.length > 8) addToast(`…and ${errs.length - 8} more errors`, 'error');
        return;
      }
      const created = await res.json().catch(() => ({}));

      // Persist the DB binding so SQL Analyst (and similar agents) work
      // out-of-the-box. Without this, the binding only lives inside the
      // YAML manifest and agent_bindings stays empty, so DialektSQL has
      // no connection_id at runtime.
      if (created.id && data.connection_id && data.connection_type && data.connection_type !== 'none') {
        try {
          await fetch(`${API}/agents/${created.id}/binding`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              connection_id: data.connection_id,
              connection_type: data.connection_type,
            }),
          });
        } catch (bindErr) {
          // Agent itself was saved — don't fail the flow; user can set
          // the binding later from Settings → Agents.
          addToast('Agent saved but connection binding failed — set it in Settings → Agents', 'warning');
        }
      }

      addToast(status === 'draft' ? 'Agent saved as draft' : 'Agent published successfully', 'success');
      setTimeout(() => onNav('settings'), 600);
    } catch (err) {
      addToast(`Failed to save: ${err.message}`, 'error');
    } finally {
      setSaving(false);
    }
  };

  const isLastStep = step === STEPS.length - 1;
  const isFirstStep = step === 0;

  const stepTitle = STEPS[step].label;

  const renderStep = () => {
    switch (step) {
      case 0: return <StepIdentity data={data} setData={setData} errors={errors} />;
      case 1: return <StepModel data={data} setData={setData} />;
      case 2: return <StepSystemPrompt data={data} setData={setData} errors={errors} />;
      case 3: return <StepCapabilities data={data} setData={setData} />;
      case 4: return <StepConnections data={data} setData={setData} />;
      case 5: return <StepVariables data={data} setData={setData} />;
      case 6: return <StepAutonomy data={data} setData={setData} />;
      case 7: return <StepTrigger data={data} setData={setData} />;
      case 8: return <StepPublish data={data} saving={saving} onSave={save} />;
      default: return null;
    }
  };

  return (
    <AppFrame title="dialekt.ai — New Agent">
      {/* ── Body ── */}
      <div style={{ flex: 1, display: 'flex', minHeight: 0, overflow: 'hidden' }}>

        {/* ── Left panel ── */}
        <div style={{
          width: 220, flexShrink: 0,
          background: T.bg1,
          borderRight: `1px solid ${T.border}`,
          display: 'flex', flexDirection: 'column',
        }}>
          {/* Header */}
          <div style={{
            padding: '14px 16px 12px',
            borderBottom: `1px solid ${T.border}`,
          }}>
            <div style={{ fontFamily: T.mono, fontSize: 9, color: T.dim, letterSpacing: '.14em', marginBottom: 5 }}>
              AGENT WIZARD
            </div>
            <div style={{ fontFamily: T.mono, fontSize: 13, color: T.cyan, letterSpacing: '.06em' }}>
              New Agent
            </div>
          </div>

          <StepList current={step} completed={completed} />

          {/* Back to main */}
          <div style={{ borderTop: `1px solid ${T.border}`, padding: '10px 16px' }}>
            <button
              onClick={() => onNav('main')}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                background: 'transparent', border: 'none',
                color: T.dim, fontFamily: T.mono, fontSize: 11,
                cursor: 'pointer', padding: 0, letterSpacing: '.06em',
              }}
            >
              <Icon name="chevR" size={12} color={T.dim} style={{ transform: 'rotate(180deg)' }} />
              CANCEL
            </button>
          </div>
        </div>

        {/* ── Content area ── */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          {/* Step header */}
          <div style={{
            padding: '16px 28px 14px',
            borderBottom: `1px solid ${T.border}`,
            background: T.bg1,
            flexShrink: 0,
            display: 'flex', alignItems: 'center', gap: 12,
          }}>
            <Icon name={STEPS[step].icon} size={16} color={T.cyan} />
            <div>
              <div style={{ fontFamily: T.mono, fontSize: 9, color: T.dim, letterSpacing: '.14em', marginBottom: 2 }}>
                STEP {step + 1} OF {STEPS.length}
              </div>
              <div style={{ fontFamily: T.mono, fontSize: 14, color: T.text, letterSpacing: '.04em' }}>
                {stepTitle}
              </div>
            </div>
          </div>

          {/* Scrollable step content */}
          <div
            className="dlk-scroll"
            style={{
              flex: 1, overflowY: 'auto',
              padding: '24px 28px',
              background: T.bg0,
            }}
          >
            {renderStep()}
          </div>

          {/* ── Bottom bar ── */}
          {!isLastStep && (
            <div style={{
              borderTop: `1px solid ${T.border}`,
              padding: '12px 24px',
              background: T.bg1,
              display: 'flex', alignItems: 'center', gap: 12,
              flexShrink: 0,
            }}>
              {/* Back */}
              <button
                onClick={goBack}
                disabled={isFirstStep}
                style={{
                  padding: '8px 20px',
                  background: 'transparent',
                  border: `1px solid ${isFirstStep ? T.bg3 : T.borderHi}`,
                  color: isFirstStep ? T.bg3 : T.muted,
                  fontFamily: T.mono, fontSize: 11, cursor: isFirstStep ? 'default' : 'pointer',
                  letterSpacing: '.08em',
                }}
              >
                BACK
              </button>

              {/* Counter */}
              <span style={{
                flex: 1, textAlign: 'center',
                fontFamily: T.mono, fontSize: 11, color: T.dim,
                letterSpacing: '.1em',
              }}>
                {step + 1} / {STEPS.length}
              </span>

              {/* Next */}
              <button
                onClick={goNext}
                style={{
                  padding: '8px 28px',
                  background: T.cyan,
                  border: `1px solid ${T.cyan}`,
                  color: T.bg0,
                  fontFamily: T.mono, fontSize: 11, fontWeight: 700,
                  cursor: 'pointer', letterSpacing: '.1em',
                }}
              >
                NEXT
              </button>
            </div>
          )}

          {/* Publish step has no bottom bar — buttons are inline in StepPublish */}
          {isLastStep && (
            <div style={{
              borderTop: `1px solid ${T.border}`,
              padding: '12px 24px',
              background: T.bg1,
              display: 'flex', alignItems: 'center',
              flexShrink: 0,
            }}>
              <button
                onClick={goBack}
                style={{
                  padding: '8px 20px',
                  background: 'transparent',
                  border: `1px solid ${T.borderHi}`,
                  color: T.muted,
                  fontFamily: T.mono, fontSize: 11, cursor: 'pointer',
                  letterSpacing: '.08em',
                }}
              >
                BACK
              </button>
              <span style={{
                flex: 1, textAlign: 'center',
                fontFamily: T.mono, fontSize: 11, color: T.dim,
                letterSpacing: '.1em',
              }}>
                {step + 1} / {STEPS.length}
              </span>
              <div style={{ width: 90 }} />
            </div>
          )}
        </div>
      </div>

      <ToastStack toasts={toasts} />
    </AppFrame>
  );
}
