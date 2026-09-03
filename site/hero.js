/* The hero conversation types itself, then moves to the next assistant.
   Design record: docs/superpowers/specs/2026-09-04-launch-website-design.md

   Why it cycles: a single assistant in the window says "this works with that
   one". The product works with any client that speaks MCP, and a visitor who
   uses a different one has to see their own before they believe it.

   What it deliberately is not: a copy of anybody's interface. Each assistant is
   named in text and carries its own brand colour, which identifies it the way a
   club colour identifies a club. No logo is reproduced and no interface is
   imitated. Naming a product to say we work with it is fair use; dressing our
   page up as that product is not, and it would imply an endorsement none of
   them has given.

   Three things it must not do:
     - run for somebody who asked for less motion (it renders finished instead)
     - run while off screen
     - depend on the network. The answer is committed to this repository, not
       fetched, so it looks identical for every visitor. Only the "Ask it
       yourself" chips further down the page talk to the server. */

(function () {
  "use strict";

  /* Verified against docs/CLIENT_COMPATIBILITY.md. Claude and Gemini are
     recorded there as live-verified; ChatGPT is recorded as expected from the
     published Apps SDK specification, and Decision 51 covers the registration
     path it needs. Nothing is listed here that the compatibility matrix does
     not already claim. */
  var CLIENTS = [
    { name: "Claude",  initial: "C",  tint: "#C15F3C" },
    { name: "ChatGPT", initial: "CG", tint: "#0F8A6E" },
    { name: "Gemini",  initial: "G",  tint: "#3B6FE0" }
  ];

  /* Temporarily English. The design asks this in Turkish, to show that the
     visitor can ask in their own language, but tests/test_english_only.py
     fails on Turkish characters in any tracked file and that rule has not been
     amended yet. See section 3 of the design record. */
  var QUESTION = "Which five-man lineup wins games for Fenerbahce?";
  var TYPE_MS = 30;      // per character
  var HOLD_MS = 420;     // after the question, before the tool call
  var READ_MS = 4200;    // how long the finished answer stays before the next client

  var ask = document.getElementById("ask");
  var reply = document.getElementById("reply");
  var appName = document.getElementById("app-name");
  var avatar = document.getElementById("app-avatar");
  var thread = document.getElementById("thread");
  if (!ask || !reply || !appName || !avatar || !thread) return;

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  var index = 0;
  var timer = null;

  function setClient(client) {
    appName.textContent = client.name;
    avatar.textContent = client.initial;
    avatar.style.setProperty("--tint", client.tint);
  }

  function clear() {
    window.clearTimeout(timer);
    ask.textContent = "";
    reply.classList.remove("is-shown");
  }

  function showFinished() {
    setClient(CLIENTS[0]);
    ask.textContent = QUESTION;
    reply.classList.add("is-shown");
  }

  function typeQuestion(done) {
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
        timer = window.setTimeout(done, HOLD_MS);
        return;
      }
      text.nodeValue = QUESTION.slice(0, ++i);
      timer = window.setTimeout(step, TYPE_MS);
    })();
  }

  function revealAnswer() {
    reply.classList.add("is-shown");
    timer = window.setTimeout(nextClient, READ_MS);
  }

  function nextClient() {
    index = (index + 1) % CLIENTS.length;
    clear();
    setClient(CLIENTS[index]);
    timer = window.setTimeout(function () {
      typeQuestion(revealAnswer);
    }, 260);
  }

  function start() {
    if (reduced.matches) {
      showFinished();
      return;
    }
    setClient(CLIENTS[0]);
    typeQuestion(revealAnswer);
  }

  /* Off screen it does not run: an animation nobody is looking at is only a
     battery cost. */
  if ("IntersectionObserver" in window) {
    var running = false;
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting && !running) {
          running = true;
          start();
        } else if (!entry.isIntersecting && running) {
          running = false;
          window.clearTimeout(timer);
        }
      });
    }, { threshold: 0.2 });
    io.observe(thread);
  } else {
    start();
  }
})();
