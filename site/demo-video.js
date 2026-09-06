/* Recorded demos: one rule for every <video class="demo-video"> on the page.
   Design record: docs/superpowers/specs/2026-09-04-launch-website-design.md,
   Decisions 60 and 61.

   A recording is an upgrade, never a dependency. The drawn version of each
   figure stays in the markup and is what the visitor sees until the browser
   says it can play the file (canplay). Only then does the host get .has-video,
   which hides the drawn version and shows the recording; a missing or
   unplayable file changes nothing. A visitor who asked for less motion keeps
   the drawn version in its finished state and no recording ever loads.

   Four rules the owner set on 2026-09-06, all kept here and nowhere else:

   1. Nothing loads until it is near the screen. Every video carries
      preload="none"; the file is fetched when the host comes within half a
      screen of the viewport, not on page load. Four recordings are ~6 MB, and a
      visitor who leaves from the hero should not have paid for them.
   2. Nothing plays until it is on the screen, and it pauses when it leaves or
      the tab is hidden - the same rule the drawn animations followed.
   3. Only one recording plays at a time. Two moving windows in one viewport
      compete for the eye; the one highest on the page wins and the other waits.
   4. A thin progress bar under each recording says how far along it is, so a
      visitor knows a clip is a clip and how much of it is left. It is the
      hairline the court is drawn in, filled in ink, never orange: progress is
      not a measured value.

   Scripts that used to drive a figure listen for "demo-video-ready" on the
   video and stop their own choreography. */

(function () {
  "use strict";

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  if (reduced.matches) return;

  var videos = Array.prototype.slice.call(document.querySelectorAll("video.demo-video"));
  if (!videos.length) return;

  var onScreen = [];     // videos currently intersecting, in DOM order
  var ready = [];        // videos whose file the browser can play

  function hostOf(video) {
    return video.closest("[data-demo-host]") || video.parentNode;
  }

  /* One player. The first on-screen, ready video in document order plays;
     every other one is paused. Called whenever anything changes. */
  function reconcile() {
    var chosen = null;
    if (document.visibilityState === "visible") {
      for (var i = 0; i < videos.length; i++) {
        var v = videos[i];
        if (onScreen.indexOf(v) !== -1 && ready.indexOf(v) !== -1) { chosen = v; break; }
      }
    }
    videos.forEach(function (v) {
      if (v === chosen) {
        if (v.paused && !v.ended) v.play().catch(function () { /* the poster stands */ });
      } else if (!v.paused) {
        v.pause();
      }
    });
  }

  function addProgress(video) {
    var bar = document.createElement("div");
    bar.className = "demo-progress";
    bar.setAttribute("aria-hidden", "true");
    var fill = document.createElement("i");
    bar.appendChild(fill);
    /* Directly under the recording, before any caption the host carries. */
    video.insertAdjacentElement("afterend", bar);

    /* Driven by the clock, not by timeupdate: timeupdate fires about four
       times a second and the bar would step rather than travel. */
    (function tick() {
      if (video.duration > 0) {
        fill.style.transform = "scaleX(" + Math.min(1, video.currentTime / video.duration) + ")";
      }
      window.requestAnimationFrame(tick);
    })();
  }

  videos.forEach(function (video) {
    var host = hostOf(video);

    video.addEventListener("canplay", function onCanPlay() {
      video.removeEventListener("canplay", onCanPlay);
      ready.push(video);
      host.classList.add("has-video");
      var figure = video.closest(".claim-figure");
      if (figure) figure.classList.add("has-video");
      addProgress(video);
      video.dispatchEvent(new CustomEvent("demo-video-ready", { bubbles: true }));
      reconcile();
    });

    if (!("IntersectionObserver" in window)) {
      video.load();
      onScreen.push(video);
      return;
    }

    /* Near: fetch the file. Half a screen ahead is early enough that the clip
       is usually playable by the time the host is in view. */
    var near = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        near.disconnect();
        video.load();
      });
    }, { rootMargin: "50% 0px" });
    near.observe(host);

    /* Visible: eligible to play. Sorted into document order so reconcile()
       can prefer the highest one without measuring anything. */
    new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        var at = onScreen.indexOf(video);
        if (entry.isIntersecting && at === -1) {
          onScreen.push(video);
          onScreen.sort(function (a, b) { return videos.indexOf(a) - videos.indexOf(b); });
        } else if (!entry.isIntersecting && at !== -1) {
          onScreen.splice(at, 1);
        }
      });
      reconcile();
    }, { threshold: 0.4 }).observe(host);
  });

  document.addEventListener("visibilitychange", reconcile);
})();
