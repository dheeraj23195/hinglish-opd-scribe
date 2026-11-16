#!/bin/bash
# Hinglish OPD scribe: generate consult audio with macOS's built-in Hindi voice.
# Double-click this file (or run: bash make_audio.command). Takes ~5-10 minutes.
# Output: consult_audio.zip in this folder. Nothing is uploaded anywhere.
cd "$(dirname "$0")" || exit 1

VOICES=$(say -v '?' | grep -i 'hi_IN' | sed -E 's/ +hi_IN.*//' | sed -E 's/[[:space:]]+$//')
if [ -z "$VOICES" ]; then
  echo "No Hindi voice found."
  echo "Add one: System Settings > Accessibility > Spoken Content > System Voice > Manage Voices > Hindi (e.g. Lekha), then run this again."
  read -r -p "Press Enter to close." _; exit 1
fi
DOC_VOICE=$(echo "$VOICES" | sed -n 1p)
PAT_VOICE=$(echo "$VOICES" | sed -n 2p); [ -z "$PAT_VOICE" ] && PAT_VOICE="$DOC_VOICE"
echo "Doctor voice: $DOC_VOICE | Patient voice: $PAT_VOICE"

mkdir -p audio
N=$(wc -l < tts_jobs.tsv); i=0
while IFS=$'\t' read -r id speaker text; do
  i=$((i+1))
  out="audio/$id.m4a"
  [ -s "$out" ] && continue
  if [ "$speaker" = "doctor" ]; then V="$DOC_VOICE"; R=180; else V="$PAT_VOICE"; R=165; fi
  say -v "$V" -r "$R" -o "audio/$id.aiff" -- "$text" && \
    afconvert -f m4af -d aac -b 48000 "audio/$id.aiff" "$out" && rm -f "audio/$id.aiff"
  [ $((i % 100)) -eq 0 ] && echo "$i / $N"
done < tts_jobs.tsv

rm -f consult_audio.zip
zip -q -r consult_audio.zip audio
echo "Done: $(ls audio | wc -l) clips -> consult_audio.zip"
read -r -p "Press Enter to close." _
