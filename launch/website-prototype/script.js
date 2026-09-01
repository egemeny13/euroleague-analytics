/* ==========================================================================
   EuroLeague Analytics — 6-Beat Product Interactive Script
   ========================================================================== */

document.addEventListener('DOMContentLoaded', () => {

  // ==========================================================================
  // 1. LIVING BASKETBALL COURT & SHOT-COORDINATE CANVAS
  // ==========================================================================
  const canvas = document.getElementById('hero-court-canvas');
  if (canvas) {
    const ctx = canvas.getContext('2d');
    let animationFrameId;
    let isCanvasActive = true;

    const rawShots = [
      { x: 0, y: 60, make: true }, { x: -30, y: 80, make: true }, { x: 40, y: 70, make: false },
      { x: -70, y: 130, make: true }, { x: 60, y: 140, make: true }, { x: -10, y: 110, make: true },
      { x: 20, y: 160, make: false }, { x: -80, y: 90, make: false },
      { x: -160, y: 220, make: true }, { x: 170, y: 210, make: false }, { x: -140, y: 280, make: true },
      { x: 150, y: 270, make: true }, { x: 0, y: 290, make: true }, { x: -60, y: 310, make: false },
      { x: -340, y: 60, make: true }, { x: -340, y: 120, make: false }, { x: -340, y: 180, make: true },
      { x: 340, y: 70, make: true }, { x: 340, y: 130, make: true }, { x: 340, y: 190, make: false },
      { x: -280, y: 320, make: true }, { x: -220, y: 380, make: false }, { x: -120, y: 440, make: true },
      { x: 0, y: 460, make: true }, { x: 130, y: 430, make: true }, { x: 230, y: 370, make: false }
    ];

    let width = 0;
    let height = 0;
    let time = 0;

    function resizeCanvas() {
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      width = rect.width;
      height = rect.height;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      ctx.scale(dpr, dpr);
    }

    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);

    const ball = {
      angle: 0,
      radius: 10,
    };

    function drawCourt(centerX, baselineY, scale) {
      ctx.save();
      ctx.strokeStyle = '#E5E6EA';
      ctx.lineWidth = 1.2;

      // 1. Paint / Key Rectangle
      const keyWidth = 190 * scale;
      const keyHeight = 220 * scale;
      ctx.strokeRect(centerX - keyWidth / 2, baselineY - keyHeight, keyWidth, keyHeight);

      // 2. Free Throw Circle
      ctx.beginPath();
      ctx.arc(centerX, baselineY - keyHeight, 70 * scale, 0, Math.PI * 2);
      ctx.stroke();

      // 3. Three-Point Line
      const cornerX = 330 * scale;
      const cornerLength = 120 * scale;
      const arcRadius = 310 * scale;

      ctx.beginPath();
      ctx.moveTo(centerX - cornerX, baselineY);
      ctx.lineTo(centerX - cornerX, baselineY - cornerLength);
      ctx.arc(centerX, baselineY - 40 * scale, arcRadius, Math.PI + 0.38, 0 - 0.38, false);
      ctx.lineTo(centerX + cornerX, baselineY);
      ctx.stroke();

      // 4. Restricted Area Semi-Circle
      ctx.beginPath();
      ctx.arc(centerX, baselineY - 40 * scale, 45 * scale, Math.PI, 0, false);
      ctx.stroke();

      // 5. Center Court Rim Marker
      ctx.beginPath();
      ctx.arc(centerX, baselineY - 40 * scale, 8 * scale, 0, Math.PI * 2);
      ctx.fillStyle = '#E2541A';
      ctx.fill();

      ctx.restore();
    }

    function render() {
      if (!isCanvasActive) return;

      time += 0.015;
      ctx.clearRect(0, 0, width, height);

      const centerX = width * 0.85;
      const baselineY = height * 0.85;
      const courtScale = Math.min(width / 1200, 1) * 0.85;

      drawCourt(centerX, baselineY, courtScale);

      rawShots.forEach((shot, index) => {
        const sx = centerX + shot.x * courtScale;
        const sy = baselineY - shot.y * courtScale;
        const offset = Math.sin(time + index * 0.4) * 1.5;
        const alpha = shot.make ? 0.4 + Math.sin(time + index) * 0.15 : 0.2;

        ctx.beginPath();
        ctx.arc(sx, sy + offset, shot.make ? 3 : 2, 0, Math.PI * 2);
        ctx.fillStyle = shot.make ? `rgba(226, 84, 26, ${alpha})` : `rgba(97, 101, 110, ${alpha})`;
        ctx.fill();
      });

      // Subtle slow basketball trajectory
      ball.angle += 0.007;
      const trajectoryRadiusX = 220 * courtScale;
      const trajectoryRadiusY = 140 * courtScale;
      const bx = centerX + Math.cos(ball.angle) * trajectoryRadiusX;
      const by = (baselineY - 160 * courtScale) + Math.sin(ball.angle) * trajectoryRadiusY;

      ctx.save();
      ctx.beginPath();
      ctx.ellipse(centerX, baselineY - 160 * courtScale, trajectoryRadiusX, trajectoryRadiusY, 0, 0, Math.PI * 2);
      ctx.strokeStyle = 'rgba(226, 84, 26, 0.1)';
      ctx.setLineDash([4, 6]);
      ctx.stroke();

      ctx.beginPath();
      ctx.arc(bx, by, 9, 0, Math.PI * 2);
      ctx.fillStyle = '#E2541A';
      ctx.fill();

      ctx.strokeStyle = '#FFFFFF';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(bx, by, 9, -0.4, 0.4);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(bx - 9, by);
      ctx.lineTo(bx + 9, by);
      ctx.stroke();
      ctx.restore();

      animationFrameId = requestAnimationFrame(render);
    }

    render();

    const heroSection = document.getElementById('hero');
    if (heroSection && 'IntersectionObserver' in window) {
      const heroObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
          isCanvasActive = entry.isIntersecting;
          if (isCanvasActive) {
            cancelAnimationFrame(animationFrameId);
            render();
          }
        });
      }, { threshold: 0.05 });
      heroObserver.observe(heroSection);
    }
  }


  // ==========================================================================
  // 2. KINETIC HEADLINE TYPING & CYCLING HERO ASSISTANT CONVERSATION DEMO
  // ==========================================================================
  const headlineTarget = document.getElementById('hero-headline-text');
  const headlineCursor = document.getElementById('hero-text-cursor');
  const mediaPromptTarget = document.getElementById('media-typed-prompt');
  const mediaPromptCursor = document.getElementById('media-prompt-cursor');
  const mediaToolActivity = document.getElementById('media-tool-activity');
  const toolStatusText = document.getElementById('tool-status-text');
  const mediaAssistantMsg = document.getElementById('media-assistant-msg');
  const assistantLeadText = document.getElementById('assistant-lead-text');
  const assistantStatGrid = document.getElementById('assistant-stat-grid');

  const headlinePrefix = 'Ask EuroLeague questions that normally take ';
  const headlinePunchline = 'SQL.';

  const assistantScenarios = [
    {
      prompt: 'How did Paris perform with TJ Shorts on vs. off the floor?',
      tool: 'Using el_get_player_on_off (PRS · TJ Shorts · E2024)…',
      lead: 'In E2024, Paris was significantly more dangerous with TJ Shorts on the floor:',
      statsHtml: `
        <div class="mini-stat-card on-card">
          <div class="mini-label">Shorts ON</div>
          <div class="mini-val text-orange highlighter-brush">+5.09 Net</div>
          <div class="mini-sub">116.14 ORtg &middot; 111.04 DRtg</div>
        </div>
        <div class="mini-stat-card off-card">
          <div class="mini-label">Shorts OFF</div>
          <div class="mini-val text-dark">−11.45 Net</div>
          <div class="mini-sub">117.05 ORtg &middot; 128.50 DRtg</div>
        </div>
      `
    },
    {
      prompt: 'Which 5-man lineup had the best net rating in E2024 (min. 150 poss)?',
      tool: 'Auditing 5-man lineup combinations across 107,311 possessions\u2026',
      lead: 'Paris Basketball held the #1 lineup net efficiency rating in Europe:',
      statsHtml: `
        <div class="mini-stat-card on-card">
          <div class="mini-label">Paris Top Lineup</div>
          <div class="mini-val text-orange highlighter-brush">+25.45 Net</div>
          <div class="mini-sub">Hayes &middot; Herrera &middot; Jantunen &middot; Shorts &middot; Ward</div>
        </div>
        <div class="mini-stat-card off-card">
          <div class="mini-label">Sample Size</div>
          <div class="mini-val text-dark">184 Possessions</div>
          <div class="mini-sub">132.8 ORtg &middot; 107.3 DRtg</div>
        </div>
      `
    },
    {
      prompt: 'Define clutch as last 120s within 3 pts. Which offense was most efficient?',
      tool: 'Applying caller-defined clutch filter (seconds <= 120, margin <= 3)\u2026',
      lead: 'Fenerbahce Beko led all teams in caller-defined clutch efficiency:',
      statsHtml: `
        <div class="mini-stat-card on-card">
          <div class="mini-label">Fenerbahce Clutch</div>
          <div class="mini-val text-orange highlighter-brush">154.84 ORtg</div>
          <div class="mini-sub">+35.63 points per 100 over baseline</div>
        </div>
        <div class="mini-stat-card off-card">
          <div class="mini-label">Clutch Efficiency</div>
          <div class="mini-val text-dark">31 Possessions</div>
          <div class="mini-sub">1.55 Points Per Possession</div>
        </div>
      `
    }
  ];

  let currentScenarioIndex = 0;
  let isTypingPrompt = false;

  if (headlineTarget) {
    headlineTarget.textContent = '';
    let charIndex = 0;
    const headlineSpeed = 18;
    const fullHeadline = headlinePrefix + headlinePunchline;

    function typeHeadline() {
      if (charIndex < fullHeadline.length) {
        headlineTarget.textContent = fullHeadline.substring(0, charIndex + 1);
        charIndex++;
        setTimeout(typeHeadline, headlineSpeed);
      } else {
        // Highlight the keyword 'SQL.'
        headlineTarget.innerHTML = headlinePrefix + '<span class="highlighter">SQL</span>.';
        setTimeout(() => {
          if (headlineCursor) headlineCursor.style.display = 'none';
          runAssistantCycle();
        }, 200);
      }
    }

    setTimeout(typeHeadline, 80);

    function runAssistantCycle() {
      if (!mediaPromptTarget || isTypingPrompt) return;
      isTypingPrompt = true;

      const scenario = assistantScenarios[currentScenarioIndex];
      mediaPromptTarget.textContent = '';
      if (mediaPromptCursor) mediaPromptCursor.style.display = 'inline-block';
      if (mediaToolActivity) mediaToolActivity.classList.remove('is-active');
      if (mediaAssistantMsg) mediaAssistantMsg.classList.remove('is-visible');

      let pIndex = 0;
      const typeSpeed = 22;

      function typeChar() {
        if (pIndex < scenario.prompt.length) {
          mediaPromptTarget.textContent = scenario.prompt.substring(0, pIndex + 1);
          pIndex++;
          setTimeout(typeChar, typeSpeed);
        } else {
          // Finished typing prompt
          setTimeout(() => {
            if (mediaPromptCursor) mediaPromptCursor.style.display = 'none';
            if (toolStatusText) toolStatusText.textContent = scenario.tool;
            if (mediaToolActivity) mediaToolActivity.classList.add('is-active');

            setTimeout(() => {
              if (assistantLeadText) assistantLeadText.textContent = scenario.lead;
              if (assistantStatGrid) assistantStatGrid.innerHTML = scenario.statsHtml;
              if (mediaAssistantMsg) mediaAssistantMsg.classList.add('is-visible');

              // Hold reading time then transition to next prompt
              setTimeout(() => {
                if (mediaAssistantMsg) mediaAssistantMsg.classList.remove('is-visible');
                if (mediaToolActivity) mediaToolActivity.classList.remove('is-active');

                setTimeout(() => {
                  currentScenarioIndex = (currentScenarioIndex + 1) % assistantScenarios.length;
                  isTypingPrompt = false;
                  runAssistantCycle();
                }, 400);
              }, 4600);

            }, 500);
          }, 200);
        }
      }

      setTimeout(typeChar, 150);
    }
  }


  // ==========================================================================
  // 3. INTERSECTION OBSERVER FOR FLUID REVEALS & KINETIC QUESTION REVEALS
  // ==========================================================================
  const revealElements = document.querySelectorAll('.reveal');
  
  if ('IntersectionObserver' in window) {
    const observerOptions = {
      threshold: 0.12,
      rootMargin: '0px 0px -40px 0px',
    };

    const revealObserver = new IntersectionObserver((entries, observer) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          const el = entry.target;
          el.classList.add('is-visible');
          
          if (el.classList.contains('stream-node')) {
            const promptHeading = el.querySelector('.kinetic-prompt-text');
            if (promptHeading && !promptHeading.dataset.animated) {
              promptHeading.dataset.animated = 'true';
              const rawText = promptHeading.getAttribute('data-text') || promptHeading.textContent.trim();
              promptHeading.textContent = '“';
              let charIdx = 0;
              const typeSpeed = 14;

              function typeStreamPrompt() {
                if (charIdx < rawText.length) {
                  promptHeading.textContent = '“' + rawText.substring(0, charIdx + 1) + (charIdx + 1 < rawText.length ? '' : '”');
                  charIdx++;
                  setTimeout(typeStreamPrompt, typeSpeed);
                }
              }
              setTimeout(typeStreamPrompt, 100);
            }
          }

          observer.unobserve(el);
        }
      });
    }, observerOptions);

    revealElements.forEach(el => revealObserver.observe(el));
  } else {
    revealElements.forEach(el => el.classList.add('is-visible'));
  }


  // ==========================================================================
  // 4. VIDEO MEDIA SHOWCASE PLAYER
  // ==========================================================================
  const playBtn = document.getElementById('play-video-btn');
  const videoOverlay = document.getElementById('video-cover-overlay');
  const showcaseVideo = document.getElementById('showcase-video-player');

  if (playBtn && videoOverlay && showcaseVideo) {
    function playProductVideo() {
      videoOverlay.classList.add('is-hidden');
      showcaseVideo.play().catch(() => {});
    }

    playBtn.addEventListener('click', playProductVideo);
    videoOverlay.addEventListener('click', (e) => {
      if (e.target !== playBtn) {
        playProductVideo();
      }
    });

    showcaseVideo.addEventListener('pause', () => {
      if (showcaseVideo.currentTime === 0 || showcaseVideo.ended) {
        videoOverlay.classList.remove('is-hidden');
      }
    });
  }


  // ==========================================================================
  // 5. AI ONBOARDING CLIENT PICKER TABS
  // ==========================================================================
  const tabButtons = document.querySelectorAll('.client-tab-btn');
  const panels = document.querySelectorAll('.client-panel');

  tabButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      const clientKey = btn.getAttribute('data-client');
      if (!clientKey) return;

      // Update active tab button
      tabButtons.forEach(b => {
        b.classList.remove('is-active');
        b.setAttribute('aria-selected', 'false');
      });
      btn.classList.add('is-active');
      btn.setAttribute('aria-selected', 'true');

      // Update active panel
      panels.forEach(p => p.classList.remove('is-active'));
      const targetPanel = document.getElementById(`panel-${clientKey}`);
      if (targetPanel) {
        targetPanel.classList.add('is-active');
      }
    });
  });


  // ==========================================================================
  // 6. DYNAMIC SNIPPET COPY BUTTONS
  // ==========================================================================
  document.querySelectorAll('.snippet-copy-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const textToCopy = btn.getAttribute('data-copy');
      if (!textToCopy) return;

      const originalText = btn.textContent;
      try {
        await navigator.clipboard.writeText(textToCopy);
        btn.classList.add('copied');
        btn.textContent = 'Copied!';
        setTimeout(() => {
          btn.classList.remove('copied');
          btn.textContent = originalText;
        }, 2000);
      } catch (err) {
        btn.textContent = 'Copied!';
        setTimeout(() => {
          btn.textContent = originalText;
        }, 2000);
      }
    });
  });


  // ==========================================================================
  // 7. SMOOTH NAVIGATION ANCHOR SCROLL WITH SAFE HEADER OFFSET
  // ==========================================================================
  document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function(e) {
      const targetId = this.getAttribute('href');
      if (targetId === '#') return;
      
      const targetEl = document.querySelector(targetId);
      if (targetEl) {
        e.preventDefault();
        const headerHeight = document.querySelector('.site-header')?.offsetHeight || 64;
        const targetPos = targetEl.getBoundingClientRect().top + window.pageYOffset - headerHeight - 16;
        window.scrollTo({
          top: targetPos,
          behavior: 'smooth'
        });
      }
    });
  });

});
