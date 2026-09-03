/* The shot chart fills itself, then stops on the shot that decided the game.
   Design record: docs/superpowers/specs/2026-09-04-launch-website-design.md

   The coordinates are the league's own, in centimetres, and they are placed
   with no transform beyond the identity: the court behind them is drawn to the
   same FIBA dimensions in the same units, so a shot lands where it was
   recorded. A hand-tuned scale factor would make the picture look right while
   quietly meaning nothing, which is the failure this file exists to avoid.

   Free throws never appear. They carry (-1, -1), a sentinel standing in for a
   location the source does not have, and plotting it would print a row of
   phantom shots behind the baseline. A handful of real attempts do sit behind
   the baseline, and those stay: the drawing is widened to show them rather than
   the data being clipped to make the picture tidy.

   The data file lists the game's notable shots; the page opens a card on the
   last of them, which is the one that won it. The sentences in that card live
   in the page, so they can be translated with the rest of the page. The card
   opens once and then closes for good: a thing that keeps reappearing stops
   being an event. */

(function () {
  "use strict";

  var STEP_MS = 24;      // between shots, once the section is on screen
  var SETTLE_MS = 650;   // after the last shot, before the card opens
  var CARD_MS = 5000;    // how long the card stays, then it closes for good
  var DOT_R = 21;        // centimetres on the court, not pixels on the screen

  var court = document.getElementById("halfcourt");
  var marks = document.getElementById("shot-marks");
  var ring = document.getElementById("shot-spotlight");
  var counter = document.getElementById("shot-count");
  var card = document.getElementById("winner-card");
  if (!court || !marks || !ring || !counter || !card) return;

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  var SVG_NS = "http://www.w3.org/2000/svg";

  function place(shot) {
    var dot = document.createElementNS(SVG_NS, "circle");
    dot.setAttribute("cx", shot[0]);
    dot.setAttribute("cy", shot[1]);
    dot.setAttribute("r", DOT_R);
    dot.setAttribute("class", shot[2] ? "shot-made" : "shot-miss");
    marks.appendChild(dot);
    return dot;
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

    window.setTimeout(function close() {
      card.classList.remove("is-open");
      marks.classList.remove("is-dimmed");
      ring.textContent = "";
      window.setTimeout(function () { card.hidden = true; }, 400);
    }, CARD_MS);
  }

  function drawOneByOne(shots, spotlight) {
    var i = 0;
    (function step() {
      if (i >= shots.length) {
        var chosen = shots[spotlight[spotlight.length - 1]];
        if (chosen) window.setTimeout(function () { openCard(chosen); }, SETTLE_MS);
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
      window.setTimeout(step, STEP_MS);
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
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          io.disconnect();
          drawOneByOne(shots, data.spotlight || []);
        }
      });
    }, { threshold: 0.3 });
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
