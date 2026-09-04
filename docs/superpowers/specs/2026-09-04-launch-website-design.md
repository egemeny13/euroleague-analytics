# Launch website — design

Written 2026-09-04, from a design session directed by the owner. Every choice
below was made by the owner; this file records what was chosen and why, so the
implementation has one place to disagree with.

**Authority.** `CLAUDE.md`, then `DECISIONS.md`, then `ROADMAP.md`. This is a
design document, not a decision log: the decisions it creates are listed at the
end and belong in `DECISIONS.md` in the pull request that implements them.

**Status, 2026-09-04 end of day.** v1 is built and complete end to end on the
branch `feat/launch-site`. Nothing is merged and nothing is deployed. Section 15
records what the session changed after this document was first written, and
section 16 is the remaining work.

---

## 1. What the site is for

**The site succeeds when a visitor connects the MCP server to their own AI
assistant and asks their own question.** That is the single measure. Everything
else the site could do — attract a sponsor, build reputation, serve as a
portfolio — was explicitly ranked below it by the owner and is treated as a
by-product of doing this one thing well, not as a section to build.

Consequences that follow, and that the rest of this document obeys:

- The page has one job, so it has one primary action: **Connect**.
- No sponsor section, no pricing table, no feature grid, no blog.
- Anything that does not move a visitor toward connecting is either cut or
  pushed below the point where only a curious reader goes.

## 2. Who is reading it

Two readers, both real, and the copy has to work for both at once:

- **A 45-plus basketball follower.** Uses an AI assistant, is not technical, and
  will assume there is an app to download unless told otherwise.
- **A 16-to-17-year-old.** Understands the tooling immediately and needs a
  reason to care rather than an explanation of what it is.

The owner named the failure mode precisely: the older reader thinks they must
install something. The site answers that in words (**"No app, no spreadsheet"**)
and, more importantly, in pictures — see §4.

The visitor must already have Claude or ChatGPT. That narrows the audience and
is accepted; the site does not try to explain what an AI assistant is.

## 3. Language

**English site, with a Turkish switch. English thread.**

The Turkish text is **written, not translated.** A literal rendering of "nothing
to download" says nothing useful in Turkish; the sentence that works there is
closer to "you are not installing an app, you connect the AI you already use,
once". Two authored texts, one switch between them.

**This collided with an existing rule, and the collision is settled.**
`tests/test_english_only.py` failed on any tracked file containing Turkish
characters, which is `CLAUDE.md`'s "no exceptions" rule expressed as a test.
Decision 53 exempts `.html` files under `site/` and nothing else: scripts and
stylesheets stay English, comments included, which is why `site/hero.js` reads
the demo question from a `data-question` attribute rather than holding a
sentence of its own.

**English is the default, and the Turkish page is reached by redirect rather
than by a button.** The owner's decision: detect the browser's language, send a
Turkish reader to `/tr/`, and keep a small link back so nobody is trapped in a
language they did not choose. A prominent switch was rejected; removing the
escape hatch entirely was rejected too. Neither the page nor the redirect is
built.

`CLAUDE.md` requires English for code, comments, documentation and tool
descriptions. Site copy is product text and is not covered by that rule; this
paragraph exists so nobody reads the Turkish strings as a rule violation.

## 4. The hero, and how it does the explaining

**Headline:** *Add EuroLeague to the AI you already use.*
**Sub-line:** *Connect once, then ask in your own words — every lineup, every
shot, every second on court. **No app, no spreadsheet.***

Chosen over a curiosity-led headline (naming a club and asking which five wins
its games) because the older reader has to understand *what this is* before being
teased, and the younger reader is caught by the demo regardless.

**Beside it, a conversation that types itself.** No play button, no click. The
owner's rule for the whole site is *minimum activity, maximum received*, and
this is where it starts: the visitor learns what the product is without doing
anything.

**The conversation is drawn inside a recognisable assistant window**, its title
bar reading `Claude · EuroLeague Analytics connected`. This is the single most
load-bearing detail on the page. It says "this lives inside software you already
have" without spending a word, and it is what stops the older reader looking for
a download button. The word "MCP" does not appear above the fold; it appears
once, far below, for the reader who wants it.

**The question is asked in Turkish, the answer comes in English.** Deliberate:
it shows that the visitor can ask in their own language, and it is what actually
happens.

**Arrangement:** side by side on the desktop — headline and buttons left,
window right. On a phone: short headline, then the **whole** window, then the
sub-line, then the button. Owner's choice: on a small screen the animation is
worth more than the sentence, so the visitor sees before reading.

The side-by-side arrangement narrows the window and the answer has to be shorter
than it would be stacked. That is a real cost and it was accepted knowingly.

## 5. Page order

1. **Hero** — the self-typing conversation. (§4)
2. **Every shot's location** — a half court fills with real shot coordinates as
   the visitor scrolls. One claim: *we know where every shot was taken.*
3. **Change one player, everything changes** — five names, one substitution, and
   a single large number that moves. One claim: *the lineup is the team.*
4. **Ask it yourself** — the live question chips. (§6)
5. **Connect** — Claude or ChatGPT, in as few steps as the truth allows. (§7)
6. **How it works** — short, quiet, honest, and a link to GitHub for the rest.

**Trying comes after being convinced, not before.** The owner's own sequence was
"if they like the demo and want to test it without leaving the screen". A visitor
who reaches the chips has already seen what good looks like and asks a better
question because of it.

**One idea per section.** An earlier attempt combined the court and the lineup
into a single animated stage carrying a clock, five name plates, a net rating, a
possession count, a shot chart and a stint strip. The owner could not read it,
and was right: a visual that argues two things proves neither. The left column
of each section states one claim; the right column shows only that claim.

### Deliberately absent

- **A row of three big numbers under the hero.** The owner's objection, and it is
  correct twice over: it is the clearest tell of a templated page, and a visitor
  who does not yet know what the product is cannot be moved by "732 games".
- Feature cards, a pricing table, a sponsor block, a chart gallery, a blog.

Proof does not disappear — it moves. See §8.

## 6. The live question box

**Chips, never a free text field.** Three or four good questions the visitor can
click. This is a security decision and an experience decision at once: an empty
box invites a bad question and a bad first impression, and it is also the only
thing that would make the endpoint dangerous.

**Chosen approach: a locked live endpoint.** A public, unauthenticated route on
the existing hosted server accepts *an identifier from an allowlist and nothing
else*, runs the query that identifier names, and returns the answer. The
visitor's browser cannot express any other request.

Its risk is closed three ways, all of which must exist before it ships:

- **No free text, so no injection surface.** An identifier that is not on the
  list is refused.
- **Server-side caching**, so a thousand visitors cost the database a handful of
  queries an hour rather than a thousand. The free tier is a design constraint
  (`DECISIONS.md` item 12) and this is what keeps it out of danger.
- **Per-IP rate limiting.**

**Why live rather than recorded:** the season opens on 2026-09-24, eight days
after launch. A live endpoint lets the page say *including last night's games*
and be telling the truth, with no rebuild.

**The fallback, if this is not ready or measures badly: answers recorded at
build time**, labelled with the date they were taken. The page looks identical
either way — only the origin of the number changes — so choosing the fallback
late costs nothing already built. This is the reason the fallback exists rather
than a second design.

**Rejected: a free text box answered by a real model.** Every question would cost
money, the abuse surface is unbounded, and the project's purpose is to recover
its cost, not to create one.

## 7. Connect

One URL — `https://euroleague-analytics-mcp.fly.dev/mcp` — added as a custom
connector, then a Google sign-in. Claude and ChatGPT each get their own short
path, written from `docs/CLIENT_COMPATIBILITY.md` rather than from memory.

**This section is blocked on R-9.** The invite-only Auth0 Action is still on; the
door is scheduled to open on 2026-09-12 (`docs/LAUNCH_PLAN_2026.md`). A visitor
who follows these steps before that date is refused at the login screen. The
section must not go live before R-9 does, and whoever ships the site is
responsible for checking that R-9 actually happened rather than assuming the
calendar.

## 8. Where the proof went

The stat row is gone. The proof is now **inside the answers**, which is both less
templated and more convincing:

- Every rating carries the possessions it was measured over — *+21.6 over 184
  possessions*, never *+21.6*.
- A number that came from a quarantined or excluded population says so.
- The "how it works" section states, briefly, that games failing their validation
  invariants are excluded from every default answer.

Three honesty notes appear on the page itself, in small text next to the visuals
they constrain. They are not fine print; they are the argument:

- **Free throws are absent from the shot chart** because they have no
  coordinates — every one of them is the `(-1,-1)` sentinel.
- **The court is attack-relative**, a single normalised half court. A dot on the
  right is the right side of *that team's own attack*, not a corner of an arena.
- **A possession that spans a substitution is credited to the five who started
  it.** A stated convention, not a measurement.

## 9. Identity

**Typography.** Gabarito for headlines, Figtree for text, IBM Plex Mono for data
and numbers. All three are SIL Open Font License, so the files are self-hosted:
no third-party font request, no tracking, no licence to renew.

EuroLeague's own typeface is **BW Modelica** (measured from
`euroleaguebasketball.net`, 2026-09-04). It is not used, for two independent
reasons: it is a commercial licence that is not ours, and the league's brand
typeface beside the league's name would imply an affiliation that does not exist.

**Colour.** A quiet near-white base — the cool grey the mockups already use —
and colour that always *means* something. The owner was shown warmer paper tones
and was indifferent, so the cool base stays and is cheap to revisit later:

- **Team colours** on monogram chips, from a small hand-maintained table of club
  colours. They change from page to page, so the site does not look the same
  twice.
- **One accent (orange)** reserved for data — a made shot, a live value.
- **No decorative colour at all.** Purposeless colour is exactly what makes a
  page look generated.

**No club crests and no player photographs.** Three separate problems, and the
last of them is the one this project already knows about:

- A crest is a trademark *and* a copyrighted drawing. Referential use of a mark
  is defensible; copying the artwork is a separate act, and the files sit on the
  league's own CDN, which our API happens to hand us. No published terms-of-use
  page could be found on `euroleaguebasketball.net` — only cookie and privacy
  policies — so there is no permission to rely on either. Absence of a rule is
  not permission.
- A player photograph carries the photographer's copyright and the player's
  image rights.
- An avatar drawn or generated from such a photograph is a derivative work; the
  copyright travels with it, and a recognisable likeness raises image rights on
  its own.

`CONTEXT.md` records that the largest Turkish EuroLeague account was shut down
twice, most likely for posting unlicensed clips. Borrowed artwork would be the
one careless thing on a page whose entire argument is care.

**What replaces them, from our own data:** a coloured circle carrying the
player's jersey number, and a coloured chip carrying the club's three-letter
code. Both fields are already in the warehouse.

**Background:** static thin court geometry. It holds the page up and names the
subject. No gradient blobs, no drifting particles — motion that means nothing is
the template tell the owner is trying to avoid.

## 10. Motion

**Every animation on this site is data doing something.** A clock that advances,
a shot that lands, a lineup that changes, an answer that types. Nothing moves
decoratively.

Rules the implementation must follow:

- `prefers-reduced-motion` is honoured: the animation renders its finished state
  immediately instead of playing.
- Animations pause when their section is off screen.
- No autoplaying video anywhere. The hero conversation is text and CSS, not the
  existing `preview.mp4` — it stays crisp at any size, weighs almost nothing, and
  can be translated with the rest of the page.

## 11. Technical shape

- **Static files under `site/`**, as today: hand-written HTML, CSS and a small
  amount of JavaScript. No framework and no build step. The owner cannot read the
  code; a framework would add a layer he cannot inspect and a toolchain that
  breaks while he is not looking.
- **Deployment is unchanged**: `pages.yml` already republishes the site whenever
  `site/**` changes on `master`. Merging is therefore publishing.
- **The existing `site/` package is a draft, not a base.** `ROADMAP.md` records
  that the site may be rethought from zero, and it is being rethought.
- **The hero's answer content is a snapshot committed to the repository**,
  regenerated by a script that runs the real query. The hero must animate
  instantly and identically for every visitor, including one whose network is
  slow, so it does not call the live endpoint. Only §6's chips do that.

## 12. Out of scope for this document

Video production, social cards and the launch thread. They live in the
`euroleague-analytics-launch` repository (`DECISIONS.md` item 47). The owner has
said the videos will likely be remade once this design system exists; that is
later work and is not planned here.

## 13. What this design does not establish

- **That anybody connects.** The whole page is an argument for one action, and no
  version of it has been put in front of a stranger. There is no measurement here,
  only reasoning.
- **That the two readers are actually served.** §2's two readers were reasoned
  about, not interviewed. The mockups were judged by the owner, who is neither.
- **That the live endpoint's cost is safe.** The caching and rate limits are a
  design, not a measurement. They must be measured under real traffic before the
  page claims to be live, and free-tier behaviour under public traffic is already
  listed as unmeasured in `ROADMAP.md`.
- **That the Turkish text works.** It has not been written yet, and it must be
  authored rather than translated.
- **That the site is finished when it looks finished.** The one thing that makes
  it work — R-9 opening the door — is not part of this design and is not done.

## 14. Decisions this creates

To be written into `DECISIONS.md` by the pull request that implements them, each
with its condition:

1. **The launch site is rebuilt from zero as static files under `site/`**, with
   no framework and no build step, because the owner cannot audit a toolchain.
2. **The site's live demo answers a fixed allowlist of question identifiers over
   an unauthenticated route**, cached and rate limited, with recorded answers as
   the named fallback. Condition: the endpoint accepts no free text, ever.
3. **No club crests and no player photographs or avatars derived from them.**
   Identity is carried by club colours, club codes and jersey numbers, all from
   our own data.
4. **Site typography is self-hosted OFL fonts.** EuroLeague's own typeface is
   excluded on licence and on affiliation grounds.
5. **Proof appears inside answers rather than as a statistics row**, and every
   rate on the page carries the population it was measured over.

---

## 15. What the build changed, and why

Written as the sections were built and reviewed by the owner one at a time.
Where this contradicts an earlier section, this wins: it is later, and it was
decided while looking at the thing rather than at a description of it.

**Language is resolved.** Decision 53 exempts `.html` files under `site/` from
the Turkish scan and nothing else, which is why `site/hero.js` reads the demo
question from a `data-question` attribute instead of holding a sentence. The
owner chose a browser-language redirect to `/tr/` with a small link back rather
than a language button. Neither the Turkish page nor the redirect exists yet.

**The hero cycles three assistants, each with its own question.** One assistant
read as "works with that one"; the same question three times read as a loop.
Claude, ChatGPT and Gemini, each named in text with its own brand colour, no
logo and no imitation of anyone's interface. The owner asked about using real
logos: reproducing a logo to state compatibility is generally permitted by these
companies' brand guidelines, and the earlier blanket refusal in section 9 was too
strong. What stays off limits is dressing the page up as their product.

**Four beats, not two.** You ask; EuroLeague Analytics goes and reads; the
assistant thinks; the answer arrives. The third beat is the thing the visitor is
being asked to connect, and watching it work is what makes "connect once" mean
something.

**Never show internal identifiers.** An earlier version printed
`Called el_get_lineup_stats` in the window. The owner's instruction: technical
detail never appears in the interface a visitor is looking at.

**Section headings are capabilities, not boasts.** They drifted into describing
our data — "We know where every shot was taken" — and the owner stopped it. They
are now questions a person could type: "Ask where the shots came from", "Ask
which five actually work together".

**The shot chart is E2021 game 328**, the 2022 Final Four semi-final, Olympiacos
74-77 Anadolu Efes, pulled read-only from the immutable archive. When all 111
attempts have landed, one card opens over Micic's buzzer three — a minimal
callout with an orange "Game winner" flag — holds five seconds, closes, and does
not come back. Its position is computed from that shot's coordinates.

**The lineup section is two real units one substitution apart.** Fenerbahce,
E2025: the same four players plus Birch are +24.5 over 214 possessions; plus
Baldwin instead, -34.1 over 64. The changing player keeps a fixed row so the
substitution moves one name rather than resorting the list.

**Every number on the page is measured.** They come from the same query
functions the MCP server calls, so the site and a connected assistant cannot
disagree. No placeholder figures remain.

**The ask section is the same window, driven by the visitor.** Chips sit where
the text field would be. Answers are read from `site/data/asks.json` today; the
approved live endpoint is still to be built, and every chip already carries the
`id` it will send.

**One court runs the length of the page.** Two rails are its sidelines, the
circle at mid-page is the centre circle, keys and arcs sit at both ends, and
each section boundary nicks the sideline. This replaced the court that sat in
the hero's corner, and it is what stopped the sections reading as separate pages
stacked on each other.

**Palette and type.** Warm neutrals on a near-white paper; one saturated orange
(`#EA580C`) used for exactly two things, a measured value and the one action
worth taking. Gabarito, Figtree and IBM Plex Mono, self-hosted, sixteen faces,
latin and latin-ext. The page makes zero third-party requests.

## 15b. The lineup section became a floor, 2026-09-04

**What was wrong with it.** The section showed five names in a list and replaced
one of them. The owner's words, reading the built page: the substitution
animation is very bad, it should not happen in one go, and Baldwin and Birch
play different positions so the shape on the floor changes. He was right on the
substance and not only on the animation. A name changing in a list is not the
claim this section makes. The claim is that one change turns a unit from +24.5
to -34.1, and the reason is visible only if you can see that the change takes
the centre off the floor.

**Why it could not be built before.** Positions were not in the warehouse for
this season. `roster_registration` held E2026 only, and of the five players
named here just two are in an E2026 roster - Birch and Melli left the
competition. Loading E2024 and E2025 was done first, as its own task, and is
Decision 53.

**What is measured and what is convention.** Each player's POSITION is the
league's own record: his club's E2025 registration, joined to the game player id
through `person_game_link`. Each player's SPOT on the floor is a convention -
the ordinary arrangement of two guards, two forwards and a centre. The figure
note under the court says exactly that, in those words, because a diagram that
looks measured and is not is worse than no diagram at all.

The source publishes three buckets, Guard, Forward and Center, and nothing
finer. This is therefore not a 1-through-5 reading of a lineup and must never be
drawn as one.

**The shape, which is the whole point.**

| | Guards | Forwards | Centres |
|---|---|---|---|
| Birch on the floor | 2 | 2 | **1** |
| Baldwin on instead | 3 | 2 | **0** |

**Four beats, not one.** Birch leaves and nothing else moves, so what is
happening is unmistakable. The four who stay open up, because there is no longer
a centre to play through, and the paint lights and is labelled empty. Baldwin
arrives into the space at the top. Only then does the number change - after the
reader has been shown why, rather than before.

**Two conditions gate the motion, not one.** On screen and in the visible tab.
A section inside the layout viewport of a background tab still reports itself as
intersecting, so a page opened in a background tab would play its sequences to
nobody and be finished by the time anyone looked. That is the same defect as the
unreachable shot card, wearing a different hat, and both are now handled the
same way.

## 16. What is left

1. **The live endpoint.** Section 6's locked route: an allowlist of question
   identifiers, cached, rate limited. The page is built to switch to it in one
   function.
2. **The Turkish page and the `/tr/` redirect.** The copy must be authored, not
   translated.
3. **R-9.** Section 7 is blocked on it. The site must not go live first.
4. **Fine detail.** The owner has a list and is holding it until v1 is agreed.
5. **A pull request.** `feat/launch-site` has never been reviewed, and merging
   it publishes the site: `pages.yml` republishes on any change to `site/**`.
