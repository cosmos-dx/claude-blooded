#!/bin/sh
# Renderer fonts (static TTFs from Fontsource) -> $1/<family>/<weight>.ttf
set -eu
OUT="${1:-/usr/share/fonts/reel}"
fetch() { fam="$1"; shift
  mkdir -p "$OUT/$fam"
  for w in "$@"; do
    [ -s "$OUT/$fam/$w.ttf" ] || curl -fsSL "https://cdn.jsdelivr.net/fontsource/fonts/$fam@latest/latin-$w-normal.ttf" -o "$OUT/$fam/$w.ttf"
  done
}
fetch inter 300 400 500 600 700 900
fetch space-grotesk 300 400 500 600 700
fetch playfair-display 400 500 600 700 900
fetch jetbrains-mono 400 600 700
fetch ibm-plex-mono 400 600 700
fetch anton 400
fetch archivo-black 400
echo "fonts in $OUT"
