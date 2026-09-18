# Token Plan — BIS Standards Registry (Reskin)

## Concept
"Standards registry" — BIS certification marks, licence numbers, gazette schedules, not generic chatbot. Every token decision ties to BIS material: Paper is gazette stock, Ink Navy is document ink, Seal Brass is hallmark karat, Verified Green is cited/grounded, Alert Rust is ungrounded/abstained.

## Color — Meaningful, not decorative
- **Ink Navy #1B2A41** — headings, primary text, header letterhead rule. Contrast on Paper: 12.5:1 (passes AAA). Used for masthead, H1, registry titles.
- **Paper #F3F2ED** — page background. Greyer than #F4F1EA warm-cream AI default. Chosen to avoid AI-cream tell.
- **Slate #5B6472** — secondary, metadata, timestamps, docket log. Contrast on Paper: 6.2:1 (AA). Not pure grey.
- **Seal Brass #A9822F** — *only* for certified/verified state: grounded citation indicator left rule, active language, verified stamp fill, recording pulse ring. Not on generic buttons. Contrast 7.1:1 on Paper for text is borderline, so use for **border/fill + white text** on stamp (passes), not body text on Paper.
- **Verified Green #2F6E51** — grounded/cited badge fill, citation schedule header. Muted, not neon. White text contrast 7.8:1.
- **Alert Rust #9C4221** — ungrounded/abstained/error, fallback indicator. White text contrast 6.9:1.

**Avoid-review:** No bright accent everywhere — Seal Brass appears <8% of pixels, only where "certified/verified". No gradient washes — flat Paper + 1px hairline rules (#D8D5CF, 1px) instead of shadows. No grey box-shadows on every card — cards have 1px border + no shadow, only header letterhead has subtle rule.

## Type
- **Serif — Source Serif 4 (400,600,700)** — headings, registry entry titles, citation schedule headings. Evokes gazette/regulatory text. Loaded: `Source Serif 4:wght@400;600;700`.
- **Sans — Public Sans (400,500,600)** — body, UI, labels, docket, buttons. Designed for USWDS government services, matches BIS brief. Loaded: `Public Sans:wght@400;500;600`.
- **Scale:** 11px meta / 13px docket / 14px body / 17px H1 (masthead) / 20px registry title. Weights: 600 for headings, 500 for labels, 400 body. Two typefaces max, distinct roles.
- **Avoid-review:** Not defaulting to Inter (AI tell). No monospace for small data labels — use Public Sans 11px uppercase 0.06em tracked only for schedule head, not everywhere. No ALL-CAPS eyebrow above every heading — only one small “SCHEDULE” label in citations, justified as document structure.

## Layout & Structure
- **Header — letterhead bar:** Full-width Paper with Ink Navy 3px top rule + 1px bottom rule, masthead: “Bureau of Indian Standards” 11px Public Sans tracked 0.12em + “Intelligent Assistant  SIH26107” in Source Serif 4 17px. Not floating app title. Right: health as small “● online” with Slate, no pill.
- **Two-column under header:** Left rail `280px` (collapses to top on <900px) — **docket/log**: running queries as case entries with left Brass rule when grounded, Rust rule when ungrounded, numbered 01,02… with type (`standard_lookup`) in Slate 11px, timestamp 11px, query text 13px. Not chat bubbles.
- **Main panel:** Single `submission` control group (language select + textarea + mic + Ask) with shared Paper border, not scattered. Below: **registry entry** — status as **stamp badge**: `VERIFIED` (Verified Green fill, white, 2px double border, slight rotation 0.5deg, letter-spacing 0.08em) vs `ABSTAINED` (Alert Rust). Citations as **Schedule**: numbered `1.` with left Brass 3px rule, source title in Source Serif 4 13px, URL in Public Sans 12px, not generic chips. Answer body as clause-style with 14px Public Sans, 1.6 line-height, left 12px padding when cited.
- **Responsive:** Header stacks, rail becomes top docket on mobile (no horizontal scroll), textarea mic stays inside, grid collapses to single column at 900px (already flex-col, now with rail on top).
- **Motion — one deliberate moment:** Recording pulse (red ring with `ping` on mic, `prefers-reduced-motion` disables) and **citation reveal** (`details[open]` with `grid-template-rows 0fr→1fr` 220ms, no fade-everything-on-scroll).

## Principles
- Flat, hairline borders; no rounded-card grey shadows on every element (cards have `radius: 8px` sharp, not `12px` soft everywhere).
- No `Label — text` chrome with spaced em-dash — use `:` or line break.
- No arrow-suffixed buttons (`Listen →`) — use `🔊 Listen` / `⏹ Stop` as spec, no `→`.
- Focus: 2px Seal Brass outline + 3px Paper offset, visible.

## Review vs Avoid-List (what changed)
- Before: warm-cream `#F8FAFC`, Inter, `rounded-2xl` soft shadows, `ALL-CAPS` eyebrow, `Label — text`, monospace 11px, `→` on buttons, Seal Brass on every button.
- Now: cooler Paper `#F3F2ED`, Public Sans + Source Serif 4, `8px` radius + 1px hairline (no shadow), `Schedule` label only in citations (justified), `:` not `—`, Public Sans for labels, no arrows, Seal Brass only on verified stamp/citation rule/recording pulse.
- Contrast verified: Ink Navy/White passes, Seal Brass used as fill+white text (not Paper text), Verified Green/Alert Rust as fills.
