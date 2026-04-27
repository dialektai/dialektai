/* dias.now — shared-layout injector for static pages.
   Pages add <div data-layout="nav"></div> and <div data-layout="footer"></div>
   placeholders, then load:
     <script src="/_i18n.js" defer></script>
     <script src="/_layout.js" defer></script>
   Layout injects markup, then re-applies i18n so freshly-injected nodes get translated. */

(function () {
  'use strict';

  const navHtml = `
    <nav class="nav">
      <div class="nav-inner">
        <a href="/" class="brand" aria-label="dias.now">
          <b>dialekt</b><span class="accent">.ai</span>
        </a>
        <div class="nav-links" id="nav-links">
          <a href="/" data-route="/" data-i18n="nav.product">Product</a>
          <a href="/pricing.html" data-route="/pricing.html" data-i18n="nav.pricing">Pricing</a>
          <a href="/docs.html" data-route="/docs.html" data-i18n="nav.docs">Docs</a>
          <a href="/security.html" data-route="/security.html" data-i18n="nav.security">Security</a>
          <a href="/changelog.html" data-route="/changelog.html" data-i18n="nav.changelog">Changelog</a>
        </div>
        <div class="nav-cta">
          <div class="lang-toggle" role="group" aria-label="Language">
            <button data-lang-btn="en" aria-pressed="true">EN</button>
            <button data-lang-btn="ru" aria-pressed="false">RU</button>
          </div>
          <a href="/login.html" class="btn" data-i18n="nav.signin">Have a key</a>
          <a href="/signup.html" class="btn primary" data-i18n="nav.trial">Start free trial</a>
        </div>
      </div>
    </nav>
  `;

  const footerHtml = `
    <footer class="footer">
      <div class="footer-grid">
        <div>
          <a href="/" class="brand"><b>dialekt</b><span class="accent">.ai</span></a>
          <p style="font-size:14px;line-height:1.6;margin-top:14px;max-width:380px;color:var(--ink-2)" data-i18n="footer.tag">
            Local-first AI agent. Your prompts, code, and files never leave your machine by default.
          </p>
        </div>
        <div>
          <h4 data-i18n="footer.product">Product</h4>
          <div class="footer-links">
            <a href="/pricing.html" data-i18n="footer.product.pricing">Pricing</a>
            <a href="/docs.html" data-i18n="footer.resources.docs">Docs</a>
            <a href="/security.html" data-i18n="footer.resources.security">Security</a>
            <a href="/changelog.html" data-i18n="footer.product.changelog">Changelog</a>
          </div>
        </div>
        <div>
          <h4 data-i18n="footer.legal">Legal</h4>
          <div class="footer-links">
            <a data-href-en="/privacy.html" data-href-ru="/privacy-ru.html" data-i18n="footer.legal.privacy">Privacy</a>
            <a data-href-en="/terms.html" data-href-ru="/terms-ru.html" data-i18n="footer.legal.terms">Terms</a>
            <a href="/dpa.html" data-i18n="footer.legal.dpa">DPA</a>
            <a href="mailto:hello@dias.now" data-i18n="footer.company.contact">Contact</a>
          </div>
        </div>
      </div>
      <div class="footer-bottom">
        <span data-i18n="footer.copy">© 2026 dias.now</span>
        <span data-i18n="footer.principle">Local-first · No telemetry · No account required</span>
      </div>
    </footer>
  `;

  function inject() {
    const navSlot = document.querySelector('[data-layout="nav"]');
    if (navSlot) navSlot.outerHTML = navHtml;
    const footerSlot = document.querySelector('[data-layout="footer"]');
    if (footerSlot) footerSlot.outerHTML = footerHtml;

    const path = location.pathname.replace(/\/$/, '') || '/';
    document.querySelectorAll('.nav-links a').forEach(a => {
      const route = a.getAttribute('data-route');
      if (route === path || (route === '/' && path === '/index.html')) {
        a.classList.add('active');
      }
    });

    if (window.dlkI18n && typeof window.dlkI18n.apply === 'function') {
      const lang = window.dlkI18n.getLang();
      window.dlkI18n.apply(lang);
      document.querySelectorAll('[data-lang-btn]').forEach(btn => {
        const target = btn.getAttribute('data-lang-btn');
        btn.setAttribute('aria-pressed', target === lang ? 'true' : 'false');
        btn.addEventListener('click', e => { e.preventDefault(); window.dlkI18n.setLang(target); });
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', inject);
  } else {
    inject();
  }
})();
