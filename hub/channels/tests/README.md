# Channel integration tests

Two tiers of tests:

**Offline** (default): parse recorded HTTP responses under `fixtures/`. No
network. Fast. Runs on every CI build.

**Live** (`--live`): hits the real third-party services. Skipped by default.
Runs nightly in CI to surface API drift or outages.

## Run

```bash
# From hub/channels/
pip install -r requirements-dev.txt

pytest                     # offline only (fast, deterministic)
pytest --live              # offline + live
pytest --live -k endchan   # subset
pytest -m live --live      # live only
```

## Layout

```
tests/
├── conftest.py                          # --live flag, FakeSession, fixture loaders
├── fixtures/
│   ├── endchan/             (captured from live endchan.net)
│   ├── fourchan/            (captured from live a.4cdn.org)
│   └── spectrumcomputing/   (synthetic phpBB snippets — see note below)
├── test_endchan_offline.py
├── test_fourchan_offline.py
├── test_spectrumcomputing_offline.py
└── test_live.py
```

## Refreshing fixtures

JSON/HTML fixtures get stale when upstream changes. The live tests detect
that. To refresh the endchan/fourchan fixtures, run the capture helper at
`/tmp/capture_fixtures.py` (kept out of the repo — run it ad-hoc). The
spectrumcomputing fixtures are hand-written; see the next section.

## Why spectrumcomputing fixtures are hand-written

As of 2026-04 the site has gone login-walled for anonymous users
("This board has no forums. — forums accessible to logged in members only"),
so there is no live public content to capture. The fixtures are minimal
phpBB-style HTML that exercises the parser. The live test for
spectrumcomputing is expected to **fail** until anonymous access is restored
or the plugin gains credentialed login support — this is a feature, not a
bug: it's exactly the "API went away" signal the live tier is for.

## Known issue flagged by a test

`test_get_threads_handles_topic_without_preview_block` is marked `xfail`:
the spectrumcomputing plugin crashes when a topic lacks a
`topic_preview_content` block (calls `.find()` on `None`). The exception
handler swallows the error and silently drops the thread. Remove the
`xfail` once the plugin defends against missing previews.
