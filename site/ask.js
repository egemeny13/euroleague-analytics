/* The one place on the page where the visitor does something.
   Design record: docs/superpowers/specs/2026-09-04-launch-website-design.md,
   Decisions 60 and 61.

   Chips, never a text field. That is a security decision and an experience
   decision at the same time: an endpoint that accepts free text is the only
   version of this worth attacking, and a visitor handed an empty box asks a
   bad question and leaves with a bad impression of a warehouse that would have
   answered a good one.

   Each chip plays a recording. Until 2026-09-06 a chip appended a canned
   transcript to a drawn assistant window, and the owner read that window as a
   fake one. Now every chip has a real capture of Claude answering that exact
   question with this server connected, made the way the hero's was. The first
   chip plays the hero's own file. Nothing here is generated, typed, or
   imitated; the figures on screen are whatever the assistant said that day,
   which is also why the recordings are dated in DECISIONS.md and re-made when
   the loaded seasons change.

   Reduced motion is respected by doing nothing until asked: the stage shows a
   still until a chip is clicked, and a click is the visitor's own choice. */

(function () {
  "use strict";

  var stage = document.getElementById("ask-stage");
  var video = document.getElementById("ask-video");
  var chips = document.getElementById("chips");
  if (!stage || !video || !chips) return;

  var buttons = Array.prototype.slice.call(chips.querySelectorAll(".chip"));

  function source(name, type) {
    var node = document.createElement("source");
    node.src = name + "." + type;
    node.type = "video/" + type;
    return node;
  }

  function play(name) {
    video.pause();
    while (video.firstChild) video.removeChild(video.firstChild);
    video.appendChild(source(name, "webm"));
    video.appendChild(source(name, "mp4"));
    video.load();
    video.play().catch(function () {
      /* A browser that refuses is left showing the poster. Nothing to say. */
    });
  }

  buttons.forEach(function (chip) {
    chip.addEventListener("click", function () {
      var name = chip.getAttribute("data-clip");
      if (!name) return;
      buttons.forEach(function (other) { other.classList.remove("is-playing"); });
      /* Asked chips stay on the board and stay clickable. Marking them spent
         tells the visitor how much of this they have seen without taking
         anything away from them. */
      chip.classList.add("is-asked", "is-playing");
      play(name);
    });
  });

  video.addEventListener("ended", function () {
    buttons.forEach(function (other) { other.classList.remove("is-playing"); });
  });
})();

/* The client tabs. Four genuinely different setups, one visible at a time.
   The panels are all in the markup and only hidden, so the page still says
   everything it has to say with no JavaScript at all.

   This is a real tablist, so it has to behave like one. Declaring the roles and
   stopping there is worse than not declaring them: a screen reader announces
   "tab, 1 of 4", the reader presses an arrow key expecting to move, and nothing
   happens. Arrow keys move, Home and End jump to the ends, and only the
   selected tab is in the tab order - which is the whole point of the pattern,
   because it lets one Tab press step over the group to the content. */
(function () {
  "use strict";
  var list = document.querySelector(".client-tabs");
  if (!list) return;
  var tabs = Array.prototype.slice.call(list.querySelectorAll(".client-tab"));
  if (!tabs.length) return;

  function panelOf(tab) {
    return document.getElementById(tab.getAttribute("aria-controls"));
  }

  function select(tab, moveFocus) {
    tabs.forEach(function (other) {
      var chosen = other === tab;
      other.setAttribute("aria-selected", chosen ? "true" : "false");
      other.tabIndex = chosen ? 0 : -1;
      var panel = panelOf(other);
      if (!panel) return;
      panel.hidden = !chosen;
      /* None of these panels contains anything focusable, so without this a
         keyboard reader can select a tab and never reach what it revealed. */
      panel.tabIndex = chosen ? 0 : -1;
    });
    if (moveFocus) tab.focus();
  }

  list.addEventListener("keydown", function (event) {
    var here = tabs.indexOf(document.activeElement);
    if (here === -1) return;
    var next = null;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      next = tabs[(here + 1) % tabs.length];
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      next = tabs[(here - 1 + tabs.length) % tabs.length];
    } else if (event.key === "Home") {
      next = tabs[0];
    } else if (event.key === "End") {
      next = tabs[tabs.length - 1];
    }
    if (!next) return;
    event.preventDefault();
    select(next, true);
  });

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () { select(tab, false); });
  });

  /* Start from whichever tab the markup marked selected, so the tab order is
     correct before anybody clicks anything. */
  var initial = tabs.filter(function (tab) {
    return tab.getAttribute("aria-selected") === "true";
  })[0] || tabs[0];
  select(initial, false);
})();

/* The address is the whole of the setup, so copying it should not require
   selecting text in a code block.

   Two things this has to survive. `writeText` REJECTS when the document does
   not have focus, and it is absent entirely outside a secure context - and the
   first version had no catch and returned early when the API was missing,
   which left a button that looked live and did nothing at all. When the write
   cannot happen the address is selected instead, so Ctrl+C still works and the
   label says so.

   The label is read once, at setup. Reading it inside the handler meant a
   second click during the 1.6 seconds the button says "Copied" captured
   "Copied" as the text to restore, and the button kept that word for good. */
(function () {
  "use strict";
  var button = document.getElementById("copy-url");
  var url = document.getElementById("server-url");
  if (!button || !url) return;

  var idleLabel = button.textContent;
  var doneLabel = button.getAttribute("data-copied") || "Copied";
  var selectLabel = button.getAttribute("data-select") || "Press Ctrl+C";
  var restore = null;

  function say(label, done) {
    button.textContent = label;
    button.classList.toggle("is-done", !!done);
    window.clearTimeout(restore);
    restore = window.setTimeout(function () {
      button.textContent = idleLabel;
      button.classList.remove("is-done");
    }, 1600);
  }

  function selectTheAddress() {
    var range = document.createRange();
    range.selectNodeContents(url);
    var selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    say(selectLabel, false);
  }

  button.addEventListener("click", function () {
    var text = url.textContent.trim();
    if (!navigator.clipboard || !navigator.clipboard.writeText) {
      selectTheAddress();
      return;
    }
    navigator.clipboard.writeText(text).then(
      function () { say(doneLabel, true); },
      function () { selectTheAddress(); }
    );
  });
})();
