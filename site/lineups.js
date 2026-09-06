/* EuroLeague Analytics — Five-man Lineup Spatial Transition
   Reconstructs the five-man unit transformation on the floor:
   Birch (Center) off, Baldwin (Guard) on -> paint empties, four spread,
   net rating swings by 58.6 points per 100 possessions (+24.5 to −34.1). */

(function () {
  "use strict";

  var HOLD_STRONG_MS = 3400;
  var LEAVE_MS = 680;
  var SPREAD_MS = 600;
  var ARRIVE_MS = 720;
  var HOLD_WEAK_MS = 4600;

  var BOX = { x: -820, y: -60, width: 1640, height: 1160 };
  var MIRROR_Y = 1000;
  var BENCH = { left: -790, right: 790, y: 620 };

  var floor = document.getElementById("floor");
  var stage = document.getElementById("floor-players");
  var paint = document.getElementById("floor-paint");
  var emptyNote = document.getElementById("floor-empty");
  var net = document.getElementById("unit-net");
  var poss = document.getElementById("unit-poss");
  var swapNote = document.getElementById("unit-swap");
  var btnStrong = document.getElementById("btn-unit-strong");
  var btnWeak = document.getElementById("btn-unit-weak");

  if (!floor || !stage || !net || !poss || !swapNote) return;

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");

  var pending = null;
  var armedAt = 0;
  var handle = null;
  var onScreen = false;
  var userInteracting = false;
  var currentUnit = "strong";

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
    if (onScreen && !userInteracting) arm();
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
    if (pending && handle === null && !userInteracting) arm();
  }

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

  var SWAP_OUT_MS = 190;

  function swapFigure(element, text) {
    if (element.textContent === text) return;
    if (reduced.matches) {
      element.textContent = text;
      return;
    }
    var metric = element.parentNode;
    element.classList.remove("is-changing");
    if (metric) metric.classList.remove("is-changing");
    void element.offsetWidth;
    element.classList.add("is-changing");
    if (metric) metric.classList.add("is-changing");
    window.setTimeout(function () { element.textContent = text; }, SWAP_OUT_MS);
  }

  function setFigures(unit, animate) {
    if (!animate) {
      net.textContent = signed(unit.net_rating);
      poss.textContent = String(unit.possessions);
      return;
    }
    swapFigure(net, signed(unit.net_rating));
    swapFigure(poss, String(unit.possessions));
  }

  function updateToggleButtons(active) {
    if (btnStrong) btnStrong.classList.toggle("is-active", active === "strong");
    if (btnWeak) btnWeak.classList.toggle("is-active", active === "weak");
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

    function paintStrong(animate) {
      currentUnit = "strong";
      updateToggleButtons("strong");
      Object.keys(spots.strong).forEach(function (name) {
        var spot = spots.strong[name];
        markers[name].classList.remove("is-off", "is-leaving", "is-arriving");
        moveTo(markers[name], spot[0], spot[1]);
      });
      seat(arriving, "left");
      setFigures(strong, animate);
      swapNote.textContent = "Birch on the floor.";
      if (paint) paint.classList.remove("is-empty");
      if (emptyNote) emptyNote.hidden = true;
    }

    function paintWeak(animate) {
      currentUnit = "weak";
      updateToggleButtons("weak");
      Object.keys(spots.weak).forEach(function (name) {
        var spot = spots.weak[name];
        markers[name].classList.remove("is-off", "is-leaving", "is-arriving");
        moveTo(markers[name], spot[0], spot[1]);
      });
      seat(leaving, "right");
      setFigures(weak, animate);
      swapNote.textContent = leaving + " off, " + arriving + " on.";
      if (paint) paint.classList.add("is-empty");
      if (emptyNote) emptyNote.hidden = false;
    }

    function transitionToWeak() {
      // Step 1: Birch steps out
      swapNote.textContent = leaving + " off.";
      markers[leaving].classList.add("is-leaving");
      seat(leaving, "right");

      after(LEAVE_MS, function () {
        // Step 2: four spread
        Object.keys(spots.weak).forEach(function (name) {
          if (name === arriving) return;
          var spot = spots.weak[name];
          moveTo(markers[name], spot[0], spot[1]);
        });
        if (paint) paint.classList.add("is-empty");
        if (emptyNote) emptyNote.hidden = false;

        after(SPREAD_MS, function () {
          // Step 3: Baldwin arrives
          var spot = spots.weak[arriving];
          markers[arriving].classList.remove("is-off");
          markers[arriving].classList.add("is-arriving");
          moveTo(markers[arriving], spot[0], spot[1]);
          swapNote.textContent = leaving + " off, " + arriving + " on.";

          after(ARRIVE_MS, function () {
            currentUnit = "weak";
            updateToggleButtons("weak");
            setFigures(weak, true);
            after(HOLD_WEAK_MS, transitionToStrong);
          });
        });
      });
    }

    function transitionToStrong() {
      // Baldwin steps out
      swapNote.textContent = arriving + " off.";
      markers[arriving].classList.add("is-leaving");
      seat(arriving, "left");

      after(LEAVE_MS, function () {
        // four condense back
        Object.keys(spots.strong).forEach(function (name) {
          if (name === leaving) return;
          var spot = spots.strong[name];
          moveTo(markers[name], spot[0], spot[1]);
        });
        if (paint) paint.classList.remove("is-empty");
        if (emptyNote) emptyNote.hidden = true;

        after(SPREAD_MS, function () {
          // Birch arrives back
          var spot = spots.strong[leaving];
          markers[leaving].classList.remove("is-off");
          markers[leaving].classList.add("is-arriving");
          moveTo(markers[leaving], spot[0], spot[1]);
          swapNote.textContent = "Birch on the floor.";

          after(ARRIVE_MS, function () {
            currentUnit = "strong";
            updateToggleButtons("strong");
            setFigures(strong, true);
            after(HOLD_STRONG_MS, transitionToWeak);
          });
        });
      });
    }

    // Manual controls
    if (btnStrong) {
      btnStrong.addEventListener("click", function () {
        userInteracting = true;
        window.clearTimeout(handle);
        paintStrong(true);
      });
    }

    if (btnWeak) {
      btnWeak.addEventListener("click", function () {
        userInteracting = true;
        window.clearTimeout(handle);
        paintWeak(true);
      });
    }

    // Initial paint
    paintStrong(false);

    if (reduced.matches || !("IntersectionObserver" in window)) return;

    var started = false;
    var visible = false;

    function settle() {
      if (visible && document.visibilityState === "visible") {
        resume();
        if (!started) {
          started = true;
          after(HOLD_STRONG_MS, transitionToWeak);
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
    }, { threshold: 0.35 });

    io.observe(floor);
  }

  fetch("data/lineups.json")
    .then(function (response) {
      if (!response.ok) throw new Error("lineups.json " + response.status);
      return response.json();
    })
    .then(run)
    .catch(function () {});
})();
