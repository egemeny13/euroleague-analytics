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

  function chip(name, number, colour, changed) {
    var item = document.createElement("li");
    if (changed) item.className = "is-changed";
    var jersey = document.createElement("span");
    jersey.className = "unit-jersey";
    jersey.style.setProperty("--club", colour);
    jersey.textContent = number || "";
    item.appendChild(jersey);
    item.appendChild(document.createTextNode(name));
    return item;
  }

  /* The changing player always occupies the same row. Sorting the five
     alphabetically moved four names every time the fifth changed, which is why
     the substitution looked like a jolt rather than a swap: nothing was
     actually moving except the reader's eye. */
  function build(data) {
    var colour = data.team.colour;
    var shared = data.shared;
    var first = data.pair[0];
    var numberOf = {};
    data.pair.forEach(function (unit) {
      unit.players.forEach(function (name, i) {
        numberOf[name] = (unit.numbers || [])[i] || "";
      });
    });

    list.textContent = "";
    var slot = document.createElement("li");
    slot.className = "unit-slot";
    list.appendChild(slot);
    shared.forEach(function (name) {
      list.appendChild(chip(name, numberOf[name], colour, false));
    });
    return { slot: slot, numberOf: numberOf, colour: colour, first: first };
  }

  function fillSlot(state, name, animate) {
    var incoming = chip(name, state.numberOf[name], state.colour, true);
    incoming.classList.add("unit-slot");
    if (!animate) {
      state.slot.replaceWith(incoming);
      state.slot = incoming;
      return;
    }
    state.slot.classList.add("is-leaving");
    incoming.classList.add("is-entering");
    state.slot.after(incoming);
    var leaving = state.slot;
    state.slot = incoming;
    window.setTimeout(function () { leaving.remove(); }, SWAP_MS);
  }

  function setFigures(unit) {
    net.textContent = signed(unit.net_rating);
    poss.textContent = String(unit.possessions);
  }

  function run(data) {
    var strong = data.pair[0];
    var weak = data.pair[1];
    var state = build(data);

    function showStrong(animate) {
      fillSlot(state, data.swap.out, animate);
      setFigures(strong);
      swapNote.textContent = "";
      timer = window.setTimeout(showWeak, SETTLE_MS);
    }

    function showWeak() {
      fillSlot(state, data.swap["in"], true);
      swapNote.textContent = data.swap.out + " off, " + data.swap["in"] + " on.";
      window.setTimeout(function () { setFigures(weak); }, SWAP_MS / 2);
      timer = window.setTimeout(function () { showStrong(true); }, HOLD_MS);
    }

    if (reduced.matches || !("IntersectionObserver" in window)) {
      fillSlot(state, data.swap.out, false);
      setFigures(strong);
      return;
    }

    fillSlot(state, data.swap.out, false);
    setFigures(strong);

    var running = false;
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting && !running) {
          running = true;
          timer = window.setTimeout(showWeak, SETTLE_MS);
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
