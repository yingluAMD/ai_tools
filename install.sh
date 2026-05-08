#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$HOME/.cursor/skills"

SKILLS=(
    "translate_pdf:translate-pdf"
    "md_to_pdf:md-to-pdf"
)

info()  { printf "\033[1;32m[INFO]\033[0m  %s\n" "$*"; }
warn()  { printf "\033[1;33m[WARN]\033[0m  %s\n" "$*"; }
error() { printf "\033[1;31m[ERROR]\033[0m %s\n" "$*"; exit 1; }

install_skills() {
    info "Creating skills directory: $SKILLS_DIR"
    mkdir -p "$SKILLS_DIR"

    for entry in "${SKILLS[@]}"; do
        src="${entry%%:*}"
        dst="${entry##*:}"
        src_path="$SCRIPT_DIR/$src"
        dst_path="$SKILLS_DIR/$dst"

        if [[ ! -d "$src_path" ]]; then
            warn "Source directory not found, skipping: $src_path"
            continue
        fi

        ln -sfn "$src_path" "$dst_path"
        info "Linked $dst_path -> $src_path"
    done
}

detect_gpu() {
    if [[ -n "$GPU_OVERRIDE" ]]; then
        echo "$GPU_OVERRIDE"
        return
    fi
    if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
        echo "nvidia"
    elif [[ -d /opt/rocm ]] || command -v rocminfo &>/dev/null; then
        echo "amd"
    else
        echo "cpu"
    fi
}

install_pytorch() {
    local gpu
    gpu=$(detect_gpu)

    case "$gpu" in
        nvidia)
            info "Detected NVIDIA GPU — installing PyTorch with CUDA support"
            pip install torch torchvision
            ;;
        amd)
            local rocm_ver
            if [[ -f /opt/rocm/.info/version ]]; then
                rocm_ver=$(cut -d. -f1,2 < /opt/rocm/.info/version)
            else
                rocm_ver="6.2"
            fi
            local whl_tag="rocm${rocm_ver}"
            info "Detected AMD GPU (ROCm ${rocm_ver}) — installing PyTorch with ROCm support"
            pip install torch torchvision --index-url "https://download.pytorch.org/whl/${whl_tag}"
            ;;
        *)
            info "No GPU detected — installing CPU-only PyTorch"
            pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
            ;;
    esac
}

install_deps() {
    install_pytorch

    info "Installing Python dependencies for translate_pdf ..."
    pip install -r "$SCRIPT_DIR/translate_pdf/requirements.txt"

    info "Installing Python dependencies for md_to_pdf ..."
    pip install markdown weasyprint Pygments

    info "Installing system packages (may require sudo) ..."
    sudo apt-get install -y \
        libpango1.0-dev libcairo2-dev libgdk-pixbuf-2.0-dev \
        libffi-dev shared-mime-info fonts-noto-cjk

    if command -v tesseract &>/dev/null; then
        info "Tesseract already installed: $(tesseract --version 2>&1 | head -1)"
    else
        warn "Tesseract not found. Install it for OCR support:"
        warn "  sudo apt-get install tesseract-ocr"
    fi
}

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Install ai_tools Cursor skills into ~/.cursor/skills/

Options:
  --link-only        Only create symlinks (skip dependency installation)
  --deps-only        Only install dependencies (skip symlink creation)
  --gpu TYPE         Override GPU auto-detection (nvidia | amd | cpu)
  -h, --help         Show this help message
EOF
}

# --- main ---
do_link=true
do_deps=true
GPU_OVERRIDE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --link-only) do_deps=false ;;
        --deps-only) do_link=false ;;
        --gpu)
            shift
            [[ $# -eq 0 ]] && error "--gpu requires an argument (nvidia | amd | cpu)"
            GPU_OVERRIDE="$1"
            ;;
        -h|--help)   usage; exit 0 ;;
        *)           error "Unknown option: $1" ;;
    esac
    shift
done

if $do_link; then install_skills; fi
if $do_deps; then install_deps;  fi

info "Done!"
