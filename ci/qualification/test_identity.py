"""Exercise the qualification worker's identity gate using real local Git clones."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

APPROVED = "7dc4ecbf4d29817e723e04ae94b14f1326764f61"
REPOSITORY = "joris97jansen/rust-url"
SOURCE = Path(sys.argv.pop(1)).resolve()
WORKER = Path(__file__).with_name("run.py")
RESULTS = []


class SourceIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="url-source-identity-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.output = self.root / "results"
        subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", str(SOURCE), str(self.source)], check=True)
        self.git("remote", "set-url", "origin", "https://github.com/" + REPOSITORY + ".git")
        self.git("checkout", "--quiet", "--detach", APPROVED)

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.source), *args], text=True).strip()

    def worker(self, lane="native", **overrides):
        env = os.environ.copy()
        env.pop("QUALIFICATION_REVISION", None)
        env.pop("QUALIFICATION_TOOLCHAIN", None)
        env.update(QUALIFICATION_OUTPUT=str(self.output), GITHUB_REPOSITORY=REPOSITORY)
        env.update(overrides)
        result = subprocess.run([sys.executable, str(WORKER), str(self.source), "borrowser", lane],
                                env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        RESULTS.append({"case": self.id(), "exit": result.returncode, "output": result.stdout,
                        "prepared_lock_exists": (self.output / "qualified-Cargo.lock").exists(),
                        "test_commands_exist": (self.output / "native-commands.json").exists()})
        return result

    def rejected(self, reason, **overrides):
        result = self.worker(**overrides)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(reason, result.stdout)
        # Rejection must precede dependency preparation, compiler calls and tests.
        self.assertEqual(list(self.output.iterdir()), [], result.stdout)
        self.assertFalse((self.source / "Cargo.lock").exists())

    def test_approved_source_accepted(self):
        result = self.worker(lane="prepare")
        self.assertEqual(result.returncode, 0, result.stdout)
        identity = json.loads((self.output / "prepare-identity.json").read_text())
        self.assertEqual(identity["source_revision"], APPROVED)
        self.assertEqual(identity["source_repository"], "https://github.com/" + REPOSITORY + ".git")

    def test_matching_environment_is_only_an_assertion(self):
        result = self.worker(lane="prepare", QUALIFICATION_REVISION=APPROVED)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_wrong_commit_rejected(self):
        self.git("checkout", "--quiet", "--detach", APPROVED + "^")
        self.rejected("Source revision does not match the approved commit")

    def test_wrong_commit_cannot_override_pin(self):
        self.git("checkout", "--quiet", "--detach", APPROVED + "^")
        self.rejected("Source revision does not match the approved commit",
                      QUALIFICATION_REVISION=self.git("rev-parse", "HEAD"))

    def test_wrong_environment_on_approved_commit_rejected(self):
        self.rejected("Environment revision contradicts the approved commit",
                      QUALIFICATION_REVISION=self.git("rev-parse", APPROVED + "^"))

    def test_wrong_origin_cannot_be_hidden_by_environment(self):
        self.git("remote", "set-url", "origin", "https://github.com/servo/rust-url.git")
        self.rejected("Source repository does not match the approved repository",
                      QUALIFICATION_REVISION=APPROVED, GITHUB_REPOSITORY=REPOSITORY)

    def test_wrong_workflow_repository_rejected(self):
        self.rejected("Workflow repository contradicts the approved repository",
                      GITHUB_REPOSITORY="servo/rust-url")

    def test_dirty_source_rejected(self):
        (self.source / "unexpected.txt").write_text("dirty checkout\n")
        self.rejected("Source checkout must be clean")


if __name__ == "__main__":
    suite = unittest.main(verbosity=2, exit=False)
    output = Path(os.environ.get("QUALIFICATION_OUTPUT", "qualification-results"))
    output.mkdir(parents=True, exist_ok=True)
    (output / "source-identity-tests.json").write_text(json.dumps(RESULTS, indent=2) + "\n")
    sys.exit(not suite.result.wasSuccessful())
