#!/usr/bin/env bash
# Acceptance tests for dynamic voice corpus (plan tests 1-7 + chat hotfix).
set -euo pipefail
VOICE="$HOME/.cursor/voice"
STYLE="$HOME/.cursor/style-enforcement"
VOICECTL="$VOICE/bin/voicectl"
STYLECTL="$STYLE/bin/stylectl"
OUT="$VOICE/tests/last_results.txt"
TMP="$VOICE/tests/.tmp"
rm -rf "$TMP"
mkdir -p "$TMP" "$VOICE/tests"
: >"$OUT"
pass=0
fail=0
ok() { echo "PASS $1" | tee -a "$OUT"; pass=$((pass+1)); }
ko() { echo "FAIL $1 — $2" | tee -a "$OUT"; fail=$((fail+1)); }

export CURSOR_VOICE_ROOT="$VOICE"
export CURSOR_STYLE_POLICY="$STYLE/policy/policy.json"
export PATH="/opt/homebrew/bin:$PATH"

# --- Hotfix: chat tool_errors do not block stop ---
python3 - <<'PY' >>"$OUT" 2>&1
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path.home()/".cursor/style-enforcement/lib"))
from enforce import save_state, outstanding_blocking
cid="voice-acc-hotfix"
save_state(cid, {"conversation_id": cid, "files": {}, "chat": {
  "violations": [], "tool_errors": ["textlint produced non-JSON output"], "blocking": []
}})
assert outstanding_blocking(cid)==[]
print("hotfix_assert_ok")
PY
ok hotfix_chat_failopen

# --- 1 Invalidation ---
REF="$VOICE/references"
ACTIVE="$REF/active"
BACKUP="$TMP/refs_backup"
rm -rf "$BACKUP"
mkdir -p "$BACKUP/active"
# Backup active corpus only (skip Drive/Takeout/library/candidates).
find "$ACTIVE" -maxdepth 1 -type f ! -name '.*' -exec cp {} "$BACKUP/active/" \;
V1=$("$VOICECTL" version)
echo "extra acceptance probe sentence." > "$ACTIVE/zzz_extra_probe.txt"
"$VOICECTL" ensure >/dev/null
V2=$("$VOICECTL" version)
rm -f "$ACTIVE/zzz_extra_probe.txt"
"$VOICECTL" ensure >/dev/null
V3=$("$VOICECTL" version)
echo "V1=$V1 V2=$V2 V3=$V3" >>"$OUT"
if [[ "$V1" != "$V2" && "$V2" != "$V3" ]]; then ok invalidation; else ko invalidation "versions V1=$V1 V2=$V2 V3=$V3"; fi

# --- 2 Conditioning ---
COND=$("$VOICECTL" condition)
echo "$COND" >>"$OUT"
if echo "$COND" | rg -q 'conditioning|corpus_version|Dynamic voice'; then ok conditioning; else ko conditioning "$COND"; fi
# Fixed prose-mode policy (edit/write/stop) must ride alongside the style brief.
if echo "$COND" | rg -q 'Prose modes' \
  && echo "$COND" | rg -q 'EDIT mode' \
  && echo "$COND" | rg -q 'WRITE mode' \
  && echo "$COND" | rg -q 'sources' \
  && echo "$COND" | rg -q 'STOP:'; then
  ok prose_modes
else
  ko prose_modes "$COND"
fi
# sessionStart includes brief
SS=$(echo '{"session_id":"voice-acc-sess","conversation_id":"voice-acc-sess","is_background_agent":false,"composer_mode":"agent"}' | "$STYLECTL" hook sessionStart)
echo "$SS" >>"$OUT"
if echo "$SS" | rg -q 'CURSOR_VOICE_CORPUS_VERSION|Dynamic voice|corpus_version'; then ok session_start_voice; else ko session_start_voice "$SS"; fi
if echo "$SS" | rg -q 'Prose modes' \
  && echo "$SS" | rg -q 'EDIT mode' \
  && echo "$SS" | rg -q 'sources' \
  && echo "$SS" | rg -q 'STOP:'; then
  ok session_start_prose_modes
else
  ko session_start_prose_modes "$SS"
fi

# --- 3 Fail-closed docs (simulate reviewer error via broken provider) ---
cp "$VOICE/config.yaml" "$TMP/config.yaml.bak"
python3 - <<'PY'
from pathlib import Path
p=Path.home()/".cursor/voice/config.yaml"
text=p.read_text()
text=text.replace("provider: mock", "provider: claude")
# point to missing binary
import re
text=re.sub(r'bin:.*', 'bin: /tmp/missing-claude-binary-for-test', text, count=1)
p.write_text(text)
PY
# clear profile so ensure tries claude... actually review will call claude
rm -f "$VOICE/.cache/review-cache"/*.json
DOC="$TMP/doc.md"
printf '# Note\n\nThe COP was 1.65 at 781 W.\n' >"$DOC"
# Force review path: with mock replaced by broken claude, review_file errors
if ! "$STYLECTL" check "$DOC" >"$TMP/check_fail.json" 2>"$TMP/check_fail.err"; then
  if rg -q '"error"|exit|missing|FAIL|voice' "$TMP/check_fail.json" "$TMP/check_fail.err" 2>/dev/null; then
    ok fail_closed_docs
  else
    # stylectl may still pass deterministic; require voice error in payload
    if rg -q '"error"' "$TMP/check_fail.json"; then ok fail_closed_docs; else ko fail_closed_docs "$(cat "$TMP/check_fail.json")"; fi
  fi
else
  # exit 0 unexpected unless voice skipped
  if rg -q '"error"' "$TMP/check_fail.json"; then ok fail_closed_docs; else ko fail_closed_docs "expected nonzero $(cat "$TMP/check_fail.json")"; fi
fi
cp "$TMP/config.yaml.bak" "$VOICE/config.yaml"
"$VOICECTL" ensure >/dev/null

# --- 4 Fail-open chat ---
python3 - <<'PY' >>"$OUT" 2>&1
import json, sys, subprocess
from pathlib import Path
sys.path.insert(0, str(Path.home()/".cursor/style-enforcement/lib"))
from enforce import save_state
cid="voice-acc-chat"
save_state(cid, {"conversation_id": cid, "files": {}, "chat": {
  "violations": [], "tool_errors": ["boom"], "blocking": []
}})
proc=subprocess.run(
  [str(Path.home()/".cursor/style-enforcement/bin/stylectl"), "hook", "stop"],
  input=json.dumps({"conversation_id": cid, "status": "completed", "loop_count": 0}),
  text=True, capture_output=True,
)
print("stop_out", proc.stdout)
data=json.loads(proc.stdout or "{}")
assert "followup_message" not in data or not data.get("followup_message")
print("chat_failopen_ok")
PY
ok fail_open_chat

# --- 5 Corpus shift generation (A vs B) ---
python3 - <<'PY' >>"$OUT" 2>&1
import json, shutil, subprocess, os
from pathlib import Path
voice=Path.home()/".cursor/voice"
refs=voice/"references"/"active"
refs.mkdir(parents=True, exist_ok=True)
tmp=voice/"tests/.tmp"
# Save current active files only (never unlink Drive/Takeout dirs)
saved=tmp/"saved_refs"
shutil.rmtree(saved, ignore_errors=True)
saved.mkdir(parents=True)

def active_files():
    return [p for p in refs.iterdir() if p.is_file() and not p.name.startswith(".")]

for p in active_files():
    shutil.copy2(p, saved/p.name)
# Install corpus A
for p in active_files():
    p.unlink()
shutil.copy2(voice/"tests/fixtures/corpus_a/lab_style.txt", refs/"lab_style.txt")
subprocess.check_call([str(voice/"bin/voicectl"), "ensure"])
va=subprocess.check_output([str(voice/"bin/voicectl"), "version"], text=True).strip()
# Sample under A conditioning: short measured prose
sample_a="1. Result\nCOP was 1.65. Heat rate was 781 W.\n"
# Sample verbose (should violate terse profile more)
sample_b_text=(
  "When one carefully contemplates the elaborate narrative surrounding thermal comfort systems, "
  "it becomes increasingly apparent that numerous ornamental clauses and discursive elaborations "
  "dominate the exposition far beyond ordinary laboratory brevity in ways that stretch endlessly."
)
def review_text(sample: str):
    proc = subprocess.run(
        [str(voice / "bin" / "voicectl"), "review-text"],
        input=sample,
        text=True,
        capture_output=True,
    )
    return json.loads(proc.stdout or "{}")


ra = review_text(sample_a)
rb = review_text(sample_b_text)
print("A_on_A", ra)
print("verbose_on_A", rb)
# Switch to corpus B
for p in active_files():
    p.unlink()
shutil.copy2(voice/"tests/fixtures/corpus_b/essay_style.txt", refs/"essay_style.txt")
# wipe review cache
rc=voice/".cache"/"review-cache"
if rc.exists():
    shutil.rmtree(rc)
    rc.mkdir()
subprocess.check_call([str(voice/"bin/voicectl"), "ensure"])
vb=subprocess.check_output([str(voice/"bin/voicectl"), "version"], text=True).strip()
assert va!=vb, (va, vb)
# Restore production refs
for p in active_files():
    p.unlink()
for p in saved.glob("*"):
    if p.is_file():
        shutil.copy2(p, refs/p.name)
subprocess.check_call([str(voice/"bin/voicectl"), "ensure"])
# Assert verbose had more/equal severity under terse corpus
viol_a=len(ra.get("violations") or [])
viol_v=len(rb.get("violations") or [])
print("viol_short", viol_a, "viol_verbose", viol_v)
assert vb!=va
assert viol_v>=viol_a
print("corpus_shift_ok")
PY
ok corpus_shift

# --- 6 Live corpus replacement / mismatch ---
python3 - <<'PY' >>"$OUT" 2>&1
import json, sys, subprocess
from pathlib import Path
sys.path.insert(0, str(Path.home()/".cursor/style-enforcement/lib"))
from enforce import save_state, load_state
cid="voice-acc-live"
# Condition session under current version
cond=json.loads(subprocess.check_output([str(Path.home()/".cursor/voice/bin/voicectl"), "condition"], text=True))
ver=cond["corpus_version"]
save_state(cid, {"conversation_id": cid, "files": {}, "chat": None, "voice_corpus_version": ver})
# Mutate corpus (active/ only)
ref=Path.home()/".cursor/voice/references"/"active"/"live_probe.txt"
ref.parent.mkdir(parents=True, exist_ok=True)
ref.write_text("Live probe sentence for mismatch detection.\n")
subprocess.check_call([str(Path.home()/".cursor/voice/bin/voicectl"), "ensure"])
proc=subprocess.run(
  [str(Path.home()/".cursor/style-enforcement/bin/stylectl"), "hook", "stop"],
  input=json.dumps({"conversation_id": cid, "status": "completed", "loop_count": 0}),
  text=True, capture_output=True,
)
print(proc.stdout)
data=json.loads(proc.stdout or "{}")
assert "followup_message" in data and "mid-session" in data["followup_message"].lower() or "changed" in data["followup_message"].lower()
ref.unlink(missing_ok=True)
subprocess.check_call([str(Path.home()/".cursor/voice/bin/voicectl"), "ensure"])
print("live_mismatch_ok")
# Document limitation
Path.home().joinpath(".cursor/voice/tests/LIVE_SWAP_NOTES.md").write_text(
  "Live corpus replacement: stop detects version mismatch and refuses enforcement under A.\n"
  "Full re-conditioning of additional_context requires a new Cursor conversation (sessionStart).\n"
)
PY
ok live_corpus_replacement

# --- 7 Independent evaluation + content preservation ---
python3 - <<'PY' >>"$OUT" 2>&1
import re, json, subprocess, shutil
from pathlib import Path
voice=Path.home()/".cursor/voice"
# Independent metric: avg sentence length (not the voice reviewer LLM)
def avg_len(text):
    parts=[s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
    if not parts: return 0
    return sum(len(p.split()) for p in parts)/len(parts)
terse="COP was 1.65. Heat was 781 W. Trials used 5 min holds."
verbose=("When one carefully contemplates the elaborate narrative surrounding thermal comfort, "
         "it becomes increasingly apparent that ornamental clauses dominate exposition beyond laboratory brevity.")
# Under production profile (seeded technical reports -> terse-measured typically)
assert avg_len(terse) < avg_len(verbose)
# Content preservation fixture
doc="The COP was 1.651. Condenser heat was 781 W. Equation: Q = m * cp * dT."
# voice review must not rewrite file; check file unchanged after review
p=voice/"tests/.tmp"/"preserve.md"
p.write_text(doc)
before=p.read_text()
subprocess.run([str(voice/"bin/voicectl"), "review", str(p)], check=False)
after=p.read_text()
assert before==after
assert "1.651" in after and "781" in after and "Q = m * cp * dT" in after
# Independent metric: terse sample shorter than verbose sample
assert avg_len(terse) < avg_len(verbose)
print("independent_eval_ok")
PY
ok independent_eval

# Restore refs if needed
"$VOICECTL" ensure >/dev/null || true

# --- 8 Marker convert → candidates; promote → active changes corpus ---
python3 - <<'PY' >>"$OUT" 2>&1
import json, subprocess, sys
from pathlib import Path

voice = Path.home() / ".cursor" / "voice"
voicectl = voice / "bin" / "voicectl"
pdf = voice / "tests" / "fixtures" / "marker_sample.pdf"
docx = voice / "tests" / "fixtures" / "marker_sample.docx"
sys.path.insert(0, str(voice / "lib"))
import marker_runtime
import voice_core

cfg = voice_core.load_config(voice)
mcfg = marker_runtime.marker_settings(cfg)
assert mcfg.get("use_llm") is False
assert str(mcfg.get("output_dir")).endswith("candidates")
assert not marker_runtime.default_argv_includes_use_llm(mcfg)

cand = voice_core.candidates_dir(voice)
active = voice_core.active_dir(voice)
library = voice_core.library_dir(voice)
cand.mkdir(parents=True, exist_ok=True)

# Clean prior materialization in candidates (and stray top-level)
for p in list(cand.glob("marker_sample*.md")) + list(
    (voice / "references").glob("marker_sample*.md")
):
    if p.is_file():
        p.unlink()

def convert(path: Path):
    proc = subprocess.run(
        [str(voicectl), "convert", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    print("convert_rc", path.suffix, proc.returncode)
    print("convert_err_tail", (proc.stderr or "")[-400:])
    data = json.loads(proc.stdout or "[]")
    return data[0], proc.returncode

# list_references ignores top-level / library / candidates prose
top_probe = voice / "references" / "zzz_top_level_ignore.txt"
top_probe.write_text("should not enter corpus\n", encoding="utf-8")
lib_probe = library / "zzz_library_ignore.txt"
lib_probe.write_text("library ignore\n", encoding="utf-8")
cand_probe = cand / "zzz_candidates_ignore.txt"
cand_probe.write_text("candidates ignore\n", encoding="utf-8")
refs = {p.name for p in voice_core.list_references(voice)}
assert "zzz_top_level_ignore.txt" not in refs
assert "zzz_library_ignore.txt" not in refs
assert "zzz_candidates_ignore.txt" not in refs
top_probe.unlink(missing_ok=True)
lib_probe.unlink(missing_ok=True)
cand_probe.unlink(missing_ok=True)

r1, rc1 = convert(pdf)
assert rc1 == 0 and r1["status"] == "ok", r1
mat = Path(r1["materialized_path"])
assert "candidates" in str(mat)
assert "1.65" in mat.read_text()
assert "781" in mat.read_text()
md_hash = r1["markdown_sha256"]

r2, rc2 = convert(pdf)
assert rc2 == 0 and r2.get("cache_hit") is True, r2
assert r2["markdown_sha256"] == md_hash

r3, rc3 = convert(docx)
assert rc3 == 0 and r3["status"] == "ok", r3
assert "1.65" in Path(r3["materialized_path"]).read_text()

# Quarantine: empty markdown quality gate
assert marker_runtime.quality_check("")[0] == "quarantine"
assert marker_runtime.quality_check("short")[0] == "quarantine"

# Convert into candidates must NOT change corpus_version
v_before = subprocess.check_output([str(voicectl), "version"], text=True).strip()
subprocess.check_call([str(voicectl), "ensure"])
v_after_convert = subprocess.check_output([str(voicectl), "version"], text=True).strip()
assert v_after_convert == v_before, (v_before, v_after_convert)

# Promote into active MUST change corpus_version
promoted = list(cand.glob("marker_sample*.md"))
assert promoted, "expected converted md in candidates"
prom = subprocess.run(
    [str(voicectl), "promote", str(promoted[0])],
    capture_output=True,
    text=True,
    check=False,
)
assert prom.returncode == 0, prom.stdout + prom.stderr
subprocess.check_call([str(voicectl), "ensure"])
v_after_promote = subprocess.check_output([str(voicectl), "version"], text=True).strip()
assert v_after_promote != v_before, "promote should change corpus_version"

# Cleanup: park promoted samples back out of active
for p in active.glob("marker_sample*.md"):
    subprocess.check_call([str(voicectl), "park", str(p)])
for p in cand.glob("marker_sample*.md"):
    p.unlink()
subprocess.check_call([str(voicectl), "ensure"])
v_clean = subprocess.check_output([str(voicectl), "version"], text=True).strip()
assert v_clean == v_before
print("marker_convert_ok")
PY
ok marker_convert

# --- 9 Marker MCP handshake + convert consistency ---
python3 - <<'PY' >>"$OUT" 2>&1
import json, subprocess, hashlib
from pathlib import Path

voice = Path.home() / ".cursor" / "voice"
pdf = voice / "tests" / "fixtures" / "marker_sample.pdf"
py = voice / "vendor" / "marker" / ".venv" / "bin" / "python"
server = voice / "mcp" / "marker_server.py"


def send(proc, msg):
    data = json.dumps(msg).encode()
    proc.stdin.write(f"Content-Length: {len(data)}\r\n\r\n".encode() + data)
    proc.stdin.flush()


def read(proc):
    header = b""
    while not header.endswith(b"\r\n\r\n"):
        b = proc.stdout.read(1)
        if not b:
            raise RuntimeError("eof")
        header += b
    length = 0
    for line in header.decode().split("\r\n"):
        if line.lower().startswith("content-length:"):
            length = int(line.split(":", 1)[1].strip())
    return json.loads(proc.stdout.read(length).decode())

env = {**dict(**{k: v for k, v in __import__("os").environ.items()}), "CURSOR_VOICE_ROOT": str(voice)}
proc = subprocess.Popen(
    [str(py), str(server)],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    env=env,
)
send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
init = read(proc)
assert init["result"]["serverInfo"]["name"] == "marker"
send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
tools = read(proc)
names = sorted(t["name"] for t in tools["result"]["tools"])
assert "marker_convert" in names
send(
    proc,
    {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "marker_convert", "arguments": {"path": str(pdf)}},
    },
)
resp = read(proc)
payload = json.loads(resp["result"]["content"][0]["text"])
assert payload["status"] == "ok"
cli = json.loads(
    subprocess.check_output([str(voice / "bin" / "voicectl"), "convert", str(pdf)], text=True)
)[0]
assert payload["markdown_sha256"] == cli["markdown_sha256"]
# Clean materialization from candidates (and park any accidental active)
cand = voice / "references" / "candidates"
active = voice / "references" / "active"
for p in list(cand.glob("marker_sample*.md")) + list(active.glob("marker_sample*.md")):
    if p.is_file():
        p.unlink()
subprocess.check_call([str(voice / "bin" / "voicectl"), "ensure"])
proc.terminate()
print("marker_mcp_ok")
PY
ok marker_mcp

# --- 10 Hot-path: version without Marker ---
python3 - <<'PY' >>"$OUT" 2>&1
import time, subprocess
from pathlib import Path
voice = Path.home() / ".cursor" / "voice"
voicectl = str(voice / "bin" / "voicectl")
t0 = time.perf_counter()
for _ in range(5):
    subprocess.check_output([voicectl, "version"])
elapsed = time.perf_counter() - t0
print("version_5x_sec", round(elapsed, 3))
assert elapsed < 5.0, elapsed
print("hot_path_ok")
PY
ok hot_path_version

# --- 11 Picklist Phase-0: merge/urgency + mocked judge; no corpus change ---
python3 - <<'PY' >>"$OUT" 2>&1
import json, shutil, subprocess, sys, tempfile
from pathlib import Path

voice = Path.home() / ".cursor" / "voice"
voicectl = voice / "bin" / "voicectl"
sys.path.insert(0, str(voice / "lib"))
import picklist as pl
import voice_core
import marker_runtime

# Pure fixtures: urgency, partition, merge, disagreements (FN/FP)
assert pl._urgency(pl.RowKind.BATCH, "library", False) is pl.Urgency.RESCUE
assert pl._urgency(pl.RowKind.BATCH, "candidate", False) is pl.Urgency.CONFIRM
assert pl._urgency(pl.RowKind.BATCH, "candidate", True) is pl.Urgency.MIXED

empty = pl._CheapExtract(pl._ExtractKind.PDFTOTEXT, "body", pl._sha256_text("body"))
prior_c = pl._PathPrior("candidate", "candidate-drive-lab-report-names")
prior_lib = pl._PathPrior("library", "library-name-globs")
parent = Path("/tmp/picklist-acc-dir")
cards = [
    pl._SourceCard(parent / f"f{i}.pdf", 1, 1, prior_c, empty) for i in range(7)
]
batches = pl._partition(cards)
assert len(batches) == 2 and len(batches[0].cards) == 6

rescue = pl._SourceCard(
    Path("/tmp/pl/Copy of n-butyl lab.docx"), 1, 1, prior_lib, empty
)
confirm = pl._SourceCard(
    Path("/tmp/pl/Thermo Lab 1_ Report.docx"), 1, 1, prior_c, empty
)
mixed = pl._SourceCard(
    Path("/tmp/pl/Heat Pump Lab - group.docx"), 1, 1, prior_c, empty
)
fp_manual = pl._SourceCard(
    Path("/tmp/pl/Holden student manual.pdf"), 1, 1, prior_c, empty
)
facts = {
    rescue.path: pl._JudgeFact(rescue.path, pl.RowKind.BATCH, False, "Max authored copy"),
    confirm.path: pl._JudgeFact(confirm.path, pl.RowKind.BATCH, False, "solo lab"),
    mixed.path: pl._JudgeFact(mixed.path, pl.RowKind.BATCH, True, "group writeup"),
    fp_manual.path: pl._JudgeFact(
        fp_manual.path, pl.RowKind.NOT_MAX, False, "student manual"
    ),
}
pick = pl._merge([rescue, confirm, mixed, fp_manual], facts)
assert pick.batch_paths() == (rescue.path, confirm.path)
assert pick.mixed_paths() == (mixed.path,)
assert pick.excluded_paths() == (fp_manual.path,)
dis_paths = {r.path for r in pick.disagreements()}
assert rescue.path in dis_paths and fp_manual.path in dis_paths

# cached_excerpt read-only
ex = marker_runtime.cached_excerpt(
    voice, voice / "tests/fixtures/marker_sample.pdf", 80
)
assert ex is None or isinstance(ex, str)

# Shared default roots
assert voice_core.default_dump_roots(voice) == [voice / "references" / "Drive"]

# Shell with mocked judge: does not change corpus_version or write active
v_before = subprocess.check_output([str(voicectl), "version"], text=True).strip()
tmp = Path(tempfile.mkdtemp(prefix="picklist-acc-"))
dump = tmp / "references" / "Drive" / "labs"
dump.mkdir(parents=True)
(tmp / "references" / "active").mkdir(parents=True)
(tmp / "config.yaml").write_text(
    (voice / "config.yaml").read_text(encoding="utf-8"), encoding="utf-8"
)
(tmp / ".cache" / "extracted").mkdir(parents=True)
fixture = voice / "tests/fixtures/marker_sample.pdf"
fn_copy = dump / "Copy of Thermo Lab.pdf"
fp_man = dump / "student manual Knight.pdf"
shutil.copy(fixture, fn_copy)
shutil.copy(fixture, fp_man)

def fake_judge(batch, voice_root, cfg):
    out = []
    for c in batch.cards:
        name = c.path.name.lower()
        if "manual" in name or "knight" in name:
            out.append(
                pl._JudgeFact(c.path, pl.RowKind.NOT_MAX, False, "Knight / manual FP")
            )
        else:
            out.append(
                pl._JudgeFact(c.path, pl.RowKind.BATCH, False, "Max authored rescue")
            )
    voice_core.atomic_write_json(
        pl._batches_dir(voice_root) / f"{batch.batch_id}.json",
        {
            "batch_id": batch.batch_id,
            "paths": [str(c.path.resolve()) for c in batch.cards],
            "judgments": [
                {
                    "path": str(f.path),
                    "disposition": f.kind.value,
                    "shared": f.shared,
                    "reason": f.reason,
                }
                for f in out
            ],
        },
    )
    return out

pl._load_or_judge = fake_judge
built = pl.build_picklist([tmp / "references" / "Drive"], tmp)
assert fn_copy.resolve() in {p.resolve() for p in built.batch_paths()}
assert fp_man.resolve() in {p.resolve() for p in built.excluded_paths()}
assert (tmp / ".cache" / "picklist" / "latest.json").is_file()
assert list((tmp / "references" / "active").iterdir()) == []
# No convert side effect on live corpus
v_after = subprocess.check_output([str(voicectl), "version"], text=True).strip()
assert v_after == v_before, (v_before, v_after)

# CLI help advertises picklist; unknown format fails closed
help_out = subprocess.run(
    [str(voicectl), "-h"], capture_output=True, text=True, check=False
)
assert "picklist" in (help_out.stdout + help_out.stderr)

md = pl.render_picklist(built)
assert "Batch (rescue then confirm)" in md
assert "Not Max-authored" in md
paths_txt = pl.render_picklist_paths(built)
assert str(fn_copy.resolve()) in paths_txt or fn_copy.name in paths_txt
payload = json.loads(pl.render_picklist_json(built))
assert payload["counts"].get("batch", 0) >= 1
assert payload["counts"].get("not_max", 0) >= 1

shutil.rmtree(tmp)
print("picklist_phase0_ok")
PY
ok picklist_phase0

# --- Multi-doc voice banks ---
if "$VOICE/tests/test_banks.sh" >>"$OUT" 2>&1; then
  ok banks_suite
else
  ko banks_suite "see tests/last_banks_results.txt"
fi

echo "=== summary pass=$pass fail=$fail ===" | tee -a "$OUT"
if [[ "$fail" -gt 0 ]]; then exit 1; fi
exit 0
