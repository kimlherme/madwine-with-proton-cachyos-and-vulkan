#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
appdir="${MADWINE_APPDIR:-$script_dir/Madwine-CachyOS}"
proton_root="${MADWINE_PROTON_ROOT:-/usr/share/steam/compatibilitytools.d/proton-cachyos-native}"
vulkaninfo_bin="${MADWINE_VULKANINFO:-vulkaninfo}"

if [[ "$(basename -- "$proton_root")" != "proton-cachyos-native" || ! -x "$proton_root/proton" ]]; then
    printf 'Erro: Proton CachyOS nativo não encontrado ou não executável em:\n  %s/proton\nInstale proton-cachyos-native em /usr/share/steam/compatibilitytools.d.\n' "$proton_root" >&2
    exit 1
fi

if [[ "$vulkaninfo_bin" == */* ]]; then
    [[ -x "$vulkaninfo_bin" ]] || { printf 'Erro: vulkaninfo não executável: %s\n' "$vulkaninfo_bin" >&2; exit 1; }
else
    command -v "$vulkaninfo_bin" >/dev/null 2>&1 || { printf 'Erro: vulkaninfo não encontrado; instale vulkan-tools e confira os drivers Vulkan.\n' >&2; exit 1; }
fi

vulkan_summary="$("$vulkaninfo_bin" --summary 2>&1)" || {
    printf 'Erro: vulkaninfo --summary falhou; nenhum caminho Vulkan utilizável foi confirmado.\n%s\n' "$vulkan_summary" >&2
    exit 1
}
if ! grep -Eq 'GPU[[:space:]_-]*[0-9]+:' <<<"$vulkan_summary"; then
    printf 'Erro: Vulkan não listou nenhum dispositivo gráfico.\n%s\n' "$vulkan_summary" >&2
    exit 1
fi
printf '%s\n' "$vulkan_summary"

app_run="$appdir/AppRun"
[[ -x "$app_run" ]] || { printf 'Erro: AppRun do Madwine preparado não encontrado: %s\n' "$app_run" >&2; exit 1; }

config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
config_file="$config_home/madwine/config.json"
python3 - "$config_file" <<'PY'
import datetime
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
if path.exists():
    try:
        raw = path.read_text(encoding="utf-8")
        config = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Erro: não foi possível ler a configuração Madwine {path}: {exc}")
    if not isinstance(config, dict):
        raise SystemExit(f"Erro: a configuração Madwine não é um objeto JSON: {path}")
else:
    raw = None
    config = {}

if config.get("reuseSteamProton") is not True:
    if raw is not None:
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = path.with_name(f"config.json.pre-cachyos-{timestamp}.bak")
        suffix = 1
        while backup.exists():
            backup = path.with_name(f"config.json.pre-cachyos-{timestamp}-{suffix}.bak")
            suffix += 1
        shutil.copy2(path, backup)

    config["reuseSteamProton"] = True
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, temporary = tempfile.mkstemp(prefix=".config.json.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(config, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
PY

# O binário também tenta ativar WineD3D quando a variável está ausente. Definir
# zero aqui impede esse padrão; remover a variável secundária evita conflito.
export PROTON_USE_WINED3D=0
unset PROTON_USE_WINED3D11
unset PROTONPATH
exec "$app_run" "$@"
