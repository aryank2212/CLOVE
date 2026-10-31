# CLOVE design

One look for every CLOVE surface. It is the CLOVE island's window (`~/Projects/clove-island`,
`windows/src/hub/hub.css`), and everything else follows it:

| Surface | Where |
|---|---|
| The island's window (hub): Assistant, Flow and Notch pages | `clove-island/windows/src/hub/` |
| The CLOVE window (Assistant pages in the hub, or its own Chrome window) | `ui/clove.css`, `ui/clove.js` |
| The Chrome extension's popup | `chrome_extension/popup.html` |
| The island's CLOVE pill and chat provider | `clove-island/windows/src/island/agents.ts`, `src/core/providers.ts` |

Dark only: the brand is OLED black. There is no light theme to keep in step.

## Colour

| Token | Value | Use |
|---|---|---|
| `--bg` | `#000` | the window and its sidebar |
| `--panel` | `#0e0f11` | the rounded panel holding the pages |
| `--card` | `#18191c` | cards, the message box, the palette |
| `--field` | `#1f2024` | text fields |
| `--line` | `rgba(255,255,255,.07)` | every border and divider |
| `--text` / `--body` | `#f5f6f8` / `#e1e3e6` | titles / reading text |
| `--secondary` / `--muted` | `#8e939c` / `#6b7079` | details / timestamps, group labels |
| `--accent` | `#fb923c` (hover `#fdab63`, text on it `#170c04`) | the CLOVE orange: primary buttons, CLOVE's name, live state, sparklines |
| `--ok` `--warn` `--crit` | `#34d399` `#f7b32b` `#ff453a` | health only, always with a word next to the dot |
| switch on | `#22c55e` | the island's switches |

Each page's band has its own colour, glowing in its top-right corner: Conversation `#FB923C`, Activity `#3B9EFF`,
Systems `#34D399`, Preferences `#8E939C` (the hub's own pages keep theirs, `hero.ts` THEMES).

## Type

- Interface: `system-ui` stack, 13px body, 13.5px navigation and row titles, 14px conversation.
- Band titles 26px bold (22px on compact bands), tight tracking. No other large headings.
- Group and section labels: 10.5–11px bold uppercase, `.12em` tracking, `--muted`. Only these are uppercase.
- Monospace only for code, commands, paths, model names and identifiers.
- Numbers that change (times, percentages, sizes): tabular figures.
- The wordmark "CLOVE": Eurostile Extended Bold when installed (commercial, not shipped), else Michroma (SIL OFL,
  shipped as `ui/fonts` and the island's `public/fonts`), 15px, `.1em` tracking.

## Shape and space

Radii: panel 22, band 18, card 14, button 10, field and nav item 9, small tag 5. Nav items and buttons are 32px
high. Page padding 22–26px; cards 14–16px inside; 8px between a label and its card.

## The mark

Four sepals around a bud, in a state ring. Drawn by `drawCloveMark` (island, `src/mochi/engine.ts`) and `drawMark`
(`ui/clove.js`) with the same geometry; the ring takes the state colour: orange, amber while a plan waits for
approval, grey when nothing is connected. On the Conversation band it is CLOVE's presence (see README › Window).

## Motion

140ms for hovers, 220ms for things appearing. The bands' particles and the mark animate only while on screen and
the window is shown; with "Reduce motion" or the system setting they are drawn once and stay still.

## Words

Say what happened and what to do next ("Not connected to CLOVE: the setting was not saved."). No exclamation marks,
no "Oops", no invented numbers: anything unavailable says so.
