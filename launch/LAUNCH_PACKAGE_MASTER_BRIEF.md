# EuroLeague Analytics — Launch Package Master Brief

**Status:** Working source of truth for the launch worktree  
**Scope:** Website, launch videos, X/Twitter announcement thread, shared art direction, research notes, production rules  
**Target launch window:** ~2026-09-27, only after two or three clean live game nights  
**Primary implementation environment:** launch-specific worktree/branch  
**Last consolidated:** 2026-09-01

---

## 0. Why This File Exists

The launch work has accumulated decisions across website design, motion/video production, tool experiments, launch copy, and product positioning.

This file consolidates those decisions into one source of truth for the launch worktree.

It is intentionally broader than a storyboard or a website spec. The website, videos, and X thread should feel like one launch package created from the same product story and the same design system.

This document should guide agents working in the launch worktree. It is not permission to expand product scope.

### Repository authority

For product behavior and engineering decisions, existing repository authority still wins:

1. `CLAUDE.md`
2. `DECISIONS.md`
3. `ROADMAP.md`
4. current implementation and evaluation tests
5. this launch brief

For launch-package creative decisions, this file is the working source of truth unless the owner explicitly changes direction.

---

# 1. Launch Objective

EuroLeague Analytics should not be introduced as “an MCP server with 11 tools.”

That is technically true, but it is not the story.

The product story is:

> Ask meaningful EuroLeague basketball questions in natural language and get answers backed by verified possession-level data that would normally require SQL, Python, or manual analysis.

The launch should make three things clear:

1. **It is useful.** You can ask real basketball questions, not just retrieve box scores.
2. **It is trustworthy.** The answers are re-earned from a validated warehouse rather than guessed by an LLM.
3. **It is easy to use.** Connect the MCP server to an AI assistant and ask questions naturally.

---

# 2. Intended Audience

Primary audiences:

- basketball analytics people
- EuroLeague fans interested in deeper analysis
- developers interested in MCP and agent tooling
- data engineers / analytics engineers
- AI developers
- open-source users
- potential collaborators or sponsors

The page should not assume that the visitor already knows what MCP means.

At the same time, it should not waste the hero explaining the Model Context Protocol. The visitor should understand the outcome first.

---

# 3. Core Positioning

## Working headline

> **Ask EuroLeague questions that normally take SQL.**

Possible supporting line:

> **Verified possession-level analytics, directly inside your AI assistant.**

These are working lines, not immutable final copy.

## Positioning hierarchy

The message order should be:

1. question
2. answer
3. proof
4. mechanism
5. setup
6. open source

Not:

1. MCP
2. architecture
3. tools
4. database
5. eventually a use case

---

# 4. Non-Negotiable Creative Principles

## 4.1 The launch must not smell AI-generated

Do not use:

- blue/purple “AI” gradients
- glowing gradient blobs
- glassmorphism
- floating decorative cards
- random 3D objects
- fake futuristic HUDs
- generic Lucide-icon-per-feature layouts
- arbitrary particle systems
- fake testimonials
- fake users
- fake dashboards
- decorative charts with no analytical meaning
- excessive rounded containers
- meaningless status badges
- meaningless “MCP connected” indicators
- generic startup copy such as “Unlock the power of…”, “Supercharge…”, “Revolutionary…”, “Next-generation…”, “The future of…”
- animation simply because an element exists

**Rule: when uncertain, remove rather than add.**

## 4.2 Use the product as the visual material

Prefer:

- real questions
- real tool names
- verified data
- real analytical results
- real repository claims
- real setup configuration
- typography
- cursor/typing interaction
- simple basketball/court geometry
- whitespace
- motion
- camera framing

The product already has interesting material. Decoration should not compete with it.

## 4.3 No copyrighted match footage

Do not use EuroLeague broadcast footage or copyrighted match clips.

Basketball identity should come from terminology, data, court geometry, restrained orange, sound design, and statistical rhythm.

## 4.4 Minimal content, strong pacing

Minimalism does not mean static.

Energy should come from camera movement, timing, scale, cropping, typography, interaction, hard cuts when useful, music synchronization, and subtle sound design — not from adding more assets.

---

# 5. Shared Visual Direction

The website, launch film, guide film, and social clips should share one design language.

## 5.1 Color direction

Move away from the old dark slate/cyan developer-dashboard visual language.

Preferred foundation:

- white
- warm white
- very light neutral grey
- dark charcoal text
- one restrained orange accent

The white/orange relationship may be loosely inspired by the visual energy of EuroLeague’s public identity, but EuroLeague branding should not be copied.

Orange should be used for active state, focus, important values, and small basketball references. Do not flood the page with orange.

## 5.2 Typography

Use no more than:

- one excellent modern sans-serif family
- one excellent monospace family

Requirements:

- open-source / safely licensed
- highly readable
- understated
- strong numeric rendering
- not futuristic
- not playful
- not “AI startup”
- not obviously template-driven

Hierarchy should come from size, weight, spacing, layout, and motion — not boxes.

Exact font selection remains open and should be visually tested before being locked.

## 5.3 Geometry

Use geometry only when it serves the basketball/data story.

Acceptable:

- partial half-court line
- key/arc geometry
- coordinate dots
- thin grid lines derived from data structure
- possession flow lines

Avoid floating basketballs, generic basketball illustrations, 3D basketball renders, and sports-broadcast graphics.

---

# 6. Existing Website: What Is Wrong

The current `site/index.html` is technically informative but functions more like documentation than a launch page.

Current structure includes:

- large technical hero
- six stat boxes
- six feature cards
- all 11 MCP tools
- a large setup section
- a large sponsorship section
- many top-navigation items

Problems:

1. The visitor is asked to understand implementation before seeing the product experience.
2. The most interesting thing — asking a real basketball question and getting a verified answer — is not the hero.
3. Six stat cards + six feature cards + eleven tool rows create a generic developer-dashboard/AI-generated visual pattern.
4. Sponsorship competes with the product narrative.
5. The page does not behave like a visual story.
6. The site is descriptive rather than demonstrative.

The new website should be rebuilt around a scroll narrative rather than feature taxonomy. Support and Privacy can remain separate pages.

---

# 7. Website Research — Reverse-Engineering Findings

Research date: 2026-09-01.

The goal is not to copy styles. It is to identify structural patterns.

## 7.1 Context7

Source: https://context7.com/

Current positioning is extremely direct: “Up-to-date docs for AI agents.” The homepage quickly gives the visitor one-line outcome, one install command, immediate product interaction/search, GitHub/API access, and very little explanatory clutter.

### Borrow

- outcome-first hero
- immediate “this is usable” feeling
- install/connect action near the top
- minimal explanation of MCP itself
- product interaction as hero material

### Do not copy

Context7 is utility/search-oriented. EuroLeague Analytics has a richer storytelling opportunity through real basketball questions.

## 7.2 Resend MCP

Source: https://resend.com/mcp

This is one of the strongest direct MCP references.

The page structure is approximately:

1. simple outcome-led hero
2. what MCP enables
3. real example prompts
4. tool/capability groups
5. demo
6. setup / CTA

The strongest idea is the **prompt examples**. Instead of explaining the server abstractly, the page shows what a user can ask.

### Borrow

For EuroLeague Analytics, use a small “Ask your agent…” sequence with strong questions such as:

- “How did Paris perform with TJ Shorts on vs. off the floor?”
- “Which five-man unit had the best E2024 net rating above 150 possessions?”
- “Define clutch as the final two minutes within three points. Which offense was best?”

These questions communicate more value than a list of MCP tools.

### Do not copy

Do not reproduce Resend’s long capability grid. Keep the homepage more editorial and compact.

## 7.3 Browserbase MCP

Source: https://www.browserbase.com/mcp

Useful structure:

- what it does
- ideal use cases
- capabilities
- setup config
- FAQ

### Borrow

Use this pattern for support/documentation content, especially one clear “what it does” paragraph, a direct configuration example, FAQ, and connection instructions.

### Do not copy

Do not use it as the main homepage structure. It is a technical MCP page, not a launch narrative.

## 7.4 Supabase MCP

Source: https://supabase.com/docs/guides/ai-tools/mcp

Supabase focuses heavily on connection UX: hosted connection, project selection, client selection, read-only options, security warnings, and generated config.

### Borrow

The Connect section should make client setup extremely easy. Potential tabs:

- Claude
- Claude Code
- Cursor
- Codex
- Other MCP client

Select client → show the shortest correct setup. Do not place every configuration on screen simultaneously.

### Do not copy

Detailed troubleshooting belongs in Support/README, not the homepage.

## 7.5 Google Antigravity

Source: https://antigravity.google/

Strong structural reference for a single page that feels like a presentation while scrolling.

Useful traits:

- large confident copy
- big product visuals
- one idea per major scroll section
- generous whitespace
- demos/use cases instead of feature-card overload
- repeated but restrained CTA
- sections feel like acts of a presentation

### Borrow

- presentation-like scroll rhythm
- one focal point per viewport
- minimal section copy
- visual progression
- demos instead of feature explanations

### Do not copy

Do not imitate the space/liftoff theme. Borrow the storytelling structure, not the aesthetic.

## 7.6 Raycast

Source: https://www.raycast.com/

Useful traits:

- strong short headlines
- product visually central
- large statements break up sections
- one idea at a time
- emotional brand copy used sparingly
- typography and spacing create much of the premium feeling

### Borrow

- confidence
- short statements
- large typography
- product-first imagery
- intentional pauses/whitespace

### Do not copy

Do not make EuroLeague Analytics feel like a consumer productivity brand. It should remain technical and analytical.

## 7.7 Resend Main Product Site

Source: https://resend.com/

Resend demonstrates that real technical interaction can be beautiful and that a developer product does not require a dashboard aesthetic.

Borrow the idea of integrating real technical interaction into the narrative instead of saving it all for docs.

---

# 8. Website Strategy

Target:

> a minimalist, single-page, scroll-driven product presentation

Not:

> a documentation portal with a homepage

The homepage should feel closer to a short product film that happens to be scrollable.

## Navigation

Keep navigation very small.

Possible top nav:

- EuroLeague Analytics
- How it works
- Connect
- GitHub
- optional Support

Do not put 11 Tools, Sponsorship, Privacy, or every feature category in primary navigation.

Privacy and support can live in the footer. Sponsorship should be secondary.

---

# 9. Proposed Website Narrative

Use native scrolling. Avoid aggressive scroll hijacking. Sticky sections and subtle progress-based transforms are acceptable.

## ACT 1 — Hero: Ask the Question

**Goal:** explain the value in seconds.

Working headline:

> Ask EuroLeague questions that normally take SQL.

Supporting line:

> Verified possession-level analytics, directly inside your AI assistant.

Primary CTA: **Connect MCP**  
Secondary CTA: **GitHub**

The hero should include a real product interaction, not a decorative illustration.

Possible treatment: a minimal AI-assistant input types:

> How did Paris perform with TJ Shorts on vs. off the floor in E2024?

The homepage may reuse a muted/shortened version of the launch-film interaction. No autoplay audio.

## ACT 2 — The Product Answers

As the visitor scrolls, the same question should evolve instead of disappearing into an unrelated section.

Flow:

question input → submitted state → small MCP/process state → result

Verified result:

**TJ Shorts ON**

- ORtg 116.14
- DRtg 111.04
- Net **+5.09**

**OFF**

- ORtg 117.05
- DRtg 128.50
- Net **−11.45**

Do not dump every value immediately. The visual hero can be simply:

> +5.09 ON  
> −11.45 OFF

Then smaller supporting context.

## ACT 3 — Ask Better Basketball Questions

Do not present “features.” Present questions.

Use 3–4 carefully chosen prompts in a simple vertical sequence.

### Lineup question

> Which five-man unit had the best E2024 net rating among units with at least 150 offensive possessions?

Verified result:

Paris Basketball — Kevarrius Hayes / Sebastian Herrera / Mikael Jantunen / TJ Shorts / Tyson Ward  
127.45 ORtg  
102.00 DRtg  
+25.45 Net  
Paris team offense rank: 8th of 18

### Caller-defined clutch

> Define clutch as the last 120 seconds within 3 points. Which E2024 offense was best with at least 20 possessions?

Verified result:

Fenerbahce Beko Istanbul  
48 points / 31 possessions  
154.84 ORtg  
Full-season ORtg: 119.21

Other possible prompts: shot-location question, Four Factors question, game-specific possession question.

Do not show too many.

## ACT 4 — Verified, Not Guessed

Do not use a six-card grid.

Use 2–4 full-width typographic proof moments.

Current public-site claims include:

- **732 games loaded**
- **107,311 reconstructed possessions**
- **100% final-score reconciliation**
- **41,524 verified E2024 field-goal coordinates**
- **99.54% minute precision to exact second**
- **11 specialized read-only MCP tools**

Final launch should re-check these before publication because warehouse/archive state can change.

Core proof message:

> The model does not invent the analytics. It asks the warehouse.

Supporting concept:

> Published evaluations re-run the same questions through ground-truth SQL and the live MCP tool path. Both must agree.

## ACT 5 — How It Works

Use one extremely simple diagram:

**QUESTION**  
↓  
**MCP TOOLS**  
↓  
**VERIFIED WAREHOUSE**  
↓  
**ANSWER**

No giant architecture diagram. Technical users can go to GitHub/README.

## ACT 6 — Connect

Headline:

> Ask your first question.

The hosted endpoint/auth flow should be current and verified at launch time.

Use a small client selector rather than dumping every config at once.

Detailed setup and troubleshooting remain in Support/README.

## ACT 7 — Open Source / Under the Hood

Keep concise.

Potential copy:

> Open source. Every result can be inspected.

Links:

- GitHub
- evaluation suite
- methodology / README
- support

## ACT 8 — Close

Very clean close.

Possible structure:

> EuroLeague Analytics  
> Ask better basketball questions.

Links:

- Connect
- GitHub

Optional secondary line: Built by Egemen Yücelen.

Do not end with a giant generic CTA panel.

---

# 10. Website Motion Grammar

The page can move, but it should never become a scroll-effects demo.

## Prefer

- native scroll
- CSS sticky
- IntersectionObserver
- subtle scale
- controlled translate
- opacity
- clipping/masking
- small camera-like reframing
- continuous transformation between related states

## Avoid

- custom scroll physics
- scroll hijacking
- parallax everywhere
- elements flying from random directions
- excessive 3D
- cursor-chasing effects
- constant animation while the user is reading

## Strong concept

The first 2–3 sections can feel like one continuous interaction:

hero question → submit → process → answer → answer expands into proof

This mirrors the desired launch-film continuity.

---

# 11. Website Technical Direction

The current site is static HTML/CSS and this remains valid.

Do not open a framework rewrite merely to make the launch site look modern.

Preferred implementation order:

1. semantic HTML
2. excellent CSS
3. small amount of JavaScript for interaction/scroll states
4. optional lightweight animation library only if it materially improves the result

The website must remain fast, responsive, accessible, usable without animation, easy to deploy, and easy to maintain.

The visual result matters more than the framework.

---

# 12. Video Strategy

One video should not try to be both cinematic launch film and detailed product guide.

Recommended package:

### A. Main Launch Film — 25–35 seconds

Purpose:

- create interest
- communicate the core product moment
- establish quality
- make the project memorable

### B. How-It-Works / Product Guide — 40–60 seconds

Purpose:

- show how to connect/use the MCP
- show realistic AI interaction
- explain the workflow

This can be closer to the Notion/Figma-style product-guide language.

### C. Micro Demo Clips — 8–15 seconds each

Purpose:

- X thread media
- website embeds
- individual use-case demos

Examples:

- TJ Shorts on/off
- caller-defined clutch
- validation / SQL vs MCP
- connection/setup

---

# 13. Video Tooling Decisions

## 13.1 Model / agent preference

Based on direct experiments in this launch work:

- Gemini in Antigravity has produced more promising video output than Codex.
- Codex was tested and was not preferred for this specific creative/motion task.
- This is a project-specific creative judgment, not a general model benchmark.

Current preferred agent environment:

> **Antigravity + Gemini**

## 13.2 Existing Remotion experiments

Remotion works technically and remains a valid fallback.

Repeated attempts showed a risk of scene-by-scene/slideshow feeling, static camera, and checklist-like execution without cinematic flow.

The problem is not only Remotion; it is also the motion grammar given to the agent.

## 13.3 HyperFrames — next tool to test

Project: https://github.com/heygen-com/hyperframes

HyperFrames is especially relevant because it is designed around HTML/CSS/JS → deterministic video rendering and is explicitly agent-oriented.

Potential advantages:

- agent-friendly
- Gemini is comfortable with HTML/CSS/JS
- GSAP-compatible
- strong camera/composition possibilities
- local rendering
- open-source Apache-2.0
- designed for agent workflows

The next meaningful A/B test should be:

**Gemini + existing Remotion system**

versus

**Gemini + HyperFrames + motion-design skills**

Do not run endless tool experiments after this. The tool must serve the final creative direction.

## 13.4 Supporting open-source motion skills/repositories

### product-launch-motion
https://github.com/AbubakrChan/product-launch-motion

Useful for launch-film discipline, camera rigs, music/word sync, shot-based composition, sound design, and QA.

### video-shotcraft
https://github.com/RoyTao2025/apa2-video-shotcraft

Useful as a shot vocabulary and camera/motion reference library.

### launch-video-skill
https://github.com/serenakeyitan/launch-video-skill

Useful principles: story not feature tour, one aha moment, real product material, pixel verification, concise beat structure.

### Motion Canvas
https://github.com/motion-canvas/motion-canvas

Possible Plan B for more handcrafted vector/typography animation.

### OpenCut
https://github.com/OpenCut-app/OpenCut

Not recommended as the current launch pipeline, but worth monitoring because its direction includes headless/API/MCP-like editing workflows.

---

# 14. Video References — Current Taste Filter

## Keep / study further

### Raycast

Already familiar. Useful for momentum, punch-ins, hard cuts, pace, camera energy, and beat-driven editing.

### Framer 3.0

**Liked.**

Useful for launch-film flow, UI motion, continuous transitions, product-first visual language, and strong rhythm.

### Notion 3.0 Agents

**Liked.**

Especially useful for a separate **how-it-works / guide video**.

Useful for user → AI → processing → result, teaching product use through motion, and maintaining clarity while showing a workflow.

### Figma Motion

**Liked.**

Useful for guide/showcase hybrid, cursor/UI choreography, product canvas as visual material, and a different instructional tone from Notion.

## Reject as primary references

### Linear “Coding Sessions” / people-heavy product video

Not the desired direction: long, real-life people, lifestyle/human footage, wrong format for this project.

### EuroLeague promotional video

Ignore. The launch does not need to imitate official sports promo content.

---

# 15. Video Reverse-Engineering Method

Before locking the final film, manually reverse-engineer the selected references.

Use a table:

| Time | What is visible | Camera | Transition | Audio | New information | Why it works | Possible use |
|---|---|---|---|---|---|---|---|

Inspect:

1. first three seconds
2. shot length
3. why the cut occurs
4. when camera pushes in
5. when camera pulls out
6. when UI stops moving so the viewer can read
7. typography scale changes
8. transition from large type → UI
9. transition from UI → proof/stat
10. music phrase changes
11. impact sounds
12. silence
13. how many actual product ideas are communicated
14. what is intentionally omitted

Watch strong references again at 0.25x or 0.5x speed.

The purpose is to derive **motion grammar**, not visual imitation.

---

# 16. Desired Motion Grammar for the Main Film

The final launch film must not feel like:

slide → slide → slide → stat card → logo

Instead use visual causality.

Example:

wide composition → user starts typing → camera slowly pushes into input → Enter → input shifts upward into conversation → assistant enters processing state → camera follows active region → MCP tool completes → answer emerges from the same region → camera pushes into +5.09 → +5.09 becomes the transition object → camera pulls back into validation proof → proof resolves into product identity

The next shot should feel caused by the previous one.

---

# 17. Chat / AI Interaction Direction

A chat interaction is an important product demonstration.

Do not recreate Claude, ChatGPT, or Gemini pixel-for-pixel.

Build an original, minimal assistant interaction.

Micro-behaviors may include:

- blinking cursor
- realistic typing cadence
- keyboard SFX
- Enter key
- short waiting state
- simple process/tool status
- answer arriving progressively
- camera tracking the active area

Do not display hidden chain-of-thought. Show only legitimate process states such as querying possession data, calling a real `el_` tool, processing, and answer.

The interaction should feel believable because of timing and behavior, not fake UI detail.

---

# 18. Sound Direction

Sound should be authored with the motion.

Music should not simply play underneath unrelated animation.

Preferred music character:

- minimal electronic
- modern
- rhythmic
- restrained
- no generic corporate inspiration track
- enough transients/beats to edit against

Basketball SFX can be used sparingly:

- net swish
- subtle ball bounce
- sneaker/court squeak
- impact

Interface SFX:

- typing
- Enter
- subtle click
- process/tool completion tick
- restrained whoosh

Basketball sounds are punctuation, not ambience.

Example: verified answer lands + very subtle net swish.

All third-party audio must have documented licensing/source information.

---

# 19. Verified Product Material Available for Launch

Always verify again immediately before final publication.

## 19.1 Current public-site dataset claims

- 732 games loaded
  - 330 E2024
  - 402 E2025
- 107,311 reconstructed possessions
- 99.54% minute precision to exact second
- 100% final score reconciliation
- zero point mismatches across the 732 games
- 41,524 verified E2024 field-goal coordinates
- 11 specialized read-only MCP tools

Do not blindly hard-code these into final launch assets if production state changes before launch.

## 19.2 Evaluation example: TJ Shorts on/off

From `evaluation.xml`, frozen to non-quarantined E2024 games.

TJ Shorts:

- 34 included games
- 19.26 official points/game
- 27.3 corrected minutes/game
- 927.5 corrected minutes total

Paris with TJ Shorts ON:

- 1,936 points
- 1,667 offensive possessions
- 1,850 points allowed
- 1,666 defensive possessions
- ORtg 116.14
- DRtg 111.04
- **Net +5.09**

Paris with TJ Shorts OFF:

- 961 points
- 821 offensive possessions
- 1,064 points allowed
- 828 defensive possessions
- ORtg 117.05
- DRtg 128.50
- **Net −11.45**

Important disclosure: on/off is team context, not an estimate of individual value.

## 19.3 Evaluation example: best qualifying five-man lineup

E2024, non-quarantined, at least 150 offensive possessions:

Paris Basketball:

- Kevarrius Hayes
- Sebastian Herrera
- Mikael Jantunen
- TJ Shorts
- Tyson Ward

Results:

- 195 points
- 153 offensive possessions
- ORtg 127.45
- 153 points allowed
- 150 defensive possessions
- DRtg 102.00
- **Net +25.45**

Paris team offensive rating: 117.81, rank 8th of 18.

## 19.4 Evaluation example: custom clutch

Definition:

- possession starts in final 120 seconds
- absolute margin ≤ 3
- at least 20 qualifying possessions

Best E2024 offense: Fenerbahce Beko Istanbul

- 48 points
- 31 possessions
- **154.84 ORtg**
- full-season ORtg: 119.21
- difference: +35.63 per 100

This is a strong example because the user defines “clutch” rather than accepting a hard-coded definition.

---

# 20. Main Launch Film — Current Story Direction

Do not lock exact seconds until the reference videos have been manually reverse-engineered.

Conceptual beats:

1. **Hook** — short; no generic title animation
2. **Ask** — real basketball question typed
3. **Process** — brief MCP/data process
4. **Answer** — verified result becomes the hero
5. **Trust** — strongest 2–3 validation facts
6. **Resolve** — EuroLeague Analytics / Open source / GitHub / website

The main launch film is **not** the setup tutorial.

---

# 21. How-It-Works Film

Target: **40–60 seconds**

This can borrow more heavily from the Notion/Figma guide-video language.

Possible structure:

1. Connect EuroLeague Analytics
2. Ask a real question
3. AI chooses MCP tools
4. Answer arrives
5. Ask a custom query
6. Show another example
7. Explain verification briefly
8. Link to site/GitHub

This video may be embedded lower on the website and linked in the launch thread.

---

# 22. Micro Clips

Create reusable short media instead of one monolithic asset.

### Clip A — TJ Shorts (8–15 sec)
question → tool → +5.09 / −11.45

### Clip B — Custom clutch (8–15 sec)
custom definition → Fenerbahce → 154.84 ORtg

### Clip C — Verification (8–12 sec)
same evaluation → SQL path → MCP path → match

### Clip D — Connect (8–12 sec)
client → MCP URL/config → connected → first question

Reuse in X, website, README, and future posts.

---

# 23. X / Twitter Launch Strategy

The existing `docs/LAUNCH_COPY.md` contains a seven-post draft.

For final launch, a tighter **3–4 post thread** is currently preferred.

Every tweet should have one job.

## Tweet 1 — What I built

Purpose: launch hook + product identity + main launch film.

Working draft:

> I built EuroLeague Analytics — an open-source MCP server that lets AI assistants query reconstructed EuroLeague possessions, lineups, on/off splits and shot data.
>
> Instead of asking an LLM to guess from box scores, you can ask basketball questions like this ↓

Attach: **main launch film**

## Tweet 2 — What can it actually do?

Purpose: real use case + real result.

Working draft:

> Example: “How did Paris perform with TJ Shorts on vs. off the floor in E2024?”
>
> The MCP pulls the underlying possessions and returns the split: +5.09 NetRtg on court vs -11.45 off.
>
> No prewritten answer — the result is re-earned from the warehouse.

Attach: **TJ Shorts micro demo**

## Tweet 3 — Why trust it?

Purpose: validation + engineering credibility.

Working direction:

> The part I cared about most was verification.
>
> [current verified game/possession numbers]
>
> A published evaluation suite checks answers through both ground-truth SQL and live MCP tool calls.
>
> The code is open source.

Attach: **validation micro clip**

Final numbers must be refreshed at launch time.

## Tweet 4 — Try it

Purpose: direct action.

Working direction:

> Connect it to an MCP-compatible client and ask your own questions — lineups, Four Factors, custom clutch definitions, shot locations and more.
>
> Website: egemenyucelen.me  
> GitHub: github.com/egemeny13/euroleague-analytics
>
> Feedback is welcome.

Attach optional **connect clip**, or no media if previous media is enough.

---

# 24. X Video Technical Target

Safe master:

- 1920×1080
- 30 fps
- H.264 / AVC
- AAC audio
- MP4
- under 60 seconds for launch/guide clips when possible

X currently states that videos 60 seconds or shorter loop automatically.

For non-Premium accounts, X currently allows up to 140 seconds / 512 MB.

Official source: https://help.x.com/en/using-x/x-videos

Keep source/render files in the launch worktree/release assets; do not treat X as the archive.

---

# 25. Website + Video + Thread Must Be One System

The three surfaces should reuse the same product moments.

Example:

**Website:** TJ Shorts question → result → proof  
**Main film:** TJ Shorts question → result → proof  
**Tweet 2:** TJ Shorts short clip

This repetition is intentional.

Shared elements:

- type system
- orange
- light background
- question styling
- stat typography
- cursor
- process state
- audio cues in video
- language/copy

---

# 26. Sponsorship

Sponsorship should not dominate the launch homepage.

The current website gives it a major full section and nav entry. This competes with the product story.

Preferred treatment:

- no top-nav Sponsorship item
- optional small section near the end or footer link
- one sentence
- measured facts only

The launch plan already states that the sponsor ask should be one sentence plus measured numbers.

Keep it secondary to product adoption.

---

# 27. Suggested Launch Worktree Structure

Conceptually:

```text
launch/
├── LAUNCH_PACKAGE_MASTER_BRIEF.md
├── research/
│   ├── video-reverse-engineering.md
│   ├── website-reverse-engineering.md
│   └── references.md
├── video/
│   ├── launch-film/
│   ├── how-it-works/
│   ├── clips/
│   ├── audio/
│   └── output/
├── social/
│   ├── x-thread.md
│   └── media-map.md
└── assets/
```

Existing production `site/` can be rebuilt directly if preferred.

Do not duplicate files merely to satisfy this suggested structure.

---

# 28. Production Workflow

## Phase A — Research / direction

Before final implementation:

- manually reverse-engineer Framer
- manually reverse-engineer Notion
- manually reverse-engineer Figma Motion
- use Raycast as an already-known motion reference
- record specific observations
- finalize typography
- test website scroll story as static frames
- run one HyperFrames experiment

## Phase B — Lock

Lock:

- homepage narrative
- main launch film story
- guide video story
- typefaces
- palette
- main query example
- proof claims
- X thread structure

After this point, agents should not invent new design directions.

## Phase C — Implement

- rebuild website
- produce video masters
- produce micro clips
- draft final X thread
- verify all repository claims
- verify setup instructions
- verify licenses

## Phase D — Live-season replacement

Per current launch plan:

- prepare scripts/storyboards before live season
- record final live material on 2026-09-25 / 2026-09-26 after clean nights
- launch around 2026-09-27 only if live validation conditions are satisfied

The launch date is not more important than correctness.

---

# 29. Agent Instructions

Any coding/design agent working on the launch package should read:

- this file
- repository README
- launch plan
- evaluation suite
- current website
- support/setup docs

Do not invent statistics, capabilities, tool names, results, customer logos, testimonials, or integrations.

## Visual decision rule

If an element does not improve hierarchy, comprehension, product demonstration, pacing, or basketball identity, remove it.

Agents may solve implementation details, but should not independently redefine art direction, product positioning, core story, or reference pool without explicit owner direction.

---

# 30. Website QA

### Story

- Can a new visitor explain the product after the first two sections?
- Is the first real basketball question visible early?
- Does the page show rather than merely describe?
- Is setup easy to find?

### Visual

- Does anything look like generic AI SaaS?
- Are there too many cards?
- Are there meaningless icons?
- Is orange overused?
- Does typography feel intentional?
- Is there enough whitespace?

### Motion

- Does motion guide attention?
- Does the page still work with reduced motion?
- Is native scrolling preserved?
- Does any animation interfere with reading?

### Technical

- mobile
- desktop
- keyboard navigation
- contrast
- reduced-motion preference
- loading performance
- no layout shifts
- no unnecessary JS
- links correct
- production endpoint correct

---

# 31. Video QA

### Story

- one core idea
- no feature tour
- no filler
- product understood on first view

### Flow

- each visual event motivates the next
- no slideshow feeling
- camera directs attention
- information gets enough hold time

### Design

- typography strong
- minimal asset count
- no AI-generated visual smell
- no generic SaaS decoration

### Sound

- music edits align with visuals
- SFX subtle
- basketball SFX used as punctuation
- audio license documented
- video works muted

### Accuracy

- all stats verified
- tool names real
- disclosures not misleading
- no copyrighted match footage

---

# 32. Thread QA

Before posting:

- Tweet 1 makes sense to someone who does not know MCP.
- Tweet 2 demonstrates a real question.
- Tweet 3 proves trust.
- Tweet 4 gives a clear path to try it.
- No tweet becomes a README paragraph.
- All metrics are current.
- Attached clips are readable on mobile.
- First frames work as thumbnails.
- Videos have meaningful visual content without sound.
- Links are final.
- No unnecessary hashtags.

---

# 33. Open Decisions

These should be answered through research/testing, not by an agent guessing.

1. Exact sans-serif font
2. Exact monospace font
3. Exact orange accent
4. HyperFrames vs Remotion for final launch film
5. Final main launch-film reference grammar after manual reverse engineering
6. Final guide-video length
7. Final live-season example to record after 2026-09-24
8. Hero implementation: live DOM interaction vs pre-rendered muted video vs hybrid
9. Connect section: client tabs vs universal endpoint first
10. Final X wording
11. Sponsorship: tiny homepage mention vs footer-only

Do not prematurely lock these.

---

# 34. Research Source List

## MCP/product website references

Context7  
https://context7.com/

Resend MCP  
https://resend.com/mcp

Browserbase MCP  
https://www.browserbase.com/mcp

Supabase MCP  
https://supabase.com/docs/guides/ai-tools/mcp

## Product website references

Google Antigravity  
https://antigravity.google/

Raycast  
https://www.raycast.com/

Resend  
https://resend.com/

Framer  
https://www.framer.com/

Notion Agents  
https://www.notion.com/product/agents

Figma Motion  
https://www.figma.com/blog/introducing-figma-motion/

## Video tooling / skills

HyperFrames  
https://github.com/heygen-com/hyperframes

HyperFrames launch video source  
https://github.com/heygen-com/hyperframes-launch-video

product-launch-motion  
https://github.com/AbubakrChan/product-launch-motion

video-shotcraft  
https://github.com/RoyTao2025/apa2-video-shotcraft

launch-video-skill  
https://github.com/serenakeyitan/launch-video-skill

Motion Canvas  
https://github.com/motion-canvas/motion-canvas

OpenCut  
https://github.com/OpenCut-app/OpenCut

## Platform specifications

X video help  
https://help.x.com/en/using-x/x-videos

---

# 35. Final Creative Test

Before approving any launch artifact, ask:

> If the viewer did not know this was made with AI-assisted tools, would anything in the result make them suspect it?

If yes, identify why.

Common causes:

- generic card grids
- excessive decorative motion
- predictable startup copy
- synthetic assets
- excessive glow
- bad typography
- over-explaining
- perfect-but-meaningless symmetry
- every section having the same layout
- too many features per screen

Then simplify.

The target is not:

> “This does not look AI-generated.”

The target is:

> The viewer never thinks about how it was made. They think about the product.

---

# 36. One-Sentence Direction

If every other section of this document is forgotten, preserve this:

> **Make EuroLeague Analytics feel like a real basketball question turning into a trustworthy answer — with as little visual noise as possible.**
