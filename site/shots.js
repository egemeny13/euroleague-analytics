/* The shot chart fills itself, then stops on the shot that decided the game.
   Design record: docs/superpowers/specs/2026-09-04-launch-website-design.md

   The coordinates are the league's own, in centimetres, and they are placed
   with no transform beyond the identity: the court behind them is drawn to the
   same FIBA dimensions in the same units, so a shot lands where it was
   recorded. A hand-tuned scale factor would make the picture look right while
   quietly meaning nothing, which is the failure this file exists to avoid.

   Free throws never appear. They carry (-1, -1), a sentinel standing in for a
   location the source does not have, and plotting it would print a row of
   phantom shots behind the baseline. Four real attempts in this game do sit
   behind the baseline, the furthest 50 cm back, and those stay: the frame is
   drawn to show them rather than the data being clipped to make the picture
   tidy. The caption says so.

   The data file lists the game's notable shots; the page opens a card on the
   last of them, which is the one that won it. The sentences in that card live
   in the page, so they can be translated with the rest of the page. The card
   opens once and then closes for good: a thing that keeps reappearing stops
   being an event.

   Every wait in here is measured in time the section spends ON SCREEN, not in
   wall clock time. The first version used plain timers, so a visitor who spent
   a few seconds in the hero arrived to find the chart already full and the card
   already gone for good - the one moment this section exists for, missed, with
   no way to get it back. Scrolling away now pauses the sequence mid-shot, and
   scrolling back resumes it where it stopped. */

(function () {
  "use strict";

  var STEP_MS = 26;      // between shots, once the section is on screen
  var SETTLE_MS = 650;   // after the last shot, before the card opens
  var CARD_MS = 6000;    // on-screen time the card stays, then it closes for good
  var DOT_R = 21;        // centimetres on the court, not pixels on the screen

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

  /* ---- a clock that only runs while the section is being looked at ----
     One pending step at a time, which is all this sequence ever has. Pausing
     banks the time already served, so resuming does not restart the wait. */
  var pending = null;   // { fn: function, left: milliseconds }
  var armedAt = 0;
  var handle = null;
  var onScreen = false;

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

  /* ---- drawing ---- */

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

  /* The card is positioned from the shot's own coordinates, read back out of
     the SVG viewBox, so it stays on the dot at any width. */
  function positionCard(shot) {
    var box = court.viewBox.baseVal;
    var x = shot[0];
    var y = 1000 - shot[1];   // the same mirror the drawing uses
    card.style.left = (((x - box.x) / box.width) * 100).toFixed(3) + "%";
    card.style.top = (((y - box.y) / box.height) * 100).toFixed(3) + "%";
  }

  function openCard(shot) {
    positionCard(shot);

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
    core.setAttribute("class", "shot-made");
    ring.appendChild(core);

    marks.classList.add("is-dimmed");
    card.hidden = false;
    /* Two frames, so the browser has a layout to animate from. */
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
        /* The bar runs the last of the way to full during the pause, so it
           fills at the moment the card opens rather than before it. */
        if (bar) {
          bar.classList.add("is-settling");
          if (barLabel) barLabel.textContent = "The last event of the game";
          setBar(100);
        }
        var chosen = shots[spotlight[spotlight.length - 1]];
        after(SETTLE_MS, function () {
          if (bar) bar.classList.remove("is-running", "is-settling");
          if (chosen) openCard(chosen);
        });
        return;
      }
      var dot = place(shots[i]);
      dot.animate(
        [
          { opacity: 0, transform: "scale(0.2)" },
          { opacity: 1, transform: "scale(1)" }
        ],
        { duration: 360, easing: "cubic-bezier(.2,.8,.3,1)", fill: "both" }
      );
      counter.textContent = String(++i);
      /* Held short of full: the remaining sliver belongs to the pause. */
      setBar((i / shots.length) * 92);
      after(STEP_MS, step);
    })();
  }

  function drawAll(shots) {
    shots.forEach(place);
    counter.textContent = String(shots.length);
  }

  function run(data) {
    var shots = (data.shots || []).filter(function (s) {
      /* Belt and braces: the export already drops free throws, and a sentinel
         that slipped through would look like a real shot. */
      return !(s[0] === -1 && s[1] === -1);
    });
    if (!shots.length) return;

    if (reduced.matches || !("IntersectionObserver" in window)) {
      drawAll(shots);
      return;
    }

    /* Two conditions, not one. A section can be inside the layout viewport of
       a tab nobody is looking at - open the page in a background tab and the
       observer still reports it as intersecting - and the sequence would run
       and finish there, which is the same defect as before wearing a different
       hat. It has to be on screen AND the tab has to be the visible one. */
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
    }, { threshold: 0.45 });
    io.observe(court);
  }

  fetch("data/shots.json")
    .then(function (response) {
      if (!response.ok) throw new Error("shots.json " + response.status);
      return response.json();
    })
    .then(run)
    .catch(function () {
      /* An empty court says nothing false. The claim beside it is about the
         data, and a failed fetch is not evidence against it. */
    });
})();
