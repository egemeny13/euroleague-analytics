/* EuroLeague Analytics — Continuous Question → Answer Experience
   Principles: Minimal when paused. Extremely dynamic when moving.
   Transforms question → query inspection → sample size proof → verified verdict. */

(function () {
  "use strict";

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");

  var tabs = Array.prototype.slice.call(document.querySelectorAll(".qa-tab"));
  var panels = Array.prototype.slice.call(document.querySelectorAll(".qa-panel"));
  var container = document.getElementById("qa");

  if (!tabs.length || !panels.length) return;

  var currentIndex = 0;
  var timer = null;
  var isHoveredOrFocused = false;
  var isVisible = false;

  var STEP_INTERVAL = 8000; // time before cycling to next question if unattended

  function activateTab(index, animate) {
    currentIndex = index;

    tabs.forEach(function (tab, i) {
      var active = i === index;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", active ? "true" : "false");
      tab.tabIndex = active ? 0 : -1;
    });

    panels.forEach(function (panel, i) {
      var active = i === index;
      panel.hidden = !active;
      panel.classList.toggle("is-active", active);

      if (active && animate && !reduced.matches) {
        animatePanel(panel);
      }
    });
  }

  function animatePanel(panel) {
    var queryRow = panel.querySelector(".qa-query-row");
    var proofRow = panel.querySelector(".qa-proof-row");
    var answerCard = panel.querySelector(".qa-answer-card");

    if (!queryRow || !proofRow || !answerCard) return;

    queryRow.style.opacity = "0";
    queryRow.style.transform = "translateY(6px)";
    proofRow.style.opacity = "0";
    proofRow.style.transform = "translateY(6px)";
    answerCard.style.opacity = "0";
    answerCard.style.transform = "translateY(8px) scale(0.99)";

    window.requestAnimationFrame(function () {
      queryRow.style.transition = "opacity 280ms cubic-bezier(0.16, 1, 0.3, 1), transform 280ms cubic-bezier(0.16, 1, 0.3, 1)";
      queryRow.style.opacity = "1";
      queryRow.style.transform = "none";

      window.setTimeout(function () {
        proofRow.style.transition = "opacity 320ms cubic-bezier(0.16, 1, 0.3, 1), transform 320ms cubic-bezier(0.16, 1, 0.3, 1)";
        proofRow.style.opacity = "1";
        proofRow.style.transform = "none";

        window.setTimeout(function () {
          answerCard.style.transition = "opacity 380ms cubic-bezier(0.16, 1, 0.3, 1), transform 380ms cubic-bezier(0.16, 1, 0.3, 1)";
          answerCard.style.opacity = "1";
          answerCard.style.transform = "none";
        }, 180);
      }, 200);
    });
  }

  function scheduleNext() {
    if (reduced.matches || isHoveredOrFocused || !isVisible) return;
    window.clearTimeout(timer);
    timer = window.setTimeout(function () {
      var next = (currentIndex + 1) % tabs.length;
      activateTab(next, true);
      scheduleNext();
    }, STEP_INTERVAL);
  }

  // Keyboard navigation for tablist
  var tablist = document.querySelector(".qa-selector");
  if (tablist) {
    tablist.addEventListener("keydown", function (e) {
      var activeTab = document.activeElement;
      var index = tabs.indexOf(activeTab);
      if (index === -1) return;

      var target = null;
      if (e.key === "ArrowRight" || e.key === "ArrowDown") {
        target = tabs[(index + 1) % tabs.length];
      } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
        target = tabs[(index - 1 + tabs.length) % tabs.length];
      } else if (e.key === "Home") {
        target = tabs[0];
      } else if (e.key === "End") {
        target = tabs[tabs.length - 1];
      }

      if (target) {
        e.preventDefault();
        target.focus();
        var newIdx = parseInt(target.getAttribute("data-index"), 10);
        window.clearTimeout(timer);
        activateTab(newIdx, true);
      }
    });
  }

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      var idx = parseInt(tab.getAttribute("data-index"), 10);
      window.clearTimeout(timer);
      activateTab(idx, true);
    });
  });

  if (container) {
    container.addEventListener("mouseenter", function () {
      isHoveredOrFocused = true;
      window.clearTimeout(timer);
    });
    container.addEventListener("mouseleave", function () {
      isHoveredOrFocused = false;
      scheduleNext();
    });
    container.addEventListener("focusin", function () {
      isHoveredOrFocused = true;
      window.clearTimeout(timer);
    });
    container.addEventListener("focusout", function () {
      isHoveredOrFocused = false;
      scheduleNext();
    });
  }

  // Visibility & Intersection gating
  function checkState() {
    if (isVisible && document.visibilityState === "visible") {
      scheduleNext();
    } else {
      window.clearTimeout(timer);
    }
  }

  document.addEventListener("visibilitychange", checkState);

  if ("IntersectionObserver" in window && container) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        isVisible = entry.isIntersecting;
        checkState();
      });
    }, { threshold: 0.25 });
    observer.observe(container);
  } else {
    isVisible = true;
    scheduleNext();
  }

  // Initial state — don't animate on first paint so content is instant
  activateTab(0, false);
})();
