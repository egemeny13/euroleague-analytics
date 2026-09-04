/* One substitution, and the number moves from one end of the scale to the other.
   Design record: docs/superpowers/specs/2026-09-04-launch-website-design.md

   Both units are real and they are one player apart, which is the whole reason
   this section exists: it is the claim, not an illustration of the claim. The
   figures come from data/lineups.json, produced by `el_get_lineup_stats` - the
   same query the MCP server answers with - so the website and a connected
   assistant cannot disagree.

   The number is never shown without the possessions behind it. +24.5 over 214
   possessions and -34.1 over 64 are not the same kind of fact, and a reader who
   sees only the first pair of numbers has been misled by omission. */

(function () {
  "use strict";

  var SETTLE_MS = 2600;  // the first unit, before the substitution
  var SWAP_MS = 520;     // the name sliding out and the new one in
  var HOLD_MS = 4200;    // the second unit, before it goes back

  var host = document.getElementById("unit");
  var list = document.getElementById("unit-names");
  var net = document.getElementById("unit-net");
  var poss = document.getElementById("unit-poss");
  var swapNote = document.getElementById("unit-swap");
  if (!host || !list || !net || !poss || !swapNote) return;

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  var timer = null;

  function signed(value) {
    /* A minus sign, not a hyphen: the figures are set in a monospaced face and
       the hyphen is visibly shorter. */
    return (value > 0 ? "+" : value < 0 ? "−" : "") + Math.abs(value).toFixed(1);
  }

  function render(unit, changed) {
    list.textContent = "";
    unit.players.forEach(function (name) {
      var item = document.createElement("li");
      item.textContent = name;
      if (name === changed) item.className = "is-changed";
      list.appendChild(item);
    });
    net.textContent = signed(unit.net_rating);
    poss.textContent = String(unit.possessions);
  }

  function run(data) {
    var strong = data.pair[0];
    var weak = data.pair[1];

    function showStrong() {
      render(strong, null);
      swapNote.textContent = "";
      timer = window.setTimeout(showSwap, SETTLE_MS);
    }

    function showSwap() {
      var leaving = list.querySelector("li.is-changed") ||
        Array.prototype.filter.call(list.children, function (item) {
          return item.textContent === data.swap.out;
        })[0];
      if (leaving) leaving.classList.add("is-leaving");
      swapNote.textContent = data.swap.out + " off, " + data.swap["in"] + " on.";
      timer = window.setTimeout(showWeak, SWAP_MS);
    }

    function showWeak() {
      render(weak, data.swap["in"]);
      timer = window.setTimeout(showStrong, HOLD_MS);
    }

    if (reduced.matches || !("IntersectionObserver" in window)) {
      render(strong, null);
      return;
    }

    var running = false;
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting && !running) {
          running = true;
          showStrong();
        } else if (!entry.isIntersecting && running) {
          running = false;
          window.clearTimeout(timer);
        }
      });
    }, { threshold: 0.35 });
    io.observe(host);
  }

  fetch("data/lineups.json")
    .then(function (response) {
      if (!response.ok) throw new Error("lineups.json " + response.status);
      return response.json();
    })
    .then(run)
    .catch(function () {
      /* Empty says nothing false. */
    });
})();
