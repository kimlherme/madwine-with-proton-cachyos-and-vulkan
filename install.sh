#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
install_dir="$data_home/madwine"
original="$install_dir/Madwine_0.1.22_amd64.original.AppImage"
expected_sha256="f6a05177f186c96dde5b948ed12c16e9ca9e85e703f947be8e267da3a584501b"
download_url="https://github.com/Ring0lw/madwine/releases/download/v0.1.22/Madwine_0.1.22_amd64.AppImage"

[[ -f "$script_dir/prepare-cachyos.py" && -f "$script_dir/run-cachyos.sh" ]] || {
    printf 'Execute install.sh a partir de uma cópia completa do repositório Madwine.\n' >&2
    exit 1
}
command -v python3 >/dev/null 2>&1 || { printf 'Erro: python3 é necessário.\n' >&2; exit 1; }
command -v unsquashfs >/dev/null 2>&1 || {
    printf "Erro: 'unsquashfs' não encontrado. No CachyOS/Arch, instale com: sudo pacman -S --needed squashfs-tools\n" >&2
    exit 1
}
mkdir -p "$install_dir"

check_hash() {
    python3 - "$1" "$expected_sha256" <<'PY'
import hashlib
from pathlib import Path
import sys

path = Path(sys.argv[1])
digest = hashlib.sha256(path.read_bytes()).hexdigest()
if digest != sys.argv[2]:
    raise SystemExit(f"SHA-256 inesperado para {path}: {digest}")
PY
}

if [[ -e "$original" || -L "$original" ]]; then
    [[ -f "$original" && ! -L "$original" ]] || { printf 'Erro: o arquivo original existe, mas não é um arquivo regular: %s\n' "$original" >&2; exit 1; }
    check_hash "$original" || { printf 'O AppImage original existente foi preservado; não será sobrescrito.\n' >&2; exit 1; }
else
    temporary="$install_dir/.Madwine_0.1.22.download.$$"
    trap 'rm -f -- "$temporary"' EXIT
    if command -v curl >/dev/null 2>&1; then
        curl -fL --retry 3 --output "$temporary" "$download_url"
    elif command -v wget >/dev/null 2>&1; then
        wget -O "$temporary" "$download_url"
    else
        printf 'Erro: instale curl ou wget para baixar o AppImage v0.1.22.\n' >&2
        exit 1
    fi
    check_hash "$temporary" || { printf 'O download não corresponde ao AppImage v0.1.22 fixado.\n' >&2; exit 1; }
    mv -- "$temporary" "$original"
    chmod 0755 "$original"
    trap - EXIT
fi

python3 "$script_dir/prepare-cachyos.py" \
    --appimage "$original" \
    --output "$install_dir/Madwine-CachyOS"

runner="$install_dir/run-cachyos.sh"
if [[ -e "$runner" ]] && ! cmp -s -- "$script_dir/run-cachyos.sh" "$runner"; then
    backup="$runner.pre-update-$(date -u +%Y%m%dT%H%M%SZ).bak"
    cp -p -- "$runner" "$backup"
    printf 'Launcher anterior salvo em: %s\n' "$backup"
fi
temporary_runner="$install_dir/.run-cachyos.sh.$$"
cp -- "$script_dir/run-cachyos.sh" "$temporary_runner"
chmod 0755 "$temporary_runner"
mv -f -- "$temporary_runner" "$runner"

printf 'Original preservado em: %s\n' "$original"
printf 'Use este launcher também nos atalhos do desktop: %s\n' "$runner"
exec "$runner" "$@"
