/* Draws the shot chart from site/data/final-shots.json.

   Coordinates are placed exactly as the league recorded them, in
   centimetres with the ring at (0, 0) (Decision 55), so no arithmetic of ours
   moves a shot. Each row is [x, y, made, three, team, player]; made shots are
   filled discs, misses are rings, both in the club's colour. The shots arrive
   in game order the first time the chart scrolls into view.

   The data path is resolved against this script's own address, so the same
   script works from the Turkish page one directory down. The script holds no
   sentences; every word on the chart lives in the page. */
(function () {
  var figure = document.getElementById("court-chart");
  if (!figure) return;

  var script = document.currentScript;
  var source = new URL(figure.dataset.src, script ? script.src : location.href);
  var layer = figure.querySelector(".shots");
  var buttons = Array.prototype.slice.call(document.querySelectorAll(".team[data-team]"));
  var colours = {};
  buttons.forEach(function (button) {
    colours[button.dataset.team] = getComputedStyle(button).getPropertyValue("--team").trim();
  });

  var still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var svgns = "http://www.w3.org/2000/svg";
  var dots = [];

  function draw(rows) {
    rows.forEach(function (row) {
      var x = row[0], y = row[1], made = row[2], team = row[4];
      var colour = colours[team] || "#15130f";
      var dot = document.createElementNS(svgns, "circle");
      dot.setAttribute("cx", x);
      dot.setAttribute("cy", y);
      dot.setAttribute("r", made ? 17 : 14);
      dot.setAttribute("fill", made ? colour : "none");
      dot.setAttribute("stroke", colour);
      dot.setAttribute("stroke-width", made ? 0 : 5);
      dot.setAttribute("class", still ? "shot" : "shot is-waiting");
      dot.dataset.team = team;
      layer.appendChild(dot);
      dots.push(dot);
    });
  }

  function arrive() {
    dots.forEach(function (dot, i) {
      setTimeout(function () { dot.classList.remove("is-waiting"); }, i * 18);
    });
  }

  buttons.forEach(function (button) {
    button.addEventListener("click", function () {
      var on = button.getAttribute("aria-pressed") !== "true";
      button.setAttribute("aria-pressed", on ? "true" : "false");
      dots.forEach(function (dot) {
        if (dot.dataset.team === button.dataset.team) dot.classList.toggle("is-off", !on);
      });
    });
  });

  fetch(source)
    .then(function (response) { return response.json(); })
    .then(function (data) {
      draw(data.shots || []);
      if (still || !("IntersectionObserver" in window)) return arrive();
      var seen = new IntersectionObserver(function (entries) {
        if (entries[0].isIntersecting) {
          seen.disconnect();
          arrive();
        }
      }, { threshold: 0.3 });
      seen.observe(figure);
    })
    .catch(function () {
      /* No data: the court stays drawn and empty, and the copy still reads. */
    });
})();
