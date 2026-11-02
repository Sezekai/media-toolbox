# Design: Media Toolbox

Status: version 5, compact dark. Version 3 sizes, no sideways scrolling anywhere, Ubuntu type, a chosen accent colour, and a sidebar that shows labels or collapses to icons. Functionality is unchanged.

## Mode

Operate. The owner completes file tasks: choose a folder, set options, run, review the results, act on them. Scanability and consistency outrank expression.

## Scene

One person at a Windows PC working through long lists of files and video copies. The screen should be mostly results; controls stay small, aligned and predictable.

## One look

Everything comes from `theme.py`. The only choice is the accent colour (12 presets or any colour), set from the sidebar and remembered.

- Colours: ground #111214, panels #18191c, raised controls #202226, fields and lists #0d0e10, hairlines #2a2c31. Text #e8eaed, secondary #9aa0a8, faint #6c727b. One accent, blue #4a9eff by default; text on it is white, regular weight. Hover, selection and the active tool are derived from the accent. Danger #e5484d, used only by Delete. Selected rows #1d3557.
- Accent jobs only: the primary button, selection, progress, focus, the active tool and the "Best copy" tag.
- Type: Ubuntu (Segoe UI if Ubuntu is missing), 13 px body, 12 px captions and column headers, 15 px page titles. Ubuntu Mono only in the log.
- Icons: one outline set on a 24-unit grid, same stroke, round ends, drawn in code.

## Sizes

- Every button, text box, drop-down and spin box is 28 px tall. List rows are 24 px.
- Gaps: 8 px between controls and panels, 10 px inside panels, 12 px around the page.
- Corners: 5 px on controls, 7 px on panels. No shadows.
- Field labels share one 88 px column, so text boxes line up from row to row and page to page.

## Layout

- Sidebar on the left: 176 px with the tool names, or 44 px with icons only (names on hover). Collapse / Expand and Accent colour sit at the bottom. The choice is remembered.
- Page header is one line: the title, then what the tool does, cut short with "..." if the window is narrow.
- Tool bar: row one is the main folder and the main button at the right; row two is the second folder or the options.
- Results panel takes all the remaining height. A summary sits on the left above the list and the list's own buttons on the right.
- Lists never scroll sideways: the first column takes the spare width; other columns keep their width and can be dragged.
- Status bar (36 px) with the job, progress and Log. The log is a drawer that opens by itself on an error.
- No sideways scrolling, ever. When something cannot fit, it wraps or scrolls up and down. The smallest window is worked out from the content (about 1140 px wide with labels, 1010 px collapsed), so every page always fits; pages are checked at that size, 1280 and 1920 wide in both sidebar states.

## Duplicate videos

- Tool bar: mode, then the folder (or library and Add videos), with Cancel and Scan at the right.
- Left column (290 px, fixed): matching options and the engine. Long explanations live in tooltips. It scrolls up and down only.
- Groups list with filter and sort, then Keep, Delete, Move, Ignore and a More menu (open, show in Explorer, open clip).
- Compare copies: a header with the size slider at the right; cards wrap onto new rows and the area scrolls up and down; a card is never wider than the area; with nothing selected, a centred placeholder.
- Copy card: 16:9 preview, name, folder, a "Best copy" tag when it is, then the details as a two-column list. Ctrl + wheel or the slider scales the whole card.

## Not in this world

Theme pickers beyond the accent colour, gradients, glass, glows, shadows, coloured side borders, kicker labels, decorative monospace, illustrated empty states.
