from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell.exe") or "powershell.exe"


class InstallerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="Semantic SRS tests ")
        self.local = Path(self.temp.name) / "Local App Data"
        self.profile = Path(self.temp.name) / "User Profile"
        self.local.mkdir()
        self.profile.mkdir()
        self.env = os.environ.copy()
        self.env["LOCALAPPDATA"] = str(self.local)
        self.env["USERPROFILE"] = str(self.profile)

    def tearDown(self):
        self.temp.cleanup()

    def run_script(self, name, *arguments, check=True):
        command = [
            POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(REPO / name), *arguments,
        ]
        return subprocess.run(command, env=self.env, text=True, capture_output=True, check=check)

    def test_codex_default_stages_both_plugins_and_is_idempotent(self):
        args = ("-Host", "Codex", "-NonInteractive", "-SkipHostRegistration", "-SkipDependencies")
        self.run_script("setup.ps1", *args)
        self.run_script("setup.ps1", *args)
        root = self.local / "SemanticSRS"
        self.assertTrue((root / "apps/current/semantic-srs/server.py").exists())
        self.assertTrue((root / "apps/current/local-rag/server.py").exists())
        state = json.loads((root / "install.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(state["host"], "Codex")

    def test_claude_without_local_rag(self):
        self.run_script(
            "setup.ps1", "-Host", "Claude", "-NonInteractive",
            "-SkipLocalRag", "-SkipHostRegistration", "-SkipDependencies",
        )
        root = self.local / "SemanticSRS"
        self.assertTrue((root / "apps/current/semantic-srs").exists())
        self.assertFalse((root / "apps/current/local-rag").exists())

    def test_both_hosts_value_and_path_with_spaces(self):
        self.run_script(
            "setup.ps1", "-Host", "Both", "-NonInteractive",
            "-SkipHostRegistration", "-SkipDependencies",
        )
        state = json.loads((self.local / "SemanticSRS/install.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(state["host"], "Both")

    def test_fake_host_clis_receive_marketplace_and_plugin_commands(self):
        fake_bin = Path(self.temp.name) / "fake hosts"
        fake_bin.mkdir()
        log = Path(self.temp.name) / "host.log"
        for name in ("codex", "claude"):
            (fake_bin / f"{name}.cmd").write_text(
                f'@echo off\r\necho {name} %*>>"{log}"\r\nexit /b 0\r\n',
                encoding="ascii",
            )
        self.env["PATH"] = str(fake_bin) + os.pathsep + self.env["PATH"]
        self.run_script(
            "setup.ps1", "-Host", "Both", "-NonInteractive", "-SkipDependencies",
        )
        calls = log.read_text(encoding="utf-8")
        self.assertIn("codex plugin marketplace add", calls)
        self.assertIn("codex plugin add semantic-srs@semantic-srs", calls)
        self.assertIn("claude plugin install local-rag@semantic-srs", calls)

    def test_legacy_rag_migration_and_conflict_refusal(self):
        legacy = self.profile / "local-rag-data"
        legacy.mkdir()
        (legacy / "legacy.txt").write_text("legacy", encoding="utf-8")
        args = ("-Host", "Codex", "-NonInteractive", "-MigrateLegacy", "-SkipHostRegistration", "-SkipDependencies")
        self.run_script("setup.ps1", *args)
        self.assertTrue((self.local / "SemanticSRS/rag/legacy.txt").exists())
        (legacy / "other.txt").write_text("other", encoding="utf-8")
        failed = self.run_script("setup.ps1", *args, check=False)
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("Refusing to merge", failed.stderr)

    def test_uninstall_preserves_then_purges_data(self):
        args = ("-Host", "Codex", "-NonInteractive", "-SkipHostRegistration", "-SkipDependencies")
        self.run_script("setup.ps1", *args)
        data = self.local / "SemanticSRS/data/marker.txt"
        data.write_text("keep", encoding="utf-8")
        self.run_script("uninstall.ps1", "-Host", "Codex", "-SkipHostRegistration")
        self.assertTrue(data.exists())
        self.run_script("uninstall.ps1", "-Host", "Codex", "-SkipHostRegistration", "-PurgeData")
        self.assertFalse(data.exists())


if __name__ == "__main__":
    unittest.main()
