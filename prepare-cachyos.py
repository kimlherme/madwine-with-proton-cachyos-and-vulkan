#!/usr/bin/env python3
"""Prepare the fixed Madwine v0.1.22 AppImage for CachyOS Proton."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile


RELEASE = "v0.1.22"
APPIMAGE_SHA256 = "f6a05177f186c96dde5b948ed12c16e9ca9e85e703f947be8e267da3a584501b"
ORIGINAL_ELF_SHA256 = "8c9079e40659145e9de979601d2d9d740f5c7a157f76d9385b9c64f55215a42b"
PATCHED_ELF_SHA256 = "512837169e6b1a16ac454ecb847e08b466d899254fbda7349e6ecd1e581b7be6"
SQUASHFS_OFFSET = 944_632
ELF_PATH = Path("usr/bin/madwine")

OLD_PROTON = b"GE-Proton11-5-x86_64"
NEW_PROTON = b"proton-cachyos-native"
OLD_COMPAT_DIR = b".local/share/Steam/compatibilitytools.d"
NEW_COMPAT_DIR = b"/usr/share/steam/compatibilitytools.d"
OLD_PROTON_FILE_OFFSET = 0x48D347
NEW_PROTON_FILE_OFFSET = 0x74BFE8
COMPAT_DIR_FILE_OFFSET = 0x610781
OLD_SEGMENT_SIZE = 0x74BFE8
RX_SEGMENT_OFFSET = 0x74C000
RX_SEGMENT_VADDR = 0x74D000

# Raw ELF virtual addresses observed in the pinned v0.1.22 binary. Each LEA
# points at the shared GE name; its following mov r8d, 0x14 supplies the Rust
# string length.
PROTON_REFERENCES = (
    (0xA060B4, 0xA060BB),
    (0xA8D4B7, 0xA8D4C1),
    (0xA8D5BD, 0xA8D5C7),
    (0xA8D6C3, 0xA8D6CD),
    (0xA8D7C9, 0xA8D7D3),
    (0xA8D8CF, 0xA8D8D9),
)
COMPAT_DIR_REFERENCE = 0xA8D48E
COMPAT_DIR_LENGTH_IMMEDIATE = 0xA8D49C


class PatchError(Exception):
    """The input is not the exact binary layout this patch supports."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _offset(raw_va: int) -> int:
    """Map a code VA in the observed RX segment to its ELF file offset."""
    if raw_va < RX_SEGMENT_VADDR:
        raise PatchError(f"Endereço de código inesperado: {raw_va:#x}")
    return RX_SEGMENT_OFFSET + (raw_va - RX_SEGMENT_VADDR)


def _check_range(data: bytearray, offset: int, size: int, what: str) -> None:
    if offset < 0 or offset + size > len(data):
        raise PatchError(f"Arquivo truncado ao verificar {what} em {offset:#x}")


def _read_phdrs(data: bytearray) -> tuple[int, int, list[tuple[int, int]]]:
    _check_range(data, 0, 64, "cabeçalho ELF")
    if data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 1:
        raise PatchError("O executável não é ELF64 little-endian")
    e_type, e_machine = struct.unpack_from("<HH", data, 16)
    if e_type != 3 or e_machine != 62:
        raise PatchError("O executável não é um ELF x86_64 PIE compatível")
    e_entry = struct.unpack_from("<Q", data, 24)[0]
    e_phoff = struct.unpack_from("<Q", data, 32)[0]
    e_phentsize, e_phnum = struct.unpack_from("<HH", data, 54)
    if e_entry != RX_SEGMENT_VADDR or e_phentsize != 56 or e_phnum != 13:
        raise PatchError("Cabeçalho ELF diverge do release v0.1.22 analisado")
    _check_range(data, e_phoff, e_phentsize * e_phnum, "tabela de segmentos ELF")
    headers: list[tuple[int, int]] = []
    loads: list[tuple[int, int, int, int, int, int, int]] = []
    for index in range(e_phnum):
        at = e_phoff + index * e_phentsize
        p_type, p_flags, p_offset, p_vaddr, _p_paddr, p_filesz, p_memsz, _p_align = struct.unpack_from(
            "<IIQQQQQQ", data, at
        )
        headers.append((at, p_type))
        if p_type == 1:
            loads.append((at, p_flags, p_offset, p_vaddr, p_filesz, p_memsz, index))
    first_ro = [entry for entry in loads if entry[1:4] == (4, 0, 0)]
    rx = [entry for entry in loads if entry[1:4] == (5, RX_SEGMENT_OFFSET, RX_SEGMENT_VADDR)]
    if len(first_ro) != 1 or len(rx) != 1:
        raise PatchError("Segmentos PT_LOAD esperados não encontrados")
    ro = first_ro[0]
    rx_segment = rx[0]
    if ro[4] != OLD_SEGMENT_SIZE or ro[5] != OLD_SEGMENT_SIZE:
        raise PatchError("Tamanho do primeiro PT_LOAD diverge do release analisado")
    if rx_segment[4] != 0x76F970 or rx_segment[5] != 0x76F970:
        raise PatchError("Tamanho do PT_LOAD executável diverge do release analisado")
    return ro[0], e_phentsize, headers


def patch_elf(original: bytes, expected_sha256: str = ORIGINAL_ELF_SHA256) -> bytes:
    """Patch one exact ELF, refusing unknown hashes or any unexpected bytes.

    expected_sha256 is an injectable test seam; the CLI always uses the
    pinned production hash above.
    """
    actual_hash = sha256_bytes(original)
    if actual_hash != expected_sha256:
        raise PatchError(f"SHA-256 ELF inesperado: {actual_hash}")
    data = bytearray(original)
    ro_phdr_at, _phentsize, _headers = _read_phdrs(data)

    _check_range(data, OLD_PROTON_FILE_OFFSET, len(OLD_PROTON) + 25, "nome GE e string adjacente")
    if data[OLD_PROTON_FILE_OFFSET : OLD_PROTON_FILE_OFFSET + len(OLD_PROTON)] != OLD_PROTON:
        raise PatchError("Nome GE esperado não está no offset analisado")
    if data[OLD_PROTON_FILE_OFFSET + len(OLD_PROTON) : OLD_PROTON_FILE_OFFSET + len(OLD_PROTON) + 25] != b"using the copy from Steam":
        raise PatchError("String compartilhada adjacente ao nome GE diverge")
    _check_range(data, NEW_PROTON_FILE_OFFSET, 24, "folga após .eh_frame")
    if any(data[NEW_PROTON_FILE_OFFSET : NEW_PROTON_FILE_OFFSET + 24]):
        raise PatchError("A folga ELF para o novo nome não está zerada")

    for lea_va, length_va in PROTON_REFERENCES:
        lea_at = _offset(lea_va)
        length_at = _offset(length_va)
        _check_range(data, lea_at, 7, "referência ao nome GE")
        if data[lea_at : lea_at + 3] != b"\x48\x8d\x0d":
            raise PatchError(f"Instrução LEA inesperada em {lea_va:#x}")
        old_disp = struct.unpack_from("<i", data, lea_at + 3)[0]
        old_target = lea_va + 7 + old_disp
        if old_target != OLD_PROTON_FILE_OFFSET:
            raise PatchError(f"Referência em {lea_va:#x} não aponta para o nome GE esperado")
        new_disp = NEW_PROTON_FILE_OFFSET - (lea_va + 7)
        if not -(2**31) <= new_disp < 2**31:
            raise PatchError("Nova referência LEA excede o alcance de 32 bits")
        data[lea_at + 3 : lea_at + 7] = struct.pack("<i", new_disp)

        length_at = _offset(length_va)
        _check_range(data, length_at, 6, "comprimento do nome Proton")
        if data[length_at : length_at + 2] != b"\x41\xb8":
            raise PatchError(f"Instrução de comprimento inesperada em {length_va:#x}")
        old_length = struct.unpack_from("<I", data, length_at + 2)[0]
        if old_length != len(OLD_PROTON):
            raise PatchError(f"Comprimento antigo inesperado em {length_va:#x}: {old_length}")
        struct.pack_into("<I", data, length_at + 2, len(NEW_PROTON))

    compat_at = _offset(COMPAT_DIR_REFERENCE)
    _check_range(data, compat_at, 7, "referência ao diretório Steam")
    if data[compat_at : compat_at + 3] != b"\x48\x8d\x0d":
        raise PatchError("Instrução LEA do diretório Steam inesperada")
    compat_disp = struct.unpack_from("<i", data, compat_at + 3)[0]
    if COMPAT_DIR_REFERENCE + 7 + compat_disp != COMPAT_DIR_FILE_OFFSET:
        raise PatchError("LEA do diretório não aponta para o caminho analisado")
    if data[COMPAT_DIR_FILE_OFFSET : COMPAT_DIR_FILE_OFFSET + len(OLD_COMPAT_DIR)] != OLD_COMPAT_DIR:
        raise PatchError("Sufixo de diretório Steam inesperado")
    compat_len_at = _offset(COMPAT_DIR_LENGTH_IMMEDIATE)
    _check_range(data, compat_len_at - 2, 6, "comprimento do diretório Steam")
    if data[compat_len_at - 2 : compat_len_at] != b"\x41\xb8":
        raise PatchError("Instrução de comprimento do diretório Steam inesperada")
    old_compat_length = struct.unpack_from("<I", data, compat_len_at)[0]
    if old_compat_length != len(OLD_COMPAT_DIR):
        raise PatchError("Comprimento do diretório Steam inesperado")

    data[NEW_PROTON_FILE_OFFSET : NEW_PROTON_FILE_OFFSET + len(NEW_PROTON)] = NEW_PROTON
    data[COMPAT_DIR_FILE_OFFSET : COMPAT_DIR_FILE_OFFSET + len(NEW_COMPAT_DIR)] = NEW_COMPAT_DIR
    struct.pack_into("<I", data, compat_len_at, len(NEW_COMPAT_DIR))
    struct.pack_into("<Q", data, ro_phdr_at + 32, OLD_SEGMENT_SIZE + len(NEW_PROTON))
    struct.pack_into("<Q", data, ro_phdr_at + 40, OLD_SEGMENT_SIZE + len(NEW_PROTON))
    return bytes(data)


def _prepared_matches(output: Path, source_hash: str) -> bool:
    manifest_path = output / "madwine-cachyos-manifest.json"
    binary_path = output / ELF_PATH
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return (
            (output / "AppRun").is_file()
            and os.access(output / "AppRun", os.X_OK)
            and (output / "AppRun.wrapped").is_file()
            and manifest.get("release") == RELEASE
            and manifest.get("source_appimage_sha256") == source_hash
            and manifest.get("source_elf_sha256") == ORIGINAL_ELF_SHA256
            and manifest.get("patched_elf_sha256") == PATCHED_ELF_SHA256
            and manifest.get("patched_elf_sha256") == sha256_file(binary_path)
        )
    except (OSError, ValueError, TypeError):
        return False


def prepare(appimage: Path, output: Path, unsquashfs: str) -> str:
    appimage = appimage.expanduser().resolve()
    output = output.expanduser().absolute()
    if not appimage.is_file():
        raise PatchError(f"AppImage não encontrado: {appimage}")
    source_hash = sha256_file(appimage)
    if source_hash != APPIMAGE_SHA256:
        raise PatchError(f"SHA-256 AppImage inesperado: {source_hash}; somente {RELEASE} é suportado")
    if output.exists():
        if _prepared_matches(output, source_hash):
            return sha256_file(output / ELF_PATH)
        raise PatchError(f"O destino já existe e não corresponde a uma preparação verificada: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".madwine-cachyos-", dir=output.parent) as temp_name:
        temp_root = Path(temp_name)
        squashfs = temp_root / "root.squashfs"
        appdir = temp_root / "appdir"
        with appimage.open("rb") as source, squashfs.open("wb") as target:
            source.seek(SQUASHFS_OFFSET)
            shutil.copyfileobj(source, target)
        result = subprocess.run(
            [unsquashfs, "-no-progress", "-quiet", "-d", str(appdir), str(squashfs)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode:
            details = result.stderr.strip() or result.stdout.strip()
            raise PatchError(f"Falha ao extrair SquashFS com {unsquashfs}: {details}")
        squashfs.unlink()
        binary = appdir / ELF_PATH
        if not binary.is_file():
            raise PatchError(f"Executável ausente no AppDir extraído: {ELF_PATH}")
        if not (appdir / "AppRun").is_file() or not os.access(appdir / "AppRun", os.X_OK):
            raise PatchError("AppRun ausente ou não executável no AppDir extraído")
        if not (appdir / "AppRun.wrapped").is_file():
            raise PatchError("AppRun.wrapped ausente no AppDir extraído")
        elf_bytes = binary.read_bytes()
        if sha256_bytes(elf_bytes) != ORIGINAL_ELF_SHA256:
            raise PatchError("SHA-256 do executável extraído difere do v0.1.22 analisado")
        patched = patch_elf(elf_bytes)
        binary.write_bytes(patched)
        patched_hash = sha256_bytes(patched)
        if patched_hash != PATCHED_ELF_SHA256:
            raise PatchError(f"Hash do patch produzido não corresponde ao patch validado: {patched_hash}")
        manifest = {
            "release": RELEASE,
            "source_appimage_sha256": source_hash,
            "source_elf_sha256": ORIGINAL_ELF_SHA256,
            "patched_elf_sha256": patched_hash,
            "changes": [
                "GE-Proton11-5-x86_64 -> proton-cachyos-native (6 references)",
                ".local/share/Steam/compatibilitytools.d -> /usr/share/steam/compatibilitytools.d",
                "first read-only PT_LOAD extended by 21 bytes into verified zero padding",
            ],
        }
        (appdir / "madwine-cachyos-manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(appdir, output)
        return patched_hash


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--appimage", required=True, type=Path, help="AppImage original v0.1.22")
    parser.add_argument("--output", required=True, type=Path, help="Diretório AppDir preparado; deve ainda não existir")
    parser.add_argument("--unsquashfs", default="unsquashfs", help="Executável squashfs-tools (padrão: PATH)")
    args = parser.parse_args(argv)
    try:
        result_hash = prepare(args.appimage, args.output, args.unsquashfs)
    except (PatchError, OSError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    print(f"Madwine {RELEASE} preparado em: {args.output}")
    print(f"SHA-256 ELF corrigido: {result_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
