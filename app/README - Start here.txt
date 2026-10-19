TEKKEN APP: START HERE
======================

This folder is the whole thing: site, live poller, stream overlay, GitHub sync and Session Gallery.
The old overlay folder (D:\SW-T8\overlay) is retired. Nothing else needs to run.

START / STOP
  Start Tekken App.bat             Starts the app. Its window IS the poller: keep it open (minimized is fine).
  Start with Windows (on-off).bat  Starts the app by itself at login. Double-click again to turn off.

OPEN (the app must be running)
  Open Stage Tracker.url           Stage data + matchup guides
  Open Session Gallery.url         Run reviews, browse saved ones
  Open Scoreboard.url              Full off-stream scoreboard (live)

STREAMLABS (Browser source, Local file UNticked, 700 x 56)
  http://localhost:8787/overlay.html?layout=strip&anchor=bottom&scale=1.25

LEAVE THESE ALONE
  ewgf-key.txt, github-token.txt   Your keys (never uploaded)
  data\, reviews\, site\           Your games, reviews and the website (kept in sync with GitHub)
  *.py, queue.md                   The app itself
  app-log.txt                      What the app window printed; send it to Ledger if something looks off
