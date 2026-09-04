/* The one place on the page where the visitor does something.
   Design record: docs/superpowers/specs/2026-09-04-launch-website-design.md

   Chips, never a text field. That is a security decision and an experience
   decision at the same time: an endpoint that accepts free text is the only
   version of this worth attacking, and a visitor handed an empty box asks a
   bad question and leaves with a bad impression of a warehouse that would have
   answered a good one.

   Today the answers are read from data/asks.json, produced by the same query
   functions the MCP server calls, so the page and a connected assistant cannot
   disagree. The approved next step is a locked endpoint on the hosted server
   that accepts one identifier from an allowlist and runs that query live -
   which is why every chip already carries an `id`. Swapping the source is one
   function; nothing above it changes, and the page looks identical either way. */

(function () {
  "use strict";

  var THINK_MS = 900;   // long enough to read as work, short enough not to annoy

  var chips = document.getElementById("chips");
  var panel = document.getElementById("ask-answer");
  if (!chips || !panel) return;

  /* The chosen question is echoed as your own message before the answer
     arrives, because that is what the window looks like when a person uses it.
     Without it the panel reads as a search result, not as a conversation. */
  function render(ask) {
    panel.textContent = "";

    var mine = document.createElement("div");
    mine.className = "from-you";
    var bubble = document.createElement("p");
    bubble.className = "bubble-user";
    bubble.textContent = ask.question;
    mine.appendChild(bubble);
    panel.appendChild(mine);

    var working = document.createElement("p");
    working.className = "ask-working";
    ["working-dot", "working-what", "working-state"].forEach(function (part, i) {
      var span = document.createElement(i === 0 ? "i" : "span");
      span.className = part;
      if (i === 1) span.textContent = "EuroLeague Analytics";
      if (i === 2) span.textContent = "reading the play-by-play";
      working.appendChild(span);
    });
    panel.appendChild(working);

    window.setTimeout(function () {
      working.remove();

      var reply = document.createElement("div");
      reply.className = "reply is-shown";

      if (ask.players) {
        var lead = document.createElement("p");
        lead.className = "reply-line";
        lead.textContent = "Their most efficient five this season:";
        reply.appendChild(lead);

        var list = document.createElement("ul");
        list.className = "lineup";
        ask.players.forEach(function (name) {
          var item = document.createElement("li");
          item.textContent = name;
          list.appendChild(item);
        });
        reply.appendChild(list);
      } else if (ask.answer) {
        var line = document.createElement("p");
        line.className = "reply-line";
        line.textContent = ask.answer;
        reply.appendChild(line);
      }

      var verdict = document.createElement("p");
      verdict.className = "verdict";
      var figure = document.createElement("span");
      figure.className = "figure";
      figure.textContent = ask.figure;
      verdict.appendChild(figure);
      verdict.appendChild(document.createTextNode(" " + ask.unit));

      /* The number never appears without the population behind it. */
      var qualifier = document.createElement("span");
      qualifier.className = "qualifier";
      qualifier.textContent = ask.qualifier;
      verdict.appendChild(qualifier);

      reply.appendChild(verdict);
      panel.appendChild(reply);
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
          Array.prototype.forEach.call(chips.children, function (other) {
            other.classList.toggle("is-chosen", other === chip);
          });
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
