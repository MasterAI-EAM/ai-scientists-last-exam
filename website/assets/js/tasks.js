/* Task-only navigation and catalogue sizing/anchors.
 * Extracted from AISLE src/scripts/navigation.js and main.js at
 * yangsen-hub-dot/AISLE @ 4322bd0e1fc278e02c0fe334ff386d107e3f9757.
 * No home, research, contribution, globe or third-party runtime imports.
 */
/* AISLE: small, dependency-free enhancements; the default results remain in HTML. */
const menu = document.querySelector('.menu-toggle');
const nav = document.querySelector('.nav-links');
menu?.addEventListener('click', () => {
  const expanded = menu.getAttribute('aria-expanded') !== 'true';
  menu.setAttribute('aria-expanded', String(expanded));
  nav?.classList.toggle('open', expanded);
});
nav?.querySelectorAll('a').forEach(link => link.addEventListener('click', () => {
  menu?.setAttribute('aria-expanded', 'false');
  nav.classList.remove('open');
}));

const catalogueFrame = document.getElementById('task-catalogue-frame');
if (catalogueFrame) {
  let observer;
  let pendingAnchor = location.hash;
  const catalogueAnchors = new Set(['#featured-case', '#task-library', '#task-colour', '#task-constraints', '#task-robustness', '#task-spectral', '#task-solid', '#task-quantum-dot', '#task-buchwald-hartwig']);
  const scrollToCatalogueAnchor = () => {
    if (!catalogueAnchors.has(pendingAnchor)) return;
    const target = catalogueFrame.contentDocument?.getElementById(pendingAnchor.slice(1));
    if (target && !target.getClientRects().length) {
      const catalogueWindow = catalogueFrame.contentWindow;
      catalogueFrame.contentDocument.dispatchEvent(new catalogueWindow.CustomEvent('catalog-reveal-task'));
    }
    if (target?.getClientRects().length && catalogueFrame.getClientRects().length) {
      target.scrollIntoView({ block: 'start' });
      pendingAnchor = '';
    }
  };
  const fitCatalogue = () => {
    observer?.disconnect();
    const catalogue = catalogueFrame.contentDocument?.getElementById('app');
    if (!catalogue?.firstElementChild) return;
    observer = new ResizeObserver(() => {
      const height = Math.ceil(catalogue.getBoundingClientRect().height);
      if (height > 0) catalogueFrame.style.height = `${height}px`;
      scrollToCatalogueAnchor();
    });
    observer.observe(catalogue);
  };
  window.addEventListener('hashchange', () => {
    pendingAnchor = location.hash;
    if (!catalogueFrame.getClientRects().length) {
      catalogueFrame.contentDocument?.querySelectorAll('video').forEach(video => video.pause());
    }
    scrollToCatalogueAnchor();
  });
  catalogueFrame.addEventListener('load', fitCatalogue);
  fitCatalogue();
}
