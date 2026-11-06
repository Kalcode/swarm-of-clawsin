# Audio credits

Every sound has a synthesized voice in `web/sound.js` (Web Audio noise, oscillators and envelopes), so a fresh clone
plays without any audio files.

On the owner's machine the viewer prefers recorded samples from the "Universal Sound Effects" packs by **ElvGames &
Pegonthetrack** (Achievements 1, Brewing and Alchemy, Crafting and Tinkering, Footsteps 2 and 3, Magic and Spells 3
and 4, User Interface Pack 4). The owner bought these packs and holds the license. `scripts/extract_sfx.py` builds a
curated set of clips from them into `web/assets/sfx/`, which is gitignored: the clips and the packs are never committed
or redistributed. When the clips are there, the viewer's footer and About panel show "Sound: ElvGames &
Pegonthetrack".
