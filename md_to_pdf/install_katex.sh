#!/usr/bin/env bash
# Install KaTeX assets for the md-to-pdf skill.
# Idempotent: re-running skips download but always rebuilds the CSS bundle.
#
# Override KaTeX version via env: KATEX_VER=0.16.45 ./install_katex.sh

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SKILL_DIR"

KATEX_VER="${KATEX_VER:-0.16.45}"
VENDOR="$SKILL_DIR/vendor"
KATEX_DIR="$VENDOR/katex"

log() { printf "[install_katex] %s\n" "$*"; }
die() { printf "[install_katex] ERROR: %s\n" "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. Preflight: node >= 16
# ---------------------------------------------------------------------------
command -v node >/dev/null 2>&1 \
    || die "node not found. Install Node.js 16+ (fnm/nvm don't need sudo)."

node_major=$(node -p 'process.versions.node.split(".")[0]')
if [ "$node_major" -lt 16 ]; then
    die "Node >= 16 required, got $(node -v)."
fi
log "node $(node -v) OK"

command -v python3 >/dev/null 2>&1 || die "python3 not found."

# ---------------------------------------------------------------------------
# 2. Download + extract katex tarball (skip if already present)
# ---------------------------------------------------------------------------
mkdir -p "$VENDOR"

if [ -f "$KATEX_DIR/dist/katex.min.js" ]; then
    log "katex already present at $KATEX_DIR (skipping download)"
else
    log "Downloading katex@$KATEX_VER from registry.npmjs.org ..."
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    curl -fsSL \
        "https://registry.npmjs.org/katex/-/katex-${KATEX_VER}.tgz" \
        -o "$tmp/katex.tgz"
    tar xzf "$tmp/katex.tgz" -C "$tmp"
    rm -rf "$KATEX_DIR"
    mv "$tmp/package" "$KATEX_DIR"
fi

[ -f "$KATEX_DIR/dist/katex.min.js" ] \
    || die "dist/katex.min.js missing after extraction."
[ -f "$KATEX_DIR/dist/katex.min.css" ] \
    || die "dist/katex.min.css missing after extraction."
[ -d "$KATEX_DIR/dist/fonts" ] \
    || die "dist/fonts dir missing after extraction."

# ---------------------------------------------------------------------------
# 3. Slim down vendored KaTeX: keep only what the server-side path needs
# ---------------------------------------------------------------------------
log "Slimming $KATEX_DIR ..."
rm -rf \
    "$KATEX_DIR/src" \
    "$KATEX_DIR/types" \
    "$KATEX_DIR/contrib" \
    "$KATEX_DIR/coverage" \
    "$KATEX_DIR/node_modules" \
    "$KATEX_DIR/test" \
    "$KATEX_DIR/docs" \
    "$KATEX_DIR/dist/contrib"

# Keep only the minified JS + minified CSS + woff2 fonts in dist/.
find "$KATEX_DIR/dist" -maxdepth 1 -type f \
    ! -name 'katex.min.js' \
    ! -name 'katex.min.css' \
    -delete
find "$KATEX_DIR/dist/fonts" -type f ! -name '*.woff2' -delete

# Strip TS sources, source maps, SCSS that may sit at package root.
find "$KATEX_DIR" -maxdepth 2 -type f \( \
        -name '*.ts' -o \
        -name '*.map' -o \
        -name '*.tsbuildinfo' -o \
        -name '*.scss' -o \
        -name 'cli.js' \
    \) -delete

# ---------------------------------------------------------------------------
# 4. Build single-file CSS bundle (fonts base64-inlined)
# ---------------------------------------------------------------------------
log "Building katex_bundle.css ..."
python3 "$SKILL_DIR/build_katex_bundle.py"

# ---------------------------------------------------------------------------
# 5. Smoke test: render a cases formula end-to-end
# ---------------------------------------------------------------------------
log "Running smoke test (\\begin{cases}) ..."
smoke_input='[{"id":"t","tex":"\\begin{cases} a \\\\ b \\end{cases}","display":true}]'
smoke_out=$(printf '%s' "$smoke_input" | node "$VENDOR/render_katex.js")

if printf '%s' "$smoke_out" | grep -q '"ok":true'; then
    log "Smoke test passed."
else
    printf "[install_katex] Smoke test output:\n%s\n" "$smoke_out" >&2
    die "Smoke test failed. Inspect $VENDOR contents."
fi

bundle_size=$(du -sh "$VENDOR/katex_bundle.css" | cut -f1)
katex_size=$(du -sh "$KATEX_DIR" | cut -f1)
log "Done. vendor/katex=$katex_size, katex_bundle.css=$bundle_size"
