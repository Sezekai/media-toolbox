# Product

<!-- impeccable:product-schema 1 -->

## Platform

Windows desktop (a PySide6 desktop app, packaged as a single portable .exe). This is not one of the four schema values (web, ios, android, adaptive), so the platform reference cannot be inferred from it; treat the design language as desktop Windows.

## Users
The app's owner, on their own Windows PC, for everyday file tasks on their own media. The app is for personal use; there is no other audience confirmed.

## Product Purpose
Media Toolbox bundles small, everyday file tools in one window: finding and sorting videos, making GIFs, zipping folders, converting images and copying folder structures, plus finding duplicate videos. Success means each tool does its job quickly and safely, and nothing is permanently deleted without a trace.

## Positioning
One portable program that gathers several small file tools behind a single side rail, with a shared activity log and a Recycle-Bin-only rule for removals. Unlike a folder of separate scripts, every tool shows what it is doing and can be undone through the Recycle Bin.

## Operating Context
Used on the owner's Windows PC, usually with folders on local drives. Long-running jobs (scans, conversions, the duplicate engine) run in the background and report progress and errors in the shared log. FFmpeg is bundled in the .exe. The duplicate tool downloads its detection engine (vdf-cli) when asked, into Models\vdf-cli beside the app folder, and copies the bundled FFmpeg into Models\ffmpeg for it.

## Capabilities and Constraints
- Tools: Silent videos, GIF maker, Zip subfolders, WebP to JPG, Copy folder structure, Duplicate videos.
- Removals go to the Recycle Bin and are logged; nothing is permanently deleted.
- Must stay a single portable .exe built with PyInstaller (see build.bat and the GitHub Actions workflow).
- Must keep the existing tools working; new tools are added alongside them.
- The look follows the suite's DESIGN.md: Obsidian background, Lime → Teal accent, Inter, with the Look screen for changing and saving themes. "Media Toolbox classic" keeps version 1's look as a saved theme.
- The duplicate engine is AGPLv3 and is never bundled in the repository or the .exe.
- Follows Sezekai/app-standards (copies in STANDARDS.md and DESIGN.md), with the exceptions below.
- Undecided: none recorded.

## Exceptions to the suite standards
- Keep the best copy where it is. The suite's rule for duplicates is "keep the best, bin the rest". Here the best copy never moves; the other copies can be sent to the Recycle Bin, moved (with Undo), or kept by ignoring the group. Moving a whole group moves every copy into its own folder.
- Duplicates keep three columns (what to match, the groups, the copies side by side) and the copy cards, instead of the suite's single list and Gallery. Only the colours and the Best copy tag follow the suite.
- No count badges on the rail; the rail only shows a dot when the duplicate engine isn't installed.

## Viewer decisions
- Silent videos, WebP to JPG and GIF maker show their files as a collection with List, Grid and Gallery views, a folder tree with counts, sorting and a size slider. List is the default for videos, Grid for pictures.
- Gallery shows one item with nothing drawn over it and a 300 px side panel. Only one video plays at a time; volume is remembered; videos always start from the beginning.
- Silent previews play on duplicate cards while the pointer rests on them (Settings can turn this off; safe mode turns it off).

## Brand Commitments
None confirmed beyond the app name, Media Toolbox.

## Evidence on Hand
No testimonials, customers or benchmarks exist. Reference screenshots the owner has shared earlier are design references for the look, not product evidence.

## Product Principles
- Every tool is safe to use: removals go to the Recycle Bin, and each action is logged.
- Long jobs never freeze the window: they run in the background and show progress and errors in the log.
- Every tool is reachable from one side rail, and the window layout stays under the user's control.
- Nothing is downloaded or installed without the user asking for it.
