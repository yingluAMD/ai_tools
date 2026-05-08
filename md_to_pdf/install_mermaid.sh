#!/usr/bin/env bash
# Install mermaid assets for the md-to-pdf skill.
# Renders mermaid diagrams via system chromium (no npm/puppeteer needed).
# Idempotent: re-running skips download and just re-runs the smoke test.
#
# Override mermaid version via env: MERMAID_VER=11.4.1 ./install_mermaid.sh

set -euo pipefail

# Resolve symlinks so the render dir lives at the real path. snap chromium's
# AppArmor profile blocks file:// access to top-level hidden dirs in $HOME
# (~/.cursor/, ~/.cache/, ...), but is fine with hidden subdirs of a non-hidden
# parent. Resolving lets users install the skill via a symlink from
# ~/.cursor/skills/ to e.g. ~/projects/md-to-pdf/ and still have rendering work.
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$SKILL_DIR"

MERMAID_VER="${MERMAID_VER:-11.4.1}"
VENDOR="$SKILL_DIR/vendor"
MMD_DIR="$VENDOR/mermaid"
RENDER_CACHE="$MMD_DIR/render-cache"

log() { printf "[install_mermaid] %s\n" "$*"; }
die() { printf "[install_mermaid] ERROR: %s\n" "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. Preflight: chromium binary on PATH
# ---------------------------------------------------------------------------
CHROMIUM_BIN=""
for c in chromium-browser chromium google-chrome chrome; do
    if command -v "$c" >/dev/null 2>&1; then
        CHROMIUM_BIN="$(command -v "$c")"
        break
    fi
done
[ -n "$CHROMIUM_BIN" ] \
    || die "No chromium-browser/chromium/google-chrome on PATH. Install one (apt/snap/dnf)."
log "chromium binary: $CHROMIUM_BIN"

command -v curl >/dev/null 2>&1 || die "curl not found."
command -v tar  >/dev/null 2>&1 || die "tar not found."
command -v python3 >/dev/null 2>&1 || die "python3 not found."

# ---------------------------------------------------------------------------
# 2. Probe whether chromium can read $SKILL_DIR. Snap chromium blocks several
#    hidden parents in $HOME; warn early if that's the case.
# ---------------------------------------------------------------------------
mkdir -p "$RENDER_CACHE"
PROBE="$RENDER_CACHE/_probe.html"
cat > "$PROBE" <<'PEOF'
<!DOCTYPE html><html><head><title>PROBE_OK</title></head><body>x</body></html>
PEOF
probe_dump=$("$CHROMIUM_BIN" --headless --no-sandbox --disable-gpu \
    --disable-dev-shm-usage --dump-dom "file://$PROBE" 2>/dev/null || true)
rm -f "$PROBE"
if ! printf '%s' "$probe_dump" | grep -q '<title>PROBE_OK</title>'; then
    die "chromium can't read $SKILL_DIR (likely snap AppArmor confinement). \
Move the skill to a non-hidden directory in \$HOME (e.g. ~/projects/md-to-pdf) \
and symlink ~/.cursor/skills/md-to-pdf -> there."
fi
log "chromium can read render cache: OK"

# ---------------------------------------------------------------------------
# 3. Download + extract mermaid tarball (skip if already present)
# ---------------------------------------------------------------------------
mkdir -p "$VENDOR" "$MMD_DIR"

if [ -f "$MMD_DIR/mermaid.min.js" ]; then
    log "mermaid already present at $MMD_DIR (skipping download)"
else
    log "Downloading mermaid@$MERMAID_VER from registry.npmjs.org ..."
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    curl -fsSL \
        "https://registry.npmjs.org/mermaid/-/mermaid-${MERMAID_VER}.tgz" \
        -o "$tmp/mermaid.tgz"
    tar xzf "$tmp/mermaid.tgz" -C "$tmp"
    cp "$tmp/package/dist/mermaid.min.js" "$MMD_DIR/"
    cp "$tmp/package/package.json"        "$MMD_DIR/" 2>/dev/null || true
    cp "$tmp/package/LICENSE"             "$MMD_DIR/" 2>/dev/null || true
    rm -rf "$tmp"
    trap - EXIT
fi

[ -f "$MMD_DIR/mermaid.min.js" ] \
    || die "mermaid.min.js missing after extraction."

# ---------------------------------------------------------------------------
# 4. Smoke test: render two different diagram types end-to-end
# ---------------------------------------------------------------------------
log "Running smoke test (flowchart + sequence) ..."

cat > "$RENDER_CACHE/_smoke.html" <<'HTMLEOF'
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>PEND</title></head><body>
<div id="d0"></div><div id="d1"></div>
<script src="../mermaid.min.js"></script>
<script>
(async () => {
  try {
    mermaid.initialize({ startOnLoad: false, theme: 'default', securityLevel: 'loose' });
    const items = [
      { id: 'd0', src: 'flowchart LR\n  A[Start] --> B{OK?}\n  B -->|Yes| C[Go]\n  B -->|No| D[Stop]' },
      { id: 'd1', src: 'sequenceDiagram\n  Alice->>Bob: hi\n  Bob-->>Alice: hi back' },
    ];
    for (const it of items) {
      const { svg } = await mermaid.render('mmdsmoke-' + it.id, it.src);
      document.getElementById(it.id).innerHTML = svg;
    }
    document.title = 'MMD_OK';
  } catch (e) {
    document.title = 'MMD_ERR';
    document.getElementById('d0').textContent = 'ERR:' + (e && e.message);
  }
})();
</script>
</body></html>
HTMLEOF

dump=$(
    "$CHROMIUM_BIN" \
        --headless \
        --no-sandbox \
        --disable-gpu \
        --disable-dev-shm-usage \
        --virtual-time-budget=20000 \
        --run-all-compositor-stages-before-draw \
        --dump-dom \
        "file://$RENDER_CACHE/_smoke.html" 2>/dev/null
)
rm -f "$RENDER_CACHE/_smoke.html"

if printf '%s' "$dump" | grep -q '<title>MMD_OK</title>' \
   && [ "$(printf '%s' "$dump" | grep -oE '<svg[^>]+id="mmdsmoke-d[01]"' | wc -l)" -ge 2 ]; then
    log "Smoke test passed (2 SVGs rendered)."
else
    printf 'first 600 chars of dump:\n%s\n' "$(printf '%s' "$dump" | head -c 600)"
    die "Smoke test failed: title or SVGs missing."
fi

mmd_size=$(du -sh "$MMD_DIR/mermaid.min.js" | cut -f1)
log "Done. mermaid.min.js=$mmd_size, chromium=$CHROMIUM_BIN, render_cache=$RENDER_CACHE"
