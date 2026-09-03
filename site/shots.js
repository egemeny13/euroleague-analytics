/* The shot chart fills itself once, when the section is reached.
   Design record: docs/superpowers/specs/2026-09-04-launch-website-design.md

   The coordinates are the league's own, in centimetres, and they are placed
   with no transform beyond the identity: the court behind them is drawn to the
   same FIBA dimensions in the same units, so a shot lands where it was
   recorded. A hand-tuned scale factor would make the picture look right while
   quietly meaning nothing, which is the failure this file exists to avoid.

   Free throws never appear here. They carry (-1, -1), a sentinel standing in
   for a location the source does not have, and plotting it would put a cluster
   of phantom shots just outside the baseline. */

(function () {
  "use strict";

  var HOLD_MS = 26;   // between shots, once the section is on screen
  var DOT_R = 21;     // centimetres on the court, not pixels on the screen

  var court = document.getElementById("halfcourt");
  var marks = document.getElementById("shot-marks");
  var counter = document.getElementById("shot-count");
  if (!court || !marks || !counter) return;

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

  function drawAll(shots) {
    shots.forEach(place);
    counter.textContent = String(shots.length);
  }

  function drawOneByOne(shots) {
    var i = 0;
    (function step() {
      if (i >= shots.length) return;
      var dot = place(shots[i]);
      dot.animate(
        [
          { opacity: 0, transform: "scale(0.2)" },
          { opacity: 1, transform: "scale(1)" }
        ],
        { duration: 380, easing: "cubic-bezier(.2,.8,.3,1)", fill: "both" }
      );
      counter.textContent = String(++i);
      window.setTimeout(step, HOLD_MS);
    })();
  }

  function run(shots) {
    if (reduced.matches || !("IntersectionObserver" in window)) {
      drawAll(shots);
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          io.disconnect();
          drawOneByOne(shots);
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
    .then(function (data) {
      /* Belt and braces: the export already drops free throws, and this drops
         anything still carrying the sentinel. A silent plot of (-1,-1) would
         look like a real shot. */
      var shots = (data.shots || []).filter(function (s) {
        return !(s[0] === -1 && s[1] === -1);
      });
      if (shots.length) run(shots);
    })
    .catch(function () {
      /* An empty court says nothing false. The claim beside it is about the
         data, and a failed fetch is not evidence against it. */
    });
})();
