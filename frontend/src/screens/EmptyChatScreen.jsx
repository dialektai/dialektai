import { useState, useEffect, useRef } from 'react';
import { T } from '../tokens.js';
import Icon from '../components/Icon.jsx';
import { AppFrame } from '../components/Shell.jsx';
import LeftPanel from '../components/LeftPanel.jsx';
import RightPanel from '../components/RightPanel.jsx';

const API = 'http://localhost:8765';

const STARTERS = [
  { icon: 'terminal', t: 'Debug this trace', sub: 'paste a stack trace, I\'ll triage' },
  { icon: 'folder',   t: 'Audit the repo',  sub: 'find unused code, risky deps, TODO debt' },
  { icon: 'file',     t: 'Explain a file',  sub: 'walk me through the logic, line by line' },
  { icon: 'globe',    t: 'Research + summarize', sub: '10 tabs → one markdown brief' },
];

function timeAgo(iso) {
  const diff = (Date.now() - new Date(iso)) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 172800) return 'yesterday';
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function EmptyChatScreen({ onNav }) {
  const [text, setText] = useState('');
  const [recents, setRecents] = useState([]);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef(null);
  const folderRef = useRef(null);

  useEffect(() => {
    fetch(`${API}/sessions`)
      .then(r => r.json())
      .then(data => setRecents(data.slice(0, 4)))
      .catch(() => {});
  }, []);

  const go = (msg) => {
    if (!msg.trim()) return;
    onNav('main', { initialMessage: msg.trim() });
  };

  const appendText = (str) => setText(t => t ? t + '\n' + str : str);

  const handleFiles = async (e) => {
    const files = Array.from(e.target.files || []);
    e.target.value = '';
    if (!files.length) return;
    setUploading(true);
    for (const f of files) {
      try {
        const fd = new FormData();
        fd.append('file', f, f.name);
        const res = await fetch(`${API}/upload`, { method: 'POST', body: fd });
        const { path } = await res.json();
        appendText(`@file:${path}`);
      } catch {
        appendText(`@file:${f.name}`);
      }
    }
    setUploading(false);
  };

  const handleScreenshot = async () => {
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 1 }, audio: false });
      const track = stream.getVideoTracks()[0];
      const capture = new ImageCapture(track);
      const bitmap = await capture.grabFrame();
      track.stop();
      stream.getTracks().forEach(t => t.stop());
      const canvas = document.createElement('canvas');
      canvas.width = bitmap.width; canvas.height = bitmap.height;
      canvas.getContext('2d').drawImage(bitmap, 0, 0);
      canvas.toBlob(async (blob) => {
        try {
          const fd = new FormData();
          fd.append('file', blob, 'screenshot.png');
          const res = await fetch(`${API}/upload`, { method: 'POST', body: fd });
          const { path } = await res.json();
          appendText(`@screenshot:${path}`);
        } catch { appendText('@screenshot:failed'); }
      }, 'image/png');
    } catch (err) {
      if (err.name !== 'NotAllowedError') appendText(`[screen capture error: ${err.message}]`);
    }
  };

  return (
    <AppFrame title="dialekt.ai — new conversation">
      <LeftPanel active={-1} onNav={onNav} />
      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', background: T.bg0, minWidth: 0 }}>
        <header style={{
          height: 44, display: 'flex', alignItems: 'center', gap: 12,
          borderBottom: `1px solid ${T.border}`, padding: '0 18px', background: T.bg1, flexShrink: 0,
        }}>
          <span className="mono" style={{ color: T.cyan, fontSize: 10, letterSpacing: '.14em' }}>02 //</span>
          <span style={{ fontSize: 13 }}>New conversation</span>
          <div style={{ flex: 1 }} />
          <span className="mono" style={{ fontSize: 10, color: T.dim }}>⌘N new · ⌘K palette</span>
        </header>

        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', padding: '0 40px', minHeight: 0 }}>
          <div style={{ maxWidth: 820, margin: '0 auto', width: '100%' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 24 }}>
              <div style={{ width: 48, height: 48, border: `1px solid ${T.cyan}`, background: T.bg1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <svg width="28" height="28" viewBox="0 0 18 18">
                  <path d="M2 9 L9 2 L16 9 L9 16 Z" fill="none" stroke={T.cyan} strokeWidth="1.1" />
                  <circle cx="9" cy="9" r="2" fill={T.cyan} />
                </svg>
              </div>
              <div>
                <div className="mono" style={{ fontSize: 10, color: T.cyan, letterSpacing: '.14em' }}>READY · LOCAL</div>
                <div style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.02em', marginTop: 2 }}>What are we working on?</div>
              </div>
            </div>
            <div style={{ fontSize: 13, color: T.muted, lineHeight: 1.6, maxWidth: 620, marginBottom: 28 }}>
              Point me at a directory, paste a trace, attach a screenshot. I can read your filesystem, run shell commands, and drive the browser — all under the permissions you set.
            </div>

            {/* Composer */}
            <input ref={fileRef} type="file" multiple style={{ display: 'none' }} onChange={handleFiles} />
            <input ref={folderRef} type="file" webkitdirectory="" style={{ display: 'none' }} onChange={handleFiles} />
            <div style={{ border: `1px solid ${T.borderHi}`, background: T.bg1, marginBottom: 22 }}>
              <textarea
                value={text}
                onChange={e => setText(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); go(text); } }}
                placeholder="describe the task…"
                rows={2}
                style={{
                  display: 'block', width: '100%', boxSizing: 'border-box',
                  background: 'transparent', border: 'none', outline: 'none',
                  fontFamily: T.mono, fontSize: 13, color: T.text,
                  padding: '12px 14px', resize: 'none', lineHeight: 1.55,
                  caretColor: T.cyan,
                }}
              />
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 10px', borderTop: `1px solid ${T.border}` }}>
                <button className="dlk-btn" onClick={() => folderRef.current?.click()} disabled={uploading}><Icon name="folder" size={12} color={T.cyan} />Attach folder</button>
                <button className="dlk-btn" onClick={() => fileRef.current?.click()} disabled={uploading}><Icon name="file" size={12} color={T.muted} />File</button>
                <button className="dlk-btn" onClick={handleScreenshot}><Icon name="screen" size={12} color={T.muted} />Screenshot</button>
                <div style={{ flex: 1 }} />
                <span className="mono" style={{ fontSize: 10, color: T.dim, marginRight: 6 }}>gemma3-12b · local</span>
                <button
                  className="dlk-btn primary"
                  style={{ padding: '5px 12px', opacity: text.trim() ? 1 : 0.4 }}
                  onClick={() => go(text)}
                >
                  Send <span className="mono" style={{ fontSize: 10, opacity: .7, marginLeft: 4 }}>⏎</span>
                </button>
              </div>
            </div>

            {/* Two columns */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
              <div>
                <div className="upper" style={{ color: T.dim, marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span>Try</span><div style={{ flex: 1, height: 1, background: T.border }} />
                </div>
                {STARTERS.map((s, i) => (
                  <div key={i} onClick={() => go(s.t)} style={{
                    display: 'flex', alignItems: 'center', gap: 12, padding: '10px 12px',
                    border: `1px solid ${T.border}`, borderTop: i === 0 ? `1px solid ${T.border}` : 'none',
                    background: T.bg1, cursor: 'pointer',
                  }}>
                    <Icon name={s.icon} size={14} color={T.cyan} />
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 12, color: T.text }}>{s.t}</div>
                      <div style={{ fontSize: 11, color: T.dim, marginTop: 1 }}>{s.sub}</div>
                    </div>
                    <Icon name="chevR" size={12} color={T.dim} />
                  </div>
                ))}
              </div>
              <div>
                <div className="upper" style={{ color: T.dim, marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span>Recent</span><div style={{ flex: 1, height: 1, background: T.border }} />
                </div>
                {recents.length === 0 ? (
                  <div className="mono" style={{ padding: '18px 12px', fontSize: 11, color: T.dim, border: `1px solid ${T.border}`, background: T.bg1, textAlign: 'center' }}>
                    No sessions yet — start a conversation
                  </div>
                ) : recents.map((s, i) => (
                  <div key={s.id} onClick={() => onNav?.('main', { sessionId: s.id })} style={{
                    display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px',
                    border: `1px solid ${T.border}`, borderTop: i === 0 ? `1px solid ${T.border}` : 'none',
                    background: T.bg1, cursor: 'pointer',
                  }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 12, color: T.text, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.title}</div>
                      <div className="mono" style={{ fontSize: 10, color: T.dim, marginTop: 2 }}>{timeAgo(s.updated_at)} · {s.model}</div>
                    </div>
                    <span className="mono" style={{ fontSize: 10, color: T.dim, border: `1px solid ${T.border}`, padding: '1px 5px' }}>{s.message_count} msgs</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div style={{ borderTop: `1px solid ${T.border}`, padding: '10px 24px', background: T.bg1, display: 'flex', alignItems: 'center', gap: 14 }}>
          <span className="dlk-dot live" />
          <span className="mono" style={{ fontSize: 10, color: T.muted }}>gemma3-12b · local</span>
          <div style={{ flex: 1 }} />
          <span className="mono" style={{ fontSize: 10, color: T.dim }}>0 tokens sent to cloud · ever</span>
        </div>
      </main>
      <RightPanel items={[]} />
    </AppFrame>
  );
}
