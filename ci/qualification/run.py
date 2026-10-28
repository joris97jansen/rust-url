"""Run existing rust-url qualification commands; preserve every command's status."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib

APPROVED_REVISION = "7dc4ecbf4d29817e723e04ae94b14f1326764f61"
APPROVED_REPOSITORY = "joris97jansen/rust-url"
ROOT = Path(__file__).resolve().parent
INPUTS = json.loads((ROOT / "inputs.json").read_text())
FINDINGS = json.loads((ROOT / "findings.json").read_text())
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("source", type=Path)
parser.add_argument("graph", choices=INPUTS["graphs"])
parser.add_argument("lane", choices=["prepare", "vendor-msrv", "native", "pinned", "idna", "idna-baseline", "lint", "sanitizer", "fuzz", "wasm", "no-std"])
args = parser.parse_args()
SOURCE = args.source.resolve()
OUT = Path(os.environ.get("QUALIFICATION_OUTPUT", "qualification-results")).resolve()
OUT.mkdir(parents=True, exist_ok=True)
ENV = os.environ.copy()
ENV.update(CARGO_BUILD_JOBS="2", RUST_TEST_THREADS="1", PYTHONUTF8="1")
records = []


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(label, command, cwd=SOURCE, extra=None):
    env = ENV.copy()
    env["CARGO_TARGET_DIR"] = str(OUT / "targets" / args.lane)
    if extra:
        env.update(extra)
    print("+", json.dumps(command), flush=True)
    with (OUT / (label + ".log")).open("w", encoding="utf8") as log:
        process = subprocess.Popen(command, cwd=cwd, env=env, text=True,
                                   encoding="utf8", errors="replace",
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for line in process.stdout:
            sys.stdout.write(line)
            log.write(line)
        code = process.wait()
    records.append({"label": label, "argv": command, "cwd": str(cwd), "exit": code,
                    "environment": {k: env[k] for k in ["CARGO_TARGET_DIR", "CARGO_BUILD_JOBS", "RUST_TEST_THREADS"]},
                    "overrides": extra or {}})
    (OUT / (args.lane + "-commands.json")).write_text(json.dumps(records, indent=2) + "\n")
    return code


def copied_source(label):
    # Fixture overlays are restricted to a disposable archive. Production source stays clean.
    destination = OUT / label
    archive = subprocess.check_output(["git", "archive", "HEAD"], cwd=SOURCE)
    destination.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(destination, filter="data")
    shutil.copyfile(SOURCE / "Cargo.lock", destination / "Cargo.lock")
    return destination


def commands(rows):
    failed = False
    for label, command in rows:
        failed |= run(label, command) != 0
    return int(failed)


def main():
    for name, expected in INPUTS["checksums"].items():
        if sha(ROOT / name) != expected:
            raise ValueError("Qualification input checksum changed: " + name)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SOURCE, text=True).strip()
    # The reviewed worker pin is authoritative, never caller-controlled environment.
    if INPUTS["revision"] != APPROVED_REVISION or INPUTS["repository"] != APPROVED_REPOSITORY:
        raise ValueError("Qualification manifest does not match the approved source identity")
    if revision != APPROVED_REVISION:
        raise ValueError("Source revision does not match the approved commit")
    if os.environ.get("QUALIFICATION_REVISION", APPROVED_REVISION) != APPROVED_REVISION:
        raise ValueError("Environment revision contradicts the approved commit")
    repository = subprocess.check_output(["git", "remote", "get-url", "origin"], cwd=SOURCE, text=True).strip()
    if repository not in ["https://github.com/" + APPROVED_REPOSITORY,
                          "https://github.com/" + APPROVED_REPOSITORY + ".git"]:
        raise ValueError("Source repository does not match the approved repository")
    if os.environ.get("GITHUB_REPOSITORY", APPROVED_REPOSITORY) != APPROVED_REPOSITORY:
        raise ValueError("Workflow repository contradicts the approved repository")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=SOURCE):
        raise ValueError("Source checkout must be clean")
    if platform.python_version() != INPUTS["tools"]["python"] or sys.implementation.name != "cpython":
        raise ValueError("Python interpreter does not match the reviewed CPython pin")
    for name, expected in INPUTS["source_checksums"].items():
        if sha(SOURCE / name) != expected:
            raise ValueError("Versioned source fixture changed: " + name)
    graph = INPUTS["graphs"][args.graph]
    shutil.copyfile(ROOT / graph["lock"], SOURCE / "Cargo.lock")
    shutil.copyfile(SOURCE / "Cargo.lock", OUT / "qualified-Cargo.lock")
    shutil.copyfile(ROOT / "inputs.json", OUT / "inputs.json")
    rustc = subprocess.check_output(["rustc", "-Vv"], text=True)
    version = tuple(map(int, re.search(r"rustc (\d+)\.(\d+)", rustc).groups()))
    requested = "1.92.0" if args.lane == "vendor-msrv" else os.environ.get("QUALIFICATION_TOOLCHAIN")
    if requested:
        if requested not in INPUTS["rust"].values():
            raise ValueError("Toolchain is not a reviewed input: " + requested)
        channel = INPUTS["sources"]["rust_channels"].get(requested.split("-")[0])
        release = channel["rust"].split()[0] if channel else requested
        if re.search(r"^release: (.+)$", rustc, re.M).group(1) != release:
            raise ValueError("Actual compiler does not match requested toolchain")
    metadata = {"source_revision": revision, "source_repository": repository, "control_revision": os.environ.get("GITHUB_SHA"),
                "requested_toolchain": requested,
                "graph": args.graph, "lock_sha256": sha(SOURCE / "Cargo.lock"),
                "rustc": rustc, "cargo": subprocess.check_output(["cargo", "-V"], text=True),
                "git": subprocess.check_output(["git", "--version"], text=True),
                "platform": platform.platform(), "architecture": platform.machine(), "python": sys.version,
                "python_executable": sys.executable, "python_version": platform.python_version(),
                "runner_image": {k: os.environ.get(k) for k in ["ImageOS", "ImageVersion", "RUNNER_ARCH"]},
                "corpora": INPUTS["wpt"], "findings": FINDINGS}
    (OUT / (args.lane + "-identity.json")).write_text(json.dumps(metadata, indent=2) + "\n")
    if args.lane == "prepare":
        return 0
    if args.lane == "vendor-msrv":
        # Modern Cargo reads the frozen graph; old Cargo needs no registry-index clone.
        vendor = OUT / "vendor"
        code = run("vendor-msrv", ["cargo", "vendor", "--locked", str(vendor)])
        if code:
            return code
        home = OUT / "cargo-home"
        home.mkdir(exist_ok=True)
        config = '[source.crates-io]\nreplace-with = "qualification-vendor"\n[source.qualification-vendor]\ndirectory = ' + json.dumps(str(vendor)) + '\n'
        (home / "config.toml").write_text(config)
        if os.environ.get("GITHUB_ENV"):
            with open(os.environ["GITHUB_ENV"], "a") as output:
                output.write("CARGO_HOME=" + str(home) + "\n")
        return 0
    if args.lane == "native":
        rows = [("build", ["cargo", "build", "--all-targets", "--locked"]),
                ("workspace-without-idna-conformance", ["cargo", "test", "--workspace", "--exclude", "idna", "--locked"]),
                ("idna-units", ["cargo", "test", "-p", "idna", "--lib", "--test", "unit", "--test", "unitbis", "--locked"]),
                ("serde-internals", ["cargo", "test", "-p", "url", "--features", "serde,expose_internals", "--locked"])]
        unavailable = []
        if version >= (1, 81):
            rows.append(("no-default", ["cargo", "test", "-p", "url", "--no-default-features", "--locked"]))
        else:
            unavailable.append("Isolated no-default needs core::error::Error (1.81) and core::net (1.77); unsupported on 1.63")
        if version >= (1, 71):
            rows.append(("all-features", ["cargo", "test", "-p", "url", "--all-features", "--locked"]))
        else:
            unavailable.append("debugger_visualizer explicitly requires Rust >=1.71")
        (OUT / "unsupported-features.json").write_text(json.dumps(unavailable, indent=2) + "\n")
        return commands(rows)
    if args.lane == "pinned":
        stage = copied_source("pinned-source")
        for name in ["urltestdata.json", "setters_tests.json"]:
            shutil.copyfile(ROOT / "fixtures" / name, stage / "url/tests" / name)
        cases = [c for c in json.loads((ROOT / "fixtures/urltestdata.json").read_text()) if isinstance(c, dict)]
        setters = json.loads((ROOT / "fixtures/setters_tests.json").read_text())
        setter_count = sum(len(rows) for name, rows in setters.items() if name != "comment")
        if len(cases) != 896 or sum(c.get("base") is None for c in cases) != 560:
            raise ValueError("Pinned corpus population changed")
        if setter_count != INPUTS["wpt"]["setter_cases"]:
            raise ValueError("Pinned setter corpus population changed")
        code = run("pinned-driver", ["cargo", "test", "-p", "url", "--test", "url_wpt", "--locked"], stage)
        text = (OUT / "pinned-driver.log").read_text()
        suffix = " ... ✅ (expected fail)"
        exceptions = sorted(line[:-len(suffix)] for line in text.splitlines() if line.endswith(suffix))
        expected_exceptions = sorted(row["case"] for row in FINDINGS["setter_exceptions"])
        strict = sum(line.endswith(" ... ✅") for line in text.splitlines())
        finding = {"URL_cases": 896, "null_base": 560, "explicit_base": 336,
                   "strict_URL_and_setter_passes": strict, "setter_exceptions": exceptions,
                   "setter_cases": setter_count,
                   "all_URL_outcomes_match": code == 0 and strict == len(cases) + setter_count - len(expected_exceptions) and exceptions == expected_exceptions,
                   "note": "Nine exceptions remain findings, not conformance passes; href dispatch is a driver gap."}
        (OUT / "pinned-results.json").write_text(json.dumps(finding, indent=2) + "\n")
        return code or int(not finding["all_URL_outcomes_match"])
    if args.lane in ["idna", "idna-baseline"]:
        stage = copied_source(args.lane + "-source")
        if args.lane == "idna":
            corpus = graph["idna_corpus"]
            corpus = SOURCE / corpus.removeprefix("source:") if corpus.startswith("source:") else ROOT / corpus
            shutil.copyfile(corpus, stage / "idna/tests/IdnaTestV2.txt")
        else:
            if args.graph != "modern":
                raise ValueError("The unchanged ten-failure baseline requires the modern graph")
            corpus = SOURCE / "idna/tests/IdnaTestV2.txt"
        code = run(args.lane, ["cargo", "test", "-p", "idna", "--test", "tests", "--locked"], stage)
        text = (OUT / (args.lane + ".log")).read_text()
        failures = [line.strip() for line in text.splitlines() if re.match(r"^    UTS #46", line)]
        finding = {"corpus_sha256": sha(corpus), "command_exit": code, "failures": failures,
                   "known_baseline_matches": failures == FINDINGS["idna_unicode17_baseline"]["failures"],
                   "failures_are_not_accepted": True}
        (OUT / (args.lane + "-findings.json")).write_text(json.dumps(finding, indent=2) + "\n")
        # A known failed test remains a failed job. Unexpected disappearance also needs review.
        return code or (int(not finding["known_baseline_matches"]) if args.lane == "idna-baseline" else 0)
    if args.lane == "lint":
        return commands([("fmt", ["cargo", "fmt", "--all", "--check"]),
                         ("clippy", ["cargo", "clippy", "--workspace", "--all-targets", "--all-features", "--locked", "--", "-D", "warnings"])])
    if args.lane == "sanitizer":
        kind = os.environ["SANITIZER"]
        if kind not in ["address", "thread", "leak", "memory"]:
            raise ValueError(kind)
        host = re.search(r"^host: (.+)$", rustc, re.M).group(1)
        return run("sanitizer-" + kind, ["cargo", "test", "-p", "url", "-Z", "build-std", "--target", host,
                   "--lib", "--tests", "--all-features", "--locked"], extra={
                   "RUSTFLAGS": "-Z sanitizer=" + kind, "RUSTDOCFLAGS": "-Z sanitizer=" + kind,
                   "ASAN_OPTIONS": "detect_leaks=1:detect_stack_use_after_return=1"})
    if args.lane == "fuzz":
        if args.graph != "borrowser":
            raise ValueError("Required fuzz qualification uses the frozen consumer graph")
        stage = copied_source("fuzz-source")
        fuzz_lock = stage / "url/fuzz/Cargo.lock"
        shutil.copyfile(ROOT / "locks/fuzz.lock", fuzz_lock)
        shutil.copyfile(fuzz_lock, OUT / "fuzz-Cargo.lock")
        # url/fuzz is a separate workspace: the root Cargo.lock cannot pin it.
        command = ["cargo", "metadata", "--locked", "--format-version", "1",
                   "--manifest-path", str(stage / "url/fuzz/Cargo.toml")]
        with (OUT / "fuzz-metadata.log").open("w") as log:
            resolved = subprocess.run(command, cwd=stage, env=ENV, text=True,
                                      stdout=subprocess.PIPE, stderr=log)
        (OUT / "fuzz-metadata.json").write_text(resolved.stdout)
        if resolved.returncode:
            return resolved.returncode
        metadata = json.loads(resolved.stdout)
        packages = {p["id"]: p for p in metadata["packages"]}
        nodes = {n["id"]: n for n in metadata["resolve"]["nodes"]}
        pending = [p["id"] for p in metadata["packages"] if p["name"] == "url"]
        closure = set()
        while pending:
            package = pending.pop()
            if package in closure:
                continue
            closure.add(package)
            pending.extend(d["pkg"] for d in nodes[package]["deps"]
                           if any(k["kind"] != "dev" for k in d["dep_kinds"]))
        consumer = tomllib.loads((ROOT / graph["lock"]).read_text())["package"]
        frozen = tomllib.loads(fuzz_lock.read_text())["package"]
        consumer = {(p["name"], p["version"]): p for p in consumer}
        frozen = {(p["name"], p["version"]): p for p in frozen}
        expected = set(graph["runtime_packages"]) | {"url 2.5.8"}
        actual = {packages[p]["name"] + " " + packages[p]["version"] for p in closure}
        if actual != expected:
            raise ValueError("Resolved fuzz URL closure differs from the frozen consumer graph")
        identities = []
        for package in sorted(closure):
            p = packages[package]
            key = (p["name"], p["version"])
            reference, locked = consumer[key], frozen[key]
            if p["source"] != reference.get("source") or locked.get("checksum") != reference.get("checksum"):
                raise ValueError("Fuzz dependency source/checksum changed: " + p["name"])
            if p["source"] is None:
                directory = {"url": "url", "idna": "idna", "form_urlencoded": "form_urlencoded",
                             "percent-encoding": "percent_encoding"}[p["name"]]
                if Path(p["manifest_path"]).resolve() != stage / directory / "Cargo.toml":
                    raise ValueError("Fuzz local dependency escaped the approved source archive")
            identities.append({"name": p["name"], "version": p["version"], "source": p["source"],
                               "checksum": locked.get("checksum"), "features": nodes[package]["features"]})
        (OUT / "fuzz-graph.json").write_text(json.dumps({"argv": command, "exit": resolved.returncode,
            "lock_sha256": sha(fuzz_lock), "consumer_lock_sha256": sha(ROOT / graph["lock"]),
            "URL_dependency_closure": identities, "consumer_graph_matches": True}, indent=2) + "\n")
        corpus = OUT / "corpus"
        corpus.mkdir()
        for i, case in enumerate(json.loads((ROOT / "fixtures/urltestdata.json").read_text())):
            if isinstance(case, dict):
                (corpus / ("wpt-%04d" % i)).write_bytes(case["input"].encode("utf8"))
        for i, value in enumerate(INPUTS["fuzz_regressions"]):
            (corpus / ("regression-%d" % i)).write_bytes(bytes.fromhex(value))
        tools = OUT / "tools"
        # Install the CLI with stable Rust: its locked rustix 0.36.5 Linux
        # backend uses private attributes incompatible with the selected nightly.
        code = run("install-fuzz", ["rustup", "run", INPUTS["rust"]["adoption"], "cargo", "install", "cargo-fuzz",
                                   "--version", INPUTS["tools"]["cargo-fuzz"], "--locked", "--root", str(tools)])
        if code:
            return code
        extra = {"PATH": str(tools / "bin") + os.pathsep + ENV["PATH"], "CARGO_NET_OFFLINE": "true"}
        failed = False
        for target in ["parse", "fuzz-url"]:
            failed |= run("fuzz-" + target, ["cargo", "fuzz", "run", target, str(corpus), "--fuzz-dir", str(stage / "url/fuzz"),
                          "--target-dir", str(OUT / "targets/fuzz"), "--", "-runs=0", "-max_len=2048", "-timeout=5", "-rss_limit_mb=2048"], stage / "url", extra) != 0
            # cargo-fuzz has no --locked option; reject any resolver drift.
            if sha(fuzz_lock) != INPUTS["checksums"]["locks/fuzz.lock"]:
                raise ValueError("cargo-fuzz changed the frozen dependency graph")
        return int(failed)
    if args.lane == "wasm":
        tools = OUT / "tools"
        if run("install-wasm-pack", ["cargo", "install", "wasm-pack", "--version", INPUTS["tools"]["wasm-pack"], "--locked", "--root", str(tools)]):
            return 1
        extra = {"PATH": str(tools / "bin") + os.pathsep + ENV["PATH"]}
        failed = run("wasm-build", ["cargo", "build", "-p", "url", "--target", "wasm32-unknown-unknown", "--locked"]) != 0
        for browser in ["google-chrome", "firefox"]:
            failed |= run(browser + "-version", [browser, "--version"]) != 0
        for browser in ["chrome", "firefox"]:
            failed |= run("wasm-" + browser, ["wasm-pack", "test", "--headless", "--" + browser, str(SOURCE / "url"), "--locked"], extra=extra) != 0
        return int(failed)
    if args.lane == "no-std":
        return run("no-std", ["cargo", "check", "-p", "url", "--target", "aarch64-unknown-none", "--no-default-features", "--locked"])
    raise ValueError(args.lane)


if __name__ == "__main__":
    sys.exit(main())
