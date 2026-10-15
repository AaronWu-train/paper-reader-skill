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
python scripts/reader.py pending READER --section S1
python scripts/reader.py translate READER /path/to/translation.json
python scripts/reader.py format READER --patch /path/to/emphasis.json
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

`pending` emits only untranslated units; chapter selection includes subsections. Patches map IDs to translated strings with all `{{N}}` tokens conserved. Protected tokens reference original formulas, links, superscripts/subscripts and code. Patches are validated as a whole before saving Chinese HTML. Existing translations are protected; explicit `--replace ID` applies only to that unit and clears stale Chinese emphasis.

Strong/em/u and source-color annotations preserve original emphasis. Normalized content retains small `data-*` annotations for section membership, preservation, pending status, protected fragments and source-emphasis identity. They are stripped from the reading DOM. Do not include arbitrary source layout classes/styles. Original-math fragments may retain necessary MathML properties and sanitized equation-layout tables; prose/data tables remain PDF images.

The shared glossary starts empty. The optional [ML/RL glossary example](glossary-ml-rl.example.tsv) is a starting point for relevant papers, not a default for other disciplines. Record paper-specific choices in `source/reader.json`.

English emphasis is collected during PDF extraction or HTML reconciliation. PDF font evidence requires exact text matching within Docling boxes; drawn underlines/scans still need visual review. Repeated formatting operations on normalized HTML do not rerun PDF extraction.

Chinese emphasis aligns by meaning, without proportional character offsets. Apply the existing selection patch:

```json
{"paragraph-id": [{"source": "f0", "text": "對應的中文片語", "occurrence": 1}]}
```

Occurrence is one-based and required for repeated phrases. Explicit selections retain source properties. Direct semantic HTML emphasis is supported; missing source correspondence is reported for manual alignment, never guessed. Format patches cannot change prose, and existing manual emphasis is protected. Stale/overlapping ranges, changed protected tokens and invalid mapped styles are rejected.

Source repair/scaffolding precedes acceptance. If English/PDF/assets change after acceptance, translation stops until the source is reviewed and accepted again; do not overwrite existing Chinese to work around a conflict.

## QA and regressions

`check` preserves `quality-report.json.manual_reviews` and `source_review`, including legacy qa.json records. It checks bilingual structure/order, unique IDs, formula/link token content, missing translations, emphasis, original table crops, local assets, reference targets, inventories and PDF fingerprint. Repeated prose is a warning, not permission to delete it.

Source completeness and semantic fidelity still require actual PDF/English comparison. Record method, scope, findings and limits. `accept-source` records that review and fingerprints files; it does not perform the review for you.

```sh
python -m unittest discover -s tests -p 'test_*.py'
node tests/browser_test.cjs READER_DIR CHROME_EXECUTABLE NODE_MODULES_DIR
```

Tests cover legacy compatibility, canonical HTML, protected/manual edits, acceptance, nested lists, offline/repeatable rendering and language structure. Browser tests write screenshots/evidence into that paper's `source/validation/`; inspect the screenshots as well as results. Use one selected paper for end-to-end validation, without automatically converting the library.
