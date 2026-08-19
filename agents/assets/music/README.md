# Reel music beds

Drop audio files in here and every rendered reel gets a bed under it. Nothing
is generated and nothing is fetched — **music licensing is your call, not the
pipeline's**, so the pipeline only ever plays files you put here.

## Why this matters

Measured on four delivered reels before the audio finishing pass existed:

| reel     | integrated | true peak | range   |
|----------|-----------:|----------:|--------:|
| 0903e649 | −19.9 LUFS |  −2.4 dB  | 20.3 LU |
| 70036111 | −34.8 LUFS | −12.5 dB  | 17.1 LU |
| 914edae5 | −42.6 LUFS | −22.8 dB  | 26.9 LU |
| d15857a0 | −43.0 LUFS | −16.3 dB  | 21.4 LU |

The platform target is −14 LUFS. Every reel now lands there whether or not a
bed exists — but the only audio a reel carries without one is whatever
ambience the video model generated, lifted by up to 36 dB. That lift also
lifts its noise floor. A bed is what makes the result sound *made* rather
than *recovered*, and it is the difference a viewer notices first.

## Layout

```
assets/music/
  warm/      *.mp3 *.m4a *.wav *.opus *.ogg *.flac
  upbeat/
  calm/
  bold/
  elegant/
  <loose files here are the fallback pool>
```

The five folder names are the closed vocabulary in
`workflows/video/nodes.py:MUSIC_MOODS`. The shot planner picks one per reel;
if that folder is empty or missing, the loose files at the top level are used
instead. With nothing anywhere, the reel ships with its diegetic audio
normalized and `audio_finish` records that no bed was available.

## What the pipeline does with a track

- loops it to cover the full runtime, so a 12 s track under a 32 s reel does
  not leave two thirds bare
- sets it to −18 dB under real diegetic audio, or −6 dB when it carries the
  reel alone
- fades 0.6 s in and 1.2 s out
- normalizes the finished mix to −14 LUFS with a true-peak ceiling

So tracks do **not** need to be pre-levelled, trimmed to length, or faded.
Anything from roughly 10 seconds up works.

## Choosing files

- One file per mood is enough to start; more means consecutive reels for the
  same brand do not repeat. Selection is deterministic per calendar item, so
  re-rendering a reel keeps its bed rather than shuffling the soundtrack
  under a reviewer who already approved it.
- Instrumental. Anything with a vocal competes with the burned-in copy.
- Avoid tracks with a hard intro hit — the reel opens on the hook, and the
  0.6 s fade is short.
