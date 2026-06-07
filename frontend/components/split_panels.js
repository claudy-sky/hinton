/* Draggable panel dividers (spec §8.4). Adjusts pane widths directly so it
   composes with the fixed-width three-pane CSS instead of fighting it. */
window.OpenLM = window.OpenLM || {};
(function (O) {
  function addGutter(rightAnchor, target, dir) {
    const g = document.createElement("div");
    g.className = "gutter gutter-horizontal";
    rightAnchor.parentNode.insertBefore(g, rightAnchor);
    g.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      const startX = e.clientX;
      const startW = target.getBoundingClientRect().width;
      g.setPointerCapture(e.pointerId);
      const move = (ev) => {
        const dw = (ev.clientX - startX) * dir;
        const w = Math.max(180, Math.min(760, startW + dw));
        target.style.width = w + "px";
        target.style.flexBasis = w + "px";
      };
      const up = () => {
        document.removeEventListener("pointermove", move);
        document.removeEventListener("pointerup", up);
      };
      document.addEventListener("pointermove", move);
      document.addEventListener("pointerup", up);
    });
  }

  O.initSplit = function (mode) {
    const modeEl = document.getElementById("mode-" + mode);
    if (!modeEl || modeEl.dataset.split) return;
    modeEl.dataset.split = "1";
    const rail = modeEl.querySelector(".rail");
    const center = modeEl.querySelector(".center");
    const panel = modeEl.querySelector(".panel");
    if (rail && center) addGutter(center, rail, +1);     // drag right -> wider rail
    if (center && panel) addGutter(panel, panel, -1);    // drag right -> narrower panel
  };
})(window.OpenLM);
