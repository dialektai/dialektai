# macOS Code Signing & Notarization

dialekt macOS builds are signed with a Developer ID certificate and notarized
via Apple's notary service. This allows users to install and run the app
without Gatekeeper warnings.

---

## Prerequisites

1. **Apple Developer Program** membership ($99/year) — https://developer.apple.com/programs/
2. A **Developer ID Application** certificate (not "Mac App Distribution" — that's for the App Store)
3. An **App-Specific Password** for notarization

---

## Step 1: Create the Developer ID Application certificate

1. Go to https://developer.apple.com/account/resources/certificates/list
2. Click **+** → **Developer ID Application**
3. Follow the CSR instructions (Keychain Access → Certificate Assistant → Request a Certificate)
4. Download and double-click the `.cer` to install in Keychain

---

## Step 2: Export as .p12

1. Open **Keychain Access**
2. Find "Developer ID Application: Your Name (TEAM_ID)" under **My Certificates**
3. Right-click → **Export** → save as `.p12` with a strong password
4. Base64-encode for CI:

```bash
base64 -i Certificates.p12 | pbcopy
# paste into GitHub secret APPLE_CERTIFICATE
```

---

## Step 3: Create an App-Specific Password

1. Go to https://appleid.apple.com/account/manage → **Sign-In and Security** → **App-Specific Passwords**
2. Generate one, name it "dialekt notarization"
3. Save the password — it goes into `APPLE_PASSWORD`

---

## Step 4: Find your Team ID

```bash
# From the certificate:
security find-identity -v -p codesigning | grep "Developer ID"
# Output: ... "Developer ID Application: Your Name (ABCDE12345)"
#                                                    ^^^^^^^^^^^ this is the Team ID
```

Or find it at https://developer.apple.com/account → Membership Details.

---

## Step 5: Configure GitHub Secrets

Go to your repo → **Settings → Secrets and variables → Actions** and add:

| Secret | Value |
|--------|-------|
| `APPLE_CERTIFICATE` | Base64-encoded .p12 file (`base64 -i cert.p12 \| pbcopy`) |
| `APPLE_CERTIFICATE_PASSWORD` | Password you set when exporting the .p12 |
| `APPLE_SIGNING_IDENTITY` | Full identity string, e.g. `Developer ID Application: Dias Zhumagaliyev (ABCDE12345)` |
| `APPLE_ID` | Your Apple ID email (the one used for App Store Connect / developer portal) |
| `APPLE_PASSWORD` | The app-specific password from Step 3 |
| `APPLE_TEAM_ID` | Your 10-character Team ID (e.g. `ABCDE12345`) |

---

## Step 6: Local builds (optional)

For signing and notarizing local builds via `build.sh`, export the same variables:

```bash
export APPLE_SIGNING_IDENTITY="Developer ID Application: Dias Zhumagaliyev (ABCDE12345)"
export APPLE_ID="your@email.com"
export APPLE_PASSWORD="xxxx-xxxx-xxxx-xxxx"
export APPLE_TEAM_ID="ABCDE12345"

bash build.sh macos
```

The build script will:
1. Sign the Python sidecar with hardened runtime + entitlements
2. Build the Tauri app (Tauri auto-signs using `APPLE_SIGNING_IDENTITY`)
3. Submit the .dmg to Apple's notary service
4. Staple the notarization ticket to the .dmg

---

## Entitlements

The entitlements file (`frontend/src-tauri/Entitlements.plist`) grants:

| Entitlement | Why |
|-------------|-----|
| `cs.allow-unsigned-executable-memory` | PyInstaller sidecar uses mmap with PROT_EXEC |
| `cs.disable-library-validation` | Sidecar loads bundled .dylibs not signed by the team |
| `cs.allow-jit` | Python subprocess execution in sidecar |
| `network.server` | FastAPI backend on localhost:41337 |
| `network.client` | Connects to Ollama on localhost:11434 |

---

## Verifying a signed build

```bash
# Check code signature
codesign -dv --verbose=4 /Applications/dialekt.app

# Check notarization
spctl -a -vvv /Applications/dialekt.app
# Expected: "source=Notarized Developer ID"

# Check the sidecar inside the bundle
codesign -dv --verbose=4 "/Applications/dialekt.app/Contents/MacOS/dialekt-server"
```

---

## Troubleshooting

**"The app is damaged and can't be opened"**
→ Notarization may have failed or the staple wasn't applied. Check `xcrun notarytool log <submission-id>`.

**"Developer ID Application" identity not found in CI**
→ Verify `APPLE_CERTIFICATE` is base64-encoded correctly: `echo "$APPLE_CERTIFICATE" | base64 -d | file -`
should show "PKCS12".

**Notarization rejected**
→ Run `xcrun notarytool log <submission-id>` to see the exact issues. Common causes:
  - Missing hardened runtime on a binary inside the bundle
  - A dependency linked against a private framework
  - Unsigned nested code
