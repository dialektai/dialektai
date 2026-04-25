/* dialekt.ai — tiny shared-layout injector for static pages.
   Pages add <div data-layout="nav"></div> and <div data-layout="footer"></div>
   placeholders, then drop <script src="/_layout.js" defer></script> at end of body.
   Mentor's "accept duplication" verdict still holds — this is 30 LOC, no build step,
   and removes the maintenance burden of editing 8 files when nav changes. */

(function() {
  'use strict';

  const navHtml = `
    <nav class="nav">
      <div class="nav-inner">
        <a href="/" class="brand"><span class="dot"></span>dialekt<span class="accent">.ai</span></a>
        <div class="nav-links" id="nav-links">
          <a href="/" data-route="/">Product</a>
          <a href="/pricing.html" data-route="/pricing.html">Pricing</a>
          <a href="/docs.html" data-route="/docs.html">Docs</a>
          <a href="/changelog.html" data-route="/changelog.html">Changelog</a>
        </div>
        <div class="nav-cta">
          <a href="/login.html" class="btn">Have a key</a>
          <a href="/signup.html" class="btn primary">Start free trial</a>
        </div>
      </div>
    </nav>
  `;

  const footerHtml = `
    <footer class="footer">
      <div class="footer-grid">
        <div>
          <div class="brand"><span class="dot"></span>dialekt<span class="accent">.ai</span></div>
          <p class="text-muted" style="font-size:13px;line-height:1.55;margin-top:14px;max-width:380px">
            A local-first AI agent for developers and teams. Your prompts, code, and files never leave your machine by default.
          </p>
          <p class="mono" style="font-size:10px;color:var(--dim);margin-top:18px;letter-spacing:.06em;line-height:1.7">
            local-first · no telemetry · 18 cloud providers (opt-in)<br>
            kz пдн · gdpr ready
          </p>
        </div>
        <div>
          <h4>Product</h4>
          <div class="footer-links">
            <a href="/">Overview</a>
            <a href="/pricing.html">Pricing</a>
            <a href="/signup.html">Free trial</a>
            <a href="/changelog.html">Changelog</a>
          </div>
        </div>
        <div>
          <h4>Resources</h4>
          <div class="footer-links">
            <a href="/docs.html">Docs</a>
            <a href="/#install">Install</a>
            <a href="/#capabilities">Tools</a>
          </div>
        </div>
        <div>
          <h4>Company</h4>
          <div class="footer-links">
            <a href="mailto:hello@dialekt.ai">Contact</a>
            <a href="/privacy.html">Privacy</a>
            <a href="/privacy-ru.html" lang="ru">Конфиденциальность</a>
            <a href="/terms.html">Terms</a>
            <a href="/terms-ru.html" lang="ru">Условия</a>
            <a href="/public-offer.html" lang="ru">Публичная оферта (KZ)</a>
            <a href="/dpa.html">DPA (template)</a>
            <a href="/cross-border-consent.html">Consent &amp; UI texts</a>
            <a href="/login.html">Sign in</a>
          </div>
        </div>
      </div>
      <div class="footer-bottom">
        <span>© 2026 dialekt.ai · made by <a href="#" style="color:var(--cyan)">@weloveclaude</a></span>
        <span>local-first · no telemetry · no account required for local use</span>
      </div>
    </footer>
  `;

  function inject() {
    const navSlot = document.querySelector('[data-layout="nav"]');
    if (navSlot) navSlot.outerHTML = navHtml;
    const footerSlot = document.querySelector('[data-layout="footer"]');
    if (footerSlot) footerSlot.outerHTML = footerHtml;

    // Highlight active nav link based on path
    const path = location.pathname.replace(/\/$/, '') || '/';
    document.querySelectorAll('.nav-links a').forEach(a => {
      const route = a.getAttribute('data-route');
      if (route === path || (route === '/' && path === '/index.html')) {
        a.classList.add('active');
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', inject);
  } else {
    inject();
  }
})();
