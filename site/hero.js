/* The hero conversation types itself, then moves to the next assistant.
   Design record: docs/superpowers/specs/2026-09-04-launch-website-design.md

   Why it cycles: a single assistant in the window says "this works with that
   one". The product works with any client that speaks MCP, and a visitor who
   uses a different one has to see their own before they believe it. Each one
   gets a different question, because the same sentence three times reads as a
   loop rather than as a tool.

   The four beats are the explanation. You ask; EuroLeague Analytics goes and
   reads; the assistant thinks; the answer arrives. The third party in that
   sequence is the thing the visitor is being asked to connect, and watching it
   work is what makes "connect once" mean something. It is named the way a
   person would name it, never by its function names.

   What this deliberately is not: a copy of anybody's interface. Each assistant
   is named in text and carries its own brand colour, which identifies it the
   way a club colour identifies a club. No logo is reproduced and no interface
   is imitated. Naming a product to say we work with it is fair use; dressing
   our page up as that product is not.

   Three things it must not do:
     - run for somebody who asked for less motion (it renders finished instead)
     - run while off screen
     - depend on the network. Every answer is committed to this repository, so
       it looks identical for every visitor. Only the "Ask it yourself" chips
       further down the page talk to the server. */

(function () {
  "use strict";

  /* Verified against docs/CLIENT_COMPATIBILITY.md. Claude and Gemini are
     recorded there as live-verified; ChatGPT is recorded as expected from the
     published Apps SDK specification, and Decision 51 covers the registration
     path it needs. Nothing is claimed here that the matrix does not claim. */
  var CLIENTS = [
    { name: "Claude",  initial: "C",  tint: "#C15F3C" },
    { name: "ChatGPT", initial: "CG", tint: "#0F8A6E" },
    { name: "Gemini",  initial: "G",  tint: "#3B6FE0" }
  ];

  var TYPE_MS = 30;      // per character
  var ASK_HOLD_MS = 380; // after the question, before the lookup starts
  var WORK_MS = 1250;    // how long the lookup shows
  var THINK_MS = 620;    // the assistant's own pause before answering
  var READ_MS = 4600;    // the finished answer, before the next assistant

  var thread = document.getElementById("thread");
  var appName = document.getElementById("app-name");
  var avatar = document.getElementById("app-avatar");
  if (!thread || !appName || !avatar) return;

  var exchanges = Array.prototype.slice.call(thread.querySelectorAll(".exchange"));
  if (!exchanges.length) return;

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  var index = 0;
  var timer = null;

  function parts(exchange) {
    return {
      question: exchange.getAttribute("data-question") || "",
      typed: exchange.querySelector(".ask-typed"),
      working: exchange.querySelector(".working"),
      reply: exchange.querySelector(".reply")
    };
  }

  function reset(exchange) {
    var p = parts(exchange);
    if (p.typed) p.typed.textContent = "";
    if (p.working) p.working.classList.remove("is-shown", "is-done");
    if (p.reply) p.reply.classList.remove("is-shown");
  }

  function show(step) {
    exchanges.forEach(function (exchange, position) {
      exchange.classList.toggle("is-current", position === step);
      if (position !== step) reset(exchange);
    });
    var client = CLIENTS[step % CLIENTS.length];
    appName.textContent = client.name;
    avatar.textContent = client.initial;
    avatar.style.setProperty("--tint", client.tint);
  }

  function typeInto(p, done) {
    /* Start from empty every time. The section stops when it scrolls out of
       view and starts again when it comes back, and without this the second
       run appended a second copy of the sentence to the first one. */
    p.typed.textContent = "";

    var caret = document.createElement("span");
    caret.className = "caret";
    caret.setAttribute("aria-hidden", "true");
    var text = document.createTextNode("");
    p.typed.appendChild(text);
    p.typed.appendChild(caret);

    var i = 0;
    (function step() {
      if (i >= p.question.length) {
        caret.remove();
        timer = window.setTimeout(done, ASK_HOLD_MS);
        return;
      }
      text.nodeValue = p.question.slice(0, ++i);
      timer = window.setTimeout(step, TYPE_MS);
    })();
  }

  function play() {
    show(index);
    reset(exchanges[index]);
    var p = parts(exchanges[index]);

    typeInto(p, function lookUp() {
      if (p.working) p.working.classList.add("is-shown");
      timer = window.setTimeout(function think() {
        if (p.working) p.working.classList.add("is-done");
        timer = window.setTimeout(function answer() {
          if (p.reply) p.reply.classList.add("is-shown");
          timer = window.setTimeout(function () {
            index = (index + 1) % exchanges.length;
            play();
          }, READ_MS);
        }, THINK_MS);
      }, WORK_MS);
    });
  }

  function showFinished() {
    show(0);
    var p = parts(exchanges[0]);
    if (p.typed) p.typed.textContent = p.question;
    if (p.working) p.working.classList.add("is-shown", "is-done");
    if (p.reply) p.reply.classList.add("is-shown");
  }

  if (reduced.matches) {
    showFinished();
    return;
  }

  show(0);

  /* Off screen it does not run: an animation nobody is looking at is only a
     battery cost. */
  if ("IntersectionObserver" in window) {
    var running = false;
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting && !running) {
          running = true;
          play();
        } else if (!entry.isIntersecting && running) {
          running = false;
          window.clearTimeout(timer);
        }
      });
    }, { threshold: 0.2 });
    io.observe(thread);
  } else {
    play();
  }
})();
