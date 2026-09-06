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
  var held = null;       // a video the visitor paused or resumed by hand

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
    /* A recording the visitor paused by hand stays paused while it is on
       screen; the hold is released when it scrolls away. */
    if (held && onScreen.indexOf(held) === -1) held = null;
    videos.forEach(function (v) {
      if (v === chosen) {
        if (v === held) return;
        if (v.paused && !v.ended) v.play().catch(function () { /* the poster stands */ });
      } else if (!v.paused) {
        v.pause();
      }
    });
  }

  /* The bar is also the scrubber (owner, 2026-09-06: the visitor should be able
     to move through a recording rather than wait for it). Pointer down or drag
     anywhere on it seeks; arrow keys step two seconds; the recording keeps its
     play/pause state across a seek. Clicking the recording itself toggles
     play and pause, the way every video player a visitor has met does. */
  function addProgress(video) {
    var bar = document.createElement("div");
    bar.className = "demo-progress";
    bar.setAttribute("role", "slider");
    bar.setAttribute("aria-label", "Position in the recording");
    bar.setAttribute("aria-valuemin", "0");
    bar.setAttribute("aria-valuemax", "100");
    bar.tabIndex = 0;
    var fill = document.createElement("i");
    bar.appendChild(fill);
    /* Directly under the recording, before any caption the host carries. When
       the recording sits inside its own shape (the film's rounded wrapper),
       the bar goes under the shape instead. */
    var anchor = (video.parentElement !== hostOf(video)) ? video.parentElement : video;
    anchor.insertAdjacentElement("afterend", bar);

    /* One quiet line so a visitor knows the recording is theirs to drive. The
       same words appear under the two drawn figures, which pause the same way. */
    var hint = document.createElement("p");
    hint.className = "demo-hint";
    hint.textContent = "Click to pause, drag the line to move.";
    bar.insertAdjacentElement("afterend", hint);

    /* A recording with a soundtrack (data-sound) starts muted, because that is
       the only way a browser lets it start on its own. One quiet button turns
       the sound on; the same button turns it off again. */
    if (video.hasAttribute("data-sound")) {
      var sound = document.createElement("button");
      sound.type = "button";
      sound.className = "demo-sound";
      var label = function () { sound.textContent = video.muted ? "Turn the sound on" : "Turn the sound off"; };
      label();
      sound.addEventListener("click", function () {
        video.muted = !video.muted;
        if (!video.muted && video.paused) { held = video; video.play().catch(function () {}); }
        label();
      });
      hint.appendChild(document.createTextNode(" "));
      hint.appendChild(sound);
    }

    function seekTo(clientX) {
      var rect = bar.getBoundingClientRect();
      var p = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
      if (video.duration > 0) video.currentTime = p * video.duration;
    }

    var scrubbing = false;
    bar.addEventListener("pointerdown", function (event) {
      scrubbing = true;
      bar.classList.add("is-scrubbing");
      seekTo(event.clientX);
      /* Capture keeps the drag alive when the pointer leaves the 2 px line.
         It can refuse (a pointer the browser does not know); the seek above
         has already happened, so a refusal costs only the drag. */
      try { bar.setPointerCapture(event.pointerId); } catch (e) { /* no drag */ }
      event.preventDefault();
    });
    bar.addEventListener("pointermove", function (event) {
      if (scrubbing) seekTo(event.clientX);
    });
    function release() {
      scrubbing = false;
      bar.classList.remove("is-scrubbing");
    }
    bar.addEventListener("pointerup", release);
    bar.addEventListener("pointercancel", release);

    bar.addEventListener("keydown", function (event) {
      if (!(video.duration > 0)) return;
      var step = 2;
      if (event.key === "ArrowRight" || event.key === "ArrowUp") video.currentTime = Math.min(video.duration, video.currentTime + step);
      else if (event.key === "ArrowLeft" || event.key === "ArrowDown") video.currentTime = Math.max(0, video.currentTime - step);
      else if (event.key === "Home") video.currentTime = 0;
      else if (event.key === "End") video.currentTime = video.duration;
      else if (event.key === " " || event.key === "Enter") { if (video.paused) video.play().catch(function () {}); else video.pause(); }
      else return;
      event.preventDefault();
    });

    /* A tap on the picture pauses or resumes. It also marks the recording as
       the visitor's, so the one-player rule leaves it alone until they scroll
       away from it. */
    video.addEventListener("click", function () {
      if (video.paused) { held = video; video.play().catch(function () {}); }
      else { held = video; video.pause(); }
    });

    /* Driven by the clock, not by timeupdate: timeupdate fires about four
       times a second and the bar would step rather than travel. */
    (function tick() {
      if (video.duration > 0) {
        var p = Math.min(1, video.currentTime / video.duration);
        fill.style.transform = "scaleX(" + p + ")";
        bar.setAttribute("aria-valuenow", String(Math.round(p * 100)));
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
        /* preload="none" in the markup keeps the browser from fetching on page
           load; once the host is near, the hint flips to auto so that load()
           actually downloads and canplay can fire. */
        video.preload = "auto";
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

  /* ---- the film's two extra behaviours, measured on antigravity.google
     (2026-09-06) at the owner's request ----

     1. It arrives by growing. Their video section sits at scale 0.5 while it
        is below the fold and reaches 1 by the time its top edge has travelled
        about two thirds of the viewport, growing from its bottom centre. The
        same here, driven by the scroll position on each frame, and skipped
        entirely for a visitor who asked for less motion.

     2. The cursor becomes the control. Over the film the system pointer is
        hidden and a white pill follows the hand, reading Pause or Play - the
        same click the whole page uses, now labelled where the eye already is.
        A visitor with no fine pointer (a phone) never sees it. */

  var grow = reduced.matches ? [] : Array.prototype.slice.call(document.querySelectorAll("[data-grow-in]"));
  if (grow.length) {
    var vh = window.innerHeight;
    var paint = function () {
      grow.forEach(function (el) {
        var top = el.getBoundingClientRect().top;
        var p = Math.max(0, Math.min(1, (vh - top) / (vh * 0.65)));
        el.style.transform = "scale(" + (0.5 + 0.5 * p).toFixed(4) + ")";
      });
    };
    var queued = false;
    var onScroll = function () {
      /* A hidden tab gets no animation frames; paint straight away there so
         the shape is right the moment the tab is shown again. */
      if (document.visibilityState !== "visible") { paint(); return; }
      if (queued) return;
      queued = true;
      window.requestAnimationFrame(function () { queued = false; paint(); });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", function () { vh = window.innerHeight; onScroll(); });
    paint();
  }

  if (window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
    Array.prototype.slice.call(document.querySelectorAll("[data-cursor]")).forEach(function (stage) {
      var video = stage.querySelector("video");
      if (!video) return;
      var pill = document.createElement("div");
      pill.className = "demo-cursor";
      pill.setAttribute("aria-hidden", "true");
      var glyph = document.createElement("span");
      glyph.className = "demo-cursor-glyph";
      var word = document.createElement("span");
      pill.appendChild(glyph);
      pill.appendChild(word);
      stage.appendChild(pill);

      var relabel = function () {
        glyph.textContent = video.paused ? "▶" : "❚❚";
        word.textContent = video.paused ? "Play" : "Pause";
      };
      video.addEventListener("play", relabel);
      video.addEventListener("pause", relabel);
      relabel();

      var follow = function (event) {
        var r = stage.getBoundingClientRect();
        pill.style.transform = "translate(" + (event.clientX - r.left) + "px, " + (event.clientY - r.top) + "px) translate(-50%, -50%) scale(1)";
        pill.classList.add("is-shown");
      };
      stage.addEventListener("pointermove", follow);
      stage.addEventListener("mousemove", follow);
      stage.addEventListener("pointerleave", function () {
        pill.classList.remove("is-shown");
      });
      stage.addEventListener("mouseleave", function () {
        pill.classList.remove("is-shown");
      });
    });
  }
})();
