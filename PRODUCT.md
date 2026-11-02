# Product

<!-- impeccable:product-schema 1 -->

## Platform

Windows desktop (a PySide6 desktop app, packaged as a single portable .exe). This is not one of the four schema values (web, ios, android, adaptive), so the platform reference cannot be inferred from it; treat the design language as desktop Windows.

## Users
The app's owner, on their own Windows PC, for everyday file tasks on their own media. The app is for personal use; there is no other audience confirmed.

## Product Purpose
Media Toolbox bundles small, everyday file tools in one window: finding and sorting videos, making GIFs, zipping folders, converting images and copying folder structures, plus finding duplicate videos. Success means each tool does its job quickly and safely, and nothing is permanently deleted without a trace.

## Positioning
One portable program that gathers several small file tools behind a single sidebar, with a shared activity log and a Recycle-Bin-only rule for removals. Unlike a folder of separate scripts, every tool shows what it is doing and can be undone through the Recycle Bin.

## Operating Context
Used on the owner's Windows PC, usually with folders on local drives. Long-running jobs (scans, conversions, the duplicate engine) run in the background and report progress and errors in the shared log. The duplicate tool downloads its detection engine (vdf-cli) and FFmpeg at runtime into the app data folder; neither is bundled.

## Capabilities and Constraints
- Tools: Silent videos, GIF maker, Zip subfolders, WebP to JPG, Copy folder structure, Duplicate videos.
- Removals go to the Recycle Bin and are logged; nothing is permanently deleted.
- Must stay a single portable .exe built with PyInstaller (see build.bat and the GitHub Actions workflow).
- Must keep the existing tools working; new tools are added alongside them.
- One fixed compact dark look; the owner chose to drop theme, font and size options.
- The duplicate engine is AGPLv3 and is never bundled in the repository or the .exe.
- Undecided: none recorded.

## Brand Commitments
None confirmed beyond the app name, Media Toolbox.

## Evidence on Hand
No testimonials, customers or benchmarks exist. Reference screenshots the owner has shared earlier are design references for the look, not product evidence.

## Product Principles
- Every tool is safe to use: removals go to the Recycle Bin, and each action is logged.
- Long jobs never freeze the window: they run in the background and show progress and errors in the log.
- Every tool is reachable from one sidebar, and the window layout stays under the user's control.
- Nothing is downloaded or installed without the user asking for it.
