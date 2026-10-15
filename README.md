# Paper Reader

將一篇英文論文 PDF 轉成可離線開啟的繁體中文／英文／雙語 HTML 閱讀器。保留公式、圖片、表格裁圖、引用與文字強調，支援分批翻譯及中斷續作。

這是一個供 Codex 等支援 `SKILL.md` 的 agent 使用的 skill。Python 負責擷取、儲存、渲染與檢查，**翻譯與逐段校對由 agent 完成**，並非執行一條 Python 命令就能自動翻譯。無須另外設定翻譯 API key；使用 agent 本身仍需相應帳號與用量。

## 安裝

需要 Python 3.10 以上；已驗證的環境為 Python 3.12、Docling 2.138.0。將整個資料夾放進 agent 的 skill 目錄即可，例如 Codex 的 `~/.codex/skills/paper-reader/`，或個別專案的 `.agents/skills/paper-reader/`。資料夾根目錄應直接包含 `SKILL.md`、`scripts/`、`assets/`、`references/`。

在複製後的 skill 資料夾執行：

```sh
python3 -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell 改用：.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts/reader.py --help
```

若已有相容的 Docling 環境，可直接使用，不必重複安裝。後續命令使用同一環境的 Python；所有 `scripts/...` 路徑均相對於 skill 資料夾。從其他位置呼叫時請使用腳本完整路徑。

Docling 第一次擷取需要下載 layout／table 模型；可用 `--artifacts-path /path/to/models` 指定模型目錄。擷取與尋找輔助 HTML 可能需要網路；生成後閱讀 `index.html` 不需要網路或伺服器。

HTML 比對需要 Poppler 的 `pdftotext`；文字強調擷取使用 `pdftohtml`，未安裝時需人工檢查強調。例如 macOS 可用 `brew install poppler`，Ubuntu/Debian 可用 `sudo apt install poppler-utils`。Windows 請安裝 Poppler 並將其 `bin` 加入 PATH。掃描 PDF 可加 `--ocr`，OCR 品質及語言套件需依來源另行檢查。

## 交給 agent 使用

在已安裝 skill 的環境中輸入，例如：

> 使用 $paper-reader，將 `/path/to/paper.pdf` 完整翻譯成繁體中文離線閱讀器，輸出到 `/path/to/paper-reader`。請先檢查擷取完整性，保留原始 PDF、公式、圖片與參考文獻。

支援本機 PDF、只有一個 PDF 的資料夾、直接 PDF URL，以及 arXiv URL／ID。路徑有空格時，命令列中請加引號。

- 本機預設：`/path/to/paper.pdf` → `/path/to/paper-reader/`。
- 可用 `--output` 指定其他位置。URL／arXiv 必須指定輸出位置；下載的 PDF 存在輸出內的 `source/original.pdf`。
- 原始 PDF 不修改；同一 PDF 已有輸出時會沿用內容，保護既有翻譯。
- 預設詞彙表為空白；依論文領域建立術語選擇。`references/glossary-ml-rl.example.tsv` 為選用範例，可擷取適用詞條加入 `references/glossary.tsv`，影響之後新建的 reader。

## 命令流程

以下的 `READER` 代表輸出資料夾。詳細內容規格與命令見 [SKILL.md](SKILL.md) 與 [workflow.md](references/workflow.md)。

```sh
python scripts/reader.py resolve /path/to/paper.pdf
python scripts/reader.py extract /path/to/paper.pdf
# 或指定輸出；遠端輸入必須指定：
python scripts/reader.py extract https://arxiv.org/abs/2303.04137v5 --output /path/to/paper-reader
```

先對照 PDF 修復 `content.en.html`。若有同版本官方 HTML，可選用 `align-html` 輔助比對；沒有 HTML 也可繼續。修復後同步待翻譯結構、生成英文頁面並實際檢查，再接受來源：

```sh
python scripts/reader.py sync-source READER
python scripts/reader.py render READER
# 實際開啟 index.html、對照 PDF 後，填入真實的檢查紀錄：
python scripts/reader.py accept-source READER --review-note "實際檢查範圍、發現與限制"
python scripts/reader.py pending READER
```

由 agent 按 ID 產生翻譯 patch，保留所有 `{{N}}` token；`translate` 本身只套用譯文：

```json
{"paragraph-id": "保留 {{0}} 的完整譯文。"}
```

```sh
python scripts/reader.py translate READER /path/to/translation.json
# 同批翻譯時產生強調格式 patch，先套用翻譯，再套用格式：
python scripts/reader.py format READER --patch /path/to/emphasis.json
python scripts/reader.py render READER
python scripts/reader.py check READER
```

`pending` 預設以精簡格式輸出最多 10 個單元、8,000 JSON 字元（單一超長段落完整輸出並提示），可用 `--limit`、`--max-chars` 調整。套用當批翻譯及格式後，再取得下一批；需要公式或來源細節時使用 `pending READER --id UNIT --full`。已驗收且未變更的來源可直接續翻，無須重做來源校對。`check` 發現缺譯或結構錯誤時返回非零代碼。機械檢查通過仍需要人工確認語意、PDF 完整性及瀏覽器顯示。

正式內容為 `content.en.html`、`content.zh.html`；`index.html` 是生成檔，請勿直接修改。表格、圖內文字及不可靠的公式使用原始 PDF 圖像，圖片內文字不另外翻譯，圖說可翻譯。分享產出的 reader 時，本機來源請連同原 PDF 保留兩者相對位置；僅搬動 reader 會使「開啟 PDF」連結失效。重新產生／檢查時也需要來源 metadata 中所記錄的 PDF 路徑仍有效。

## 驗證

在已安裝依賴的環境執行：

```sh
python -m unittest discover -s tests -p 'test_*.py'
```

選用瀏覽器檢查另需 Node.js、Playwright 與 Chromium/Chrome。在獨立的 Node 環境安裝 Playwright 後，執行：

```sh
node tests/browser_test.cjs READER /path/to/chrome /path/to/node_modules
```

瀏覽器檢查適用於已完成翻譯、含章節與雙語正文的 reader；結果與截圖存在 `READER/source/validation/`。此工具沒有保證任意 PDF 都能正確自動擷取；複雜版面、掃描、公式及來源錯字仍需對照 PDF 校對。
