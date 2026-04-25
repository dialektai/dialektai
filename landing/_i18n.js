/* dialekt.ai — shared i18n for static landing pages.
   Pages mark translatable nodes:
     <span data-i18n="nav.product">Product</span>
     <input data-i18n-attr="placeholder:form.email.ph">
   Dictionary is union of `__I18N_SHARED__` (defined here) plus optional
   `__I18N_PAGE__` (per-page additions, set BEFORE this script loads).
   Language is stored in localStorage as `dlk_lang` and exposed as <html lang>. */

(function () {
  'use strict';

  const SHARED = {
    en: {
      "nav.product": "Product",
      "nav.pricing": "Pricing",
      "nav.docs": "Docs",
      "nav.changelog": "Changelog",
      "nav.security": "Security",
      "nav.signin": "Have a key",
      "nav.trial": "Start free trial",

      "footer.tag": "Local-first AI agent. Your prompts, code, and files never leave your machine by default.",
      "footer.product": "Product",
      "footer.product.overview": "Overview",
      "footer.product.pricing": "Pricing",
      "footer.product.trial": "Free trial",
      "footer.product.changelog": "Changelog",
      "footer.resources": "Resources",
      "footer.resources.docs": "Docs",
      "footer.resources.install": "Install",
      "footer.resources.tools": "Tools",
      "footer.resources.security": "Security",
      "footer.company": "Company",
      "footer.company.contact": "Contact",
      "footer.company.privacy": "Privacy policy",
      "footer.company.privacy_ru": "Конфиденциальность (RU)",
      "footer.company.terms": "Terms",
      "footer.company.terms_ru": "Условия (RU)",
      "footer.company.offer_ru": "Public offer (KZ, RU)",
      "footer.company.dpa": "DPA template",
      "footer.company.consent": "Consent & UI texts",
      "footer.company.signin": "Sign in",
      "footer.copy": "© 2026 dialekt.ai",
      "footer.principle": "Local-first · No telemetry · No account required for local use",
    },
    ru: {
      "nav.product": "Продукт",
      "nav.pricing": "Тарифы",
      "nav.docs": "Документация",
      "nav.changelog": "История версий",
      "nav.security": "Безопасность",
      "nav.signin": "Войти по ключу",
      "nav.trial": "Бесплатный пробный период",

      "footer.tag": "Локальный ИИ-агент. Запросы, код и файлы по умолчанию не покидают вашу машину.",
      "footer.product": "Продукт",
      "footer.product.overview": "Обзор",
      "footer.product.pricing": "Тарифы",
      "footer.product.trial": "Пробный период",
      "footer.product.changelog": "Версии",
      "footer.resources": "Ресурсы",
      "footer.resources.docs": "Документация",
      "footer.resources.install": "Установка",
      "footer.resources.tools": "Инструменты",
      "footer.resources.security": "Безопасность",
      "footer.company": "Компания",
      "footer.company.contact": "Связаться",
      "footer.company.privacy": "Privacy policy (EN)",
      "footer.company.privacy_ru": "Конфиденциальность",
      "footer.company.terms": "Terms (EN)",
      "footer.company.terms_ru": "Условия",
      "footer.company.offer_ru": "Публичная оферта (KZ)",
      "footer.company.dpa": "DPA-шаблон",
      "footer.company.consent": "Согласия и UI-тексты",
      "footer.company.signin": "Войти",
      "footer.copy": "© 2026 dialekt.ai",
      "footer.principle": "Локально · без телеметрии · аккаунт не требуется для локального использования",
    },
  };

  const PAGE = window.__I18N_PAGE__ || { en: {}, ru: {} };
  window.__I18N__ = {
    en: Object.assign({}, SHARED.en, PAGE.en || {}),
    ru: Object.assign({}, SHARED.ru, PAGE.ru || {}),
  };

  const STORAGE_KEY = 'dlk_lang';
  const SUPPORTED = ['en', 'ru'];

  function detectLang() {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && SUPPORTED.indexOf(stored) >= 0) return stored;
    const nav = (navigator.language || 'en').toLowerCase();
    return nav.startsWith('ru') ? 'ru' : 'en';
  }

  function setLang(lang) {
    if (SUPPORTED.indexOf(lang) < 0) return;
    localStorage.setItem(STORAGE_KEY, lang);
    document.documentElement.setAttribute('lang', lang);
    apply(lang);
    window.dispatchEvent(new CustomEvent('dlk:lang', { detail: { lang } }));
    document.querySelectorAll('[data-lang-btn]').forEach(b => {
      b.setAttribute('aria-pressed', b.getAttribute('data-lang-btn') === lang ? 'true' : 'false');
    });
  }

  function getLang() { return document.documentElement.getAttribute('lang') || detectLang(); }

  function apply(lang) {
    const dict = window.__I18N__[lang] || window.__I18N__.en;
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const key = el.getAttribute('data-i18n');
      if (dict[key] != null) el.textContent = dict[key];
    });
    document.querySelectorAll('[data-i18n-html]').forEach(el => {
      const key = el.getAttribute('data-i18n-html');
      if (dict[key] != null) el.innerHTML = dict[key];
    });
    document.querySelectorAll('[data-i18n-attr]').forEach(el => {
      const spec = el.getAttribute('data-i18n-attr');
      spec.split(',').forEach(pair => {
        const [attr, key] = pair.split(':').map(s => s.trim());
        if (attr && key && dict[key] != null) el.setAttribute(attr, dict[key]);
      });
    });
  }

  window.dlkI18n = { setLang, getLang, apply };

  function init() {
    const lang = detectLang();
    document.documentElement.setAttribute('lang', lang);
    apply(lang);
    document.querySelectorAll('[data-lang-btn]').forEach(btn => {
      const target = btn.getAttribute('data-lang-btn');
      btn.setAttribute('aria-pressed', target === lang ? 'true' : 'false');
      btn.addEventListener('click', e => { e.preventDefault(); setLang(target); });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
