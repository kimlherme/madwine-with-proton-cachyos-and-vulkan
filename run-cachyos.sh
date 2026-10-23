#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
appdir="${MADWINE_APPDIR:-$script_dir/Madwine-CachyOS}"
expected_proton_root="/usr/share/steam/compatibilitytools.d/proton-cachyos-native"
proton_root="${MADWINE_PROTON_ROOT:-$expected_proton_root}"
vulkaninfo_bin="${MADWINE_VULKANINFO:-vulkaninfo}"

proton_ready() {
    [[ -x "$1/proton" ]]
}

is_arch_family() {
    [[ -r /etc/os-release ]] || return 1
    # shellcheck disable=SC1091
    . /etc/os-release
    [[ " ${ID:-} ${ID_LIKE:-} " == *arch* || " ${ID:-} ${ID_LIKE:-} " == *cachyos* || " ${ID:-} ${ID_LIKE:-} " == *omarchy* ]]
}

if ! proton_ready "$proton_root"; then
    # MADWINE_PROTON_ROOT is useful for controlled/custom deployments. For the
    # normal installation, try the CachyOS package on Arch-family systems.
    if [[ -z "${MADWINE_PROTON_ROOT:-}" ]] && is_arch_family && command -v pacman >/dev/null 2>&1; then
        if pacman -Si proton-cachyos-native >/dev/null 2>&1; then
            printf 'Proton CachyOS não encontrado. Tentando instalar proton-cachyos-native com pacman...\n'
            if command -v sudo >/dev/null 2>&1; then
                sudo pacman -S --needed proton-cachyos-native || true
            else
                printf 'Erro: sudo não está disponível para instalar o pacote.\n' >&2
            fi
        elif command -v paru >/dev/null 2>&1; then
            printf 'Pacote ausente nos repositórios do pacman. Tentando instalar proton-cachyos-native com paru...\n'
            paru -S --needed proton-cachyos-native || true
        elif command -v yay >/dev/null 2>&1; then
            printf 'Pacote ausente nos repositórios do pacman. Tentando instalar proton-cachyos-native com yay...\n'
            yay -S --needed proton-cachyos-native || true
        else
            printf 'Não achei o pacote nos repositórios nem um helper AUR (paru/yay).\n' >&2
        fi
    fi

    if ! proton_ready "$proton_root" && [[ -z "${MADWINE_PROTON_ROOT:-}" ]]; then
        if [[ ! -t 0 ]]; then
            printf 'Erro: Proton CachyOS nativo não encontrado em:\n  %s/proton\n' "$expected_proton_root" >&2
            printf 'Execute este launcher em um terminal para informar o caminho do Proton.\n' >&2
            exit 1
        fi

        printf 'Não encontrei o Proton CachyOS nativo. Informe a pasta que contém o arquivo executável "proton".\n'
        read -r -p 'Caminho do Proton (Enter para cancelar): ' manual_proton_path
        [[ -n "$manual_proton_path" ]] || { printf 'Operação cancelada.\n' >&2; exit 1; }

        if [[ -x "$manual_proton_path/proton" ]]; then
            manual_proton_root="$manual_proton_path"
        elif [[ "$(basename -- "$manual_proton_path")" == proton && -x "$manual_proton_path" ]]; then
            manual_proton_root="$(dirname -- "$manual_proton_path")"
        else
            printf 'Erro: não achei um arquivo proton executável nesse caminho.\n' >&2
            exit 1
        fi
        manual_proton_root="$(realpath -e -- "$manual_proton_root")"

        if [[ "$manual_proton_root" != "$expected_proton_root" ]]; then
            if [[ -e "$expected_proton_root" || -L "$expected_proton_root" ]]; then
                printf 'Erro: o destino esperado já existe e não será sobrescrito:\n  %s\n' "$expected_proton_root" >&2
                exit 1
            fi
            read -r -p "Criar com sudo um link em $expected_proton_root para essa instalação? [s/N] " link_answer
            case "$link_answer" in
                s|S|sim|SIM|Sim)
                    command -v sudo >/dev/null 2>&1 || { printf 'Erro: sudo não está disponível para criar o link.\n' >&2; exit 1; }
                    sudo mkdir -p "$(dirname -- "$expected_proton_root")" && sudo ln -s -- "$manual_proton_root" "$expected_proton_root" || {
                        printf 'Erro: não foi possível registrar o Proton no caminho esperado.\n' >&2
                        exit 1
                    }
                    ;;
                *)
                    printf 'Madwine procura o Proton em %s. Não foi criado nenhum link.\n' "$expected_proton_root" >&2
                    exit 1
                    ;;
            esac
        fi
        proton_root="$expected_proton_root"
    fi
fi

if ! proton_ready "$proton_root"; then
    printf 'Erro: Proton CachyOS nativo não encontrado ou não executável em:\n  %s/proton\n' "$proton_root" >&2
    printf 'No Arch/CachyOS/Omarchy, confira se proton-cachyos-native está disponível nos repositórios configurados.\n' >&2
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
