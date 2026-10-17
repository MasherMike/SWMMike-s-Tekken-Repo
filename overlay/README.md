# Stream overlay

A small panel for OBS that shows your current session live: record on the
character you're playing, recent results, current streak, and who you've
played. It updates within about a minute of each game ending.

## One-time setup (about 10 minutes, on your streaming PC)

1. **Get the folder onto your PC.** On the repo's GitHub page, click
   **Code → Download ZIP**, unzip it, and copy the `overlay` folder somewhere
   permanent, such as `Documents\TekkenOverlay`.
2. **Add your API key.** In that folder, create a text file named
   `ewgf-key.txt` and paste your EWGF key into it (it starts with `ewgf_`).
   In Notepad, choose *Save as type: All files*, or Windows saves it as
   `ewgf-key.txt.txt` and the poller won't find it.
   This file stays on your PC; it is never uploaded.
3. **Test the poller.** Double-click `start-overlay.bat`. A window opens and,
   within a few seconds, prints a line like
   `[7:27:06 PM] 100 battles, newest ... | pro tier, 97 requests left this hour, next check in 40s`.
   If Windows shows a blue "Windows protected your PC" box, click
   **More info → Run anyway** (it's a local script you can read in Notepad).
4. **Add it to OBS.** In your scene: **Sources → + → Browser**.
   Tick **Local file**, browse to `overlay.html`, and set **Width 380, Height 300**.
   Drag the panel where you want it. The background is transparent.

## Every stream

Double-click `start-overlay.bat` before you go live and leave its window open
(minimized is fine). Close it when you're done.

## Options

To change what the overlay shows, untick **Local file** in the Browser source
and type the file address with options instead, for example:

```
file:///C:/Users/YOU/Documents/TekkenOverlay/overlay.html?modes=ranked&scale=1.2
```

| Option | What it does | Default |
|---|---|---|
| `modes` | Which modes count: `ranked`, `quick`, `player`, `group`, comma-separated | all modes |
| `scale` | Size multiplier | 1 |
| `opps` | Opponent rows shown | 4 |
| `dots` | Recent results shown | 10 |
| `gap` | Minutes without a game that start a new session | 45 |

## What the footer means

| Footer | Meaning |
|---|---|
| Updated 20s ago | Working normally |
| Not updating · is start-overlay.bat running? | The poller window was closed or the PC slept |
| ewgf.gg not responding, retrying | ewgf.gg is down or slow; the last data stays on screen |
| Hourly ewgf.gg limit reached · back at 10:10 PM | The hourly request allowance ran out; the poller waits until it resets |

## Request limit

ewgf.gg allows a set number of requests per hour (currently 100 on this key)
and reports how many are left with every reply. The poller spreads what's left
evenly over the rest of the hour, never checks more often than every 30
seconds, and keeps a few requests spare for the hourly GitHub collector.

ewgf.gg's own "resets at" time is currently wrong (it returns the time of the
request), so the poller works out the hour itself: when the count jumps back
up, a new hour has started. Until it has seen that, it assumes a full hour is
left, so it errs on the side of checking less often. If it ever does run out,
it waits exactly as long as ewgf.gg says and carries on.

## Log file

The poller keeps a copy of everything it prints in `poller-log.txt`, next to
it: every check, every "hourly limit reached" pause, and every connection
error, each with the date and time. It keeps the newest 2,000 lines (about two
weeks of streaming) and trims older ones when it starts. The file stays on your
PC and is never uploaded. Open it in Notepad any time, for example to show the
ewgf.gg developer exactly when limits were hit.

## Privacy

The poller keeps only what the panel shows: characters, ranks, results and
round scores. Opponent names and IDs are never written to disk.
