STYLE reel-kinetic-01 — bold kinetic typography. Every spoken line is cut into 1–3 "beats": a huge condensed headline (1–3 words per row, ≤ 3 rows, ≤ 14 characters per row) that slams in on a specific spoken word, on a flat full-screen colour pair, with one sticker. The full spoken line appears tiny underneath automatically.

# Length
The voiceover must last about {target_seconds} seconds: write {word_budget} spoken words in total (± 10%). Use short, punchy lines (6–16 words).

# Lines
Each line: {"spk","text","el","emo","pace","gap","beats":[...]}. "text" = exact spoken words in Roman script; "el" = the same words for ElevenLabs v3 with 0–2 audio tags ([calmly] [chuckles] [excited] [whispers] [sighs] [deadpan] [softly] [confident]) and "..." for beats; for Hindi/Hinglish/Bhojpuri write "el" in Devanagari, keep "text" Roman. gap 0.2–0.5.

# Beats
{"word": index of the word in "text" where the beat lands (0 = first word), "big": headline with "\n" between rows, "pair": a pair code from the palette, "sticker": one of none|zzz|cross|check|star|circle|ring|arrow|burst|tape|stack, "label": tiny mono note (≤ 30 chars, optional; for "star" it is the 1–6 letter text inside the star)}
Rules: the headline repeats or sharpens the key words being said, never a different message. Alternate pairs so consecutive beats change colour. cross = wrong/fail, check = right/done, star = punchline, arrow = next step, ring = signal/live, circle = deflating, stack = piles/notes, burst = big finish, tape = warning or final CTA, zzz = lazy/boring.

# Palettes (the chosen palette is fixed; use only its pair codes)
{palettes}

# Output JSON
{"title","slug" (kebab-case),"brand" (tiny top-left topic label, e.g. "SYSTEM DESIGN · BHOJPURI EDITION"),"caption","lines":[...]}
Only state facts the user gave or that are standard; never invent numbers.
