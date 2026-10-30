// About tab: hover or focus a box in the architecture diagram for its detail.
(function () {
  const fig = document.querySelector(".arch");
  const tip = document.querySelector(".arch-tip");
  if (!fig || !tip) return;
  const card = tip.parentElement;

  function show(el) {
    tip.textContent = el.getAttribute("data-tip");
    tip.hidden = false;
    const box = el.getBoundingClientRect();
    const host = card.getBoundingClientRect();
    const width = Math.min(340, host.width - 24);
    tip.style.width = width + "px";
    let left = box.left - host.left + box.width / 2 - width / 2;
    left = Math.max(12, Math.min(left, host.width - width - 12));
    tip.style.left = left + "px";
    tip.style.top = (box.bottom - host.top + 8) + "px";
    el.classList.add("on");
  }
  function hide(el) {
    tip.hidden = true;
    if (el) el.classList.remove("on");
  }
  fig.querySelectorAll("[data-tip]").forEach(function (el) {
    // A focusable box that is not a link is announced with its detail.
    if (el.tagName.toLowerCase() === "g" && !el.hasAttribute("aria-label")) {
      el.setAttribute("aria-label", el.textContent.trim().replace(/\s+/g, " ") + ". " + el.getAttribute("data-tip"));
    }
    el.addEventListener("mouseenter", function () { show(el); });
    el.addEventListener("mouseleave", function () { hide(el); });
    el.addEventListener("focus", function () { show(el); });
    el.addEventListener("blur", function () { hide(el); });
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") hide(); });
})();
