import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from auditor.probes import _output_inventory, run_probe, sandbox_profile, validate_probe


def probe():
    return {"id": "changed-content", "hypothesis": "The index must reflect changed text",
            "files": [{"path": "book.toml", "content": '[book]\ntitle = "Same title"\n'},
                      {"path": "src/SUMMARY.md", "content": "# Summary\n\n- [Page](page.md)\n"},
                      {"path": "src/page.md", "content": "# Page\n\nNew paragraph.\n"}]}


class ProbeValidationTests(unittest.TestCase):
    def test_include_and_summary_cannot_read_outside_supplied_sources(self):
        for directive in ("include", "rustdoc_include", "playground", "playpen"):
            for target in ("../../AGENTS.md", "/etc/passwd", "missing.md"):
                case = probe()
                case["files"][2]["content"] = "{{#" + directive + " " + target + "}}"
                with self.subTest(directive=directive, target=target), self.assertRaises(ValueError):
                    validate_probe(case)
        case = probe()
        case["files"][1]["content"] = "- [Secret](../../secret.md)"
        with self.assertRaises(ValueError):
            validate_probe(case)
        case["files"][1]["content"] = "- [Secret][ref]\n\n[ref]: ../../secret.md"
        with self.assertRaises(ValueError):
            validate_probe(case)

    def test_path_configuration_cannot_escape_fixture(self):
        for config in ('[output.html]\nadditional-css=["../../secret.css"]',
                       '[output.html]\nadditional-js=["/tmp/secret.js"]',
                       '[output.html]\ninput-404="../../secret.md"',
                       '[output.html]\ntheme="../../theme"',
                       '[output.html.redirect]\n"../../overwrite"="page.html"',
                       '[build]\nbuild-dir="../../overwrite"',
                       '[build]\nextra-watch-dirs=["../../outside"]'):
            case = probe()
            case["files"][0]["content"] += config
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate_probe(case)

    def test_supplied_include_and_local_css_are_valid(self):
        case = probe()
        case["files"][0]["content"] += '[output.html]\nadditional-css=["src/style.css"]\n'
        case["files"][2]["content"] += "{{#include snippet.txt:1}}"
        case["files"] += [{"path": "src/style.css", "content": "body { color: black; }"},
                          {"path": "src/snippet.txt", "content": "included words"}]
        self.assertIn("src/snippet.txt", validate_probe(case))

    def test_output_cannot_redirect_evidence_collection_to_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            reference = root / "reference"
            reference.mkdir()
            (reference / "secret").write_text("private")
            output = root / "output"
            output.symlink_to(reference, target_is_directory=True)
            with self.assertRaises(ValueError):
                _output_inventory(output)
            output.unlink()
            output.mkdir()
            os.link(reference / "secret", output / "secret")
            with self.assertRaises(ValueError):
                _output_inventory(output)

    def test_traversal_hidden_duplicate_and_executable_files_rejected(self):
        for name in ("/tmp/x.md", "src/../x.md", "src/.secret.md", "src/tool.sh", "src//x.md", "book.toml"):
            with self.subTest(name=name):
                case = probe()
                case["files"].append({"path": name, "content": "anything"})
                with self.assertRaises(ValueError):
                    validate_probe(case)

    def test_custom_tools_and_external_source_rejected(self):
        for config in ('[preprocessor.foo]\ncommand="evil"', '[output.custom]\n', '[book]\nsrc="../outside"'):
            with self.subTest(config=config):
                case = probe()
                case["files"][0]["content"] = config
                with self.assertRaises(ValueError):
                    validate_probe(case)


@unittest.skipUnless(Path("/usr/bin/sandbox-exec").exists(), "macOS sandbox required")
class ProbeOutcomeTests(unittest.TestCase):
    def run_records(self, records):
        with tempfile.TemporaryDirectory() as temp, patch("auditor.probes._execute", side_effect=copy.deepcopy(records)) as execute:
            result = run_probe(probe(), {"original": Path("original"), "candidate": Path("candidate")}, Path(temp) / "evidence", [])
            return result, execute.call_count

    def test_original_failure_is_not_candidate_finding(self):
        result, count = self.run_records([{"exit_code": 1}, {"exit_code": 1}])
        self.assertEqual(result["status"], "inconclusive")
        self.assertEqual(count, 2)

    def test_unstable_original_is_not_candidate_finding(self):
        result, count = self.run_records([{"exit_code": 0, "inventory": {"index": "one"}}, {"exit_code": 0, "inventory": {"index": "two"}}])
        self.assertEqual(result["status"], "inconclusive")
        self.assertEqual(count, 2)

    def test_changed_candidate_needs_repeated_difference(self):
        good = {"exit_code": 0, "inventory": {"index": "original"}}
        bad = {"exit_code": 0, "inventory": {"index": "changed"}}
        result, count = self.run_records([good, good, bad, bad])
        self.assertEqual(result["status"], "reproduced")
        self.assertEqual(result["differences"]["changed"], ["index"])
        self.assertEqual(count, 4)
        result, _ = self.run_records([good, good, bad, good])
        self.assertEqual(result["status"], "inconclusive")

    def test_candidate_error_is_reproduced_but_timeout_is_inconclusive(self):
        good = {"exit_code": 0, "inventory": {"index": "original"}}
        for failure, status in (({"exit_code": 1}, "reproduced"), ({"exit_code": -9, "timed_out": True}, "inconclusive")):
            result, _ = self.run_records([good, good, failure, failure])
            self.assertEqual(result["status"], status)

    def test_matching_candidate_is_not_reproduced(self):
        good = {"exit_code": 0, "inventory": {"index": "original"}}
        result, _ = self.run_records([good] * 4)
        self.assertEqual(result["status"], "not_reproduced")


@unittest.skipUnless(Path("/usr/bin/sandbox-exec").exists(), "macOS sandbox required")
class SandboxTests(unittest.TestCase):
    def test_sandbox_blocks_protected_reads_external_writes_network_and_fork(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            scratch = root / "scratch"
            scratch.mkdir()
            secret = root / "reference.txt"
            secret.write_text("reference")
            executable = scratch / "python"
            framework_binary = Path(sys.base_prefix) / "Resources/Python.app/Contents/MacOS/Python"
            shutil.copy2(framework_binary if framework_binary.exists() else sys.executable, executable)
            profile = sandbox_profile(scratch, executable, [root])
            code = '''import errno,json,os,socket,sys
results = {}
actions = {
 "read": lambda: open(sys.argv[1]).read(),
 "write": lambda: open(sys.argv[2], "w"),
 "network": lambda: socket.create_connection(("127.0.0.1", 9), timeout=1),
 "fork": os.fork,
}
for name, action in actions.items():
 try:
  value = action()
  if name == "fork" and value == 0: os._exit(0)
  results[name] = "allowed"
 except OSError as error:
  results[name] = error.errno
open("allowed.txt", "w").write("scratch write permitted")
print(json.dumps(results))
'''
            command = ["/usr/bin/sandbox-exec", "-p", profile, str(executable), "-I", "-c", code, str(secret), str(root / "outside.txt")]
            result = subprocess.run(command, cwd=scratch, env={"PATH": "/usr/bin:/bin", "HOME": str(scratch), "PYTHONHOME": sys.base_prefix}, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            denied = json.loads(result.stdout)
            self.assertEqual(denied, {"read": 1, "write": 1, "network": 1, "fork": 1})
            self.assertTrue((scratch / "allowed.txt").is_file())
            self.assertFalse((root / "outside.txt").exists())


if __name__ == "__main__":
    unittest.main()
