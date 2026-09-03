/* The shot chart fills itself, then stops on the two shots that decided it.
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

   The spotlight indices come from the data file. The sentences beside them live
   in the page, so they can be translated with the rest of the page. */

(function () {
  "use strict";

  var STEP_MS = 24;        // between shots, once the section is on screen
  var SETTLE_MS = 700;     // after the last shot, before the first spotlight
  var SPOTLIGHT_MS = 3400; // how long each highlighted shot holds
  var DOT_R = 21;          // centimetres on the court, not pixels on the screen

  var court = document.getElementById("halfcourt");
  var marks = document.getElementById("shot-marks");
  var ring = document.getElementById("shot-spotlight");
  var counter = document.getElementById("shot-count");
  var notes = document.getElementById("spotlights");
  if (!court || !marks || !ring || !counter || !notes) return;

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  var SVG_NS = "http://www.w3.org/2000/svg";
  var dots = [];

  function place(shot) {
    var dot = document.createElementNS(SVG_NS, "circle");
    dot.setAttribute("cx", shot[0]);
    dot.setAttribute("cy", shot[1]);
    dot.setAttribute("r", DOT_R);
    dot.setAttribute("class", shot[2] ? "shot-made" : "shot-miss");
    marks.appendChild(dot);
    dots.push(dot);
    return dot;
  }

  function highlight(shot) {
    ring.textContent = "";
    var halo = document.createElementNS(SVG_NS, "circle");
    halo.setAttribute("cx", shot[0]);
    halo.setAttribute("cy", shot[1]);
    halo.setAttribute("r", 62);
    halo.setAttribute("class", "shot-halo");
    ring.appendChild(halo);

    var core = document.createElementNS(SVG_NS, "circle");
    core.setAttribute("cx", shot[0]);
    core.setAttribute("cy", shot[1]);
    core.setAttribute("r", DOT_R + 3);
    core.setAttribute("class", shot[2] ? "shot-made" : "shot-miss");
    ring.appendChild(core);
  }

  function runSpotlights(shots, order) {
    var step = 0;
    (function next() {
      if (step >= order.length) {
        marks.classList.remove("is-dimmed");
        ring.textContent = "";
        Array.prototype.forEach.call(notes.children, function (item) {
          item.classList.remove("is-active");
        });
        return;
      }
      var index = order[step];
      var shot = shots[index];
      if (shot) {
        marks.classList.add("is-dimmed");
        highlight(shot);
        Array.prototype.forEach.call(notes.children, function (item, position) {
          item.classList.toggle("is-active", position === step);
        });
      }
      step += 1;
      window.setTimeout(next, SPOTLIGHT_MS);
    })();
  }

  function drawOneByOne(shots, spotlight) {
    var i = 0;
    (function step() {
      if (i >= shots.length) {
        if (spotlight.length) window.setTimeout(function () {
          runSpotlights(shots, spotlight);
        }, SETTLE_MS);
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
