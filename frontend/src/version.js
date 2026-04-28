// Single source of truth for the version string the FE renders when it
// can't (or hasn't yet) reached the backend's /about endpoint. Kept in
// lockstep with frontend/src-tauri/Cargo.toml + tauri.conf.json + the
// git tag at every release. Screens that show version should prefer
// the dynamic /about response and fall back to APP_VERSION on failure.
export const APP_VERSION = '0.27.14';
