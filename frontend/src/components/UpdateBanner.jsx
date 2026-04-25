import { useEffect, useState } from 'react';
import { T } from '../tokens.js';

const REPO = 'dialektai/dialektai';

// Strip leading "v" + any pre-release suffix; compare numeric x.y.z.
// Returns 1 if a > b, -1 if a < b, 0 if equal. Pilot-stage simple — no
// full SemVer 2.0 ordering of pre-release tags (we don't ship those yet).
function cmpVer(a, b) {
  const norm = (s) => String(s).replace(/^v/, '').split(/[-+]/)[0].split('.').map(Number);
  const [ax = 0, ay = 0, az = 0] = norm(a);
  const [bx = 0, by = 0, bz = 0] = norm(b);
  if (ax !== bx) return ax > bx ? 1 : -1;
  if (ay !== by) return ay > by ? 1 : -1;
  if (az !== bz) return az > bz ? 1 : -1;
  return 0;
}

/**
 * Top-of-window nag banner shown when GitHub's `releases/latest` advertises
 * a newer version than the running desktop bundle. Dismissal is keyed by
 * the new tag so each release re-prompts exactly once per machine.
 *
 * No-ops outside Tauri (dev / web preview) — `__TAURI_INTERNALS__` gate.
 */
export default function UpdateBanner() {
  const [latest, setLatest] = useState(null); // { tag, url }
  const [current, setCurrent] = useState(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (!window.__TAURI_INTERNALS__) return;
    let cancelled = false;
    (async () => {
      try {
        const { getVersion } = await import('@tauri-apps/api/app');
        const cur = await getVersion();
        if (cancelled) return;
        setCurrent(cur);
        const r = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`, {
          headers: { 'Accept': 'application/vnd.github+json' },
        });
        if (!r.ok) return;
        const data = await r.json();
        const tag = data.tag_name;
        if (cancelled || !tag) return;
        if (cmpVer(tag, cur) > 0) {
          if (localStorage.getItem(`update-banner-dismissed:${tag}`)) {
            setDismissed(true);
          }
          setLatest({ tag, url: data.html_url });
        }
      } catch {
        // network / parse — silent
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (!latest || dismissed) return null;

  const handleDownload = async () => {
    try {
      const { open } = await import('@tauri-apps/plugin-shell');
      await open(latest.url);
    } catch {
      // shell plugin missing — fall back to webview navigation
      window.location.href = latest.url;
    }
  };

  const handleDismiss = () => {
    localStorage.setItem(`update-banner-dismissed:${latest.tag}`, '1');
    setDismissed(true);
  };

  return (
    <div style={{
      padding: '6px 14px',
      background: T.bg2,
      borderBottom: `1px solid ${T.border}`,
      display: 'flex', alignItems: 'center', gap: 12,
      fontSize: 11, fontFamily: T.mono, color: T.muted,
      flexShrink: 0,
    }}>
      <span style={{ color: T.cyan, letterSpacing: '.08em' }}>↑ UPDATE</span>
      <span style={{ flex: 1 }}>
        New release <span style={{ color: T.text }}>{latest.tag}</span> available
        {current ? <> — you're on <span style={{ color: T.text }}>{current}</span></> : null}
      </span>
      <button
        onClick={handleDownload}
        style={{
          background: 'transparent',
          border: `1px solid ${T.cyan}66`,
          color: T.cyan,
          padding: '3px 10px', fontSize: 11,
          cursor: 'pointer', letterSpacing: '.04em',
          fontFamily: T.mono,
        }}>Download →</button>
      <button
        onClick={handleDismiss}
        aria-label="Dismiss"
        style={{
          background: 'transparent', border: 'none',
          color: T.dim, fontSize: 14,
          cursor: 'pointer', padding: '0 4px',
        }}>×</button>
    </div>
  );
}
