/* Small page behaviours: content arriving on scroll, the assistant tabs,
   the copy button and the film. Each one degrades to a plain, complete page
   without script. No sentences live here; the copy button reads its
   "copied" word from the page so the Turkish page can supply its own. */
(function () {
  var still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* Arrive on scroll, once. */
  var reveals = document.querySelectorAll(".reveal");
  if (still || !("IntersectionObserver" in window)) {
    reveals.forEach(function (el) { el.classList.add("is-in"); });
  } else {
    var watcher = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-in");
        watcher.unobserve(entry.target);
      });
    }, { threshold: 0.15, rootMargin: "0px 0px -8% 0px" });
    reveals.forEach(function (el) { watcher.observe(el); });
  }

  /* Assistant tabs. Without script every panel shows, one under another. */
  var tabs = Array.prototype.slice.call(document.querySelectorAll('[role="tab"]'));
  function select(tab) {
    tabs.forEach(function (other) {
      var on = other === tab;
      other.setAttribute("aria-selected", on ? "true" : "false");
      other.tabIndex = on ? 0 : -1;
      document.getElementById(other.getAttribute("aria-controls")).hidden = !on;
    });
  }
  tabs.forEach(function (tab, i) {
    tab.addEventListener("click", function () { select(tab); });
    tab.addEventListener("keydown", function (event) {
      var step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
      if (!step) return;
      var next = tabs[(i + step + tabs.length) % tabs.length];
      select(next);
      next.focus();
    });
  });

  /* Copy the address. */
  document.querySelectorAll("[data-copy]").forEach(function (button) {
    var label = button.textContent;
    button.addEventListener("click", function () {
      var text = document.getElementById(button.dataset.copy).textContent.trim();
      var done = function () {
        button.textContent = button.dataset.done || label;
        setTimeout(function () { button.textContent = label; }, 1800);
      };
      if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, function () {});
    });
  });

  /* The film plays with sound only when asked; it never autoplays. */
  var player = document.getElementById("player");
  var video = document.getElementById("film-video");
  var play = document.getElementById("play");
  if (player && video && play) {
    play.addEventListener("click", function () {
      video.controls = true;
      player.classList.add("is-playing");
      video.play().catch(function () { player.classList.remove("is-playing"); });
    });
  }
})();
