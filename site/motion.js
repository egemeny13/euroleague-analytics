/* EuroLeague Analytics — Global Motion, Counting Figures & Client Tabs
   Handles viewport-gated number counting, copy-to-clipboard, and client tab navigation. */

(function () {
  "use strict";

  var COUNT_MS = 1400;
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");

  function easeOutExpo(t) {
    return t === 1 ? 1 : 1 - Math.pow(2, -10 * t);
  }

  function formatNumber(num, isOriginalFormatted) {
    if (isOriginalFormatted && num >= 1000) {
      return num.toLocaleString("en-US");
    }
    return String(num);
  }

  function countUp(el, target, hasComma) {
    var start = null;

    function step(timestamp) {
      if (!start) start = timestamp;
      var progress = Math.min(1, (timestamp - start) / COUNT_MS);
      var current = Math.round(easeOutExpo(progress) * target);
      el.textContent = formatNumber(current, hasComma);
      if (progress < 1) {
        window.requestAnimationFrame(step);
      } else {
        el.textContent = formatNumber(target, hasComma);
      }
    }

    window.requestAnimationFrame(step);
  }

  function whenSeen(el, fn) {
    if (!("IntersectionObserver" in window)) {
      fn();
      return;
    }
    var seen = false;
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting && !seen) {
          seen = true;
          io.disconnect();
          fn();
        }
      });
    }, { threshold: 0.3 });
    io.observe(el);
  }

  // Animate trust section numbers
  var factNumbers = Array.prototype.slice.call(document.querySelectorAll(".fact-num[data-target]"));
  factNumbers.forEach(function (el) {
    var target = parseInt(el.getAttribute("data-target"), 10);
    var hasComma = el.textContent.indexOf(",") !== -1;

    if (reduced.matches) {
      el.textContent = formatNumber(target, hasComma);
      return;
    }

    el.textContent = "0";
    whenSeen(el, function () {
      countUp(el, target, hasComma);
    });
  });

  // Client tabs in Connect section
  var tablist = document.querySelector(".client-tabs");
  if (tablist) {
    var tabs = Array.prototype.slice.call(tablist.querySelectorAll(".client-tab"));
    var panels = Array.prototype.slice.call(document.querySelectorAll(".client-panel"));

    function selectTab(tab, focus) {
      var targetId = tab.getAttribute("aria-controls");
      tabs.forEach(function (t) {
        var active = t === tab;
        t.setAttribute("aria-selected", active ? "true" : "false");
        t.tabIndex = active ? 0 : -1;
      });

      panels.forEach(function (p) {
        p.hidden = p.id !== targetId;
      });

      if (focus) tab.focus();
    }

    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        selectTab(tab, false);
      });
    });

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
        selectTab(target, true);
      }
    });
  }

  // Copy server URL button
  var copyBtn = document.getElementById("copy-url");
  var urlEl = document.getElementById("server-url");

  if (copyBtn && urlEl) {
    var idleText = copyBtn.textContent;
    var copiedText = copyBtn.getAttribute("data-copied") || "Copied";
    var resetTimer = null;

    copyBtn.addEventListener("click", function () {
      var text = urlEl.textContent.trim();
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () {
          showCopied();
        }).catch(function () {
          fallbackSelect();
        });
      } else {
        fallbackSelect();
      }
    });

    function showCopied() {
      copyBtn.textContent = copiedText;
      copyBtn.classList.add("is-done");
      window.clearTimeout(resetTimer);
      resetTimer = window.setTimeout(function () {
        copyBtn.textContent = idleText;
        copyBtn.classList.remove("is-done");
      }, 1800);
    }

    function fallbackSelect() {
      var range = document.createRange();
      range.selectNodeContents(urlEl);
      var sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      showCopied();
    }
  }
})();
