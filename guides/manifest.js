// Anti-character guide index — read by index.html (Matchup Guides tab).
// The weekly scheduled task appends one entry here per new guide.
//
// Fields:
//   character  Display name, must match queue.md
//   file       Path to the standalone guide, relative to index.html
//   artifact   claude.ai artifact link (optional)
//   tags       The guide's title tags — the one-line takeaways
//   step       Recommended step direction from the Movement section
//   record     Your ranked record vs this character as Victor when the guide was built
//   added      Date the guide was added (YYYY-MM-DD)

window.GUIDES = [
  {
    character: 'Victor',
    file: 'guides/Anti-Victor.html',
    artifact: 'https://claude.ai/artifact/Ca1pDa973nyEWx5aSGu5yb',
    tags: ['SW Right', 'HS tracks Right'],
    step: 'SSR',
    record: { w: 7, l: 4 },
    added: '2026-10-03'
  },
  {
    character: 'Bob',
    file: 'guides/Anti-Bob.html',
    artifact: 'https://claude.ai/artifact/YJUB7HN8ZEGS1KDZ18rvTj',
    tags: ['SW Right'],
    step: 'SSR',
    record: { w: 10, l: 7 },
    added: '2026-10-03'
  },
  {
    character: 'Jin',
    file: 'guides/Anti-Jin.html',
    artifact: 'https://claude.ai/artifact/BNi1BSSZkcwtqFYDBPaE7d',
    tags: ['SSR/SWR Default', 'EWHF +5~6 oB'],
    step: 'SSR',
    record: { w: 9, l: 16 },
    added: '2026-10-03'
  },
  {
    character: 'Lili',
    file: 'guides/Anti-Lili.html',
    artifact: 'https://claude.ai/artifact/K1qur7ndKEd2GS4UdBPzAE',
    tags: ['SSR Default', "Don't Step Backturn"],
    step: 'SSR',
    record: { w: 14, l: 8 },
    added: '2026-10-03'
  },
  {
    character: 'Dragunov',
    file: 'guides/Anti-Dragunov.html',
    artifact: 'https://claude.ai/artifact/1gmUFPVEz5QFA1usycxZyQ',
    tags: ['SSR', 'Tackles Whiff Left'],
    step: 'SSR',
    record: { w: 11, l: 20 },
    added: '2026-10-03'
  },
  {
    character: 'Miary Zo',
    file: 'guides/Anti-Miary-Zo.html',
    artifact: 'https://claude.ai/artifact/2T3hxEtHjXjBAX354XBeY3',
    tags: ['Duck BAO.1', 'Heat Smash → BAO +6'],
    step: 'SSL',
    record: { w: 9, l: 9 },
    added: '2026-10-03'
  },
  {
    character: 'Hwoarang',
    file: 'guides/Anti-Hwoarang.html',
    artifact: 'https://claude.ai/artifact/ER1nkNzao69aH8qdtMV4zE',
    tags: ['SSR Default', "Flamingo Can't Block"],
    step: 'SSR',
    record: { w: 10, l: 13 },
    added: '2026-10-03'
  },
  {
    character: 'Heihachi',
    file: 'guides/Anti-Heihachi.html',
    artifact: 'https://claude.ai/artifact/GC1pfnnGpScaqrFqKQN5KP',
    tags: ['SSL', 'Heat Smash +10 → RAI'],
    step: 'SSL',
    record: { w: 8, l: 2 },
    added: '2026-10-03'
  },
  {
    character: 'Eddy',
    file: 'guides/Anti-Eddy.html',
    artifact: 'https://claude.ai/artifact/CN6GVKPDe86j4TUPYBmHN2',
    tags: ['SSR', 'Mids Beat RLX', "HSP Can't Block"],
    step: 'SSR',
    record: { w: 7, l: 5 },
    added: '2026-10-09'
  },
  {
    character: 'Zafina',
    file: 'guides/Anti-Zafina.html',
    artifact: 'https://claude.ai/artifact/GmJL19EM42iz5mrvguwuqK',
    tags: ['SSR Default', 'PC Scarecrow', 'Duck Heat Smash'],
    step: 'SSR',
    record: { w: 0, l: 4 },
    added: '2026-10-09'
  }
];
