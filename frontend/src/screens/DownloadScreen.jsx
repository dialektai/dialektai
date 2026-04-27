import { useState, useEffect, useRef, useCallback } from 'react';
import { T } from '../tokens.js';
import Icon from '../components/Icon.jsx';
import { AppFrame, Logo } from '../components/Shell.jsx';

const API = 'http://localhost:8765';

const DEFAULT_MODELS = [
  { name: 'qwen2.5-coder', tag: '32b-instruct-q5_K_M', size: '22.8 GB', purpose: 'SQL & code generation' },
  { name: 'nomic-embed-text', tag: 'v1.5', size: '274 MB', purpose: 'Schema RAG embeddings' },
];

function fmt(bytes) {
  if (!bytes) return '—';
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

function fmtPct(completed, total) {
  if (!total) return 0;
  return Math.min(100, Math.round((completed / total) * 100));
}

function LayerRow({ digest, total, completed, status }) {
  const pct = fmtPct(completed, total);
  const short = digest ? digest.replace('sha256:', 'sha256:').slice(0, 19) + '…' : status;
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '20px 1fr auto auto',
      gap: 12, alignItems: 'center', padding: '8px 12px',
      borderBottom: `1px solid ${T.border}`,
      background: status === 'active' ? T.bg2 : 'transparent',
    }}>
      {status === 'done'
        ? <Icon name="check" size={13} color={T.green} />
        : status === 'active'
          ? <span className="dlk-dot cyan live" />
          : <span style={{ width: 6, height: 6, border: `1px solid ${T.dim}`, borderRadius: '50%', display: 'inline-block' }} />}
      <span className="mono" style={{ fontSize: 11, color: status === 'queue' ? T.dim : T.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {short}
      </span>
      {status === 'active'
        ? <div style={{ width: 160, height: 4, background: T.bg0, border: `1px solid ${T.border}` }}>
            <div style={{ width: `${pct}%`, height: '100%', background: T.cyan, transition: 'width .3s' }} />
          </div>
        : <span />}
      <span className="mono" style={{ fontSize: 11, minWidth: 80, textAlign: 'right',
        color: status === 'done' ? T.green : status === 'active' ? T.cyan : T.dim }}>
        {status === 'done' ? `✓ ${fmt(total)}` : status === 'active' ? `${pct}% · ${fmt(total)}` : fmt(total) || '—'}
      </span>
    </div>
  );
}

export default function DownloadScreen({ onNav, model: modelProp, onComplete }) {
  const modelName = modelProp || 'qwen2.5-coder:32b-instruct-q5_K_M';
  const [layers, setLayers] = useState({});
  const [overallStatus, setOverallStatus] = useState('idle'); // idle | connecting | pulling | done | error | cancelled
  const [errorMsg, setErrorMsg] = useState('');
  const [currentStatusText, setCurrentStatusText] = useState('');
  const [overallCompleted, setOverallCompleted] = useState(0);
  const [overallTotal, setOverallTotal] = useState(0);
  const abortRef = useRef(null);

  const startDownload = useCallback(async () => {
    setOverallStatus('connecting');
    setLayers({});
    setErrorMsg('');
    setOverallCompleted(0);
    setOverallTotal(0);

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      const url = `${API}/ollama/pull/stream?model=${encodeURIComponent(modelName)}`;
      const resp = await fetch(url, { signal: ctrl.signal });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      setOverallStatus('pulling');

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop();

        for (const line of lines) {
          if (!line.startsWith('data:')) continue;
          const raw = line.slice(5).trim();
          if (!raw) continue;
          try {
            const ev = JSON.parse(raw);
            if (ev.error) {
              setOverallStatus('error');
              setErrorMsg(ev.error);
              return;
            }

            const status = ev.status || '';
            setCurrentStatusText(status);

            if (ev.digest) {
              const digest = ev.digest;
              const total = ev.total || 0;
              const completed = ev.completed || 0;
              const layerStatus = (completed > 0 && completed < total)
                ? 'active'
                : (completed >= total && total > 0) ? 'done' : 'queue';

              setLayers(prev => ({
                ...prev,
                [digest]: { digest, total, completed, status: layerStatus },
              }));

              // aggregate totals for overall progress
              setLayers(prev => {
                const allLayers = Object.values({ ...prev, [digest]: { digest, total, completed, status: layerStatus } });
                const tc = allLayers.reduce((s, l) => s + (l.completed || 0), 0);
                const tt = allLayers.reduce((s, l) => s + (l.total || 0), 0);
                setOverallCompleted(tc);
                setOverallTotal(tt);
                return prev;
              });
            }

            if (status === 'success') {
              setOverallStatus('done');
              if (onComplete) onComplete(modelName);
              return;
            }
          } catch { /* malformed line */ }
        }
      }
      // stream ended without 'success' — check if cancelled
      if (!ctrl.signal.aborted) setOverallStatus('done');
    } catch (e) {
      if (e.name === 'AbortError') {
        setOverallStatus('cancelled');
      } else {
        setOverallStatus('error');
        setErrorMsg(String(e));
      }
    }
  }, [modelName, onComplete]);

  useEffect(() => { startDownload(); return () => abortRef.current?.abort(); }, []);

  const cancel = () => { abortRef.current?.abort(); setOverallStatus('cancelled'); };

  const overallPct = fmtPct(overallCompleted, overallTotal);
  const layerList = Object.values(layers);
  const doneCount = layerList.filter(l => l.status === 'done').length;
  const activeLayer = layerList.find(l => l.status === 'active');

  const statusColor = { done: T.green, error: T.red, cancelled: T.amber }[overallStatus] || T.cyan;

  return (
    <AppFrame title={`dias.now — pulling ${modelName}`}>
      <div style={{ flex: 1, display: 'flex', background: T.bg0, minWidth: 0 }}>
        {/* Sidebar */}
        <div style={{ width: 300, background: T.bg1, borderRight: `1px solid ${T.border}`, padding: '36px 28px', display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 40 }}>
            <Logo />
            <div>
              <div style={{ fontSize: 15, fontWeight: 700 }}>dialekt<span style={{ color: T.cyan }}>.ai</span></div>
              <div className="mono" style={{ fontSize: 10, color: T.dim, letterSpacing: '.1em' }}>SETUP · STEP 3/5</div>
            </div>
          </div>

          <div className="mono" style={{ fontSize: 10, color: T.cyan, letterSpacing: '.14em', marginBottom: 10 }}>DOWNLOADING</div>
          <div style={{ fontSize: 20, fontWeight: 700, letterSpacing: '-0.02em', lineHeight: 1.2, marginBottom: 10, color: T.text }}>
            Pulling weights<br />to <span style={{ color: T.cyan }}>this machine.</span>
          </div>
          <div style={{ fontSize: 12, color: T.muted, lineHeight: 1.55, marginBottom: 24 }}>
            Downloaded once, runs forever. You can close dialekt — download resumes on next launch.
          </div>

          <div style={{ padding: 12, border: `1px solid ${T.border}`, background: T.bg0, marginBottom: 16 }}>
            <div style={{ fontSize: 9, letterSpacing: '.1em', color: T.dim, marginBottom: 6 }}>MODEL</div>
            <div className="mono" style={{ fontSize: 12, color: T.text, wordBreak: 'break-all' }}>{modelName}</div>
          </div>

          <div style={{ flex: 1 }} />

          {overallStatus === 'done'
            ? <button
                onClick={() => onNav?.('onboarding-step4')}
                style={{ padding: '10px 20px', background: T.cyan, color: T.bg0, border: 'none', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}
              >CONTINUE →</button>
            : overallStatus === 'pulling' || overallStatus === 'connecting'
              ? <button onClick={() => { cancel(); onNav?.('main'); }}
                  style={{ padding: '10px 20px', background: 'none', border: `1px solid ${T.border}`, color: T.muted, fontSize: 12, cursor: 'pointer' }}
                >Continue in background</button>
              : null}

          {overallStatus === 'cancelled' && (
            <button onClick={startDownload}
              style={{ padding: '10px 20px', background: T.bg2, border: `1px solid ${T.border}`, color: T.text, fontSize: 12, cursor: 'pointer', marginBottom: 8 }}
            >RESUME DOWNLOAD</button>
          )}
        </div>

        {/* Main */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '36px 40px' }}>
          {/* Overall progress block */}
          <div style={{ border: `1px solid ${T.border}`, background: T.bg1, padding: 22, marginBottom: 18 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
              <span className="mono" style={{ fontSize: 10, color: statusColor, letterSpacing: '.14em' }}>
                {overallStatus.toUpperCase()}
              </span>
              {(overallStatus === 'pulling' || overallStatus === 'connecting') && <span className="dlk-dot cyan live" />}
            </div>

            <div className="mono" style={{ fontSize: 18, fontWeight: 600, letterSpacing: '-0.01em', marginBottom: 18, color: T.text, wordBreak: 'break-all' }}>
              {modelName.split(':')[0]}
              <span style={{ color: T.cyan }}>:{modelName.split(':')[1] || 'latest'}</span>
            </div>

            {/* Progress bar */}
            <div style={{ position: 'relative', height: 28, background: T.bg0, border: `1px solid ${T.border}`, marginBottom: 16 }}>
              <div style={{
                position: 'absolute', inset: 0, width: `${overallPct}%`,
                background: overallStatus === 'done' ? T.green : overallStatus === 'error' ? T.red : T.cyan,
                transition: 'width .5s, background .3s',
              }} className={overallStatus === 'pulling' ? 'dlk-scan' : undefined} />
              <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <span className="mono" style={{ fontSize: 12, fontWeight: 600, color: T.text, letterSpacing: '.08em' }}>
                  {overallStatus === 'done' ? '✓ Complete' :
                   overallStatus === 'error' ? `✗ Error` :
                   overallStatus === 'cancelled' ? '— Cancelled' :
                   overallStatus === 'connecting' ? 'Connecting…' :
                   overallTotal > 0
                     ? `${fmt(overallCompleted)} / ${fmt(overallTotal)} · ${overallPct}%`
                     : currentStatusText || 'Waiting…'}
                </span>
              </div>
            </div>

            {/* Stats row */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', border: `1px solid ${T.border}` }}>
              {[
                ['Layers', `${doneCount} / ${layerList.length}`],
                ['Downloaded', fmt(overallCompleted)],
                ['Status', currentStatusText || (overallStatus === 'connecting' ? 'connecting' : '—')],
              ].map(([k, v], i) => (
                <div key={k} style={{ padding: '10px 14px', borderRight: i < 2 ? `1px solid ${T.border}` : 'none' }}>
                  <div style={{ fontSize: 9, letterSpacing: '.1em', color: T.dim }}>{k.toUpperCase()}</div>
                  <div className="mono" style={{ fontSize: 13, fontWeight: 500, marginTop: 4, color: T.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{v}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Error message */}
          {overallStatus === 'error' && (
            <div style={{ padding: '12px 16px', background: T.bg1, border: `1px solid ${T.red}`, color: T.red, fontSize: 12, marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>{errorMsg}</span>
              <button onClick={startDownload} style={{ background: 'none', border: `1px solid ${T.red}`, color: T.red, padding: '4px 12px', fontSize: 11, cursor: 'pointer' }}>RETRY</button>
            </div>
          )}

          {/* Layer list */}
          {layerList.length > 0 && (
            <>
              <div style={{ display: 'flex', alignItems: 'center', marginBottom: 10 }}>
                <span style={{ fontSize: 9, letterSpacing: '.1em', color: T.dim }}>LAYERS</span>
                <div style={{ flex: 1, height: 1, margin: '0 10px', background: `repeating-linear-gradient(90deg, ${T.border} 0 4px, transparent 4px 8px)` }} />
                <span className="mono" style={{ fontSize: 10, color: T.dim }}>
                  {doneCount} done · {layerList.length - doneCount} remaining
                </span>
              </div>
              <div style={{ border: `1px solid ${T.border}`, background: T.bg1 }}>
                {layerList.map((l, i) => (
                  <LayerRow key={l.digest || i} {...l} />
                ))}
              </div>
            </>
          )}

          {/* Action row */}
          {overallStatus === 'pulling' && (
            <div style={{ display: 'flex', gap: 10, marginTop: 18 }}>
              <button onClick={cancel}
                style={{ padding: '7px 14px', background: 'none', border: `1px solid ${T.border}`, color: T.muted, fontSize: 11, cursor: 'pointer' }}>
                Cancel
              </button>
            </div>
          )}
        </div>
      </div>
    </AppFrame>
  );
}
