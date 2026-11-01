# Design: Media Toolbox

Status: replacement world, usability first. Recorded after the design roll ran degraded (no network, no challengers). The owner chose a usability-first redesign over a degraded hand.

## Mode

Operate. The visitor completes a file task (choose folder, check options, run, review results, act). Scanability, consistency and native expectations outrank expression.

## Scene

One person on a Windows PC, in daylight or evening light, switching between several small file jobs. They want to find the control, start the job, see progress, and undo nothing by accident. Dark is the default because the owner chose it, and the scene allows it.

## World

"Graphite workbench": a calm, cool graphite instrument. Surfaces are near-neutral and layered only by one step of lightness. A single blue accent marks what the user can act on: the primary action, the selected row, progress and keyboard focus. Nothing decorative: no gradients, glows, illustrations or shadows.

## Colour strategy

Restrained. Tinted neutrals for every surface, one accent (blue) at under 10% of the screen. State colours are used only where they carry meaning: red for delete and failure, the accent for progress and selection.

Palette (Graphite, the default theme): ground #101113, sidebar #16171a, cards #1d1e22, field #141517, hairline #2e3036, text #eef0f4, muted text #9ba1ad (about 6.5:1 on cards), accent #3b9cf0, text on accent #06121f, danger #c0392b, selection #1f3550.

## Type

Inter (bundled), with the system fallback Segoe UI. Scale 12 / 14 / 16 / 24 px. Body 14 px. Headings are bold, not larger than 16 px inside a card. Page titles 24 px. Tabular numbers in counts and sizes.

## Density

Compact. Table rows 26–28 px. Control height at least 30 px. Gutters 14–16 px inside cards, 12 px between cards. Cards use a 10 px radius and a one-pixel hairline, with no shadow.

## Controls

- One primary (filled accent) action per panel: Scan, Move, Convert, Copy, Zip.
- Secondary: filled neutral. Text buttons are not used for actions.
- Destructive: red, and only for Delete. Removals still go to the Recycle Bin and are logged.
- Focus: a one-pixel accent border on every control, so keyboard users can see where they are.
- Disabled: muted text on the neutral fill.

## Signature

The status line under the page: the running job's name, a progress bar in accent, and the log. It is the only persistent element that moves, so the owner always knows whether something is running.

## Layout rules

- Sidebar: tools with icons and labels; the active tool has a neutral lift and bold text. No section kicker above the tool list.
- Each tool page: title, one-sentence purpose, then the setup card, then the action row, then the results.
- The results list fills the remaining height. Columns stay resizable and remembered.
- Ctrl + wheel zooms the comparison area. Setup columns scroll with the wheel.

## Honest risk

Without the roll there is no challenger check, so this world is a sensible default rather than an argued-for one. It may look close to other dark utilities. That is accepted, because the owner asked for things to work without friction.

## Not in this world

Gradients, glass, neon, illustrated empty states, coloured left borders on cards, shadows, kicker labels, monospace as decoration. The log stays monospace because it holds paths and numbers.
