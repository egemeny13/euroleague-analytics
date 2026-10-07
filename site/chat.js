/* Plays the hero conversation once, when it scrolls into view.
   The decimal separator comes from the page (data-sep on the window), so the
   Turkish page counts up to 38,7 rather than 38.7.

   Nothing is added to or removed from the page: every message is already
   in the markup at its final size and is only revealed, so the page under
   the window never moves. Without script, or with reduced motion, the
   finished conversation simply shows. */
(function () {
  var chat = document.getElementById("chat");
  var replay = document.getElementById("replay");
  if (!chat) return;

  var steps = Array.prototype.slice.call(chat.querySelectorAll(".msg"));
  var still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var run = 0;

  function wait(ms, id) {
    return new Promise(function (resolve, reject) {
      setTimeout(function () { id === run ? resolve() : reject(); }, ms);
    });
  }

  function type(el, id) {
    var text = el.querySelector(".ghost").textContent;
    var out = el.querySelector(".typed");
    var i = 0;
    return new Promise(function (resolve, reject) {
      (function next() {
        if (id !== run) return reject();
        out.textContent = text.slice(0, i);
        if (i++ >= text.length) return resolve();
        setTimeout(next, 34 + Math.random() * 40);
      })();
    });
  }

  function count(el) {
    var target = parseFloat(el.dataset.count);
    var decimals = parseInt(el.dataset.decimals || "0", 10);
    var prefix = el.dataset.prefix || "";
    var suffix = el.dataset.suffix || "";
    var sep = chat.dataset.sep || ".";
    var start = performance.now();
    var length = 900;
    (function frame(now) {
      var t = Math.min(1, (now - start) / length);
      var eased = 1 - Math.pow(1 - t, 4);
      el.textContent = prefix + (target * eased).toFixed(decimals).replace(".", sep) + suffix;
      if (t < 1) requestAnimationFrame(frame);
    })(start);
  }

  function reset() {
    steps.forEach(function (el) {
      el.classList.add("is-hidden");
      var typed = el.querySelector(".typed");
      if (typed) typed.textContent = "";
      var ghost = el.querySelector(".ghost");
      if (ghost) ghost.style.visibility = "hidden";
    });
  }

  function play() {
    var id = ++run;
    reset();
    var chain = wait(400, id);
    steps.forEach(function (el) {
      var kind = el.dataset.step;
      chain = chain.then(function () {
        el.classList.remove("is-hidden");
        if (kind === "ask") return type(el, id).then(function () { return wait(500, id); });
        if (kind === "working") return wait(1400, id);
        el.querySelectorAll("[data-count]").forEach(function (n, i) {
          setTimeout(function () { if (id === run) count(n); }, i * 260);
        });
        return wait(1100, id);
      });
    });
    chain.catch(function () { /* a replay started; this run stops */ });
  }

  if (still || !("IntersectionObserver" in window)) {
    if (replay) replay.hidden = true;
    return;
  }

  reset();
  var seen = new IntersectionObserver(function (entries) {
    if (entries[0].isIntersecting) {
      seen.disconnect();
      play();
    }
  }, { threshold: 0.25 });
  seen.observe(chat);

  if (replay) replay.addEventListener("click", play);
})();
