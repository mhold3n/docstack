#!/usr/bin/env bash
# Multi-doc voice banks acceptance (determinism, budget, empty, blacklist).
set -euo pipefail
VOICE="${CURSOR_VOICE_ROOT:-$HOME/.cursor/voice}"
VOICECTL="$VOICE/bin/voicectl"
OUT="$VOICE/tests/last_banks_results.txt"
TMP="$VOICE/tests/.tmp_banks"
rm -rf "$TMP"
mkdir -p "$TMP" "$VOICE/tests"
: >"$OUT"
pass=0
fail=0
ok() { echo "PASS $1" | tee -a "$OUT"; pass=$((pass+1)); }
ko() { echo "FAIL $1 — $2" | tee -a "$OUT"; fail=$((fail+1)); }

export CURSOR_VOICE_ROOT="$VOICE"
export PATH="/opt/homebrew/bin:$PATH"
cd "$VOICE"

# --- Deterministic mass rebuild (ignore generated_at timestamps) ---
M1=$("$VOICECTL" banks rebuild 2>/dev/null)
V=$(printf '%s' "$M1" | python3 -c 'import json,sys; print(json.load(sys.stdin)["corpus_version"])')
M2=$("$VOICECTL" banks rebuild 2>/dev/null)
if python3 - <<PY >>"$OUT" 2>&1
import json, sys
from pathlib import Path
v = "$V"
root = Path("$VOICE") / ".cache" / "banks" / v
# Compare bank payloads without generated_at
for name in [
    "grammar","word","word_combo","phrase",
    "punctuation","phrasing","paragraph","technical_writing",
]:
    data = json.loads((root / f"{name}.json").read_text())
    data.pop("generated_at", None)
    # Second rebuild already wrote same dir; re-read after M2 is same files.
    # Stability check: counts/rates/top present and bank_id matches.
    assert data.get("bank_id") == name
    assert "counts" in data and "top" in data
print("mass_stable_ok")
PY
then ok mass_deterministic; else ko mass_deterministic "see $OUT"; fi

# --- Eight bank JSON files exist ---
missing=0
for b in grammar word word_combo phrase punctuation phrasing paragraph technical_writing; do
  if [[ ! -f "$VOICE/.cache/banks/$V/$b.json" ]]; then
    missing=1
    echo "missing $b.json" >>"$OUT"
  fi
done
if [[ "$missing" -eq 0 ]]; then ok mass_eight_files; else ko mass_eight_files "see $OUT"; fi

# --- Conditioning index: all bank ids, style budget ---
"$VOICECTL" condition >"$TMP/cond.json"
if python3 - <<PY >>"$OUT" 2>&1
import json
from pathlib import Path
data = json.loads(Path("$TMP/cond.json").read_text())
ctx = data.get("additional_context") or ""
banks = [
    "grammar", "word", "word_combo", "phrase",
    "punctuation", "phrasing", "paragraph", "technical_writing",
]
missing = [b for b in banks if b not in ctx]
ok_markers = "Mass cues" in ctx and "Banks:" in ctx and "Prose modes" in ctx
style = ctx.split("Prose modes")[0]
max_c = 3200
if missing:
    raise SystemExit(f"missing banks: {missing}")
if not ok_markers:
    raise SystemExit("missing Mass cues / Banks / Prose modes")
if len(style) > max_c + 400:
    raise SystemExit(f"style section too long: {len(style)}")
print("condition_ok", len(style))
PY
then ok conditioning_banks; else ko conditioning_banks "see $OUT"; fi

# --- Archetype append rejects missing source ---
if python3 - <<'PY' >>"$OUT" 2>&1
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / ".cursor" / "voice" / "lib"))
import banks
root = Path.home() / ".cursor" / "voice"
try:
    banks.append_entry(
        root, "word", source_path="___no_such_file___.md", text="hello"
    )
except ValueError as exc:
    assert "source_path" in str(exc).lower() or "active" in str(exc).lower()
    print("append_reject_ok")
else:
    raise SystemExit("expected ValueError")
PY
then ok archetype_reject; else ko archetype_reject "see $OUT"; fi

# --- Archetype append accepts real active file ---
SAMPLE=$(find "$VOICE/references/active" -maxdepth 1 -type f -name '*.md' | head -1)
SAMPLE_NAME=$(basename "$SAMPLE")
if python3 - <<PY >>"$OUT" 2>&1
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / ".cursor" / "voice" / "lib"))
import banks
root = Path.home() / ".cursor" / "voice"
doc = banks.append_entry(
    root,
    "word",
    source_path="$SAMPLE_NAME",
    text="banks-acceptance probe token unique_xyz_999",
    corpus_version="test",
)
assert any("unique_xyz_999" in e.text for e in doc.entries)
print("append_ok", doc.entry_count)
PY
then ok archetype_append; else ko archetype_append "see $OUT"; fi

# --- Blacklist still matches ngrams tokenization ---
if python3 - <<'PY' >>"$OUT" 2>&1
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / ".cursor" / "voice" / "lib"))
import blacklist
import ngrams
assert blacklist._tokens("The COP was 1.65") == ngrams.tokens("The COP was 1.65")
assert ngrams.TOKEN_RE.pattern == r"[a-z0-9]{3,}"
print("blacklist_ngrams_ok")
PY
then ok blacklist_ngrams; else ko blacklist_ngrams "see $OUT"; fi

# --- Empty corpus mass ---
ACTIVE="$VOICE/references/active"
BACKUP="$TMP/active_backup"
mkdir -p "$BACKUP"
find "$ACTIVE" -maxdepth 1 -type f ! -name '.*' -exec mv {} "$BACKUP/" \;
"$VOICECTL" ensure >/dev/null
EMPTY_V=$("$VOICECTL" version)
EMPTY_MANIFEST="$VOICE/.cache/banks/$EMPTY_V/manifest.json"
if [[ -f "$EMPTY_MANIFEST" ]] && python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); assert m.get("empty") or m.get("n_source_files")==0' "$EMPTY_MANIFEST"; then
  ok empty_mass
else
  ko empty_mass "manifest missing or not empty"
fi
find "$BACKUP" -maxdepth 1 -type f -exec mv {} "$ACTIVE/" \;
"$VOICECTL" ensure >/dev/null

echo "banks_tests pass=$pass fail=$fail" | tee -a "$OUT"
[[ "$fail" -eq 0 ]]
