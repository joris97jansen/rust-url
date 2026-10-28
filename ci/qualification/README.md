# Maintained URL qualification

This configuration qualifies a specific rust-url revision with existing Cargo tests,
the upstream WPT driver, wasm-pack and cargo-fuzz. It does not change parser code,
public APIs, generic IDNA conversion, setter implementations or upstream fixtures.

## Source and execution

The reusable worker checks out the literal approved commit
`7dc4ecbf4d29817e723e04ae94b14f1326764f61` from `joris97jansen/rust-url`.
The Python worker independently checks that actual HEAD and the canonical HTTPS
origin match its reviewed constants and that `inputs.json` agrees. It rejects a
contradictory `QUALIFICATION_REVISION` or `GITHUB_REPOSITORY`; neither variable can
select the source. These checks precede dependency preparation, compiler calls and
tests. The source checkout disables CRLF conversion so Windows uses the same bytes.

The push trigger only accepts `qualification/borrowser-ci`. CI controls come from
that immutable push SHA, separately from production source. The reusable job is
restricted to this fork and branch; caller strings are passed through quoted
environment variables rather than inserted into shell commands. Source-identity
regressions use real local clones: approved and matching-environment cases pass;
wrong commits (including a matching hostile override), wrong origin, contradictory
environment/context and dirty checkouts fail before a test command can run.

Qualification checks are attached to the CI control commit on GitHub; the tested
source SHA is recorded separately in every result. Do not mistake the control
commit for the dependency revision. Existing PR workflows remain unchanged; this
workflow handles maintained/control-branch pushes without duplicating their PR jobs.

No manual-dispatch or schedule trigger is assumed: those require the workflow on
the default branch. `main` stays synchronized with official upstream. The immediate
execution path, **after review and explicit approval**, is to commit and push this
qualification branch. That matching push tests the pinned source, without moving
`borrowser`. Merely keeping this workflow on the qualification branch cannot
observe future `borrowser` pushes automatically. For each qualification, update the
reviewed literal checkout pin, worker constant and input manifest together, then
push this control branch after approval. Installing workflows on `borrowser` would
need separate approval.

Repository Actions permissions report enabled/all-actions/read-only default token,
but inherited workflows are not registered. The old workflows only accept pushes
to `main`, so the published `borrowser` pushes were ineligible. A fork-local PR is
also present in the event history, so filters do not explain every missing run.
GitHub documents that fork workflows need activation in the fork's Actions tab.
The API exposes neither a disabled-fork workflow record nor proof that this UI
activation happened: filename lookups return 404. Verify the activation prompt
before execution; if activation is needed, it requires explicit approval. No
settings, branch protection, workflow run or remote ref has been changed here.

## Frozen graphs and independent data

| Graph | Purpose | Backend/corpus |
| --- | --- | --- |
| `borrowser` | Required consumer graph | Adapter 1.2.1, ICU 2.0, Unicode 16 |
| `modern` | Published reference/support graph | Adapter 1.2.2, ICU 2.4, Unicode 18 |
| `msrv` | Declared standard-feature MSRV | Adapter 1.1.0, Unicode 16 |

The consumer lock was recovered from preserved qualification evidence. All 34
packages in the current consumer's URL runtime dependency closure match its versions
and registry checksums; the fork's local URL/IDNA packages intentionally replace
registry sources. Workspace dev dependencies are additional, not runtime identity
claims. Actual dependency integration must preserve this graph, or requalify the
chosen replacement graph on all adoption platforms.

The MSRV input differs from `ci-lockfiles/1.63.Cargo.lock` only by normalizing the
local workspace URL package version from 2.5.7 to the source version 2.5.8. No
external dependency version changes. Modern Cargo vendors that frozen input before
Rust/Cargo 1.63 runs, avoiding an old Cargo registry-index bootstrap. The original
CI lock and all source manifests stay unchanged.

Cargo test/build/metadata commands use `--locked`. The nested fuzz workspace has
its own frozen `locks/fuzz.lock`: the root lock cannot govern it. Before fuzzing,
`cargo metadata --locked` must resolve exactly the 34 consumer URL dependencies
plus the local URL package. The worker checks their actual versions, registry
sources and checksums against the consumer lock, and checks local manifest paths
stay in the approved archive. Full metadata, enabled features and compared
identities are uploaded. Fuzzer-only dependencies are frozen separately in the same
nested lock. `cargo-fuzz` 0.13.1 exposes no `--locked` switch: replay runs offline
following locked metadata resolution, and any lock change fails qualification.
Both existing fuzz targets and all seeds are unchanged. The earlier modern-graph
fuzz result remains historical additional coverage, never consumer qualification.

IDNA conformance and pinned-WPT overlays run in separate
archives of the exact source revision, with separate build directories. Only test
fixture files are replaced in those disposable copies. The original source checkout
and normative expectations are preserved. Unicode 16 is the unchanged tracked fixture;
Unicode 18 is a separately downloaded official corpus with a version header and SHA.

The independent WPT revision is `c48d58747e1f211527fb695fd60548a997fae617`:
896 URL cases (560 null-base, 336 explicit-base) and **278** setter cases. The older
bundled source fixture has 274 setter cases. The four additional independent cases
must run; their expectations have not been rewritten. The existing driver should
report 1,165 strict component-outcome passes and nine recorded setter exceptions.
Those exceptions are findings, not conformance passes. Native focused tests cover
callback order, fatal errors and serialization invariants; the WPT driver does not
claim a complete independent oracle for every WHATWG diagnostic category.

`inputs.json` records checksums and provenance. Actions use full commit SHAs,
Rust uses release/date pins, Python is 3.12.12, cargo-fuzz is 0.13.1 and wasm-pack
is 0.13.1. Runner labels are explicit; runner image/architecture and actual tool
identities are recorded. Hosted images, browser builds and advisory databases are
not hermetic snapshots. Browser versions are logged; current security audit results
must be retained with their run date. Locks and input manifests are uploaded with logs.

## Matrix and acceptance

| Lane | Coverage | Role for current Borrowser adoption |
| --- | --- | --- |
| Native adoption | Rust 1.92.0; Ubuntu 24.04 x64, Windows 2022 x64, macOS 14 ARM64; consumer graph | Required |
| Native support | Upstream's 11 OS/toolchain cells, with stable 1.99.1, beta-2026-10-18 and nightly-2026-10-28 pinned; plus Linux 1.92 modern reference | Supported-library maintenance; additional to current 1.92 consumer use |
| Native features | Workspace non-conformance tests, IDNA units, URL serde/internals, isolated no-default and all-features where supported | Required on adoption cells |
| Pinned WPT | Existing unmodified driver on all 15 native cells | Required on adoption cells; nine findings remain explicit |
| Matched IDNA | Unicode 16 or 18 appropriate to each graph, using unchanged driver | Required on adoption cells |
| Original IDNA baseline | Linux 1.92, modern graph, unchanged Unicode 17 fixture | Must stay visibly failed on the known ten; not a conformance pass |
| AddressSanitizer | Native Linux and macOS, pinned nightly, consumer graph | Required before adoption |
| ThreadSanitizer | Native Linux/macOS | Additional upstream-supported coverage |
| Leak/MemorySanitizer | Linux | Additional upstream-supported coverage |
| Fuzz regressions | Consumer graph; existing `parse` and `fuzz-url`; 896 WPT inputs plus eight preserved seeds | Required; deterministic seed replay, not extended random fuzzing |
| Formatting/Clippy | Rust 1.92, consumer graph, warnings denied | Required |
| cargo-deny | Both frozen consumer and modern graphs; existing audit action/config | Consumer audit required; modern is additional coverage |
| WASM | wasm32 build and actual Chrome/Firefox execution | Supported library coverage; optional for this native Borrowser consumer |
| Bare-metal no_std | Nightly `aarch64-unknown-none` compile check | Supplemental; never native Linux/Windows/macOS proof |

The 11 support cells preserve upstream's exclusions: 1.63 on all three OSes,
1.82 only Linux, stable on all three, beta only Linux, nightly on all three.

Isolated no-default builds are unsupported on 1.63: `core::error::Error` requires
at least 1.81 and `core::net` at least 1.77. This was reproduced, not inferred from
a passing workspace feature-unified build. The proposal records unavailable features
and runs isolated no-default tests on 1.82 and newer selected toolchains.
`debugger_visualizer` explicitly needs 1.71, so all-features is unavailable on 1.63.
The separate Windows CDB debugger test is not a URL parser adoption gate; upstream
makes it non-gating. It is not run or reported as passed by this configuration.

No `continue-on-error`, shell failure masking or sanitizer suppression is used.
Matched-version IDNA success does not turn the original ten failed tests green.
The original-baseline job remains failed even when its observed names match the
known finding list. The overall workflow therefore remains red while that lane
fails. Unexpected new failures, changed finding inventories and missing tests fail
qualification. All other jobs run independently and retain artifacts after failure.
No successful native job automatically approves dependency adoption.

Before adoption, require native consumer results on all three platforms, actual
896/896 outcomes, serialization/diagnostic regressions, matched-version IDNA success,
address sanitizers, fuzz regression replay, lint and a consumer dependency audit.
Then explicitly review the ten legacy-corpus findings and the eight setter defects
plus one missing-href-dispatch exception against intended API usage. Borrowser's
`DomainToAscii -> Unclassified` mapping and actual direct/transitive dependency
source selection need a separate integration review. No Borrowser changes are part
of this configuration. A graph update invalidates the corresponding qualification.

## Local runner and review validation

Example (use a disposable detached source clone):

```sh
git -C /tmp/url-source remote set-url origin https://github.com/joris97jansen/rust-url.git
QUALIFICATION_OUTPUT=/tmp/identity-results python ci/qualification/test_identity.py /tmp/url-source
QUALIFICATION_OUTPUT=/tmp/url-results python ci/qualification/run.py /tmp/url-source borrowser native
QUALIFICATION_OUTPUT=/tmp/url-results python ci/qualification/run.py /tmp/url-source borrowser pinned
QUALIFICATION_OUTPUT=/tmp/url-results python ci/qualification/run.py /tmp/url-source borrowser idna
```

The runner records every command's real exit status, input identity and output.
Input mismatch or a dirty source checkout fails before tests. It does not run git
commit/push, create issues or invoke the GitHub Actions API.

Preparation was validated locally on native macOS ARM64: consumer Rust 1.92 native
feature tests and pinned outcomes pass; all three graphs preserve 896/896 outcomes
and the nine setter findings; matched Unicode 16 passes 12,804 tests and matched
Unicode 18 passes 12,818; the untouched modern/Unicode 17 baseline still reports
12,798 passes and the exact ten failures. Actual Rust/Cargo 1.63 standard-feature
and pinned lanes pass with the frozen vendored input. The two fuzz regression
wrappers passed previously on the modern graph; that evidence alone does not
qualify consumer fuzzing. In this corrected proposal, all eight source-identity
regressions pass, both existing fuzz targets replay the consumer graph successfully,
and the 34 consumer URL dependency identities match. Consumer native features,
pinned WPT, matched Unicode 16, formatting and Clippy with warnings denied pass.
Actionlint checks all four workflows and Python 3.12 grammar checks pass. The local
interpreter is Python 3.14.2; the hosted Python 3.12.12 lane remains pending. Hosted Linux/Windows,
other support toolchains, sanitizer/WASM/no_std and audit jobs remain unexecuted
by this proposal; no remote workflow was triggered.
