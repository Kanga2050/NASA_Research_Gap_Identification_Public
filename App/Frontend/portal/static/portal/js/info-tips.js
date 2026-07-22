/* Info-icon tooltips.
 *
 * Renders every `.info-icon[data-tip]` help bubble into one <body>-level box so
 * it paints above all the app chrome. The icons live inside scrolling sidebars,
 * cards and the agent dock — an ::after on the icon gets clipped by those
 * overflow boxes whatever its z-index, which is why the tip is portalled out
 * here instead. See the `.info-tip-pop` / `:root.js-tips` rules in style.css.
 */
(function () {
  var GAP = 8; // px between the icon and the bubble
  var EDGE = 8; // min gap from the viewport edge

  document.documentElement.classList.add("js-tips"); // kills the CSS fallback

  var pop = null;
  var current = null;

  function ensurePop() {
    if (!pop) {
      pop = document.createElement("div");
      pop.className = "info-tip-pop";
      pop.setAttribute("role", "tooltip");
      document.body.appendChild(pop);
    }
    return pop;
  }

  function show(icon) {
    var text = icon.getAttribute("data-tip");
    if (!text) return;
    current = icon;
    var el = ensurePop();
    el.textContent = text;
    el.classList.add("show");

    // Measure after the text is in, then place above the icon — flipping below
    // when there isn't room, and clamping to the viewport horizontally.
    var r = icon.getBoundingClientRect();
    var w = el.offsetWidth;
    var h = el.offsetHeight;
    var left = Math.min(Math.max(r.left, EDGE), window.innerWidth - w - EDGE);
    var top = r.top - h - GAP;
    if (top < EDGE) top = Math.min(r.bottom + GAP, window.innerHeight - h - EDGE);
    el.style.left = left + "px";
    el.style.top = top + "px";
  }

  function hide(icon) {
    if (icon && icon !== current) return;
    current = null;
    if (pop) pop.classList.remove("show");
  }

  function iconFrom(target) {
    if (!target || !target.closest) return null;
    return target.closest(".info-icon[data-tip]");
  }

  document.addEventListener("mouseover", function (e) {
    var icon = iconFrom(e.target);
    if (icon) show(icon);
  });
  document.addEventListener("mouseout", function (e) {
    var icon = iconFrom(e.target);
    if (icon) hide(icon);
  });
  document.addEventListener("focusin", function (e) {
    var icon = iconFrom(e.target);
    if (icon) show(icon);
  });
  document.addEventListener("focusout", function (e) {
    var icon = iconFrom(e.target);
    if (icon) hide(icon);
  });
  // The bubble is positioned in viewport coordinates from a one-off measurement,
  // so any scroll or resize would leave it stranded next to nothing.
  window.addEventListener("scroll", function () { hide(current); }, true);
  window.addEventListener("resize", function () { hide(current); });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") hide(current);
  });
})();
