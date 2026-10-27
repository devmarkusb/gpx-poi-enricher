# Repository correctness audit

Audit date: 27 October 2026. Scope: the entire repository, including the Python library,
CLIs, desktop UI, profiles/catalog, Android application and bridge, packaging, and build scripts.
The final checkout retains the maintainer's Python 3.13 minimum, version 1.19.0, and CI configuration.

## Executive assessment

Confidence has improved substantially for offline search orchestration, GPX serialization, interrupted
work, profile editing, route reuse, and coordinate boundaries. The original 206 tests passed despite
several reproducible wrong-result and data-loss defects. The expanded Python suite has 274 passing
cases, including 68 additional cases. Coverage with branch measurement enabled increased from 43.74%
to 64.79%; branch coverage alone increased from 39.86% to 55.18%.

The installed wheel now exposes all ten built-in profiles and 93 catalog entries. Generated POI GPX
passes the official GPX 1.1 schema. The Android debug APK builds and Android lint reports zero errors.
Five new instrumentation tests pass on an isolated arm64 Android 17 (API 37) emulator using real Chaquopy,
ViewModels, and MediaStore. They verify interrupted resume, independent work ownership, queued
cancellation, exact export folders, truncating overwrites, and deleted-document restoration. Screen
rotation, SAF picker grants, billing, and consent screens still lack device coverage.

The continuation reproduced two further defects: checkpoint coordinate rounding silently discarded a
valid boundary POI on resume, and searches with the same input filename shared scratch files and
destroyed each other's resumable work. Both now have regressions that failed before their fixes.

The repository is more trustworthy, but confidence remains moderate overall. Public-service behavior,
device lifecycle interactions, and several conflicting product contracts still need attention.
The approved dependency update cleared all 21 previously reported audit findings. The updated lockfile
passes `uv audit`, and all 274 tests pass with the updated dependencies on Python 3.13 and 3.14.

## System model and bug search map

Profiles define tag predicates, country-specific text terms, and search defaults. User profiles override
built-ins. The enrichment engine samples GPX vertices, optionally groups them by country through
Nominatim, queries Overpass in batches, filters and deduplicates candidates, and writes waypoint GPX.
Checkpoint counters and the GPX snapshot jointly represent interrupted work.

Directions conversion resolves Google Maps stops and obtains OSRM geometry. Desktop and Android each
orchestrate primary routes, alternates, detours, milestone companions, and enrichment. Desktop workers
run in Qt threads; Android uses coroutine IO workers around blocking Chaquopy calls. Both redirect
process-wide Python stderr, so their operations must serialize capture and maintain operation ownership.
Android publishes work files through document-provider URIs or Downloads.

The main invariants are that a successful batch contains a complete accepted API result, every skipped
batch belongs to the same search, snapshots survive interrupted publication, profile edits preserve
unmodified predicates, reused GPX matches the current route, and cancellation affects its own job.

| Pass | High-risk areas | Evidence and outcome |
| --- | --- | --- |
| Documentation and contracts | README, profiles, API helpers, tests, packaged resources | Found profile packaging/identity defects and conflicting milestone, matching, and deduplication contracts. |
| Failures and persistence | Overpass responses, retries, checkpoints, final writes, session ownership | Reproduced accepted partial failures, unsafe resume, lost snapshots, and leaked sessions. |
| Boundaries and geometry | Empty/invalid inputs, long loops, dateline, antipodes, disconnected segments | Added concrete regressions and compared the polyline search with an exhaustive reference. |
| Concurrency and lifecycle | Shared stderr, queued cancellation, Qt shutdown, Android restoration and streams | Reproduced cancellation interference and inspected ownership across Kotlin/Python boundaries. |
| Persistence continuation | Coordinate round-trips, repeated Android operations, same-named documents | Reproduced a disappearing boundary POI and one operation deleting another's resumable work; added real device regressions. |
| Duplication and integration | Desktop/Android route pipelines, resume summaries, catalog/profile forms, build scripts | Found stale route reuse, missing alternate milestones, missing prior counts, and destructive form round-trips. |
| Regression review | Resulting diff, both Python runtimes, packaged wheel, XSD, Android build/lint, hooks | Reviewed publication order, cancellation cleanup, numeric compatibility, and restored edits after the accidental reset. |

Semantic search was unavailable because JetBrains authentication was missing. Discovery used direct
source and test inspection. No live Overpass, Nominatim, or OSRM requests were used in tests.

## Bugs fixed

Classification A means a demonstrated contract/invariant violation. Classification B marks an inferred
intention whose assumption is stated. Confidence reflects the defect evidence, not complete device or
production verification. Device evidence is identified explicitly; remaining Kotlin fixes have
build/lint verification and the device limitations above.

| Location | Symptom and root cause | Fix | Evidence and confidence |
| --- | --- | --- | --- |
| `profiles.py`, wheel configuration | An installed wheel listed no built-ins: YAML was outside the package and lookup assumed a source checkout. | Bundle profiles under package data and prefer that directory, retaining the checkout fallback. | An extracted original wheel returned zero profiles; the final wheel returns ten. A, 99%+. |
| `profiles.py` loading and identity | Filename fallback was missing; listing used YAML IDs while lookup used filenames. An aliased user override could be listed but never selected. | Use filename when ID is absent and resolve IDs consistently across directories. | `test_profile_without_id_uses_filename`, `test_profile_selection_uses_yaml_id_and_user_override`. A, 99%+. |
| `profiles.py` saving and deletion | Saving a canonical file could leave an older alias winning lookup; deletion missed aliases. | Canonical filenames take precedence within a directory; deletion removes that user's files defining the selected ID. Save/delete normalize IDs. | Save, reload, and delete regression in `test_profiles.py`. B, 98%: a successful save must become the selected profile; built-in/user directory precedence is preserved. |
| `profiles.py`, `enricher.py` validation | Zero batch size divided by zero; negative/non-finite distances and fractional counts reached query or batching code. | Validate finite distances, integral counts, and nonnegative retries before work. Invalid GPX/track coordinates are rejected. | Invalid-default and coordinate parameter cases. A, 99%+. |
| `overpass.py` retries and radius | The UI allowed zero retries, but it issued zero initial requests. Fractional metre radii were truncated to zero. | Zero retries still makes one attempt per endpoint; retain existing positive retry counts. Round request radii upward; final distance filtering remains unchanged. | Zero-retry and fractional-metre regressions. A, 99%+ for the failures; B, 98% for preserving the UI's zero-retry option as an initial attempt. |
| `overpass.py` response acceptance | HTTP-200 JSON with a runtime-error `remark` was treated as complete, allowing partial results to advance checkpoints. | Reject runtime remarks and invalid result shapes; retry and ultimately raise. | Mocked partial timeout and exhausted-memory responses failed before the fix. A, 99%+. |
| `overpass.py` query strings | Quotes and regex backslashes from profile values produced malformed QL strings. | Escape complete QL string literals for tags and text selectors, including AND/negative clauses. | Quoted-brand and regex-backslash regression. A, 99%+. |
| `gpx_utils.py` waypoint serialization | Every POI waypoint used invalid child order; appending after root extensions/tracks also violated GPX ordering. | Emit `name`, `desc`, `sym`, `type`, and insert waypoints before routes/tracks/extensions. | Schema-order regression and `xmllint` against the official GPX 1.1 XSD. A, 99%+. |
| `gpx_utils.py` coordinate precision | Six-decimal serialization moved a valid POI just outside the search radius; resume then silently discarded it. Small coordinates also failed exact round-trips. | Preserve the input coordinate precision using ordinary decimal notation accepted by GPX. | One interrupted/resumed boundary case and two coordinate round-trip cases failed before the fix and pass afterward; tiny-coordinate output passes the GPX XSD. A, 99%+. |
| `gpx_utils.py` nearest searches | A local window around a coarse vertex could miss a remote loop. A POI exactly on vertex 200 was reported 111 m away. The polyline helper had the same failure mode. | Consider all vertices/segments, with conservative distance bounds to prune work. Keep legacy tuning arguments callable. | Exact-vertex/loop-segment regressions and 100 seeded comparisons against exhaustive segment scans. A, 99%+. |
| `gpx_utils.py`, `split_cli.py` longitude interpolation | Dateline crossings projected or interpolated through longitude zero. | Use wrapped longitude offsets and interpolate across the short longitude span. | Dateline distance and milestone regressions. A, 99%+. |
| Distance helpers | Near-antipodal roundoff put the haversine intermediate above one, causing a math-domain failure. | Clamp the intermediate to its mathematical range. | A concrete antipodal case produced `a = 1.0000000000000002`; regression checks finite distance. A, 99%+. |
| `enricher.py` country grouping | If early country lookups failed but later ones succeeded, leading samples disappeared entirely. | Search omitted samples with the existing EN fallback instead of dropping them. | Partial-country-failure regression asserts the first sample is queried. A, 99%+. |
| `enricher.py`, `enrich_checkpoint.py` resume identity | Stored batch ordinals were reused after input, profile, settings, or country grouping changed. Missing output snapshots were accepted. | Fingerprint the full input root and batch plan; require a matching fingerprint and an existing snapshot before skipping work. Validate checkpoint counters. | Changed radius, batch size, original waypoints, and missing-snapshot regressions. A, 99%+. |
| `enricher.py` resume candidates | Original route stopovers in a checkpoint GPX were restored as POIs, replacing real candidate names or duplicating stops. | Restore only generated waypoint entries after the original waypoint prefix. | Interrupted/resumed input with an original stop. A, 99%+. |
| GPX/checkpoint/profile writers | The final GPX write cleared its checkpoint before writing directly to the destination. A failed write could destroy both recovery paths; other writers exposed partial files. | Atomically replace final/point/route GPX, checkpoint JSON, and user YAML. Clear the checkpoint after successful final publication. | Injected full-disk final-write regression preserves a parseable snapshot and sidecar. A, 99%+. |
| HTTP ownership in `enricher.py`, GUI, location resolver, Android bridge | Internally created sessions were not consistently closed, including exception paths. Named point processing also created a second enrichment session. | Close owned sessions and reuse the named-point session; retain caller-owned session ownership. | Success/failure session-close tests, bridge route tests, and short-link ownership test. A, 99%+. |
| `maps_to_gpx_cli.py` | Passing `route.gpx` wrote a different endpoint-derived filename, breaking the README's subsequent CLI pipeline. GUI naming defaults were applied to an explicit CLI output. | Preserve the exact CLI output path while retaining default track naming. | CLI regression asserts the requested file exists. A, 99%+. |
| `cli.py` | Explicit `--country-sample-km 0` silently became 40 through a truthiness fallback. | Distinguish zero from an omitted option. | Direct CLI forwarding regression. A, 99%+. |
| Desktop/Android route orchestration | Existing endpoint-derived filenames were reused even when newly routed geometry differed. Alternates and detours had the same issue. | Reuse only identical generated content; atomically replace stale route files. | Both platform pipelines reproduce a changed midpoint with the same endpoint labels; repeated identical input still reuses. A, 99%+. |
| Desktop/Android Easy milestones | Only the primary route received milestones because the loop used the enrichment list, which excludes full alternates. | Generate milestone companions for primary and full alternate routes. | Both platform regressions expect two companions for primary plus alternate. A, 99%+. |
| `split_cli.py` segment boundaries | Flattening disconnected segments counted missing geometry as travel and placed milestones across gaps. | Keep segment start boundaries when accumulating distance; reject invalid segment counts in the public helper. | Disconnected-segment regression keeps every milestone on a real segment. A, 99%+. |
| `route_detours.py` gap merging | A gap containing one vertex had measured length zero because both bounding edges were omitted. | Measure from the previous far endpoint through the next far start. | A 222 km one-vertex gap no longer merges under a 120 m threshold. A, 99%+. |
| `gui_profiles.py` form/YAML round-trips | Editing radius discarded hidden `and`/`and_not` clauses. YAML edits vanished when returning to the form; unchanged comma-bearing terms were split. | Preserve tag metadata and original term lists; populate the form from valid YAML, keeping invalid YAML visible. | Nested pool exclusions, comma-term preservation, and YAML-to-form regressions. A, 99%+. |
| `gui.py` worker lifetime and logging | Different workers redirected global stderr without serialization. Window closure could destroy active worker ownership; early Easy cancellation never emitted its completion signal. | Serialize worker capture, refuse window closure while work runs, and finish cancelled pre-routing work cleanly. | Queued-capture control-flow review, active-worker close regression, early-cancel completion regression. A, 99%+. |
| Android bridge and enrichment ViewModels | One global cancel event was cleared before locking. A queued job could erase active cancellation or cancel another job. Coroutine cancellation also allowed a new job before blocking work finished. | Pass per-operation IDs/events, serialize capture, use cooperative enrichment cancellation, and guard incomplete jobs through cleanup. Synchronize bridge log writes. | Deterministic Python queued/active cancellation tests and an Android test using two ViewModels with the real bridge. A, 99%+. |
| `EnricherViewModel.kt` URI restoration | Restoring unchanged URIs on view recreation cleared the retained resume state. | Preserve state when the selected URI is unchanged. | A device test restores the same selections after interruption, deletes the original document, and resumes from the copied source. A, 99%+; actual screen rotation remains untested. |
| `EnricherViewModel.kt` scratch-file ownership | Work paths depended only on input display name and profile. A second document with the same filename overwrote and deleted an interrupted search's files. | Include the operation UUID in fresh track and point work paths; resume keeps its stored paths. | The device regression fails with identical filenames, passes when only the second filename changes, and passes with identical filenames after the fix. A, 99%+. |
| `gpx_bridge.py` Easy resume | Resuming at a detour reported zero primary POIs because only newly processed tracks contributed counts. | Read counts from completed GPX outputs and merge them with resumed results. | Three existing primary POIs plus five resumed detour POIs remain correctly reported. A, 99%+. |
| Android document IO | Nested copy streams leaked descriptors; default write mode could retain old trailing bytes. Maps/Split could publish after cancellation. | Close both streams, request truncation, check coroutine cancellation before publication, and wait for old jobs to finish cleanup. | Ownership/control-flow inspection, Android build/lint, and real MediaStore stream overwrites. A, 99%+; SAF providers and Maps/Split cancellation still need device tests. |
| `GpxApp.kt`, profile asset task | Concurrent extraction could expose truncated YAML, leak asset streams, and retain removed built-ins. | Serialize extraction, publish files atomically, close asset streams, reconcile obsolete built-ins, and use Gradle Sync. | Multi-caller extraction path inspection and Android build/asset processing. A, 99%+. |
| `PlayStoreMonetization.kt` | Startup/restore granted ownership but never acknowledged unacknowledged purchases; only foreground purchase updates did so. | Process queried purchases through the existing acknowledgement path and refresh ownership on resume. | Google Billing contract and static call-path evidence; Android build/lint. A, 99%+. |
| Android consent and ad lifecycle | Completion/error of consent collection was treated as permission to load ads, and SDK initialization happened before consent. Required privacy options were absent. | Gate initialization/loading on `canRequestAds`, expose required privacy options, and stop cached-ad use when consent is unavailable. | Official UMP/SDK contracts; Android build/lint. A, 99%+; consent behavior needs device verification. |
| `GpxDownloadsExporter.kt` | A prefix `LIKE` matched similarly named Downloads directories, allowing overwrite outside the intended folder. | Match the exact persisted relative directory; declare API-29 helper requirements for lint. | SQL predicate evidence and a device test verifying a similarly prefixed folder remains untouched, shorter overwrites truncate, skip mode preserves content, and no duplicate export row is created. A, 99%+. |
| `android/build-apk.sh` | Bootstrap installed Python 3.12 / SDK 34 while the build requires Python 3.13 / SDK 36. | Align bootstrap versions with Gradle. | Gradle configuration comparison and `bash -n`; fresh provisioning was not executed. A, 99%+. |
| `scripts/build_macos_app.py` | A checkout path containing shell substitutions or dollar variables changed when the generated environment file was sourced. | Quote the virtualenv path as a literal shell word. | A temporary path containing dollar expansion and command substitution failed before the fix and round-trips afterward. A, 99%+. |
| `uv.lock` | Locked certifi, GitPython, and virtualenv versions produced 21 dependency-audit findings. | Apply the approved targeted update: certifi 2026.10.23, GitPython 3.2.1, virtualenv 21.15.0, distlib 0.4.4, and packaging 26.3. Preserve Python 3.13 support. | The repository's locked dependency audit now reports no known vulnerabilities; 274 tests pass on both tested runtimes. A, 99%+. |

The protocol checks use the [GPX 1.1 schema](https://www.topografix.com/GPX/1/1/),
[Google Billing purchase processing](https://developer.android.com/google/play/billing/integrate),
[UMP consent guidance](https://developers.google.com/admob/android/privacy), and
[SDK initialization guidance](https://developers.google.com/admob/android/quick-start).

## Human decisions required

The dependency lockfile update was explicitly approved and applied. The product decisions below remain open.

### Milestone count

Question: Should N segments produce N−1 internal markers or N milestones including the finish?

Evidence: README specifies N−1 markers named Split; tests deliberately require N fraction labels,
including `10/10`. Current behavior was preserved.

Option A: Change output and tests to N−1 internal markers.

Option B: Preserve N milestones and update README.

Recommendation: B, following the explicit milestone tests. Can work continue without this answer? Yes.

### Track search coverage

Question: Is sparse vertex-based search intentional, or should normal mode cover the continuous track?

Evidence: A 10 km sampling interval with a 2 km radius leaves gaps even along a straight track.
Existing tests intentionally select existing vertices after a spacing threshold. Candidate filtering
also measures distance to vertices rather than the continuous polyline. These semantics were preserved.

Option A: Document the approximation and retain request volumes and quick mode.

Option B: Design continuous coverage with segment-aware sampling/filtering and explicit request costs.

Recommendation: A for compatibility during this audit; consider B as a separately controlled mode.
Can work continue without this answer? Yes; confirmed false nearest-window results are fixed independently.

### Text matching and POI identity

Question: Should profile terms be raw regex, and should different OSM elements at the same coordinates survive?

Evidence: README calls terms regex and describes deduplication by OSM ID. Implementation escapes terms
as literals and collapses candidates by rounded coordinates; tests intentionally assert coordinate collapse.
Changing either contract would alter externally visible matches/counts, so neither was changed.

Option A: Preserve literal terms and coordinate collapse, and correct the documentation.

Option B: Support raw regex and/or use OSM type plus ID for identity, with explicit compatibility rules.

Recommendation: Preserve literal matching; prefer OSM identity for distinct entities once its migration
is agreed. These are independent choices. Can work continue without this answer? Yes.

### Saving with a custom profile directory

Question: Where should desktop edits be saved while `GPX_POI_PROFILES_DIR` replaces normal read locations?

Evidence: Reads use only that directory; saves still target the normal user directory, making those
new profiles invisible to the active read configuration. Writing into a deployment-provided directory
or treating it as read-only are both plausible policies. This behavior was left unchanged.

Option A: Use the configured directory as the writable store when permitted, otherwise show an error.

Option B: Treat the environment override as read-only and disable editing while it is active.

Recommendation: A for interactive use, B for managed deployments. Can work continue without this answer? Yes.

## Suspicious unresolved areas

- Legacy GPX 1.0 inputs are rejected by the enrichment parser, while gpxpy-backed commands accept them.
  The supported-version policy is undocumented; conversion was not added speculatively.
- Cancellation remains cooperative around blocking network phases. Immediate cancellation of a running
  HTTP request is not provided, and country lookups/retries may delay cancellation.
- Checkpoints without a fingerprint, or with a changed country plan, are deliberately refused.
  Keep the partial GPX, remove the incompatible `.enrich-checkpoint.json` sidecar, and start a fresh
  search when that is intended. The UIs would benefit from an explicit restart/discard control.
- Process death loses Android's in-memory resume metadata even when work files survive. Durable
  cross-process resume is not documented as a supported product contract.
- Older snapshots retain any precision already lost through six-decimal serialization. The precision
  fix preserves new snapshots; it cannot reconstruct coordinates discarded by an older version.
- Google directions and point links use separate parsers/redirect implementations. Point-link host,
  credential, port, pin-priority, and foreign-redirect contracts now have offline tests; uncommon Google
  URL encodings and real short-link behavior still need curated, scrubbed integration examples.
- Coordinate-bearing routing logs and verbose response bodies need a clear privacy/redaction policy
  consistent with the repository's location-data guidance.

## Verification performed

All commands used the repository's required `rtk` prefix; it is omitted below for readability.

- Baseline `uv run --frozen pytest`: **206 passed**.
- Python 3.13.14, isolated environment with dev and GUI extras:
  `uv run --frozen --python 3.13 --extra dev --extra gui pytest --cov=gpx_poi_enricher`:
  **274 passed**, coverage **64.79%**, branch coverage **55.18%**. The continuation used explicit
  `--cov-branch` and wrote coverage XML to `/tmp/gpx-poi-audit-coverage-final.xml`.
- Python 3.14.5, `uv run --frozen pytest`: **274 passed**.
- Targeted regressions were run red before fixes for the significant Python/bridge defects, including
  disk-write failure, mismatched resume, stale routes, missing milestones, changed original waypoints,
  form data loss, zero retries, rounded radius, shell quoting, and checkpoint coordinate precision.
- Seeded differential probe: **100 long-polyline cases** matched an exhaustive segment reference.
  A local performance probe of 100 queries against 10,000 segments took approximately **0.66 seconds**.
- `uv run --frozen ruff check .`, `ruff format --check .`, and the full pre-commit hook suite.
  New, untracked test/report files are also checked explicitly with `pre-commit --files`.
- `uv build --out-dir /tmp/gpx-poi-audit-dist`: wheel and sdist build successfully. Extracted-wheel
  smoke test resolves **10 profiles / 93 catalog entries** outside the source checkout.
- `xmllint --noout --schema /tmp/gpx-poi-audit-schema.xsd /tmp/gpx-poi-audit-output.gpx`: **valid**.
  The continuation also validates `/tmp/gpx-poi-audit-precision.gpx`, containing tiny decimal
  coordinates that would ordinarily use scientific notation.
- Android `./gradlew assembleDebug test lintDebug lintAudit`: **successful**. Current lint reports
  **0 errors / 63 warnings** for debug and **0 errors / 74 warnings** for the audit variant. All three
  Kotlin variants compile. Local unit-test tasks still report **NO-SOURCE**.
- Android `./gradlew connectedAuditAndroidTest -Pandroid.injected.device.serial=emulator-5580`
  with `ANDROID_SERIAL=emulator-5580`: **5 device tests passed**. The scratch-file regression was
  first run failing against the original implementation. The isolated audit APK removes Internet
  permission and the ads startup provider; its runner bootstraps Python without billing/ads startup.
  External HTTP results are mocked inside Python; the Kotlin, bridge, engine, and MediaStore paths
  are real. No existing user virtual device was modified.
- `bash -n android/build-apk.sh scripts/setup-pre-commit.sh`: **passed**.
- `uv audit --locked --preview-features audit`: **passed after the approved update**, with
  **no known vulnerabilities** in 52 packages. Both Python test runs also passed after the update.
- Reviewed the final diff and confirmed CI, AGENTS, README, project version/Python policy, signing files,
  and release/deployment workflows were preserved. `uv.lock` changed only through the approved update.

Native sanitizers do not apply to the edited Python/Kotlin application logic. No production deployment,
Play upload, real-user GPX upload, or account purchase/advertising flow was executed.

## Residual risk

Desktop and Android duplicate substantial orchestration, and this caused matching defects in route
reuse and alternate milestones. Future changes need paired contract tests until there is a deliberately
designed shared seam. This audit does not redesign that architecture.

Geometry still uses a local tangent-plane projection for segments; unusually long or polar edges and
very large route sets deserve additional accuracy/performance checks. Separate snapshot/sidecar
durability has not been stress-tested through real process or power loss.

Android device coverage currently uses one recent arm64 emulator and app-owned MediaStore rows.
It does not establish behavior on older supported API levels, SAF providers or persistable picker
grants, actual Fragment recreation, process death, billing, or consent. Overall test coverage remains
incomplete, and passing tests do not establish that the repository is bug-free.

## Recommended next highest value checks

1. Extend Android device coverage to actual interrupted-job rotation, SAF grant restoration and
   provider failures, Maps/Split cancellation, restored purchase acknowledgement, consent
   errors/revocation, and the oldest supported Android versions.
2. Resolve the product contracts above, then encode them as shared desktop/Android acceptance cases.
3. Run a scrubbed, opt-in service smoke test and a large-route/cold-start Android bootstrap test.
