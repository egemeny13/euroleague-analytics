/* This file used to open with the "Now ask it yourself" window - chips that
   replayed canned answers, then chips that played recordings. The owner removed
   the section on 2026-09-06 (Decision 61, amended): the hero already shows the
   assistant answering, and a second window that only replayed clips was a
   repeat. What remains here is the connect section's behaviour.
   Design record: docs/superpowers/specs/2026-09-04-launch-website-design.md */

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
