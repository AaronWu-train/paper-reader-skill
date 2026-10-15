const path=require('path');
const {chromium}=require(require.resolve('playwright',{paths:[process.argv[4]||process.cwd()]}));
const {pathToFileURL}=require('url');
const fs=require('fs');
(async()=>{
const reader=path.resolve(process.argv[2]);
const evidence=path.join(reader,'source','validation');fs.mkdirSync(evidence,{recursive:true});
const browser=await chromium.launch({...(process.argv[3]?{executablePath:process.argv[3]}:{}),headless:true});
const page=await browser.newPage({viewport:{width:1280,height:1000}});
const failures=[];const network=[];const consoleErrors=[];
page.on('request',r=>{if(/^https?:/.test(r.url()))network.push(r.url())});
page.on('pageerror',e=>consoleErrors.push(String(e)));
page.on('requestfailed',r=>failures.push({url:r.url(),reason:r.failure()}));
await page.goto(pathToFileURL(path.join(reader,'index.html')).href);
await page.evaluate(async()=>{const imgs=[...document.images];imgs.forEach(i=>i.loading='eager');await Promise.all(imgs.map(i=>i.decode().catch(()=>null)))});
const baseline=await page.locator('main .block').evaluateAll(es=>es.map(e=>e.id));
const canonical=fs.existsSync(path.join(reader,'content.en.html'));
const title=await page.locator('main h1').textContent();
const modes=[];
for(const value of ['zh','en','both']){
 await page.locator(`input[value="${value}"]`).check();
 const state=await page.evaluate(()=>({mode:document.documentElement.dataset.mode,zhVisible:[...document.querySelectorAll('main .lang-zh')].filter(e=>getComputedStyle(e).display!=='none').length,enVisible:[...document.querySelectorAll('main .lang-en')].filter(e=>getComputedStyle(e).display!=='none').length,ids:[...document.querySelectorAll('main .block')].map(e=>e.id)}));
 if(JSON.stringify(state.ids)!==JSON.stringify(baseline))throw Error('Block order changed');
 if(state.mode!==value || (value==='zh' && state.enVisible) || (value==='en' && state.zhVisible) || (value==='both' && (!state.enVisible||!state.zhVisible)))throw Error('Language toggle failed');
 if(canonical){
  if(await page.locator('main h1').textContent()!==title || await page.locator('main h1 .lang-zh').count())throw Error('Paper title must stay in English');
  const suffixes=page.locator('main .heading-en,#toc .heading-en');
  if(!await suffixes.count() || await suffixes.evaluateAll(es=>es.some(e=>e.checkVisibility()))!==(value==='zh'))throw Error('Bilingual chapter heading display failed');
 }
 delete state.ids;modes.push(state);
}
await page.locator('input[value="zh"]').check();
const inspect=await page.evaluate(()=>({badImages:[...document.images].filter(e=>!e.complete||!e.naturalWidth).map(e=>e.src),imageCount:document.images.length,brokenAnchors:[...document.querySelectorAll('a[href^="#"]')].filter(a=>!document.getElementById(a.hash.slice(1))).map(a=>a.hash),mathCount:document.querySelectorAll('math').length,unrenderedVisibleMath:[...document.querySelectorAll('math')].filter(m=>!m.closest('.lang-en')).filter(m=>!m.getBoundingClientRect().height).length,bodyOverflow:document.documentElement.scrollWidth>innerWidth,untranslated:document.body.textContent.includes('〔待翻譯〕'),rawTex:document.body.textContent.includes('\\affilnum')||document.body.textContent.includes('\\raisebox')}));
await page.screenshot({path:path.join(evidence,'desktop.png')});
if(await page.locator('.equation').count())await page.locator('.equation').first().scrollIntoViewIfNeeded();await page.screenshot({path:path.join(evidence,'math.png')});
if(await page.locator('main .image').count())await page.locator('main .image').first().scrollIntoViewIfNeeded();await page.screenshot({path:path.join(evidence,'figure.png')});
await page.locator('#theme-toggle').click();await page.screenshot({path:path.join(evidence,'dark.png')});
await page.setViewportSize({width:390,height:844});
await page.evaluate(()=>window.scrollTo(0,0));
await page.locator('#toc-toggle').click();if(!await page.locator('#toc').isVisible())throw Error('Mobile TOC failed');
await page.locator('#toc a[href^="#"]').first().click();
const mobile=await page.evaluate(()=>({tocClosed:!document.querySelector('#toc').classList.contains('open'),overflow:document.documentElement.scrollWidth>innerWidth,overflowNodes:[...document.querySelectorAll('main *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1&&getComputedStyle(e).display!=='none').slice(0,12).map(e=>({tag:e.tagName,id:e.id,cls:e.className,text:e.textContent.slice(0,50),right:e.getBoundingClientRect().right})),hash:location.hash}));
await page.screenshot({path:path.join(evidence,'mobile.png')});
const result={modes,inspect,mobile,network,failures,consoleErrors};fs.writeFileSync(path.join(evidence,'browser-result.json'),JSON.stringify(result,null,2));
await browser.close();console.log(JSON.stringify(result));
if(inspect.badImages.length||inspect.brokenAnchors.length||inspect.unrenderedVisibleMath||inspect.bodyOverflow||inspect.untranslated||inspect.rawTex||network.length||failures.length||consoleErrors.length||mobile.overflow||!mobile.tocClosed)process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1});
