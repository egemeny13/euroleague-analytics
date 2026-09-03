/* The hero conversation types itself once, on load.
   Design record: docs/superpowers/specs/2026-09-04-launch-website-design.md

   This is the only animation on the page that nobody asked for, and it earns
   that by being the explanation: a visitor who watches it understands that the
   product lives inside an assistant they already have, without reading a word
   about connectors or protocols.

   Three things it must not do:
     - run for somebody who asked for less motion (it renders finished instead)
     - run while off screen
     - depend on the network. The answer is committed to this repository, not
       fetched, so it looks identical for every visitor. Only the "Ask it
       yourself" chips further down the page talk to the server. */

(function () {
  "use strict";

  var QUESTION = "Fenerbahçe'nin en iyi beşlisi hangisi?";
  var TYPE_MS = 30;      // per character
  var HOLD_MS = 420;     // pause after the question, before the answer

  var ask = document.getElementById("ask");
  var reply = document.getElementById("reply");
  if (!ask || !reply) return;

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");

  function showFinished() {
    ask.textContent = QUESTION;
    reply.hidden = false;
    reply.style.opacity = "1";
  }

  function type() {
    var caret = document.createElement("span");
    caret.className = "caret";
    caret.setAttribute("aria-hidden", "true");

    var text = document.createTextNode("");
    ask.appendChild(text);
    ask.appendChild(caret);

    var i = 0;
    (function step() {
      if (i >= QUESTION.length) {
        caret.remove();
        window.setTimeout(revealAnswer, HOLD_MS);
        return;
      }
      text.nodeValue = QUESTION.slice(0, ++i);
      window.setTimeout(step, TYPE_MS);
    })();
  }

  function revealAnswer() {
    reply.hidden = false;
    reply.animate(
      [
        { opacity: 0, transform: "translateY(6px)" },
        { opacity: 1, transform: "none" }
      ],
      { duration: 420, easing: "cubic-bezier(.2,.6,.2,1)", fill: "both" }
    );
  }

  function start() {
    if (reduced.matches) {
      showFinished();
      return;
    }
    type();
  }

  // Only once it is actually on screen.
  if ("IntersectionObserver" in window) {
    var seen = false;
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting && !seen) {
          seen = true;
          io.disconnect();
          start();
        }
      });
    }, { threshold: 0.2 });
    io.observe(document.getElementById("thread"));
  } else {
    start();
  }
})();
