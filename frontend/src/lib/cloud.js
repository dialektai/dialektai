// Resolves the cloud API base URL from desktop settings (~/.dialekt/config.json).
// Falls back to production https://api.dialekt.ai if the desktop backend hasn't
// been configured — this keeps shipped builds working while allowing devs and
// pilot customers to point at staging by setting cloud_api_url.

const DESKTOP_API = 'http://localhost:8765';
const FALLBACK = 'https://api.dialekt.ai';

let cached = null;

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
  cached = FALLBACK;
  return FALLBACK;
}

export function invalidateCloudApiCache() {
  cached = null;
}
