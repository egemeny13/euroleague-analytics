/* The one place on the page where the visitor does something.
   Design record: docs/superpowers/specs/2026-09-04-launch-website-design.md

   Chips, never a text field. That is a security decision and an experience
   decision at the same time: an endpoint that accepts free text is the only
   version of this worth attacking, and a visitor handed an empty box asks a
   bad question and leaves with a bad impression of a warehouse that would have
   answered a good one.

   The transcript grows. The first version replaced the answer each time, which
   meant the second question destroyed the evidence of the first, and the window
   read as a search box wearing a chat's clothes. Asking three things and
   scrolling back over all three answers is the whole point: it is what using
   this actually looks like.

   The tool call is shown, and it is shown because it is true. A connected
   assistant does exactly this - it picks one of the eleven el_* tools, runs it,
   and answers from what came back. Naming the tool is the difference between a
   mock-up of an assistant and a window onto one.

   Today the answers are read from data/asks.json, produced by the same query
   functions the MCP server calls, so the page and a connected assistant cannot
   disagree. The approved next step is a locked endpoint on the hosted server
   that accepts one identifier from an allowlist and runs that query live -
   which is why every chip already carries an `id`. Swapping the source is one
   function; nothing above it changes, and the page looks identical either way. */

(function () {
  "use strict";

  var THINK_MS = 620;   // before the tool call appears
  var TOOL_MS = 780;    // the tool call, running
  var TYPE_MS = 18;     // per character of the answer's first line

  var chips = document.getElementById("chips");
  var panel = document.getElementById("ask-answer");
  if (!chips || !panel) return;

  var busy = false;

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  /* The window follows the newest message the way any assistant's does. It
     scrolls its own box, never the page, so a visitor reading further down is
     not dragged back up here. */
  function follow() {
    panel.scrollTop = panel.scrollHeight;
  }

  function typeInto(node, text, done) {
    var i = 0;
    (function step() {
      if (i >= text.length) { done(); return; }
      node.textContent = text.slice(0, ++i);
      follow();
      window.setTimeout(step, TYPE_MS);
    })();
  }

  function render(ask) {
    if (busy) return;
    busy = true;

    var empty = panel.querySelector(".ask-empty");
    if (empty) empty.remove();

    /* Your own message first, because that is what the window looks like when
       a person uses it. */
    var mine = el("div", "from-you");
    mine.appendChild(el("p", "bubble-user", ask.question));
    panel.appendChild(mine);
    follow();

    var working = el("p", "ask-working");
    working.appendChild(el("i", "working-dot"));
    working.appendChild(el("span", "working-state", "Thinking"));
    panel.appendChild(working);
    follow();

    window.setTimeout(function () {
      working.remove();

      /* The tool call. It names the tool the connected assistant would run,
         and it is the same name that appears in that assistant's own tool
         list. Nothing about it is decorative. */
      var call = el("div", "toolcall is-running");
      call.appendChild(el("span", "toolcall-spinner"));
      var name = el("span", "toolcall-name", ask.tool || "el_describe_warehouse");
      call.appendChild(name);
      call.appendChild(el("span", "toolcall-source", "EuroLeague Analytics"));
      panel.appendChild(call);
      follow();

      window.setTimeout(function () {
        call.classList.remove("is-running");
        call.classList.add("is-done");

        var reply = el("div", "reply is-shown");
        var lead = el("p", "reply-line");
        reply.appendChild(lead);
        panel.appendChild(reply);

        var opening = ask.players
          ? "Their most efficient five this season:"
          : (ask.answer || "From the play-by-play:");

        typeInto(lead, opening, function () {
          if (ask.players) {
            var list = el("ul", "lineup");
            ask.players.forEach(function (player) {
              list.appendChild(el("li", null, player));
            });
            reply.appendChild(list);
          }

          var verdict = el("p", "verdict");
          verdict.appendChild(el("span", "figure", ask.figure));
          verdict.appendChild(document.createTextNode(" " + ask.unit));
          /* The number never appears without the population behind it. */
          verdict.appendChild(el("span", "qualifier", ask.qualifier));
          reply.appendChild(verdict);

          follow();
          busy = false;
        });
      }, TOOL_MS);
    }, THINK_MS);
  }

  fetch("data/asks.json")
    .then(function (response) {
      if (!response.ok) throw new Error("asks.json " + response.status);
      return response.json();
    })
    .then(function (data) {
      (data.asks || []).forEach(function (ask) {
        var chip = document.createElement("button");
        chip.type = "button";
        chip.className = "chip";
        chip.textContent = ask.question;
        chip.addEventListener("click", function () {
          if (busy) return;
          /* Asked chips stay on the board and stay clickable. Marking them
             spent tells the visitor how much of this they have seen without
             taking anything away from them. */
          chip.classList.add("is-asked");
          render(ask);
        });
        chips.appendChild(chip);
      });
    })
    .catch(function () {
      /* Leave the invitation as it is. An error message about a JSON file
         would tell the visitor nothing they can act on. */
    });
})();

/* The client tabs. Four genuinely different setups, one visible at a time.
   The panels are all in the markup and only hidden, so the page still says
   everything it has to say with no JavaScript at all. */
(function () {
  "use strict";
  var list = document.querySelector(".client-tabs");
  if (!list) return;
  var tabs = Array.prototype.slice.call(list.querySelectorAll(".client-tab"));

  function select(tab) {
    tabs.forEach(function (other) {
      var chosen = other === tab;
      other.setAttribute("aria-selected", chosen ? "true" : "false");
      var panel = document.getElementById(other.getAttribute("aria-controls"));
      if (panel) panel.hidden = !chosen;
    });
  }

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () { select(tab); });
  });
})();

/* The address is the whole of the setup, so copying it should not require
   selecting text in a code block. */
(function () {
  "use strict";
  var button = document.getElementById("copy-url");
  var url = document.getElementById("server-url");
  if (!button || !url || !navigator.clipboard) return;
  button.addEventListener("click", function () {
    navigator.clipboard.writeText(url.textContent.trim()).then(function () {
      var original = button.textContent;
      button.textContent = button.getAttribute("data-copied");
      button.classList.add("is-done");
      window.setTimeout(function () {
        button.textContent = original;
        button.classList.remove("is-done");
      }, 1600);
    });
  });
})();
