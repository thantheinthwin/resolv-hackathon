# Unboxing Judge: UI design

The approved two-role design (approved 14 Nov 2026). Mockups:
<https://claude.ai/artifact/Wjia1FFmYRZwFUavqofsAX>. Game owns `web/`; build
every screen from this file. Where this file and PLAN.md disagree on data or
limits, PLAN.md wins.

## 1. Character

A calm evidence desk, not a courtroom and not a chatbot. Warm off-white paper,
near-black ink and one accent, gavel yellow. Large editorial headings, small
monospace capital labels, hairline borders, almost no shadow. Short,
reassuring copy that never claims a decision: **"Evidence informs. People
decide."**

## 2. Scope

- Desktop web app for windows **1024 px and wider**. Below that, show one
  line: "Open Unboxing Judge on a computer."
- One exception: a phone-sized upload page reached by scanning a QR code on
  the video step.
- Two demo roles chosen on a role picker, no password: **buyer** and **shop
  owner**.

## 3. Colour tokens

Put these on `:root`. Dark mode follows `prefers-color-scheme` and swaps only
the first six; yellow, red, brown and green stay the same.

| Token | Light | Dark | Use |
|---|---|---|---|
| `--ink` | `#20212d` | `#e6e7dd` | Text, dark buttons, video background |
| `--muted` | `#6b6d72` | `#a1a495` | Secondary text (darker than the prototype's `#797b80` for contrast) |
| `--bg` | `#f5f5f0` | `#161a18` | Page background |
| `--white` | `#fff` | `#202522` | Cards, inputs, header |
| `--line` | `#e4e5de` | `#3a4038` | Hairlines |
| `--soft` | `#fafaf7` | `#252b25` | Quiet panels, table headers |
| `--yellow` | `#ffda50` | same | Primary action, active step, brand mark |
| `--red` | `#b34030` | same | Flagged, tamper, destructive |
| `--brown` | `#875619` | same | Unclear, UNSURE |
| `--green` | `#416a50` | same | Pass, CLEAR |

Supporting: yellow hover `#f4ca31`, focus ring `#b28b00`, selected border
`#d9b625`, yellow tint `#fffae4`. Desk surface `#efefe7`, rules `#d9dbd0`.
State tints: pass `#e0ebdf` / border `#b5cab3`; flag `#f8e4db` / `#edc6ba`;
unclear `#f9efda` / `#e5d5ad`. Error alert `#fff0e9` text `#a2462f`; notice
`#eef5e9` text `#456340`.

## 4. Type

Google Fonts:

| Role | Family |
|---|---|
| Headings, brand | Bricolage Grotesque |
| Body and controls (covers Thai) | Anuphan |
| Labels, timestamps, counters | IBM Plex Mono |

Base 14px/1.6 Anuphan. Page title 40–59px, 600, ends in a yellow full stop.
Step title 30px. Verdict title 34px. Labels 8–10px mono capitals with
0.45–1.2px letter-spacing ("PRODUCT NAME", "02 / WHAT WENT WRONG"). Sentences
in sentence case. Thai text carries `lang="th"`.

## 5. Layout

- **Header**: 87px, white, bottom hairline. Brand on the left (39px yellow
  square, radius 11px, rotated −5°, gavel icon), role tabs or caption in the
  middle, role pill on the right.
- **Main**: max width 1280px, side padding 48px.
- **Buyer screens**: two columns, `minmax(0, 1fr)` and a fixed 338px desk,
  gap 28px. The desk is sticky.
- **Footer**: hairline, mono brand line, "Evidence informs. People decide."
- Radii: cards 13–14px, inputs 8–9px, buttons 6–8px, pills 99px.

## 6. Buyer flow

Role picker → **Your orders** → **Complaint** → **Video** → **Sent** →
**My reports**.

- **Your orders**: table of delivered orders. Product, variant, quantity come
  from the shop's data; the buyer never types the listing. Action per row:
  "Report a problem".
- **Stepper** with three steps: The order, The video, Sent.
- **Complaint**: product recap panel, four claim options in a 2 × 2 grid
  (Wrong item, Something missing, Damaged, Looks fake), optional text in Thai
  or English.
- **Video**: drop zone or preview, privacy note, and the scan-to-upload QR
  panel beside it. Hard limits only block a video: not a video, under 5 s,
  over 2 min, over 50 MB (show these in a mono line). Dark or shaky footage
  is accepted with a brown warning.
- **Sent**: "Sent to the shop." straight after upload. The buyer does not wait
  for the checks.
- **My reports**: table with a status per report (Sent, Being checked, With
  the shop, Shop replied) and the shop's note. **Never the verdict.**
- The right-hand desk stays on every buyer step (without the parcel drawing):
  "THE REVIEW DESK", what happens next, the privacy note.

## 7. Shop owner flow

Header tabs: **Inbox** and **Products**.

- **Inbox**: full-width table, unsure first, then newest. Columns: product and
  order, buyer's claim, verdict, CLEAR or UNSURE tag, confidence, time.
  Undecided rows have a 3px yellow left edge. A case still being checked is
  listed (with live progress) but can't be opened.
- **Case**: a context strip on top with two soft panels, "Ordered" and "Buyer
  said". Then three columns:
  - **Left**: verdict block (title, CLEAR/UNSURE tag), reason in English then
    Thai, confidence bar with a 1px marker at 90%, the four check rows, the
    decision buttons.
  - **Middle**: the video, a timeline scrubber with a 5 × 14px marker per
    finding (click to seek), then evidence pairs: the video frame beside the
    listing photo (or the frames before and after a cut), each with the check
    name, mono timestamp and notes.
  - **Right**: "Under the hood": one row per pipeline step with a status dot,
    name, CODE or MODEL tag, seconds and a one-line output; raw JSON
    collapsible.
- **Decision**: on a clear verdict, Agree or Disagree. On an unsure one, "Side
  with buyer" or "Side with seller". Disagree asks for a reason from a short
  list. Optional note to the buyer. Then "Decision saved" and "Next case".
- **Products**: table, and an add form: name, description (≤ 1,500 chars),
  what is in the box (tags), price, colours and "Size or model" (tags), up to
  3 photos with one required; the first is marked MAIN.
- Orders come from a seed file; there is no order entry screen.

## 8. Wording

| Use | Not |
|---|---|
| Buyer is right | Recommend buyer refund |
| Seller is right | Recommend rejecting claim |
| Unsure: check the video | Insufficient evidence |
| CLEAR / UNSURE tag | Human review required |
| Confidence | Demo score |

Voice: short, plain, second person. "Tell us what went wrong.", "The evidence
starts here.", "Sent to the shop." Headings end with a full stop. Honest small
print: the confidence is a model score, not a calibrated probability; face
blurring can miss faces.

## 9. Components

- **Buttons**: primary is yellow with dark text, min height 45px, radius 8px,
  trailing arrow icon, lifts 1px on hover; one per step. Secondary is ink
  fill, white text. Outline is white with a hairline, for the second choice in
  a pair. Text buttons for back, replace, delete (red). Disabled at 50%
  opacity. Tap targets at least 44px.
- **Claim option**: bordered card with icon, bold label, muted sub-line.
  Selected: `#d9b625` border, inset ring, `#fffbeb` fill, `aria-pressed`.
- **Check row**: 25px round icon, check name, mono status on the right.
  The four checks always in this order: Parcel seal, Listing match, Product
  damage, Video continuity.

  | State | Icon | Label |
  |---|---|---|
  | waiting | number 01–04 | WAITING |
  | running | spinner on yellow | CHECKING |
  | pass | tick on green tint | CLEAR |
  | flag | flag on red tint | FLAGGED |
  | unclear | alert on brown tint | UNCLEAR |

- **Tags**: CLEAR (green on its tint), UNSURE (brown on its tint), tamper
  flags (red on its tint), waiting (muted on the desk colour).
- **Tables**: mono capital header row on `--soft`, hairline dividers.
- **Tag input**: tags with a dashed "+ Add" tag.
- **Photo grid**: dashed "+ Add photo" tile; first photo marked MAIN.
- **Alerts**: icon, message, dismiss. Errors use `role="alert"`, notices
  `role="status"`.
- **Progress**: live check rows fed by the server-sent events, in an
  `aria-live="polite"` region.
- **Icons**: Lucide outline, 12–30px: Gavel, ArrowRight, ArrowLeft, Check,
  Flag, CircleAlert, Package, PackageOpen, Upload, Video, ScanLine,
  ShieldCheck, Play, Trash2, X, QrCode.

## 10. Phone upload page

Phone width, one column, 16px gutters. Brand mark, "Upload your unboxing
video.", the order recap, one big "Choose video" button (opens the camera
roll), the limits line, a progress bar, then "Done. You can close this page."
The desktop video step updates by itself when the upload finishes.

## 11. Motion and accessibility

- Primary button 0.15s lift; spinner 1s; progress bar 0.4s width transition.
- `prefers-reduced-motion: reduce` turns off all animation, and video seeks
  jump.
- Real buttons, links, labels and inputs. Focus ring 3px `#b28b00`, 4px
  offset, on everything interactive. `aria-current="step"` on the stepper.
  Frame thumbnails have alt text with the timestamp.
