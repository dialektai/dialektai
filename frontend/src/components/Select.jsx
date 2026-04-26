import { useState, useEffect, useRef } from 'react';
import { T } from '../tokens.js';

/**
 * Custom dropdown matching the dialekt dark theme. Drop-in replacement for
 * <select> in places where the browser-native control breaks visual flow.
 *
 * Props:
 *   value     — current value (string)
 *   onChange  — fn(newValue)
 *   options   — Array<{ v, l, hint? }>  v: value, l: label, hint: optional small text
 *   minWidth  — optional, default 150
 *   align     — 'left' (default, opens flush-left) or 'right'
 *   variant   — 'compact' (matches Settings) or 'full' (matches wizard fields)
 *   disabled
 */
export default function Select({
  value, onChange, options,
  minWidth, align = 'left', variant = 'compact',
  disabled = false,
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    const close = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  const current = options.find(o => o.v === value);
  const isFull = variant === 'full';

  return (
    <div ref={ref} style={{ position: 'relative', flexShrink: 0, width: isFull ? '100%' : undefined }}>
      <div
        onClick={() => !disabled && setOpen(o => !o)}
        style={{
          display: 'flex', alignItems: 'center', gap: 8,
          minWidth: minWidth || (isFull ? undefined : 150),
          width: isFull ? '100%' : undefined,
          padding: isFull ? '9px 12px' : '5px 10px',
          cursor: disabled ? 'not-allowed' : 'pointer',
          opacity: disabled ? 0.5 : 1,
          userSelect: 'none',
          background: T.bg1,
          border: `1px solid ${open ? T.cyan + '66' : T.border}`,
          fontFamily: T.mono, fontSize: isFull ? 12 : 11, color: T.text,
          transition: 'border-color .12s',
        }}>
        <span style={{ flex: 1 }}>{current?.l ?? value ?? '—'}</span>
        <svg width="10" height="10" viewBox="0 0 16 16" fill="none"
          style={{ flexShrink: 0, transition: 'transform .15s', transform: open ? 'rotate(180deg)' : 'none' }}>
          <path d="M4 6l4 4 4-4" stroke={open ? T.cyan : T.dim} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
      {open && (
        <div style={{
          position: 'absolute', top: 'calc(100% + 2px)',
          [align === 'right' ? 'right' : 'left']: 0, zIndex: 300,
          background: T.bg1, border: `1px solid ${T.cyan}44`,
          boxShadow: '0 8px 32px rgba(0,0,0,.7)', minWidth: '100%',
        }}>
          {options.map(o => {
            const active = o.v === value;
            return (
              <div key={o.v}
                onClick={() => { onChange(o.v); setOpen(false); }}
                onMouseEnter={e => { if (!active) e.currentTarget.style.background = T.bg2; }}
                onMouseLeave={e => { if (!active) e.currentTarget.style.background = 'transparent'; }}
                style={{
                  display: 'flex', alignItems: 'flex-start', gap: 8,
                  padding: isFull ? '9px 12px' : '7px 10px',
                  cursor: 'pointer', fontFamily: T.mono, fontSize: isFull ? 12 : 11,
                  background: active ? T.bg2 : 'transparent',
                  borderLeft: `2px solid ${active ? T.cyan : 'transparent'}`,
                  color: active ? T.text : T.muted,
                }}>
                <span style={{
                  width: 5, height: 5, marginTop: 6, flexShrink: 0,
                  background: active ? T.cyan : 'transparent',
                  display: 'inline-block',
                }} />
                <div style={{ flex: 1 }}>
                  <div>{o.l}</div>
                  {o.hint && (
                    <div style={{ fontSize: 10, color: T.dim, marginTop: 2 }}>{o.hint}</div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
