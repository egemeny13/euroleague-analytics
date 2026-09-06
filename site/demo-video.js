/* Recorded demos: one rule for every <video class="demo-video"> on the page.
   Design record: docs/superpowers/specs/2026-09-04-launch-website-design.md,
   Decisions 60 and 61.

   A recording is an upgrade, never a dependency. The drawn version of each
   figure stays in the markup and is what the visitor sees until the browser
   says it can play the file (canplay). Only then does the host get .has-video,
   which hides the drawn version and shows the recording; a missing or
   unplayable file changes nothing. A visitor who asked for less motion keeps
   the drawn version in its finished state and the recording never starts.

   Recordings run only while on screen and in the visible tab, the same rule
   the drawn animations followed. Scripts that used to drive a figure's
   numbers listen for "demo-video-ready" on the video and follow its clock
   instead, so the number beside a recording changes when the recording does. */

(function () {
  "use strict";

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  var videos = document.querySelectorAll("video.demo-video");

  Array.prototype.forEach.call(videos, function (video) {
    var host = video.closest("[data-demo-host]") || video.parentNode;
    var figure = video.closest(".claim-figure");

    function play() {
      if (document.visibilityState !== "visible") return;
      video.play().catch(function () { /* the poster stands; nothing errors */ });
    }

    video.addEventListener("canplay", function onCanPlay() {
      video.removeEventListener("canplay", onCanPlay);
      if (reduced.matches) return;

      host.classList.add("has-video");
      if (figure) figure.classList.add("has-video");
      video.dispatchEvent(new CustomEvent("demo-video-ready", { bubbles: true }));

      if (!("IntersectionObserver" in window)) { play(); return; }

      var onScreen = false;
      new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          onScreen = entry.isIntersecting;
          if (onScreen) play(); else video.pause();
        });
      }, { threshold: 0.4 }).observe(video);

      document.addEventListener("visibilitychange", function () {
        if (document.visibilityState === "visible") { if (onScreen) play(); }
        else video.pause();
      });
    });
  });
})();
