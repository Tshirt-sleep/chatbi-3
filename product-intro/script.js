const menuButton = document.querySelector(".menu-toggle");
const nav = document.querySelector(".nav");

menuButton?.addEventListener("click", () => {
  const isOpen = nav?.classList.toggle("open") ?? false;
  menuButton.setAttribute("aria-expanded", String(isOpen));
});

nav?.querySelectorAll("a").forEach((link) => {
  link.addEventListener("click", () => {
    nav.classList.remove("open");
    menuButton?.setAttribute("aria-expanded", "false");
  });
});

const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

if (!reduceMotion && "IntersectionObserver" in window) {
  const revealTargets = document.querySelectorAll(
    ".hero-copy > *, .hero-visual, .section-kicker, .section-heading, .pain-grid article, .audience-list article, .capability-grid article, .steps article, .trust-cards article, .validation-row, .evidence-note, .method-list > div, .sdd-grid article, .sdd-example, .usage-role-grid article, .session-feature-grid article, .metric-cards article, .storage-note, .metric-meta, .strength-strip, .roadmap-grid article, .closing > *",
  );

  revealTargets.forEach((element, index) => {
    element.dataset.reveal = "";
    element.style.setProperty("--reveal-delay", `${(index % 5) * 65}ms`);
  });

  document.body.classList.add("motion-ready");
  const revealObserver = new IntersectionObserver(
    (entries, observer) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.12, rootMargin: "0px 0px -36px 0px" },
  );

  revealTargets.forEach((element) => revealObserver.observe(element));


}


const observedSections = ["problem", "audience", "usage", "capabilities", "experience", "sessions", "metrics", "trust", "validation", "method", "sdd", "roadmap"]
  .map((id) => document.getElementById(id))
  .filter(Boolean);
const pageLinks = [...document.querySelectorAll('.nav a[href^="#"], .page-toc a[href^="#"]')];
if (pageLinks.length) {
  pageLinks.filter((link) => link.hash === "#problem").forEach((link) => {
    link.classList.add("is-current");
    link.setAttribute("aria-current", "location");
  });
}
if ("IntersectionObserver" in window) {
  const sectionObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        pageLinks.forEach((link) => {
          const active = link.hash === `#${entry.target.id}`;
          link.classList.toggle("is-current", active);
          if (active) link.setAttribute("aria-current", "location");
          else link.removeAttribute("aria-current");
        });
      });
    },
    { rootMargin: "-25% 0px -60% 0px" },
  );
  observedSections.forEach((section) => sectionObserver.observe(section));
}
const updateScrollProgress = () => {
  const scrollable = document.documentElement.scrollHeight - window.innerHeight;
  const progress = scrollable > 0 ? window.scrollY / scrollable : 0;
  document.documentElement.style.setProperty("--scroll-progress", String(progress));
};
window.addEventListener("scroll", updateScrollProgress, { passive: true });
updateScrollProgress();

const heroVisual = document.querySelector(".hero-visual");
const queryCard = document.querySelector(".query-card");
if (!reduceMotion && heroVisual && queryCard && window.matchMedia("(pointer: fine)").matches) {
  heroVisual.addEventListener("pointermove", (event) => {
    const bounds = heroVisual.getBoundingClientRect();
    const x = (event.clientX - bounds.left) / bounds.width - 0.5;
    const y = (event.clientY - bounds.top) / bounds.height - 0.5;
    queryCard.style.setProperty("--tilt-x", `${(-y * 3).toFixed(2)}deg`);
    queryCard.style.setProperty("--tilt-y", `${(x * 4).toFixed(2)}deg`);
  });
  heroVisual.addEventListener("pointerleave", () => {
    queryCard.style.setProperty("--tilt-x", "0deg");
    queryCard.style.setProperty("--tilt-y", "0deg");
  });
}
