# Design: Media Toolbox

Status: version 3, compact dark. The owner asked for one cohesive, compact dark layout that gives the most room to the lists and previews, with the theme, font and size options removed. Functionality is unchanged.

## Mode

Operate. The owner completes file tasks: choose a folder, set options, run, review the results, act on them. Scanability and consistency outrank expression.

## Scene

One person at a Windows PC working through long lists of files and video copies. The screen should be mostly results; controls stay small, aligned and predictable.

## One look

There are no themes, fonts or sizes to choose. Everything comes from `theme.py`.

- Colours: ground #111214, panels #18191c, raised controls #202226, fields and lists #0d0e10, hairlines #2a2c31. Text #e8eaed, secondary #9aa0a8, faint #6c727b. One accent, blue #4a9eff (text on it #08111f). Danger #e5484d, used only by Delete. Selected rows #1d3557.
- Accent jobs only: the primary button, selection, progress, focus, the active tool and the "Best copy" tag.
- Type: Segoe UI Variable / Segoe UI (Windows' own face), 13 px body, 12 px captions and column headers, 15 px page titles. Monospace only in the log.
- Icons: one outline set on a 24-unit grid, same stroke, round ends, drawn in code.

## Sizes

- Every button, text box, drop-down and spin box is 28 px tall. List rows are 24 px.
- Gaps: 8 px between controls and panels, 10 px inside panels, 12 px around the page.
- Corners: 5 px on controls, 7 px on panels. No shadows.
- Field labels share one 88 px column, so text boxes line up from row to row and page to page.

## Layout

- Icon rail (52 px) on the left; tool names appear on hover.
- Page header is one line: the title, then what the tool does, cut short with "..." if the window is narrow.
- Tool bar: row one is the main folder and the main button at the right; row two is the second folder or the options.
- Results panel takes all the remaining height. A summary sits on the left above the list and the list's own buttons on the right.
- Lists never scroll sideways: the first column takes the spare width; other columns keep their width and can be dragged.
- Status bar (36 px) with the job, progress and Log. The log is a drawer that opens by itself on an error.
- Smallest window 1024 x 620. At that size every page fits; nothing scrolls sideways.

## Duplicate videos

- Tool bar: mode, then the folder (or library and Add videos), with Cancel and Scan at the right.
- Left column (290 px, fixed): matching options and the engine. Long explanations live in tooltips. It scrolls up and down only.
- Groups list with filter and sort, then Keep, Delete, Move, Ignore and a More menu (open, show in Explorer, open clip).
- Compare copies: a header with the size slider at the right; cards top-aligned in a row; with nothing selected, a centred placeholder.
- Copy card: 16:9 preview, name, folder, a "Best copy" tag when it is, then the details as a two-column list. Ctrl + wheel or the slider scales the whole card.

## Not in this world

Theme pickers, gradients, glass, glows, shadows, coloured side borders, kicker labels, decorative monospace, illustrated empty states.
