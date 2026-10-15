# Paper Reader：HTML 內容規格

狀態：已實作。新轉換使用此規格；既有 JSON reader 可透過 `migrate` 轉換，不會自動批次遷移。

## 檔案與責任

每篇論文使用 `content.en.html` 與 `content.zh.html` 作為可編輯的正式內容。兩份都是 HTML fragment，只有一個 `<article>`，不包含 `<html>`、`<head>`、網站工具列、CSS 或 JavaScript。

共用模板、CSS、JS 負責外觀、目錄、語言切換、圖片放大與深色模式。每篇只填內容及本機資源，不新增逐篇 CSS，也不手改生成的 `index.html`。

保留現有離線方式：固定生成器讀取兩份 content，組合成可直接以 `file://` 開啟的 `index.html`，並複製共用 CSS／JS。閱讀時不需要 fetch、伺服器或網路。HTML 是正式內容格式，不再另外維護一份相同用途的 JSON；原始擷取資料與品質報告可仍使用 JSON。

所有 `src`／本機 `href` 均相對於 `reader/`，生成器不改變其解析位置。來源 PDF、原有 Markdown 筆記、既有 reader 資料均不因本規格被改名、搬移或刪除。

## 可使用的內容結構

- 論文標題：一個 `<h1>`。
- 章節：`<section>` 包含 `<h2>` 至 `<h4>`；原始章節編號直接保留在標題文字內。
- 正文：`<p>`；文字強調使用 `<strong>`、`<em>`、`<u>`，上下標使用 `<sup>`、`<sub>`。
- 清單：`<ul>`／`<ol>` 與 `<li>`，可巢狀。有意義的起始編號使用 `start`／`value`。
- 圖片：`<figure>` 包含 `<img>` 和 `<figcaption>`。圖內子圖、左右對照及其共同圖說維持同一個 figure；需要保留位置關係時使用整張原始 PDF 裁切。
- 表格：同樣使用 `<figure>`、原始 PDF 裁切 `<img>` 與 `<figcaption>`；表內內容不另建 HTML table，也不翻譯。裁切須包含完整表格及表內註解。
- 公式：可靠的原始 MathML；獨立公式可包在 `<div class="math-block">`。不可靠的公式使用原始 PDF 裁切，行內公式則可使用 `<img class="inline-math">`。保留原始公式編號及引用。
- 引用與註腳：`<a href="#target-id">`，外部連結使用來源提供的 `https://` 或 `http://` URL。註腳與參考文獻放在各自的 `<section>`，條目使用有 ID 的 `<li>` 或 `<p>`。
- 作者與出版資訊：`<p class="metadata">`。參考文獻標題與需保留的姓名維持英文。

圖、表、公式的原始標號直接寫在 caption／公式標號中，固定程式不重新編號。附件或演算法可用一般章節、段落、清單及原始 PDF 圖片表達。

一般文字不保留來源網站的任意 class、style、表格排版或 script。固定 class 包含 `metadata`、`caption`、`reference`、`footnote`、`anchor`、`math-block`、`inline-math`、`thumbnail-row`、`source-emphasis`、`footnote-ref`、`bibliography-number`、`preserved`；新增顯示行為時更新共用規格與 renderer。既有單獨 caption 可使用 `<p class="caption">`，不需要靠版面猜測將它搬入 figure。

原文具有語意的強調顏色可用 `<span data-source-color="#rrggbb">` 保留；也接受現有來源的安全 CSS 顏色名稱及 rgb/rgba 值。這是原文文字強調，不是逐篇排版。MathML 保留必要的數學屬性；來源公式的排版 table 可在受保護的 `data-original-math="true"` 片段中保留，正文與資料表格仍使用前述規則。

正規化工具可使用 `data-kind`、`data-section`、`data-unit`、`data-preserve` 標記類型、章節、翻譯單元與保留原文。`data-token` 包住受保護公式／連結；`data-emphasis` 與中文 `data-source` 記錄強調對應。`data-bold/italic/underline` 僅保存原始有效字型及恢復一般格式的範圍。這些都是固定屬性，不是另一套內容語法；生成閱讀頁時移除。

## 英文與中文的對應

兩份 content 共用同一套章節、段落、清單項目、figure、caption、公式及參考文獻 ID。ID 使用英數字、連字號、底線或句點，在各自文件內唯一；驗收後不因翻譯重新產生 ID。

英文章節與可翻譯單元完成整理後，先生成英文版並對照 PDF 驗收。中文檔案使用相同結構與順序；翻譯可以調整文字及對應的強調位置，保留圖片路徑、公式內容、引用目標與其他結構屬性。連結及其中的引用標記保留原文，與公式一樣作為受保護片段。圖片 alt 與 caption 可以翻譯，圖片本身共用。

未翻譯單元複製英文文字，並在該單元加上 `data-translation="pending"`；完成後移除此屬性。英文來源檢查與翻譯完成度分開判定，未翻譯不阻擋英文版產生。

中英對照由固定生成器依 ID 配對。合併顯示時只保留一個共同的目標 ID，語言內容放在其下；不得直接串接兩個 article 而造成重複 ID。對應、模式切換、目錄與引用由共用程式處理。

論文主標題在所有模式都顯示英文。中文模式的章節標題及目錄顯示「中文（English）」，括號內省略重複的章節編號；原已保留相同英文的標題不重複。英文模式顯示原文，對照模式分行顯示中英文。這些由生成器統一組合，中文 content 的章節標題只填譯文，不自行附加英文。

### 英文 content 範例

```html
<article lang="en" data-content-version="1">
  <h1 id="title">Paper title</h1>
  <section id="s1">
    <h2 id="s1-title">1 Introduction</h2>
    <p id="s1-p1">We study <strong>robot learning</strong>; see <a href="#fig1">Figure 1</a>.</p>
    <ul id="s1-list1">
      <li id="s1-list1-item1">First observation.</li>
    </ul>
    <figure id="fig1">
      <img src="assets/figure-1.png" alt="Overview of the method">
      <figcaption id="fig1-caption">Figure 1: Method overview.</figcaption>
    </figure>
  </section>
</article>
```

### 中文 content 範例

```html
<article lang="zh-Hant" data-content-version="1">
  <h1 id="title">Paper title</h1>
  <section id="s1">
    <h2 id="s1-title">1 緒論</h2>
    <p id="s1-p1">我們研究<strong>機器人學習</strong>；請見 <a href="#fig1">Figure 1</a>。</p>
    <ul id="s1-list1">
      <li id="s1-list1-item1">第一項觀察。</li>
    </ul>
    <figure id="fig1">
      <img src="assets/figure-1.png" alt="方法概覽">
      <figcaption id="fig1-caption">圖 1：方法概覽。</figcaption>
    </figure>
  </section>
</article>
```

## 固定的生成與驗證規則

1. 使用 HTML parser 讀取並驗證規格；拒絕不支援的元素、屬性、重複 ID、不安全 URL 及破損的本機資源。不要用正則或純字串取代來配對整份文件。
2. 來源轉換先將一般內容正規化為上述結構；保留原始擷取資料作為查核證據。不能忠實表達的圖表／公式使用原始 PDF 備援並記錄，不默默丟棄內容。
3. renderer 依既定結構生成，不能猜圖表配對、改標號、拆合段落、翻譯或修改 content。圖表配對與文字修復都在內容整理階段完成。
4. 翻譯後檢查結構、ID 順序、圖片、公式與連結目標不變。文字強調依語意對齊，不按字數比例移動。
5. 同一組 content、來源 metadata、資源相對位置、共用模板及 renderer 版本，重複生成相同位元組的 HTML／CSS／JS；生成前後 content 不變。QA 校對紀錄及執行時間不注入正文。
6. 瀏覽器檢查涵蓋標題／正文／caption 的三種語言模式、內部引用、圖片、公式、桌面／手機與深色模式。檢查時固定視窗、主題與語言，閱讀時仍可保存個人偏好。

內容錯誤修 content；顯示問題修共用 renderer／CSS／JS。共用功能的修正以既有 readers 回歸驗證，不新增逐篇排版補丁。

## 使用與相容性

新 `extract`／`align-html` 會輸出上述 HTML。英文修復後執行 `sync-source` 建立待翻譯的中文結構；已驗收或已有翻譯時拒絕重建。先 `render` 檢查英文，再使用 `accept-source --review-note` 記錄實際來源檢查並固定雜湊，接著 `pending`／`translate`／`format`／`render`。

`source/reader.json` 只保存 PDF、術語、來源位置、預期清單和校對旗標，沒有另一份正文。`source/accepted-source.json` 保存來源驗收記錄。HTML 是唯一正式內容；JSON patch 只是命令輸入。

`migrate` 保留舊 `content.json` 與完整備份，不覆寫既有 HTML 或人工翻譯。未遷移的舊 reader 仍可使用原本的工具。缺少完整表格裁切的舊 reader 必須先補齊來源，不能以不完整的新網頁取代舊頁面。
