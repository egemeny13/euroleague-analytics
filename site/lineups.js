/* One substitution, on the floor, and the number moves from one end of the
   scale to the other.
   Design record: docs/superpowers/specs/2026-09-04-launch-website-design.md

   Both units are real and they are one player apart, which is the whole reason
   this section exists: it is the claim, not an illustration of the claim. The
   figures come from data/lineups.json, produced by `el_get_lineup_stats` - the
   same query the MCP server answers with - so the website and a connected
   assistant cannot disagree.

   The number is never shown without the possessions behind it. +24.5 over 214
   possessions and -34.1 over 64 are not the same kind of fact, and a reader who
   sees only the first pair of numbers has been misled by omission.

   TWO KINDS OF THING ARE DRAWN HERE. A player's POSITION is measured: it is his
   club's own E2025 registration, joined to the game player id through
   person_game_link, and it is why Birch is a centre and Baldwin is a guard. A
   player's SPOT is a convention: the ordinary arrangement of two guards, two
   forwards and a centre, chosen so the picture is readable. The caption in the
   markup says so. Never let the second borrow the authority of the first.

   WHY THE SUBSTITUTION IS NOT ONE MOVE. It genuinely is not one. Birch leaves,
   the four who stay spread out because there is no longer a centre to play
   through, and Baldwin arrives into the space that opens at the top. Playing
   that as a single instant swap - which is what the first version did - showed
   a name changing and hid the only thing worth seeing, which is that the paint
   empties.

   Nothing here runs off screen, and every wait is measured in time the section
   spends being looked at, so a visitor who scrolls past and comes back sees the
   sequence rather than its aftermath. */

(function () {
  "use strict";

  var HOLD_STRONG_MS = 2800;  // the first unit, before anything moves
  var LEAVE_MS = 700;         // Birch walking off
  var SPREAD_MS = 620;        // the four who stay, opening up
  var ARRIVE_MS = 760;        // Baldwin walking on
  var HOLD_WEAK_MS = 4200;    // the second unit, before it goes back

  /* The court's own units, and the same frame the shot chart uses: x runs
     -750 to 750 across, y from the baseline. The viewBox below must match the
     one in the markup or every marker lands in the wrong place. */
  var BOX = { x: -820, y: -60, width: 1640, height: 1160 };
  var MIRROR_Y = 1000;

  /* Where a player who is not on the floor waits: just outside the sideline,
     level with the three-point line, which is where a substitute actually
     stands. It must stay inside the viewBox - a bench beyond it put the
     marker outside the card, walking across the page itself. */
  var BENCH = { left: -790, right: 790, y: 620 };

  var floor = document.getElementById("floor");
  var stage = document.getElementById("floor-players");
  var paint = document.getElementById("floor-paint");
  var emptyNote = document.getElementById("floor-empty");
  var net = document.getElementById("unit-net");
  var poss = document.getElementById("unit-poss");
  var swapNote = document.getElementById("unit-swap");
  if (!floor || !stage || !net || !poss || !swapNote) return;

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");

  /* ---- a clock that only runs while the section is being looked at ---- */
  var pending = null;
  var armedAt = 0;
  var handle = null;
  var onScreen = false;

  function arm() {
    armedAt = Date.now();
    handle = window.setTimeout(function () {
      var due = pending;
      pending = null;
      handle = null;
      if (due) due.fn();
    }, pending.left);
  }

  function after(ms, fn) {
    pending = { fn: fn, left: ms };
    if (onScreen) arm();
  }

  function pause() {
    onScreen = false;
    if (handle === null) return;
    window.clearTimeout(handle);
    handle = null;
    pending.left = Math.max(0, pending.left - (Date.now() - armedAt));
  }

  function resume() {
    if (onScreen) return;
    onScreen = true;
    if (pending && handle === null) arm();
  }

  /* ---- placing ---- */

  function percentLeft(x) {
    return (((x - BOX.x) / BOX.width) * 100).toFixed(3) + "%";
  }

  function percentTop(y) {
    return ((((MIRROR_Y - y) - BOX.y) / BOX.height) * 100).toFixed(3) + "%";
  }

  function moveTo(marker, x, y) {
    marker.style.left = percentLeft(x);
    marker.style.top = percentTop(y);
  }

  function signed(value) {
    /* A minus sign, not a hyphen: the figures are set in a monospaced face and
       the hyphen is visibly shorter. */
    return (value > 0 ? "+" : value < 0 ? "−" : "") + Math.abs(value).toFixed(1);
  }

  function build(data) {
    var colour = data.team.colour;
    var markers = {};

    Object.keys(data.players).forEach(function (name) {
      var who = data.players[name];
      var marker = document.createElement("div");
      marker.className = "player is-off";
      marker.setAttribute("data-position", who.position);

      var disc = document.createElement("span");
      disc.className = "player-disc";
      disc.style.setProperty("--club", colour);
      disc.textContent = who.number;
      marker.appendChild(disc);

      var label = document.createElement("span");
      label.className = "player-name";
      label.textContent = name;
      marker.appendChild(label);

      var role = document.createElement("span");
      role.className = "player-role";
      role.textContent = who.position;
      marker.appendChild(role);

      stage.appendChild(marker);
      markers[name] = marker;
    });

    return markers;
  }

  function setFigures(unit) {
    net.textContent = signed(unit.net_rating);
    poss.textContent = String(unit.possessions);
  }

  function run(data) {
    var strong = data.pair[0];
    var weak = data.pair[1];
    var spots = data.spots;
    var markers = build(data);
    var leaving = data.swap.out;   // Birch
    var arriving = data.swap["in"]; // Baldwin

    function seat(name, side) {
      moveTo(markers[name], BENCH[side], BENCH.y);
      markers[name].classList.add("is-off");
    }

    function showStrong(animate) {
      Object.keys(spots.strong).forEach(function (name) {
        var spot = spots.strong[name];
        markers[name].classList.remove("is-off", "is-leaving", "is-arriving");
        moveTo(markers[name], spot[0], spot[1]);
      });
      seat(arriving, "left");
      setFigures(strong);
      swapNote.textContent = "";
      if (paint) paint.classList.remove("is-empty");
      if (emptyNote) emptyNote.hidden = true;
      after(HOLD_STRONG_MS, stepOut);
    }

    /* Beat one. The centre leaves, and nothing else moves yet, so the thing
       that is happening is unmistakable. */
    function stepOut() {
      swapNote.textContent = leaving + " off.";
      markers[leaving].classList.add("is-leaving");
      seat(leaving, "right");
      after(LEAVE_MS, stepSpread);
    }

    /* Beat two. The four who stay open up, because there is no longer a centre
       to play through. This is the beat the old version had no room for. */
    function stepSpread() {
      Object.keys(spots.weak).forEach(function (name) {
        if (name === arriving) return;
        var spot = spots.weak[name];
        moveTo(markers[name], spot[0], spot[1]);
      });
      if (paint) paint.classList.add("is-empty");
      if (emptyNote) emptyNote.hidden = false;
      after(SPREAD_MS, stepIn);
    }

    /* Beat three. Baldwin arrives into the space at the top, and only then does
       the number change - after the reader has seen why. */
    function stepIn() {
      var spot = spots.weak[arriving];
      markers[arriving].classList.remove("is-off");
      markers[arriving].classList.add("is-arriving");
      moveTo(markers[arriving], spot[0], spot[1]);
      swapNote.textContent = leaving + " off, " + arriving + " on.";
      after(ARRIVE_MS, function () {
        setFigures(weak);
        after(HOLD_WEAK_MS, function () { showStrong(true); });
      });
    }

    /* Somebody who asked for less motion gets the finished first unit, not a
       sequence played quickly. */
    if (reduced.matches || !("IntersectionObserver" in window)) {
      Object.keys(spots.strong).forEach(function (name) {
        markers[name].classList.remove("is-off");
        moveTo(markers[name], spots.strong[name][0], spots.strong[name][1]);
      });
      seat(arriving, "left");
      setFigures(strong);
      return;
    }

    /* On screen AND in the visible tab. A background tab still reports its
       sections as intersecting, and the sequence would play out to nobody. */
    var started = false;
    var visible = false;

    function settle() {
      if (visible && document.visibilityState === "visible") {
        resume();
        if (!started) {
          started = true;
          showStrong(false);
        }
      } else {
        pause();
      }
    }

    document.addEventListener("visibilitychange", settle);

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        visible = entry.isIntersecting;
        settle();
      });
    }, { threshold: 0.4 });
    io.observe(floor);
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
