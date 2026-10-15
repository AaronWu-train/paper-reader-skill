# Workflow and data

The editable paper is `content.en.html` plus `content.zh.html`. Shared HTML/CSS/JS determines its appearance. JSON patches are temporary command inputs, not a second editable copy of the article.

## Commands

Run in an existing Python with lxml/pypdfium2; the installed Docling environment normally provides both. Resolve scripts relative to this skill.

```sh
python scripts/reader.py extract /path/to/paper.pdf --output /path/to/paper-reader --artifacts-path /path/to/models
# Optional, only when exact-version auxiliary HTML is available:
python scripts/reader.py align-html READER --url https://arxiv.org/html/EXACT_VERSION
# Repair/review English HTML and attach complete PDF crops if needed.
python scripts/reader.py sync-source READER
python scripts/reader.py render READER
# Actually compare English/PDF and inspect the offline reader before acceptance.
python scripts/reader.py accept-source READER --review-note "checks performed, findings, limitations"
python scripts/reader.py pending READER --section S1 --limit 10 --max-chars 8000
# Produce/review both patches from this batch while it is in context; save them.
python scripts/reader.py translate READER READER/source/translations/001.json
python scripts/reader.py format READER --patch READER/source/translations/001-emphasis.json
# Skip format for batches without source emphasis. Repeat pending only after applying.
# Render/check once batches are finished (or when investigating an actual error).
python scripts/reader.py render READER
python scripts/reader.py check READER
```

`migrate READER` converts an existing JSON reader without retranslation. `crop READER --page N --bbox L T R B --name NAME.png` saves a literal original-PDF crop; attach its relative path to content. Bbox uses top-left PDF coordinates.

## Storage and deterministic output

See [html-content-spec.md](html-content-spec.md) for supported semantic HTML and examples. Stable IDs pair both languages. Translation changes prose/emphasis; shared assets, math and link destinations remain protected. English source is fingerprinted after review and remains byte-for-byte unchanged during translation.

`source/reader.json` stores PDF/hash, glossary choices, expectations, provenance and correction flags. It contains no duplicate paragraph text or translations. `source/accepted-source.json` records accepted English/PDF/asset fingerprints and actual review note. Both are versionable; raw extraction, snapshots and legacy archives remain intermediates under `source/`.

The parser builds an in-memory view for the established translation/QA commands. That view is not another canonical article. A migrated root `content.json` remains an untouched compatibility backup and is ignored once HTML exists. Its full original bytes, including historical table translations, are also archived as `source/legacy-content.json`.

`render` reads contents, preserves manual/source QA records and emits offline index.html/CSS/JS. Identical contents/source metadata/resource locations/template/tool version produce identical output bytes; QA dates/manual-review edits do not change article rendering. There is no runtime content fetch. Renderer refuses structural/source errors before replacing index.html; pending Chinese translations are allowed, with English as the default mode.

Never edit generated index.html. Fix paper content in the HTML files and rendering behavior in shared assets. Retain existing manual edits; migration/scaffold commands refuse unsafe replacement.

## Source reconciliation

Local PDF is authoritative. Bibliography abstracts can be stale. Official HTML/ar5iv is auxiliary and must match the exact PDF version; publisher/unversioned HTML requires concrete comparison evidence. Do not bypass logins/paywalls. Remote originals require an explicitly selected output directory. Local inputs need only a PDF path or a directory containing one PDF; no `Papers/`, bibliography or note is required. Default local output is `<PDF-stem>-reader/` beside the PDF, preventing different PDFs in one folder from sharing a reader.

`align-html` uses the established PDF/HTML matching and original table-crop pairing. It runs before English acceptance/translation, then exports normalized HTML. It does not certify equivalence. Classify unmatched PDF blocks against page renders and recover missing prose/math/graphics. Keep original citations and numbering; record source conversion errors and author inconsistencies instead of silently correcting them.

Tables are original-PDF images in all modes, with separate translated captions. Match by caption label, never by table order. Missing or ambiguous matches require source inspection and complete crops including notes. Related subfigures and left/right relationships require a complete original visual or an explicitly verified content grouping, rather than a display patch.

Standard Docling needs layout/table models. Reuse a persistent cache with `--artifacts-path`; download missing layout/tableformer artifacts once. Do not download image-description/formula-generation models. Text PDFs default to no OCR; scanned PDFs require `--ocr` and extraction review. No HTML must never prevent PDF conversion.

## Translation and emphasis

`pending` defaults to compact JSON, at most 10 untranslated units and 8,000 serialized JSON characters. Chapter selection includes subsections. `--limit N` and `--max-chars N` must be positive. The first unit is emitted intact even if oversized, with a stderr warning; no prose is truncated or skipped. A short stderr summary gives emitted/matching counts and output size. This is a character budget, not a tokenizer or billing estimate. Apply a batch before fetching another; do not repeatedly dump the remaining article or raise limits just to load it all.

Compact entries include `id`, `en`, readable protected-token previews and source `styles` only when present. They omit PDF coordinates, raw markup and emphasis offsets. Math/image previews are marked `preview_only`; they cannot express all mathematical structure. If structure affects translation, a preview is truncated, or a token is unclear, inspect that unit with `pending READER --id UNIT --full`. Repeat `--id` for a few specific units. Explicit ID selection can also inspect translated units (includes `zh`) when recovering unfinished emphasis; unknown/preserved IDs fail. `--full` restores original token markup, section/type and source metadata but keeps batch limits. `--compact` explicitly selects the default format. Stdout remains a JSON array, including `[]` when no units match; summaries go to stderr.

Patches map IDs to translated strings with all `{{N}}` tokens conserved. Protected tokens reference original formulas, links, superscripts/subscripts and code; never insert preview descriptions into the translated string. Patches are validated as a whole before saving Chinese HTML. Existing translations are protected; explicit `--replace ID` applies only to that unit and clears stale Chinese emphasis.

Strong/em/u and source-color annotations preserve original emphasis. Normalized content retains small `data-*` annotations for section membership, preservation, pending status, protected fragments and source-emphasis identity. They are stripped from the reading DOM. Do not include arbitrary source layout classes/styles. Original-math fragments may retain necessary MathML properties and sanitized equation-layout tables; prose/data tables remain PDF images.

The shared glossary starts empty. The optional [ML/RL glossary example](glossary-ml-rl.example.tsv) is a starting point for relevant papers, not a default for other disciplines. Record paper-specific choices in `source/reader.json`.

English emphasis is collected during PDF extraction or HTML reconciliation. PDF font evidence requires exact text matching within Docling boxes; drawn underlines/scans still need visual review. Repeated formatting operations on normalized HTML do not rerun PDF extraction.

While translating/reviewing each batch, produce both the translation patch and, only for units with source `styles`, a separate emphasis patch. Review completeness, negation, uncertainty, conditions, quantities and terminology in that same pass. Save both patches in `source/translations/` with matching batch names; apply translation first and emphasis second before fetching another batch. They remain separate validated commands, not an atomic pair: if interrupted after translation, apply the saved emphasis patch before continuing. Use `pending --id UNIT` for just the affected unit if recovery needs context. No patch schema change or second model pass is needed. Chinese emphasis aligns by meaning, without proportional character offsets. Apply the existing selection patch:

```json
{"paragraph-id": [{"source": "f0", "text": "對應的中文片語", "occurrence": 1}]}
```

Occurrence is one-based and required for repeated phrases. Explicit selections retain source properties. Direct semantic HTML emphasis is supported; missing source correspondence is reported for manual alignment, never guessed. Format patches cannot change prose, and existing manual emphasis is protected. Stale/overlapping ranges, changed protected tokens and invalid mapped styles are rejected.

Source repair/scaffolding precedes acceptance. On resume, reuse accepted source and completed review coverage; do not repeat extraction, HTML search/reconciliation or full PDF review for each batch. `translate` verifies English/PDF/asset fingerprints. If they change, translation stops until the affected source is reviewed and accepted again; do not overwrite existing Chinese or simply renew acceptance to work around a conflict.

## QA and regressions

`check` preserves `quality-report.json.manual_reviews` and `source_review`, including legacy qa.json records. It checks bilingual structure/order, unique IDs, formula/link token content, missing translations, emphasis, original table crops, local assets, reference targets, inventories and PDF fingerprint. Repeated prose is a warning, not permission to delete it.

Source completeness and semantic fidelity still require actual PDF/English comparison. Record method, scope, findings and limits. `accept-source` records that review and fingerprints files; it does not perform the review for you.

Separate the work: review source completeness before acceptance; review translation semantics once per batch while translating; let Python check structure, IDs, tokens and assets. Run final render/check and inspect browser behavior once translation is finished. Recheck changed/unresolved passages or an actual rendering failure, rather than rereading all PDF/English/Chinese or running full browser QA per batch. Record reviewed batch IDs/ranges and unresolved issues in `manual_reviews` without duplicating article text. Do not claim semantic review coverage for passages not actually reviewed. Shared renderer/CSS/JS changes still require regressions.

```sh
python -m unittest discover -s tests -p 'test_*.py'
node tests/browser_test.cjs READER_DIR CHROME_EXECUTABLE NODE_MODULES_DIR
```

Tests cover legacy compatibility, canonical HTML, protected/manual edits, acceptance, nested lists, offline/repeatable rendering and language structure. Browser tests write screenshots/evidence into that paper's `source/validation/`; inspect the screenshots as well as results. Use one selected paper for end-to-end validation, without automatically converting the library.
