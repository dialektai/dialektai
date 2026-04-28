import { useState, useEffect, useCallback, useRef } from 'react';
import { T } from '../tokens.js';
import Icon from '../components/Icon.jsx';
import { AppFrame } from '../components/Shell.jsx';
import McpToolList from '../components/McpToolList.jsx';
import Select from '../components/Select.jsx';

const API = 'http://localhost:8765';

// ── Steps definition ──────────────────────────────────────────────────────────

const STEPS = [
  { label: 'Identity',      icon: 'diamond'  },
  { label: 'Workspace',     icon: 'folder'   },
  { label: 'Model',         icon: 'sparkle'  },
  { label: 'System Prompt', icon: 'chat'     },
  { label: 'Capabilities',  icon: 'shield'   },
  { label: 'MCP Tools',     icon: 'plug'     },
  { label: 'Connections',   icon: 'folder'   },
  { label: 'Secrets',       icon: 'shield'   },
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

function buildManifestYaml(data, mcpServers = []) {
  const now = isoWithOffset();
  const id = typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `agent-${Date.now()}`;

  const tags = data.tags
    ? data.tags.split(',').map(t => t.trim()).filter(Boolean)
    : [];

  const hasMcp = Array.isArray(data.mcp_server_names) && data.mcp_server_names.length > 0;

  // Silent capability injection (product design §3.3 ruling 3). We clone
  // into a local set so the React `data.capabilities` state stays
  // user-authored — only the YAML gets the `mcp_tools` shim.
  const enabledCaps = Object.entries(data.capabilities)
    .filter(([, v]) => v)
    .map(([k]) => k);
  if (hasMcp && !enabledCaps.includes('mcp_tools')) {
    enabledCaps.push('mcp_tools');
  }

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

  // MCP-bearing manifests require the MCP runtime shipped in v0.20.0.
  // Non-MCP manifests stay back-compat with v0.11.x installs.
  const specVersion = hasMcp ? "1.1.0" : "1.0.1";
  const minVersion  = hasMcp ? "0.20.0" : "1.0.0";

  let yaml = `spec_version: "${specVersion}"
minimum_dialekt_version: "${minVersion}"

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

  // Emit mcp_servers block when the user selected any on step 4 AND
  // the caller supplied the fresh server specs (save() does; preview
  // skips the block — the capability + spec_version bump is enough
  // signal in the read-only preview).
  if (hasMcp && mcpServers.length > 0) {
    const selectedSpecs = mcpServers.filter(
      s => data.mcp_server_names.includes(s.name)
    );
    if (selectedSpecs.length > 0) {
      yaml += `\nmcp_servers:\n`;
      selectedSpecs.forEach(s => {
        yaml += `  - name: "${s.name}"\n`;
        yaml += `    transport: "${s.transport}"\n`;
        if (s.transport === 'stdio') {
          const cmd = Array.isArray(s.command) ? s.command : [];
          yaml += `    command:\n`;
          cmd.forEach(arg => {
            yaml += `      - "${String(arg).replace(/"/g, '\\"')}"\n`;
          });
          const envRefs = s.env_refs || {};
          const envKeys = Object.keys(envRefs);
          if (envKeys.length > 0) {
            yaml += `    env:\n`;
            envKeys.forEach(envName => {
              yaml += `      ${envName}: "\${secrets.${envRefs[envName]}}"\n`;
            });
          }
          if (s.cwd) {
            yaml += `    cwd: "${String(s.cwd).replace(/"/g, '\\"')}"\n`;
          }
        } else {
          yaml += `    url: "${String(s.url || '').replace(/"/g, '\\"')}"\n`;
          if (s.auth_type && s.has_auth_token) {
            // auth_ref isn't exposed in the list response; default matches
            // backend (keyring_key(<name>, "auth_token")) unless the user
            // set a custom one during create. We cannot know the ref from
            // the list response — document this limitation in design §10
            // and assume "auth_token" for now; users who customise auth_ref
            // via direct API call own the manifest hand-edit.
            yaml += `    auth:\n`;
            yaml += `      type: "${s.auth_type}"\n`;
            yaml += `      token: "\${secrets.auth_token}"\n`;
          }
        }
        if (s.timeout_seconds && s.timeout_seconds !== 30) {
          yaml += `    timeout_seconds: ${s.timeout_seconds}\n`;
        }
        // v0.22 per-tool scoping. mode='all' → no fields emitted
        // (= "all tools allowed" by runtime). mode='allow' → allow_tools
        // list. mode='deny' → deny_tools list. Empty tool list is
        // semantically equivalent to mode='all', so we skip emission
        // in that edge case.
        const scope = (data.mcp_server_scopes || {})[s.name];
        if (scope && scope.mode === 'allow' && scope.tools.length > 0) {
          yaml += `    allow_tools:\n`;
          scope.tools.forEach(t => {
            yaml += `      - "${String(t).replace(/"/g, '\\"')}"\n`;
          });
        } else if (scope && scope.mode === 'deny' && scope.tools.length > 0) {
          yaml += `    deny_tools:\n`;
          scope.tools.forEach(t => {
            yaml += `      - "${String(t).replace(/"/g, '\\"')}"\n`;
          });
        }
      });
    }
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

function TextInput({ value, onChange, placeholder, style, type }) {
  return (
    <input
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      type={type || 'text'}
      style={{ ...INPUT, ...style }}
    />
  );
}

function ErrMsg({ msg }) {
  if (!msg) return null;
  return <div style={{ fontFamily: T.mono, fontSize: 11, color: T.red, marginTop: 4 }}>{msg}</div>;
}

// ── ModelCombobox: searchable single-select with manual-entry escape hatch ────
// Used for Preferred Model. Lists installed Ollama tags + configured cloud
// provider models; if the user types something not in the list we still let
// them commit it (covers exotic tags, custom Modelfiles, etc.).
function ModelCombobox({ value, onChange, options, loading, placeholder }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [hover, setHover] = useState(0);
  const ref = useRef(null);

  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const q = query.trim().toLowerCase();
  const filtered = options.filter(o => !q || o.label.toLowerCase().includes(q) || o.id.toLowerCase().includes(q));
  const selected = options.find(o => o.id === value);
  const showManualEntry = q && !filtered.some(o => o.id === q || o.label === q);

  const commit = (id) => { onChange(id); setOpen(false); setQuery(''); };

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        style={{
          ...INPUT,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          textAlign: 'left', cursor: 'pointer', padding: '9px 12px',
          fontFamily: T.mono,
          background: open ? T.bg2 : T.bg1,
          borderColor: open ? T.cyan : T.border,
        }}>
        <span style={{ color: value ? T.text : T.dim }}>
          {selected ? selected.label : (value || placeholder)}
          {selected && (
            <span style={{ marginLeft: 10, fontSize: 10, color: selected.installed ? T.green : T.amber, letterSpacing: '.06em' }}>
              {selected.installed ? '● INSTALLED' : '◌ WILL PULL'}
            </span>
          )}
        </span>
        <span style={{ color: T.dim, fontSize: 10, transform: open ? 'rotate(180deg)' : 'none', transition: 'transform .15s' }}>▾</span>
      </button>
      {open && (
        <div style={{
          position: 'absolute', top: 'calc(100% + 4px)', left: 0, right: 0, zIndex: 50,
          background: T.bg1, border: `1px solid ${T.cyan}66`, maxHeight: 320, overflowY: 'auto',
          boxShadow: '0 12px 28px rgba(0,0,0,0.45)',
        }}>
          <div style={{ padding: 8, borderBottom: `1px solid ${T.border}`, position: 'sticky', top: 0, background: T.bg1 }}>
            <input
              autoFocus
              value={query}
              onChange={e => { setQuery(e.target.value); setHover(0); }}
              onKeyDown={e => {
                if (e.key === 'ArrowDown') { e.preventDefault(); setHover(h => Math.min(h + 1, filtered.length - 1)); }
                if (e.key === 'ArrowUp')   { e.preventDefault(); setHover(h => Math.max(h - 1, 0)); }
                if (e.key === 'Enter') {
                  e.preventDefault();
                  if (filtered[hover]) commit(filtered[hover].id);
                  else if (showManualEntry) commit(query.trim());
                }
                if (e.key === 'Escape') setOpen(false);
              }}
              placeholder="search · or type a custom tag"
              style={{ ...INPUT, padding: '7px 10px', fontFamily: T.mono, fontSize: 12, background: T.bg0 }}
            />
          </div>
          {loading && (
            <div style={{ padding: 14, color: T.dim, fontSize: 12 }}>Loading model catalog…</div>
          )}
          {!loading && filtered.length === 0 && !showManualEntry && (
            <div style={{ padding: 14, color: T.dim, fontSize: 12 }}>No models match.</div>
          )}
          {filtered.map((o, i) => {
            const active = i === hover;
            return (
              <div
                key={o.id}
                onMouseEnter={() => setHover(i)}
                onClick={() => commit(o.id)}
                style={{
                  padding: '9px 12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 14,
                  cursor: 'pointer', background: active ? T.bg2 : 'transparent',
                  borderLeft: `2px solid ${active ? T.cyan : 'transparent'}`,
                }}>
                <div>
                  <div style={{ fontFamily: T.mono, fontSize: 13, color: T.text }}>{o.label}</div>
                  <div style={{ fontFamily: T.mono, fontSize: 10, color: T.dim, marginTop: 2 }}>{o.hint}</div>
                </div>
                <span style={{
                  fontSize: 10, fontFamily: T.mono, letterSpacing: '.08em',
                  color: o.installed ? T.green : T.amber,
                }}>
                  {o.installed ? '● READY' : '◌ PULL'}
                </span>
              </div>
            );
          })}
          {showManualEntry && (
            <div
              onClick={() => commit(query.trim())}
              style={{
                padding: '9px 12px', cursor: 'pointer', borderTop: `1px solid ${T.border}`,
                background: T.bg0, fontSize: 12, color: T.muted,
              }}>
              + Use custom tag <span style={{ color: T.cyan, fontFamily: T.mono }}>{query.trim()}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── ModelMultiPicker: chip-based multi-select for fallback models ─────────────
function ModelMultiPicker({ values, onChange, options, loading, placeholder }) {
  const add = (id) => {
    if (!id || values.includes(id)) return;
    onChange([...values, id]);
  };
  const remove = (id) => onChange(values.filter(v => v !== id));

  return (
    <div>
      <ModelCombobox
        value=""
        onChange={add}
        options={options.filter(o => !values.includes(o.id))}
        loading={loading}
        placeholder={placeholder}
      />
      {values.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
          {values.map(v => {
            const o = options.find(x => x.id === v);
            return (
              <span key={v} style={{
                display: 'inline-flex', alignItems: 'center', gap: 8,
                padding: '5px 4px 5px 10px', fontFamily: T.mono, fontSize: 11.5,
                background: T.bg2, border: `1px solid ${T.border}`,
                color: o?.installed === false ? T.amber : T.text,
              }}>
                <span>{o?.label || v}</span>
                <button
                  type="button"
                  onClick={() => remove(v)}
                  style={{
                    width: 18, height: 18, lineHeight: '16px', textAlign: 'center',
                    background: 'transparent', border: 'none', color: T.dim,
                    cursor: 'pointer', fontSize: 14,
                  }}
                  title="Remove"
                >×</button>
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
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
          <Select
            variant="full"
            value={data.language}
            onChange={v => setData(d => ({ ...d, language: v }))}
            options={[
              { v: 'en', l: 'English' },
              { v: 'ru', l: 'Russian' },
              { v: 'kk', l: 'Kazakh' },
              { v: 'multi', l: 'Multilingual' },
            ]}
          />
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

// ── Step 1: Workspace ─────────────────────────────────────────────────────────

// Per-agent working directory the user picks on their own disk. Optional —
// agents that don't need filesystem output can leave it blank. When set,
// runtime injects it into MCPServer.config.allowed_file_roots and
// {workspace} in output.destination.path resolves to this value.
//
// The Tauri dialog plugin isn't a hard dep — we dynamic-import on click
// and fall back to the text field if it's not installed (e.g. running
// in a plain browser dev shell). Path validation happens server-side
// when the file/visual tools actually try to write.

function StepWorkspace({ data, setData }) {
  const [browseError, setBrowseError] = useState('');
  const [browsing, setBrowsing] = useState(false);

  const onBrowse = async () => {
    setBrowsing(true);
    setBrowseError('');
    try {
      // The @tauri-apps/plugin-dialog package is optional — it lands
      // when the Rust side adds the dialog plugin. Until then this
      // dynamic import fails at runtime and the user types the path
      // manually. The /* @vite-ignore */ keeps Rolldown from trying
      // to resolve the module at build time.
      const moduleName = '@tauri-apps/plugin-dialog';
      const mod = await import(/* @vite-ignore */ moduleName);
      const picked = await mod.open({
        directory: true,
        multiple: false,
        title: 'Pick the agent workspace folder',
      });
      if (typeof picked === 'string' && picked) {
        setData(d => ({ ...d, working_directory: picked }));
      }
    } catch (e) {
      // Plugin not installed in this build — user can still type the
      // path manually. Surface a one-line hint, not a stack trace.
      setBrowseError('Native picker unavailable — paste the path manually');
    } finally {
      setBrowsing(false);
    }
  };

  return (
    <div>
      <div style={{ fontFamily: T.mono, fontSize: 11, color: T.dim, marginBottom: 6, letterSpacing: '.06em' }}>
        WORKING DIRECTORY — where the agent reads inputs and writes outputs
      </div>
      <div style={{ fontFamily: T.mono, fontSize: 10, color: T.dim, marginBottom: 16, lineHeight: 1.6 }}>
        Optional. Pick a folder on your disk and the agent will be allowed to
        read / write inside it (resumes, programs, .md reports, generated
        images, carousels in <span style={{ color: T.cyan }}>media/</span>).
        Leave empty if your agent doesn't need filesystem output.
      </div>
      <Field label="Workspace path">
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <TextInput
            value={data.working_directory}
            onChange={v => setData(d => ({ ...d, working_directory: v }))}
            placeholder="/home/user/iba-content"
          />
          <button
            onClick={onBrowse}
            disabled={browsing}
            style={{
              ...INPUT,
              cursor: browsing ? 'wait' : 'pointer',
              padding: '6px 14px', width: 'auto',
              fontFamily: T.mono, fontSize: 11, letterSpacing: '.04em',
              color: T.cyan, borderColor: T.cyan,
            }}
          >
            {browsing ? '…' : 'BROWSE'}
          </button>
        </div>
        {browseError ? (
          <div style={{ fontFamily: T.mono, fontSize: 10, color: T.dim, marginTop: 6 }}>
            {browseError}
          </div>
        ) : null}
      </Field>
      <div style={{
        marginTop: 12, padding: 12,
        background: T.bg1, border: `1px solid ${T.border}`,
        fontFamily: T.mono, fontSize: 10, color: T.dim, lineHeight: 1.6,
      }}>
        <div style={{ color: T.cyan, marginBottom: 6 }}>EXPECTED LAYOUT</div>
        <div>{'{workspace}/'}</div>
        <div>&nbsp;&nbsp;reports/&nbsp;&nbsp;&nbsp;&nbsp;# .md reports</div>
        <div>&nbsp;&nbsp;resumes/&nbsp;&nbsp;&nbsp;&nbsp;# trainer bios</div>
        <div>&nbsp;&nbsp;programs/&nbsp;&nbsp;&nbsp;# course / training pages</div>
        <div>&nbsp;&nbsp;media/&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;# rendered images</div>
        <div>&nbsp;&nbsp;media/carousel/{'{date}-{name}/slide_NN.png'}</div>
        <div style={{ marginTop: 6 }}>
          Subfolders are created automatically on first write.
        </div>
      </div>
    </div>
  );
}

// ── Step 2: Model ─────────────────────────────────────────────────────────────

function StepModel({ data, setData }) {
  const [installed, setInstalled] = useState([]);   // [{ id, label, kind, hint, installed }]
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([
      fetch('http://127.0.0.1:11434/api/tags').then(r => r.ok ? r.json() : { models: [] }),
      fetch(`${API}/llm/catalog`).then(r => r.json()),
      fetch(`${API}/llm/providers`).then(r => r.json()),
    ]).then(([tagsRes, catRes, provRes]) => {
      if (cancelled) return;
      const installedTags = new Set(((tagsRes.value?.models) || []).map(m => m.name));
      const opts = [];
      // Ollama: every locally installed tag (always pickable, no extra cost).
      for (const t of installedTags) {
        opts.push({
          id: t,
          label: t.replace(/:latest$/, ''),
          kind: 'ollama',
          hint: 'Local · installed',
          installed: true,
        });
      }
      // Ollama catalog (suggested but not yet pulled). Skip duplicates.
      for (const m of (catRes.value?.ollama || [])) {
        const tag = `${m.name}:${(m.tag || '').split('-')[0] || 'latest'}`;
        if (installedTags.has(tag) || installedTags.has(`${m.name}:latest`)) continue;
        opts.push({
          id: tag,
          label: tag,
          kind: 'ollama',
          hint: `Local · ${m.size_gb ? m.size_gb + ' GB download' : 'will pull on first run'}`,
          installed: false,
        });
      }
      // Cloud providers — only those configured (have credentials saved).
      for (const p of (provRes.value?.providers || [])) {
        if (!p.configured) continue;
        for (const m of (p.models || [])) {
          opts.push({
            id: `${p.id}/${m}`,
            label: `${p.id}/${m}`,
            kind: 'cloud',
            hint: `Cloud · ${p.label || p.id}`,
            installed: true,
          });
        }
      }
      setInstalled(opts);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, []);

  const acceptable = (data.model_acceptable || '')
    .split('\n').map(s => s.trim()).filter(Boolean);
  const updateAcceptable = (next) => {
    setData(d => ({ ...d, model_acceptable: next.join('\n') }));
  };

  return (
    <div>
      <Field label="Preferred Model">
        <ModelCombobox
          value={data.model_preferred}
          onChange={v => setData(d => ({ ...d, model_preferred: v }))}
          options={installed}
          loading={loading}
          placeholder="Pick a model…"
        />
        <div style={{ fontFamily: T.mono, fontSize: 10, color: T.dim, marginTop: 6 }}>
          {loading ? 'Loading model catalog…'
            : `${installed.filter(o => o.kind === 'ollama' && o.installed).length} installed locally · ${installed.filter(o => o.kind === 'cloud').length} cloud · ${installed.filter(o => !o.installed).length} pullable`}
        </div>
      </Field>
      <Field label="Acceptable Models (fallbacks)">
        <ModelMultiPicker
          values={acceptable}
          onChange={updateAcceptable}
          options={installed.filter(o => o.id !== data.model_preferred)}
          loading={loading}
          placeholder="Add a fallback model…"
        />
        <div style={{ fontFamily: T.mono, fontSize: 10, color: T.dim, marginTop: 6 }}>
          Used in order if the preferred model isn't available at runtime.
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

// Keys here must match the manifest schema's CAPABILITY_GROUPS set —
// the upstream validator's CAPABILITY_GROUPS plus
// dialekt.manifest_capabilities.EXTRA_CAPABILITY_GROUPS. The wizard
// once emitted `filesystem` / `terminal` / `screen` which the
// validator rejected; the renaming fixed that, and the v1.1
// expansion adds workflow-specific capabilities (web/RSS/Bitrix/
// Instagram/visual workspace) so the same wizard surface can author
// content + monitoring agents without bespoke screens.
const CAP_META = {
  // v1.0 baseline
  filesystem_read:          { label: 'Filesystem',     desc: 'Read and write local files and directories' },
  network:                  { label: 'Network',        desc: 'Make HTTP requests and fetch remote resources' },
  browser:                  { label: 'Browser',        desc: 'Control a headless browser, scrape pages, interact with web UIs' },
  database_read:            { label: 'Database Read',  desc: 'Run read-only SELECT queries on connected databases' },
  shell_execute:            { label: 'Terminal',       desc: 'Execute shell commands and scripts on this machine' },
  screen_capture:           { label: 'Screen',         desc: 'Capture screenshots and observe the current display' },
  // v1.1 — workflow-specific
  web_search:               { label: 'Web Search',     desc: 'Search the live web (Tavily / Brave / DuckDuckGo)' },
  web_crawl:                { label: 'Web Crawl',      desc: 'Fetch full page HTML and extract content for analysis' },
  rss_read:                 { label: 'RSS Read',       desc: 'Subscribe to RSS / Atom feeds and process new items each tick' },
  instagram_publish:        { label: 'Instagram',      desc: 'Publish feed posts, stories, and reels via the Graph API' },
  bitrix_write:             { label: 'Bitrix',         desc: 'Call any Bitrix24 REST method through an incoming webhook' },
  working_directory_read:   { label: 'Workspace Read', desc: 'Read files inside the agent\'s working directory' },
  working_directory_write:  { label: 'Workspace Write',desc: 'Write files (reports, posts, generated images, carousels) into the agent\'s working directory' },
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

// ── Step 4: MCP Tools ─────────────────────────────────────────────────────────

function StepMcpServers({ data, setData }) {
  const [servers, setServers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [testingId, setTestingId] = useState(null);
  // v0.22: per-server expander UI state (local — ephemera, not persisted).
  // toolsByServer keyed by server.id. Each: {loading, tools[], error}.
  const [expandedIds, setExpandedIds] = useState(new Set());
  const [toolsByServer, setToolsByServer] = useState({});
  // Inline "+ Add MCP server" — minimal form covering the two common transports.
  const [addOpen, setAddOpen] = useState(false);
  const [addError, setAddError] = useState('');
  const [adding, setAdding] = useState(false);
  const [newSrv, setNewSrv] = useState({
    name: '', transport: 'stdio',
    command: '',          // stdio: full command line, e.g. "npx -y @mcp/foo"
    url: '',              // http(s)
    timeout_seconds: 30,
  });

  const refresh = useCallback(async () => {
    setError('');
    try {
      const r = await fetch(`${API}/mcp-servers`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const list = await r.json();
      setServers(Array.isArray(list) ? list : []);
      // Drop selections + scope entries for servers that no longer
      // exist (mentor P2: orphan cleanup spans both name list and
      // scope dict in case server was deleted in another tab).
      const existing = new Set((list || []).map(s => s.name));
      const cleanedNames = (data.mcp_server_names || []).filter(n => existing.has(n));
      const cleanedScopes = Object.fromEntries(
        Object.entries(data.mcp_server_scopes || {}).filter(([n]) => existing.has(n))
      );
      const namesChanged = cleanedNames.length !== (data.mcp_server_names || []).length;
      const scopesChanged = Object.keys(cleanedScopes).length
        !== Object.keys(data.mcp_server_scopes || {}).length;
      if (namesChanged || scopesChanged) {
        setData(d => ({
          ...d,
          mcp_server_names: cleanedNames,
          mcp_server_scopes: cleanedScopes,
        }));
      }
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const toggle = (name, on) => {
    setData(d => {
      const set = new Set(d.mcp_server_names || []);
      if (on) set.add(name); else set.delete(name);
      const nextScopes = { ...(d.mcp_server_scopes || {}) };
      // mentor ruling D: drop scope on uncheck so re-check restarts at
      // "All tools" default rather than silently re-applying old policy
      if (!on) delete nextScopes[name];
      return {
        ...d,
        mcp_server_names: Array.from(set),
        mcp_server_scopes: nextScopes,
      };
    });
  };

  const fetchToolsFor = async (s) => {
    setToolsByServer(prev => ({
      ...prev, [s.id]: { ...(prev[s.id] || {}), loading: true, error: '' }
    }));
    try {
      const r = await fetch(`${API}/mcp-servers/${s.id}/tools`);
      const body = await r.json();
      setToolsByServer(prev => ({
        ...prev,
        [s.id]: { loading: false, tools: body.tools || [], error: body.error || '' }
      }));
    } catch (e) {
      setToolsByServer(prev => ({
        ...prev, [s.id]: { loading: false, tools: [], error: String(e) }
      }));
    }
  };

  const toggleExpander = (s) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(s.id)) {
        next.delete(s.id);
      } else {
        next.add(s.id);
        if (!toolsByServer[s.id]) fetchToolsFor(s);
      }
      return next;
    });
  };

  const setMode = (s, mode) => {
    setData(d => {
      const cur = d.mcp_server_scopes?.[s.name] || { mode: 'all', tools: [] };
      // Mentor ruling Q4: reset checklist on mode flip. For "allow"
      // mode the subtractive default is "all pre-checked"; the actual
      // default tool list is filled in once the tool catalog arrives.
      const allTools = (toolsByServer[s.id]?.tools || []).map(t => t.name);
      const tools = mode === 'allow' ? allTools : mode === 'deny' ? [] : [];
      return {
        ...d,
        mcp_server_scopes: { ...d.mcp_server_scopes, [s.name]: { mode, tools } },
      };
    });
  };

  const toggleToolInScope = (s, toolName, on) => {
    setData(d => {
      const cur = d.mcp_server_scopes?.[s.name] || { mode: 'all', tools: [] };
      const set = new Set(cur.tools || []);
      if (on) set.add(toolName); else set.delete(toolName);
      return {
        ...d,
        mcp_server_scopes: {
          ...d.mcp_server_scopes,
          [s.name]: { ...cur, tools: Array.from(set) },
        },
      };
    });
  };

  const runTest = async (s) => {
    setTestingId(s.id);
    try {
      await fetch(`${API}/mcp-servers/${s.id}/test`, { method: 'POST' });
    } catch (_) { /* refresh will reflect */ }
    await refresh();
    setTestingId(null);
  };

  const selectedCount = (data.mcp_server_names || []).length;

  const saveServer = async () => {
    setAddError('');
    if (!newSrv.name.trim()) { setAddError('Name required'); return; }
    if (newSrv.transport === 'stdio' && !newSrv.command.trim()) {
      setAddError('Command required for stdio transport'); return;
    }
    if (newSrv.transport !== 'stdio' && !newSrv.url.trim()) {
      setAddError('URL required for HTTP transport'); return;
    }
    setAdding(true);
    try {
      const body = {
        name: newSrv.name.trim(),
        transport: newSrv.transport,
        timeout_seconds: parseInt(newSrv.timeout_seconds) || 30,
        env_refs: {},
        env_secrets: [],
      };
      if (newSrv.transport === 'stdio') {
        // Split on whitespace — minimal stdio launcher. Advanced env/cwd
        // configuration stays in Settings → MCP Servers.
        body.command = newSrv.command.trim().split(/\s+/);
      } else {
        body.url = newSrv.url.trim();
      }
      const r = await fetch(`${API}/mcp-servers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const txt = await r.text().catch(() => '');
        setAddError(`Save failed: ${txt.slice(0, 160) || r.status}`);
        setAdding(false);
        return;
      }
      const created = await r.json().catch(() => null);
      await refresh();
      // Auto-select the new server so it shows up checked in the list.
      if (created?.name) toggle(created.name, true);
      setNewSrv({ name: '', transport: 'stdio', command: '', url: '', timeout_seconds: 30 });
      setAddOpen(false);
    } catch (e) {
      setAddError(`Network error: ${e.message || e}`);
    }
    setAdding(false);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div style={{
        border: `1px solid ${T.cyan}33`, background: `${T.cyan}08`,
        padding: '10px 14px', fontSize: 12, color: T.muted,
      }}>
        <span className="mono" style={{ color: T.cyan }}>[i]</span>{' '}
        Selecting any server here adds the <span className="mono" style={{ color: T.text }}>mcp_tools</span> capability automatically.
      </div>

      {loading ? (
        <div style={{ color: T.dim, fontSize: 13 }}>Loading…</div>
      ) : error ? (
        <div style={{ fontSize: 12, color: T.red, display: 'flex', alignItems: 'center', gap: 12 }}>
          <span>Failed to load MCP servers: {error}</span>
          <button onClick={refresh} style={{
            background: 'transparent', border: `1px solid ${T.border}`, color: T.text,
            padding: '4px 12px', fontSize: 11, cursor: 'pointer',
          }}>RETRY</button>
        </div>
      ) : servers.length === 0 ? (
        <div style={{ padding: '20px 16px', fontSize: 13, color: T.muted, textAlign: 'center', background: T.bg1, border: `1px solid ${T.border}` }}>
          No MCP servers configured yet. Click <span style={{ color: T.cyan }}>+ Add MCP server</span> below to wire one in without leaving the wizard.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {servers.map(s => {
            const ready = s.last_test_ok === true;
            const untested = s.last_test_ok == null;
            const failed = s.last_test_ok === false;
            const checked = (data.mcp_server_names || []).includes(s.name);
            const dotColor = ready ? T.green : untested ? T.amber : T.red;
            const statusLabel = ready ? `${s.tool_count || 0} tools`
              : untested ? 'untested'
              : 'error';
            const expanded = expandedIds.has(s.id);
            const toolState = toolsByServer[s.id];
            const scope = data.mcp_server_scopes?.[s.name] || { mode: 'all', tools: [] };
            return (
              <div key={s.id} style={{
                border: `1px solid ${T.border}`, background: T.bg1,
              }}>
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 12,
                  padding: '10px 14px',
                }}>
                  <input type="checkbox" checked={checked} disabled={!ready}
                    onChange={e => toggle(s.name, e.target.checked)}
                    style={{ cursor: ready ? 'pointer' : 'not-allowed' }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, color: T.text }}>{s.name}</div>
                    <div className="mono" style={{ fontSize: 10, color: T.dim }}>
                      {s.transport === 'stdio'
                        ? `stdio · ${(s.command || []).slice(0, 2).join(' ')}${(s.command || []).length > 2 ? ' …' : ''}`
                        : `http · ${s.url}`}
                    </div>
                    {failed && s.last_test_error && (
                      <div style={{ fontSize: 10, color: T.red, marginTop: 4 }}>{s.last_test_error}</div>
                    )}
                  </div>
                  <span className="mono" style={{ fontSize: 11, color: dotColor }} title={s.last_test_error || ''}>
                    ● {statusLabel}
                  </span>
                  {checked && ready && (
                    <button onClick={() => toggleExpander(s)} style={{
                      background: 'transparent', border: `1px solid ${T.border}`, color: T.muted,
                      padding: '4px 10px', fontSize: 10, cursor: 'pointer',
                    }}>{expanded ? '▴ tools' : '▾ tools'}{scope.mode !== 'all' ? ` · ${scope.mode}` : ''}</button>
                  )}
                  {!ready && (
                    <button onClick={() => runTest(s)} disabled={testingId === s.id} style={{
                      background: 'transparent', border: `1px solid ${T.border}`, color: T.text,
                      padding: '4px 10px', fontSize: 10, cursor: testingId === s.id ? 'default' : 'pointer',
                    }}>{testingId === s.id ? 'TESTING…' : (untested ? 'TEST FIRST' : 'RETEST')}</button>
                  )}
                </div>

                {expanded && checked && (
                  <div style={{
                    padding: '10px 14px 14px',
                    borderTop: `1px solid ${T.border}`,
                    display: 'flex', flexDirection: 'column', gap: 10,
                  }}>
                    <div style={{ display: 'flex', gap: 16, fontSize: 11 }}>
                      <span style={{ color: T.dim }}>Mode:</span>
                      {[
                        { v: 'all', l: 'All tools' },
                        { v: 'allow', l: 'Pick specific' },
                        { v: 'deny', l: 'Block some' },
                      ].map(opt => (
                        <label key={opt.v} style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
                          <input type="radio" name={`scope-${s.id}`}
                            checked={scope.mode === opt.v}
                            disabled={!!toolState?.error}
                            onChange={() => setMode(s, opt.v)} />
                          <span style={{ color: scope.mode === opt.v ? T.text : T.muted }}>{opt.l}</span>
                        </label>
                      ))}
                    </div>
                    {scope.mode !== 'all' && (
                      <McpToolList
                        tools={toolState?.tools || []}
                        loading={toolState?.loading}
                        error={toolState?.error}
                        mode="checklist"
                        selectedNames={scope.tools}
                        onToggle={(name, on) => toggleToolInScope(s, name, on)}
                      />
                    )}
                    {scope.mode === 'all' && toolState && !toolState.error && (
                      <div style={{ fontSize: 11, color: T.dim }}>
                        All {(toolState.tools || []).length} tools available — destructive calls still prompt for consent at runtime.
                      </div>
                    )}
                    {toolState?.error && scope.mode !== 'all' && (
                      <div style={{ fontSize: 11, color: T.amber }}>
                        Per-tool scoping disabled — fix server connection first.
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {selectedCount > 0 && (
        <div style={{ fontSize: 11, color: T.muted }}>
          {selectedCount} server{selectedCount === 1 ? '' : 's'} selected. The agent will be able to call tools from {selectedCount === 1 ? 'this server' : 'these servers'}; destructive calls will prompt for consent at runtime.
        </div>
      )}

      {!addOpen && (
        <button
          type="button"
          onClick={() => setAddOpen(true)}
          style={{
            alignSelf: 'flex-start', padding: '8px 14px',
            background: 'transparent', border: `1px dashed ${T.border}`,
            color: T.cyan, fontFamily: T.mono, fontSize: 11, letterSpacing: '.08em',
            cursor: 'pointer',
          }}>+ ADD MCP SERVER</button>
      )}

      {addOpen && (
        <div style={{ background: T.bg1, border: `1px solid ${T.cyan}55`, padding: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 14 }}>
            <span style={{ fontFamily: T.mono, fontSize: 11, color: T.cyan, letterSpacing: '.1em' }}>NEW MCP SERVER</span>
            <button onClick={() => { setAddOpen(false); setAddError(''); }}
              style={{ background: 'transparent', border: 'none', color: T.dim, cursor: 'pointer', fontSize: 14 }}>×</button>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 12 }}>
            <Field label="Name">
              <TextInput value={newSrv.name} onChange={v => setNewSrv(s => ({ ...s, name: v }))}
                placeholder="my-mcp-server" />
            </Field>
            <Field label="Transport">
              <Select
                variant="full"
                value={newSrv.transport}
                onChange={v => setNewSrv(s => ({ ...s, transport: v }))}
                options={[
                  { v: 'stdio', l: 'stdio',         hint: 'local subprocess' },
                  { v: 'http',  l: 'StreamableHTTP', hint: 'remote /mcp endpoint' },
                  { v: 'sse',   l: 'SSE',            hint: 'remote /sse endpoint' },
                ]}
              />
            </Field>
          </div>

          {newSrv.transport === 'stdio' ? (
            <Field label="Command (executable + args)">
              <TextInput
                value={newSrv.command}
                onChange={v => setNewSrv(s => ({ ...s, command: v }))}
                placeholder="npx -y @modelcontextprotocol/server-filesystem /tmp"
                style={{ fontFamily: T.mono }}
              />
            </Field>
          ) : (
            <Field label="URL">
              <TextInput
                value={newSrv.url}
                onChange={v => setNewSrv(s => ({ ...s, url: v }))}
                placeholder="https://my-mcp.example.com/mcp"
                style={{ fontFamily: T.mono }}
              />
            </Field>
          )}

          <div style={{ fontSize: 10, color: T.dim, marginBottom: 12, fontFamily: T.mono, letterSpacing: '.04em' }}>
            Need env vars / auth tokens / custom cwd? Save first, then edit in <span style={{ color: T.muted }}>Settings → MCP Servers</span>.
          </div>

          {addError && (
            <div style={{ fontFamily: T.mono, fontSize: 11, color: T.red, marginBottom: 10 }}>{addError}</div>
          )}

          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={saveServer} disabled={adding}
              style={{
                padding: '8px 16px', background: T.cyan, border: 'none', color: T.bg0,
                fontFamily: T.mono, fontSize: 11, fontWeight: 600, letterSpacing: '.08em',
                cursor: adding ? 'wait' : 'pointer', opacity: adding ? 0.6 : 1,
              }}>{adding ? 'SAVING…' : 'SAVE & CONNECT'}</button>
            <button onClick={() => { setAddOpen(false); setAddError(''); }}
              style={{
                padding: '8px 16px', background: 'transparent',
                border: `1px solid ${T.border}`, color: T.muted,
                fontFamily: T.mono, fontSize: 11, cursor: 'pointer',
              }}>CANCEL</button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Step 5: Connections ───────────────────────────────────────────────────────

const CONN_ENDPOINTS = {
  postgres:   '/connections',
  mysql:      '/mysql-connections',
  clickhouse: '/ch-connections',
};

const CONN_DEFAULTS = {
  postgres:   { port: '5432', label: 'PostgreSQL' },
  mysql:      { port: '3306', label: 'MySQL' },
  clickhouse: { port: '8123', label: 'ClickHouse' },
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

  // Inline "+ Add connection" form state. Stays collapsed until the user
  // explicitly opens it; on save, posts to the per-driver endpoint and
  // refreshes the list so the new row is selectable in the same step.
  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);
  const [addError, setAddError] = useState('');
  const driver = data.connection_type;
  const defaults = CONN_DEFAULTS[driver] || CONN_DEFAULTS.postgres;
  const [newConn, setNewConn] = useState({
    name: '', host: 'localhost', port: defaults.port,
    database: '', username: '', password: '', row_limit: '500',
  });

  useEffect(() => {
    setNewConn(c => ({ ...c, port: (CONN_DEFAULTS[driver] || defaults).port }));
  }, [driver]);

  const saveConnection = async () => {
    setAddError('');
    const required = ['name', 'host', 'database', 'username'];
    for (const f of required) {
      if (!newConn[f]?.trim()) { setAddError(`${f} is required`); return; }
    }
    setSaving(true);
    try {
      const ep = CONN_ENDPOINTS[driver];
      const r = await fetch(`${API}${ep}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newConn.name.trim(), host: newConn.host.trim(),
          port: parseInt(newConn.port) || parseInt(defaults.port),
          database: newConn.database.trim(),
          username: newConn.username.trim(),
          password: newConn.password,
          row_limit: parseInt(newConn.row_limit) || 500,
          ssl: 'prefer',
        }),
      });
      if (!r.ok) {
        const txt = await r.text().catch(() => '');
        setAddError(`Save failed: ${txt.slice(0, 140) || r.status}`);
        setSaving(false);
        return;
      }
      const created = await r.json().catch(() => null);
      // Refresh list and auto-select the new row.
      const fresh = await fetch(`${API}${ep}`).then(r => r.json()).catch(() => []);
      setConnList(Array.isArray(fresh) ? fresh : []);
      const newId = created?.id || created?.name || newConn.name.trim();
      setData(d => ({ ...d, connection_id: newId }));
      setAdding(false);
      setNewConn({ name: '', host: 'localhost', port: defaults.port, database: '', username: '', password: '', row_limit: '500' });
    } catch (e) {
      setAddError(`Network error: ${e.message || e}`);
    }
    setSaving(false);
  };

  return (
    <div>
      <Field label="Connection Type">
        <Select
          variant="full"
          value={data.connection_type}
          onChange={v => setData(d => ({ ...d, connection_type: v, connection_id: '' }))}
          options={[
            { v: 'none', l: 'None' },
            { v: 'postgres', l: 'PostgreSQL' },
            { v: 'mysql', l: 'MySQL' },
            { v: 'clickhouse', l: 'ClickHouse' },
          ]}
        />
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
                No {defaults.label} connections saved yet. Click <span style={{ color: T.cyan }}>+ Add connection</span> below to create one.
              </div>
            ) : (
              <Select
                variant="full"
                value={data.connection_id}
                onChange={v => setData(d => ({ ...d, connection_id: v }))}
                options={[
                  { v: '', l: '— select connection —' },
                  ...connList.map(c => ({ v: c.id || c.name, l: c.name || c.id })),
                ]}
              />
            )}
          </Field>

          {!adding && (
            <button
              type="button"
              onClick={() => setAdding(true)}
              style={{
                marginTop: -10, marginBottom: 18,
                padding: '7px 12px', background: 'transparent',
                border: `1px dashed ${T.border}`, color: T.cyan,
                fontFamily: T.mono, fontSize: 11, cursor: 'pointer',
                letterSpacing: '.06em',
              }}>+ Add {defaults.label} connection</button>
          )}

          {adding && (
            <div style={{
              marginTop: -10, marginBottom: 18, padding: 16,
              background: T.bg1, border: `1px solid ${T.cyan}55`,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 12 }}>
                <span style={{ fontFamily: T.mono, fontSize: 11, color: T.cyan, letterSpacing: '.1em' }}>NEW {defaults.label.toUpperCase()} CONNECTION</span>
                <button onClick={() => { setAdding(false); setAddError(''); }}
                  style={{ background: 'transparent', border: 'none', color: T.dim, cursor: 'pointer', fontSize: 14 }}>×</button>
              </div>
              <Field label="Name">
                <TextInput value={newConn.name} onChange={v => setNewConn(c => ({ ...c, name: v }))}
                  placeholder="prod-analytics" />
              </Field>
              <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 12 }}>
                <Field label="Host">
                  <TextInput value={newConn.host} onChange={v => setNewConn(c => ({ ...c, host: v }))} placeholder="localhost" />
                </Field>
                <Field label="Port">
                  <TextInput value={newConn.port} onChange={v => setNewConn(c => ({ ...c, port: v }))} placeholder={defaults.port} />
                </Field>
              </div>
              <Field label="Database">
                <TextInput value={newConn.database} onChange={v => setNewConn(c => ({ ...c, database: v }))} placeholder="my_db" />
              </Field>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <Field label="Username">
                  <TextInput value={newConn.username} onChange={v => setNewConn(c => ({ ...c, username: v }))} placeholder="readonly_user" />
                </Field>
                <Field label="Password">
                  <input type="password" value={newConn.password}
                    onChange={e => setNewConn(c => ({ ...c, password: e.target.value }))}
                    style={INPUT} placeholder="••••••••" />
                </Field>
              </div>
              {addError && (
                <div style={{ fontFamily: T.mono, fontSize: 11, color: T.red, marginBottom: 10 }}>{addError}</div>
              )}
              <div style={{ display: 'flex', gap: 8 }}>
                <button onClick={saveConnection} disabled={saving}
                  style={{
                    padding: '8px 16px', background: T.cyan, border: 'none', color: T.bg0,
                    fontFamily: T.mono, fontSize: 11, fontWeight: 600, letterSpacing: '.08em',
                    cursor: saving ? 'wait' : 'pointer', opacity: saving ? 0.6 : 1,
                  }}>{saving ? 'SAVING…' : 'SAVE CONNECTION'}</button>
                <button onClick={() => { setAdding(false); setAddError(''); }}
                  style={{
                    padding: '8px 16px', background: 'transparent',
                    border: `1px solid ${T.border}`, color: T.muted,
                    fontFamily: T.mono, fontSize: 11, cursor: 'pointer',
                  }}>CANCEL</button>
              </div>
            </div>
          )}

          <Field label="Role">
            <Select
              variant="full"
              value={data.connection_role}
              onChange={v => setData(d => ({ ...d, connection_role: v }))}
              options={[
                { v: 'readonly',  l: 'Read only',  hint: 'SELECT queries' },
                { v: 'readwrite', l: 'Read / write', hint: 'SELECT + INSERT/UPDATE' },
                { v: 'admin',     l: 'Admin', hint: 'DDL + all operations' },
              ]}
            />
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

// ── Step 7: Secrets ───────────────────────────────────────────────────────────

// Per-agent credentials (Bitrix webhook URL, Instagram access token,
// IG user id, etc.). On Publish they're POSTed to /agents/{id}/secrets
// which stores them under ``agent:{id}:{name}`` in the OS keychain.
// The manifest only carries the names, never the values.
//
// Names must match the keys the agent's MCP tools read by default
// (e.g. ``bitrix_webhook_url``, ``instagram_access_token``,
// ``instagram_ig_user_id``) or whatever the agent's system_prompt
// references. The wizard doesn't enforce a fixed list — different
// agents need different secrets.

function StepSecrets({ data, setData }) {
  const addSecret = () => setData(d => ({
    ...d,
    secrets: [...d.secrets, { name: '', value: '' }],
  }));
  const removeSecret = idx => setData(d => ({
    ...d,
    secrets: d.secrets.filter((_, i) => i !== idx),
  }));
  const updateSecret = (idx, field, value) => setData(d => ({
    ...d,
    secrets: d.secrets.map((s, i) => (i === idx ? { ...s, [field]: value } : s)),
  }));

  return (
    <div>
      <div style={{ fontFamily: T.mono, fontSize: 11, color: T.dim, marginBottom: 6, letterSpacing: '.06em' }}>
        SECRETS — per-agent credentials, stored in the OS keychain
      </div>
      <div style={{ fontFamily: T.mono, fontSize: 10, color: T.dim, marginBottom: 16, lineHeight: 1.6 }}>
        Add the credentials this agent needs (Bitrix webhook URL, Instagram
        access token, etc.). Values never appear in the manifest, in logs,
        or in audit rows — only the names. The MCP tools that need them
        read by name (e.g. <span style={{ color: T.cyan }}>bitrix_webhook_url</span>,{' '}
        <span style={{ color: T.cyan }}>instagram_access_token</span>,{' '}
        <span style={{ color: T.cyan }}>instagram_ig_user_id</span>).
      </div>
      {data.secrets.length === 0 ? (
        <div style={{
          padding: 16, fontFamily: T.mono, fontSize: 11, color: T.dim,
          background: T.bg1, border: `1px dashed ${T.border}`, textAlign: 'center',
        }}>
          No secrets declared yet — click Add Secret if this agent needs credentials.
        </div>
      ) : (
        data.secrets.map((s, idx) => (
          <div key={idx} style={{
            display: 'grid', gridTemplateColumns: '1fr 1fr auto', gap: 8,
            marginBottom: 8, alignItems: 'center',
          }}>
            <TextInput
              value={s.name}
              onChange={v => updateSecret(idx, 'name', v)}
              placeholder="bitrix_webhook_url"
            />
            <TextInput
              value={s.value}
              onChange={v => updateSecret(idx, 'value', v)}
              placeholder="https://portal.bitrix24.kz/rest/1/abcd1234"
              type="password"
            />
            <button
              onClick={() => removeSecret(idx)}
              style={{
                ...INPUT, cursor: 'pointer', padding: '6px 10px', width: 'auto',
                fontFamily: T.mono, fontSize: 11, color: T.dim, borderColor: T.border,
              }}
            >
              ×
            </button>
          </div>
        ))
      )}
      <button
        onClick={addSecret}
        style={{
          ...INPUT, cursor: 'pointer', padding: '8px 14px', marginTop: 12,
          width: 'auto', fontFamily: T.mono, fontSize: 11, letterSpacing: '.04em',
          color: T.cyan, borderColor: T.cyan,
        }}
      >
        + ADD SECRET
      </button>
    </div>
  );
}

// ── Step 8: Variables ─────────────────────────────────────────────────────────

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
              <Select
                variant="full"
                value={v.type || 'string'}
                onChange={val => updateVar(idx, 'type', val)}
                options={[
                  { v: 'string',  l: 'string'  },
                  { v: 'number',  l: 'number'  },
                  { v: 'boolean', l: 'boolean' },
                  { v: 'list',    l: 'list'    },
                ]}
              />
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
      <div style={{ marginBottom: 8 }}>
        <Select
          variant="full"
          value={value}
          onChange={onChange}
          options={AUTONOMY_OPTS.map(o => ({ v: o.value, l: o.label }))}
        />
      </div>
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
// at all (webhook / event) or can't drive end-to-end yet. ``scheduled``
// shipped end-to-end in v0.27 (DialektScheduler + APScheduler + missed-
// run policy + delivery + RSS poll integration), so it's no longer
// gated. Webhook + event remain on the roadmap.
const TRIGGER_OPTS = [
  { value: 'interactive', label: 'Interactive',  desc: 'User types a message to start the agent. Standard chat mode.' },
  { value: 'scheduled',   label: 'Scheduled',    desc: 'Agent runs on a cron schedule without user input. Optional RSS feeds get diffed each tick.' },
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
          <span style={{ color: T.cyan }}>hello@dias.now</span> for early access.
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
          or contact <span style={{ color: T.cyan }}>hello@dias.now</span> for
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
    // v1.1: per-agent working directory. User picks a path on their disk;
    // runtime injects it into MCP allowed_file_roots so file/visual tools
    // can write reports / posts / generated images into it. Empty means
    // "no workspace" — the agent runs without filesystem-bound output.
    working_directory: '',
    // v1.1: per-agent secrets. Names + values entered by the user; on
    // Publish they get POSTed to /agents/{id}/secrets which stores them
    // under ``agent:{id}:{name}`` in the OS keychain. The manifest only
    // carries the names (in secrets_required[]) — never the values.
    secrets: [],
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
    mcp_server_names: [],
    // v0.22 per-server tool scope: { mode: "all"|"allow"|"deny", tools: string[] }.
    // Only servers with explicit scoping appear here; anything else
    // implies mode="all" (= no allow_tools/deny_tools in manifest).
    mcp_server_scopes: {},
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
    // System Prompt step shifted to index 3 in v1.1 after the
    // Workspace step landed at index 1.
    if (stepIdx === 3) {
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
      // Fetch fresh MCP server specs so the manifest inlines the current
      // transport + env config, not a stale wizard-step snapshot. Design
      // doc §3.3 item 1 + impl plan §3 option B.
      let mcpServers = [];
      if (Array.isArray(data.mcp_server_names) && data.mcp_server_names.length > 0) {
        try {
          const mr = await fetch(`${API}/mcp-servers`);
          if (mr.ok) mcpServers = await mr.json();
        } catch (_) { /* leave empty; manifest emission skips the block */ }
      }
      const yaml = buildManifestYaml(data, mcpServers);
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

      // Push per-agent secrets into the OS keychain via /agents/{id}/secrets.
      // Manifest only carries the names (in secrets_required[]); values land
      // here so the agent's MCP tools can read them by name at runtime.
      if (created.id && Array.isArray(data.secrets) && data.secrets.length > 0) {
        const filled = data.secrets.filter(s => s.name && s.value);
        if (filled.length > 0) {
          try {
            const map = {};
            for (const s of filled) map[s.name] = s.value;
            const sr = await fetch(`${API}/agents/${created.id}/secrets`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ secrets: map }),
            });
            if (!sr.ok) {
              const sb = await sr.json().catch(() => ({}));
              addToast(
                `Agent saved but secrets failed: ${sb.detail || sb.error || sr.status}`,
                'warning',
              );
            }
          } catch (secretErr) {
            addToast('Agent saved but secrets push failed — fill them in Settings → Agents', 'warning');
          }
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
      case 0:  return <StepIdentity data={data} setData={setData} errors={errors} />;
      case 1:  return <StepWorkspace data={data} setData={setData} />;
      case 2:  return <StepModel data={data} setData={setData} />;
      case 3:  return <StepSystemPrompt data={data} setData={setData} errors={errors} />;
      case 4:  return <StepCapabilities data={data} setData={setData} />;
      case 5:  return <StepMcpServers data={data} setData={setData} />;
      case 6:  return <StepConnections data={data} setData={setData} />;
      case 7:  return <StepSecrets data={data} setData={setData} />;
      case 8:  return <StepVariables data={data} setData={setData} />;
      case 9:  return <StepAutonomy data={data} setData={setData} />;
      case 10: return <StepTrigger data={data} setData={setData} />;
      case 11: return <StepPublish data={data} saving={saving} onSave={save} />;
      default: return null;
    }
  };

  return (
    <AppFrame title="dias.now — New Agent">
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
