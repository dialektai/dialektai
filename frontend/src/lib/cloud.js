// Resolves the cloud API base URL from desktop settings (~/.dialekt/config.json).
//
// Precedence:
//   1. user-configured cloud_api_url in ~/.dialekt/config.json (Settings → Cloud)
//   2. DEFAULT_CLOUD (production: https://api.dias.now)
//
// The fallback is only used if the desktop backend itself is unreachable;
// in that case every cloud call will fail anyway, so the value doesn't matter.

const DESKTOP_API = 'http://localhost:8765';
export const DEFAULT_CLOUD = 'https://dialekt-cloud.dias.now';

let cached = null;
let lastProbe = 0;
let lastProbeResult = null;
const PROBE_TTL_MS = 60_000;

export async function getCloudApi() {
  if (cached) return cached;
  try {
    const r = await fetch(`${DESKTOP_API}/settings`);
    if (r.ok) {
      const s = await r.json();
      const url = (s.cloud_api_url || '').replace(/\/+$/, '');
      if (url) {
        cached = url;
        return url;
      }
    }
  } catch {
    // desktop backend unreachable — fall through
  }
  cached = DEFAULT_CLOUD;
  return cached;
}

export function invalidateCloudApiCache() {
  cached = null;
  lastProbe = 0;
  lastProbeResult = null;
}

/**
 * Ping the cloud /health endpoint. Used by Settings → Cloud to show a live
 * indicator ("reachable / unreachable"). Returns {ok, version?, uptime?, error?}.
 * Cached for 60s to avoid spamming on rapid re-renders.
 */
export async function probeCloud(cloudUrl) {
  const url = (cloudUrl || await getCloudApi()).replace(/\/+$/, '');
  const now = Date.now();
  if (lastProbeResult && (now - lastProbe) < PROBE_TTL_MS) {
    return lastProbeResult;
  }
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    const r = await fetch(`${url}/health`, { signal: controller.signal });
    clearTimeout(timer);
    if (!r.ok) {
      lastProbeResult = { ok: false, error: `HTTP ${r.status}` };
    } else {
      const body = await r.json();
      lastProbeResult = {
        ok: true,
        version: body.version,
        uptime: body.uptime_seconds,
      };
    }
  } catch (e) {
    lastProbeResult = { ok: false, error: String(e).replace('Error: ', '') };
  }
  lastProbe = now;
  return lastProbeResult;
}

/**
 * Save a user-specified cloud URL to desktop settings. Invalidates the cache
 * so subsequent getCloudApi() calls see the new value immediately.
 */
export async function setCloudApi(url) {
  const clean = (url || '').trim().replace(/\/+$/, '');
  if (clean && !/^https?:\/\//i.test(clean)) {
    throw new Error('Cloud URL must start with http:// or https://');
  }
  await fetch(`${DESKTOP_API}/settings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cloud_api_url: clean || null }),
  });
  invalidateCloudApiCache();
}
