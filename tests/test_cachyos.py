import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PATCHER_PATH = ROOT / "prepare-cachyos.py"
spec = importlib.util.spec_from_file_location("prepare_cachyos", PATCHER_PATH)
patcher = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(patcher)


def fixture_elf():
    """Build a sparse-layout fixture with the exact offsets the patch checks."""
    blob = bytearray(15_683_048)
    blob[:4] = b"\x7fELF"
    blob[4:7] = b"\x02\x01\x01"
    struct.pack_into("<HH", blob, 16, 3, 62)
    struct.pack_into("<Q", blob, 24, patcher.RX_SEGMENT_VADDR)
    struct.pack_into("<Q", blob, 32, 64)
    struct.pack_into("<HH", blob, 54, 56, 13)

    # First read-only PT_LOAD and executable PT_LOAD.
    struct.pack_into("<IIQQQQQQ", blob, 64, 1, 4, 0, 0, 0, patcher.OLD_SEGMENT_SIZE, patcher.OLD_SEGMENT_SIZE, 0x1000)
    struct.pack_into("<IIQQQQQQ", blob, 120, 1, 5, patcher.RX_SEGMENT_OFFSET, patcher.RX_SEGMENT_VADDR, patcher.RX_SEGMENT_VADDR, 0x76F970, 0x76F970, 0x1000)

    blob[patcher.OLD_PROTON_FILE_OFFSET:patcher.OLD_PROTON_FILE_OFFSET + 20] = patcher.OLD_PROTON
    blob[patcher.OLD_PROTON_FILE_OFFSET + 20:patcher.OLD_PROTON_FILE_OFFSET + 45] = b"using the copy from Steam"
    blob[patcher.COMPAT_DIR_FILE_OFFSET:patcher.COMPAT_DIR_FILE_OFFSET + len(patcher.OLD_COMPAT_DIR)] = patcher.OLD_COMPAT_DIR

    for lea_va, length_va in patcher.PROTON_REFERENCES:
        at = patcher._offset(lea_va)
        blob[at:at + 3] = b"\x48\x8d\x0d"
        struct.pack_into("<i", blob, at + 3, patcher.OLD_PROTON_FILE_OFFSET - (lea_va + 7))
        length_at = patcher._offset(length_va)
        blob[length_at:length_at + 2] = b"\x41\xb8"
        struct.pack_into("<I", blob, length_at + 2, len(patcher.OLD_PROTON))

    compat_at = patcher._offset(patcher.COMPAT_DIR_REFERENCE)
    blob[compat_at:compat_at + 3] = b"\x48\x8d\x0d"
    struct.pack_into("<i", blob, compat_at + 3, patcher.COMPAT_DIR_FILE_OFFSET - (patcher.COMPAT_DIR_REFERENCE + 7))
    compat_len_at = patcher._offset(patcher.COMPAT_DIR_LENGTH_IMMEDIATE)
    blob[compat_len_at - 2:compat_len_at] = b"\x41\xb8"
    struct.pack_into("<I", blob, compat_len_at, len(patcher.OLD_COMPAT_DIR))
    return blob


class PatchTests(unittest.TestCase):
    def test_patches_every_reference_and_preserves_shared_string(self):
        original = fixture_elf()
        output = patcher.patch_elf(original, hashlib.sha256(original).hexdigest())

        self.assertEqual(output[patcher.NEW_PROTON_FILE_OFFSET:patcher.NEW_PROTON_FILE_OFFSET + 21], patcher.NEW_PROTON)
        self.assertEqual(output[patcher.OLD_PROTON_FILE_OFFSET:patcher.OLD_PROTON_FILE_OFFSET + 45], patcher.OLD_PROTON + b"using the copy from Steam")
        self.assertEqual(output[patcher.COMPAT_DIR_FILE_OFFSET:patcher.COMPAT_DIR_FILE_OFFSET + 37], patcher.NEW_COMPAT_DIR)
        self.assertEqual(len(patcher.NEW_COMPAT_DIR), 37)
        self.assertEqual(output[patcher.NEW_PROTON_FILE_OFFSET + 21:patcher.NEW_PROTON_FILE_OFFSET + 24], b"\0\0\0")

        for lea_va, length_va in patcher.PROTON_REFERENCES:
            lea_at = patcher._offset(lea_va)
            disp = struct.unpack_from("<i", output, lea_at + 3)[0]
            self.assertEqual(lea_va + 7 + disp, patcher.NEW_PROTON_FILE_OFFSET)
            self.assertEqual(struct.unpack_from("<I", output, patcher._offset(length_va) + 2)[0], 21)

        phoff = struct.unpack_from("<Q", output, 32)[0]
        self.assertEqual(struct.unpack_from("<Q", output, phoff + 32)[0], patcher.OLD_SEGMENT_SIZE + 21)
        self.assertEqual(struct.unpack_from("<Q", output, phoff + 40)[0], patcher.OLD_SEGMENT_SIZE + 21)

    def test_rejects_wrong_hash_and_unexpected_instruction(self):
        original = fixture_elf()
        with self.assertRaisesRegex(patcher.PatchError, "SHA-256"):
            patcher.patch_elf(original)

        changed = bytearray(original)
        changed[patcher._offset(patcher.PROTON_REFERENCES[0][0])] = 0x90
        with self.assertRaisesRegex(patcher.PatchError, "LEA inesperada"):
            patcher.patch_elf(changed, hashlib.sha256(changed).hexdigest())

    def test_prepare_refuses_unrecognized_appimage_before_extraction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "unknown.AppImage"
            source.write_bytes(b"not the pinned release")
            with self.assertRaisesRegex(patcher.PatchError, "SHA-256 AppImage inesperado"):
                patcher.prepare(source, root / "prepared", "no-such-unsquashfs")
            self.assertFalse((root / "prepared").exists())


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="madwine test ")
        self.root = Path(self.temp.name)
        self.appdir = self.root / "App Dir"
        self.appdir.mkdir()
        self.proton_root = self.root / "Proton area" / "proton-cachyos-native"
        self.proton_root.mkdir(parents=True)
        self.proton = self.proton_root / "proton"
        self.proton.write_text("#!/bin/sh\nexit 0\n")
        self.proton.chmod(0o755)
        self.vulkaninfo = self.root / "vulkaninfo mock"
        self.vulkaninfo.write_text("#!/bin/sh\nprintf 'Devices:\\nGPU0:\\n  deviceName = Mock Vulkan GPU\\n'\n")
        self.vulkaninfo.chmod(0o755)
        self.capture = self.root / "capture.json"
        self.apprun = self.appdir / "AppRun"
        self.apprun.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "json.dump({'args': sys.argv[1:], 'wined3d': os.environ.get('PROTON_USE_WINED3D'), "
            "'wined3d11': os.environ.get('PROTON_USE_WINED3D11'), 'protonpath': os.environ.get('PROTONPATH')}, "
            "open(os.environ['CAPTURE_FILE'], 'w'))\n"
            "raise SystemExit(int(os.environ.get('APP_EXIT', '0')))\n"
        )
        self.apprun.chmod(0o755)
        self.config_home = self.root / "config home"
        self.env = os.environ.copy()
        self.env.update({
            "MADWINE_APPDIR": str(self.appdir),
            "MADWINE_PROTON_ROOT": str(self.proton_root),
            "MADWINE_VULKANINFO": str(self.vulkaninfo),
            "XDG_CONFIG_HOME": str(self.config_home),
            "CAPTURE_FILE": str(self.capture),
            "APP_EXIT": "23",
            "PROTON_USE_WINED3D": "1",
            "PROTON_USE_WINED3D11": "1",
            "PROTONPATH": "/tmp/old-ge",
        })

    def tearDown(self):
        self.temp.cleanup()

    def run_launcher(self, *args):
        return subprocess.run([str(ROOT / "run-cachyos.sh"), *args], env=self.env, text=True, capture_output=True)

    def test_launcher_checks_vulkan_sets_scoped_environment_and_preserves_args_status(self):
        config = self.config_home / "madwine" / "config.json"
        config.parent.mkdir(parents=True)
        config.write_text('{"theme":"dark","reuseSteamProton":false}\n')

        result = self.run_launcher("argument with spaces", "", "--run")
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertIn("Mock Vulkan GPU", result.stdout)
        captured = json.loads(self.capture.read_text())
        self.assertEqual(captured["args"], ["argument with spaces", "", "--run"])
        self.assertEqual(captured["wined3d"], "0")
        self.assertIsNone(captured["wined3d11"])
        self.assertIsNone(captured["protonpath"])
        self.assertEqual(json.loads(config.read_text()), {"theme": "dark", "reuseSteamProton": True})
        backups = list(config.parent.glob("config.json.pre-cachyos-*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(json.loads(backups[0].read_text())["reuseSteamProton"], False)

    def test_launcher_fails_clearly_without_proton(self):
        self.proton.chmod(0o644)
        result = self.run_launcher("--run")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Proton CachyOS nativo não encontrado", result.stderr)
        self.assertFalse(self.capture.exists())

    def test_launcher_fails_when_vulkan_has_no_device(self):
        self.vulkaninfo.write_text("#!/bin/sh\nprintf 'Devices:\\n'\n")
        self.vulkaninfo.chmod(0o755)
        result = self.run_launcher("--run")
        self.assertEqual(result.returncode, 1)
        self.assertIn("não listou nenhum dispositivo", result.stderr)
        self.assertFalse(self.capture.exists())


if __name__ == "__main__":
    unittest.main()
