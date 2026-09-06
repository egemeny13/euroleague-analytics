/* EuroLeague Analytics — Shot Coordinates & FIBA Geometry
   Precision spatial analytics: coordinates from the league's public API normalized
   to the basket ring (0,0) in centimetres on FIBA court geometry.
   Free throws carry (-1, -1) and are omitted. */

(function () {
  "use strict";

  var STEP_MS = 24;      // between shots, once on screen
  var SETTLE_MS = 650;   // after last shot, before spotlight card opens
  var CARD_MS = 7500;    // duration card stays open before graceful fade
  var DOT_R = 21;        // centimetres on FIBA court

  var court = document.getElementById("halfcourt");
  var marks = document.getElementById("shot-marks");
  var ring = document.getElementById("shot-spotlight");
  var counter = document.getElementById("shot-count");
  var card = document.getElementById("winner-card");
  var bar = document.getElementById("chart-bar");
  var barTrack = document.getElementById("chart-track");
  var barFill = document.getElementById("chart-fill");
  var barLabel = document.getElementById("chart-label");

  if (!court || !marks || !ring || !counter || !card) return;

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  var SVG_NS = "http://www.w3.org/2000/svg";

  var pending = null;
  var armedAt = 0;
  var handle = null;
  var onScreen = false;
  var spotlightShot = null;

  function arm() {
    armedAt = Date.now();
    handle = window.setTimeout(function () {
      var due = pending;
      pending = null;
      handle = null;
      if (due) due.fn();
    }, pending.left);
  }

  function after(ms, fn) {
    pending = { fn: fn, left: ms };
    if (onScreen) arm();
  }

  function pause() {
    onScreen = false;
    if (handle === null) return;
    window.clearTimeout(handle);
    handle = null;
    pending.left = Math.max(0, pending.left - (Date.now() - armedAt));
  }

  function resume() {
    if (onScreen) return;
    onScreen = true;
    if (pending && handle === null) arm();
  }

  function place(shot) {
    var dot = document.createElementNS(SVG_NS, "circle");
    dot.setAttribute("cx", shot[0]);
    dot.setAttribute("cy", shot[1]);
    dot.setAttribute("r", DOT_R);
    dot.setAttribute("class", shot[2] ? "shot-made" : "shot-miss");
    marks.appendChild(dot);
    return dot;
  }

  function setBar(percent) {
    if (!barFill) return;
    barFill.style.width = percent.toFixed(2) + "%";
    if (barTrack) barTrack.setAttribute("aria-valuenow", String(Math.round(percent)));
  }

  function positionCard(shot) {
    var box = court.viewBox.baseVal;
    var x = shot[0];
    var y = 1000 - shot[1]; // match SVG mirror
    card.style.left = (((x - box.x) / box.width) * 100).toFixed(3) + "%";
    card.style.top = (((y - box.y) / box.height) * 100).toFixed(3) + "%";
  }

  function openCard(shot) {
    spotlightShot = shot;
    positionCard(shot);
    ring.textContent = "";

    var halo = document.createElementNS(SVG_NS, "circle");
    halo.setAttribute("cx", shot[0]);
    halo.setAttribute("cy", shot[1]);
    halo.setAttribute("r", 58);
    halo.setAttribute("class", "shot-halo");
    ring.appendChild(halo);

    var core = document.createElementNS(SVG_NS, "circle");
    core.setAttribute("cx", shot[0]);
    core.setAttribute("cy", shot[1]);
    core.setAttribute("r", DOT_R + 4);
    core.setAttribute("class", "shot-made shot-spotlit");
    ring.appendChild(core);

    marks.classList.add("is-dimmed");
    card.hidden = false;

    window.requestAnimationFrame(function () {
      window.requestAnimationFrame(function () {
        card.classList.add("is-open");
      });
    });

    after(CARD_MS, function close() {
      card.classList.remove("is-open");
      marks.classList.remove("is-dimmed");
      ring.textContent = "";
      window.setTimeout(function () { card.hidden = true; }, 400);
    });
  }

  function drawOneByOne(shots, spotlight) {
    var i = 0;
    if (bar) bar.classList.add("is-running");

    (function step() {
      if (i >= shots.length) {
        if (bar) {
          bar.classList.add("is-settling");
          if (barLabel) barLabel.textContent = "Championship decider: Sergio Llull (4.9 m)";
          setBar(100);
        }
        var chosenIndex = spotlight[spotlight.length - 1];
        var chosen = shots[chosenIndex];
        after(SETTLE_MS, function () {
          if (bar) bar.classList.remove("is-running", "is-settling");
          if (chosen) openCard(chosen);
        });
        return;
      }
      var dot = place(shots[i]);
      if (!reduced.matches) {
        dot.animate(
          [
            { opacity: 0, transform: "scale(0.2)" },
            { opacity: 1, transform: "scale(1)" }
          ],
          { duration: 320, easing: "cubic-bezier(0.16, 1, 0.3, 1)", fill: "both" }
        );
      }
      counter.textContent = String(++i);
      setBar((i / shots.length) * 92);
      after(STEP_MS, step);
    })();
  }

  function drawAll(shots, spotlight) {
    shots.forEach(place);
    counter.textContent = String(shots.length);
    if (barLabel) barLabel.textContent = "123 attempts placed";
    setBar(100);
    if (spotlight && spotlight.length) {
      var chosen = shots[spotlight[spotlight.length - 1]];
      if (chosen) openCard(chosen);
    }
  }

  function run(data) {
    var shots = (data.shots || []).filter(function (s) {
      return !(s[0] === -1 && s[1] === -1);
    });
    if (!shots.length) return;

    if (reduced.matches || !("IntersectionObserver" in window)) {
      drawAll(shots, data.spotlight || []);
      return;
    }

    var started = false;
    var visible = false;

    function settle() {
      if (visible && document.visibilityState === "visible") {
        resume();
        if (!started) {
          started = true;
          drawOneByOne(shots, data.spotlight || []);
        }
      } else {
        pause();
      }
    }

    document.addEventListener("visibilitychange", settle);

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        visible = entry.isIntersecting;
        settle();
      });
    }, { threshold: 0.35 });

    io.observe(court);
  }

  fetch("data/shots.json")
    .then(function (response) {
      if (!response.ok) throw new Error("shots.json " + response.status);
      return response.json();
    })
    .then(run)
    .catch(function () {
      // Empty court fallback
    });
})();
