#!/usr/bin/env python3
"""One-paper, resumable offline reader. Python extracts/renders; Codex translates."""
from __future__ import annotations
import argparse
import base64
import copy
import csv
import hashlib
import html as stdhtml
from html.parser import HTMLParser
import json
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
TOKEN = re.compile(r"\{\{(\d+)\}\}")


def read(path):
    path=Path(path)
    if path.name=='content.json' and html_layer().active(path.parent):
        return html_layer().load(path.parent,globals())
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    path = Path(path)
    if path.name=='content.json' and html_layer().active(path.parent):
        return html_layer().write(path.parent,value,globals())
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")
    Path(f.name).replace(path)


def html_layer():
    # Lazy loading keeps resolve usable without the PDF/HTML dependencies.
    global _html_layer
    if '_html_layer' not in globals():
        spec=importlib.util.spec_from_file_location('paper_reader_html',SKILL/'scripts/html_content.py')
        _html_layer=importlib.util.module_from_spec(spec);spec.loader.exec_module(_html_layer)
    return _html_layer


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def localize_docling_assets(raw, base, out):
    """Keep cached source images independent of a temporary CLI export directory."""
    dest=out/'source/docling-assets'
    def visit(value):
        if isinstance(value,dict):
            uri=value.get('uri')
            if isinstance(uri,str) and not uri.startswith(('data:','http:','https:')):
                source=Path(urllib.parse.unquote(uri.removeprefix('file://')))
                if not source.is_absolute():source=base/source
                if source.is_file():
                    dest.mkdir(exist_ok=True)
                    target=dest/source.name
                    if source.resolve()!=target.resolve():shutil.copy2(source,target)
                    value['uri']='docling-assets/'+source.name
            for child in value.values():visit(child)
        elif isinstance(value,list):
            for child in value:visit(child)
    visit(raw)


def textnorm(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def resolve(value):
    """Resolve a PDF path or a directory containing exactly one PDF."""
    p = Path(value).expanduser()
    if p.is_file() and p.suffix.lower() == ".pdf":
        return p.resolve()
    if not p.is_dir():
        raise ValueError(f"PDF path not found: {value!r}. Pass a PDF path or a directory containing one PDF.")
    candidates = [f for f in p.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
    if len(candidates) != 1:
        raise ValueError(f"Expected one PDF for {value!r}; found {len(candidates)}. Pass its exact path.")
    return candidates[0].resolve()


def download(url, dest):
    if urllib.parse.urlparse(url).scheme not in ("https", "http"):
        raise ValueError("Only HTTP(S) sources are accepted.")
    dest = Path(dest)
    if dest.exists():
        return dest
    req = urllib.request.Request(url, headers={"User-Agent": "paper-reader/1.0"})
    with urllib.request.urlopen(req, timeout=45) as response:
        data = response.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def unit(uid, en, *, original=None, tokens=None, preserve=False):
    return {"id": uid, "en": en.strip(), "zh": None, "html": original,
            "tokens": tokens or {}, "preserve": preserve}


def all_units(content):
    for b in content["blocks"]:
        if b['type']=='table':
            continue
        for u in b.get("units", []):
            yield b, u


def token_preview(fragment):
    """Readable context only; the original protected fragment stays on disk."""
    class Preview(HTMLParser):
        def __init__(self):
            super().__init__();self.parts=[];self.tags=[]
        def handle_starttag(self,tag,attrs):
            self.tags.append(tag)
            if tag=='img':self.parts.append(dict(attrs).get('alt',''))
        def handle_data(self,data):self.parts.append(data)
    parser=Preview();parser.feed(fragment)
    text=' '.join(' '.join(parser.parts).split())
    kind=next((tag for tag in ('math','img','a','code','sup','sub','br') if tag in parser.tags),'fragment')
    preview={'kind':kind,'text':text[:240]}
    if len(text)>240 or kind in ('math','img'):preview['preview_only']=True
    return preview


def pending(args):
    c=read(Path(args.reader)/'content.json');units=list(all_units(c));selected=set()
    requested=set(args.id or [])
    unknown=requested-{u['id'] for _,u in units if not u.get('preserve')}
    if unknown:raise ValueError('Unknown or preserved unit IDs: '+', '.join(sorted(unknown)))
    if c.get('_html') and args.section:
        root=html_layer().parse(args.reader,'content.en.html')
        for section in root.xpath('.//section[@id=$id]',id=args.section):selected.update(section.xpath('.//*[@id]/@id'))
    candidates=[(b,u) for b,u in units if not u.get('preserve')
                and (u['id'] in requested if requested else u['zh'] is None)
                and (not args.section or b['section']==args.section or b['section'].startswith(args.section+'.') or u['id'] in selected)]
    batch=[];size=2
    for b,u in candidates:
        if len(batch)>=args.limit:break
        styles=u.get('styles',{}).get('en',[])
        entry={'id':u['id'],'en':u['en']}
        if args.compact:
            if u['tokens']:entry['tokens']={k:token_preview(v) for k,v in u['tokens'].items()}
            if styles:entry['styles']=[{k:v for k,v in s.items() if k not in ('start','end')} for s in styles]
        else:
            entry.update(section=b['section'],type=b['type'],tokens=u['tokens'],styles=styles,source=b.get('source',{}))
        if requested and u['zh'] is not None:entry['zh']=u['zh']
        encoded=json.dumps(entry,ensure_ascii=False,separators=(',',':'))
        added=len(encoded)+(1 if batch else 0)
        if batch and size+added>args.max_chars:break
        batch.append(encoded);size+=added
        if size>args.max_chars:
            print('One unit exceeds --max-chars; emitted intact to avoid skipping or truncating it.',file=sys.stderr)
            break
    print('['+','.join(batch)+']')
    print(f'Emitted {len(batch)} of {len(candidates)} matching units; {size} JSON characters. '
          'Apply this batch before requesting the next; use --id ID --full for details.',file=sys.stderr)


def emphasis(element):
    """Only text emphasis properties, never layout or arbitrary source CSS."""
    tag=element.tag.lower() if isinstance(element.tag,str) else ''
    classes=element.get('class','').split()
    style={}
    if tag in ('b','strong') or any(c in classes for c in ('ltx_font_bold','ltx_tag_figure','ltx_tag_table')):style['bold']=True
    if 'ltx_font_medium' in classes:style['bold']=False
    if tag in ('i','em') or 'ltx_font_italic' in classes:style['italic']=True
    if tag=='u' or any(c in classes for c in ('ltx_font_underline','ltx_text_underline')):style['underline']=True
    for declaration in element.get('style','').split(';'):
        key,sep,value=declaration.partition(':');key=key.strip().lower();value=value.strip().lower()
        if not sep:continue
        if key=='font-weight' and value in ('normal','bold','bolder','100','200','300','400','500','600','700','800','900'):
            style['bold']=value in ('bold','bolder','600','700','800','900')
        elif key=='font-style' and value in ('normal','italic','oblique'):style['italic']=value!='normal'
        elif key in ('text-decoration','text-decoration-line') and value in ('none','underline'):style['underline']=value=='underline'
        elif key in ('color','--ltx-fg-color') and re.fullmatch(r'#[0-9a-f]{3}(?:[0-9a-f]{3})?|[a-z]+|rgba?\([\d.,%\s]+\)',value):style['color']=value
    return style


def emphasis_css(style):
    css=[]
    for key,values in [('bold',('font-weight','400','700')),('italic',('font-style','normal','italic')),('underline',('text-decoration-line','none','underline'))]:
        if key in style:css.append(values[0]+':'+values[1+bool(style[key])])
    if 'color' in style:css.append('color:'+style['color'])
    return ';'.join(css)


def styled_characters(element, tokens=None, inherited=None):
    """Flatten markup with effective styles; protected content remains one token."""
    chars=[];token_index=0
    def walk(n,parent_style):
        nonlocal token_index
        style={**parent_style,**emphasis(n)}
        if tokens is not None and (n.tag in ('math','a','cite','img') or 'ltx_note' in n.get('class','').split()):
            value='{{'+str(token_index)+'}}';token_index+=1
            chars.extend((ch,style) for ch in value)
            return
        chars.extend((ch,style) for ch in n.text or '')
        for child in n:
            if isinstance(child.tag,str):walk(child,style)
            chars.extend((ch,style) for ch in child.tail or '')
    walk(element,inherited or {})
    return chars


def normalized_styles(chars):
    normalized=[]
    for ch,style in chars:
        if ch.isspace():
            if not normalized or normalized[-1][0]==' ':continue
            ch=' '
        normalized.append((ch,{k:v for k,v in style.items() if v}))
    if normalized and normalized[-1][0]==' ':normalized.pop()
    spans=[]
    for i,(ch,style) in enumerate(normalized):
        if not style:continue
        if spans and spans[-1]['end']==i and {k:v for k,v in spans[-1].items() if k not in ('id','start','end')}==style:
            spans[-1]['end']=i+1
        else:spans.append({'id':f'f{len(spans)}','start':i,'end':i+1,**style})
    # Do not emphasize incidental spaces adjacent to a styled phrase.
    text=''.join(ch for ch,_ in normalized)
    for s in spans:
        while s['start']<s['end'] and text[s['start']].isspace():s['start']+=1
        while s['end']>s['start'] and text[s['end']-1].isspace():s['end']-=1
    return text,[{**s,'text':text[s['start']:s['end']]} for s in spans if s['start']<s['end']]


def html_styles(u):
    from lxml import html
    text,spans=normalized_styles(styled_characters(html.fromstring(u['html']),u['tokens']))
    if text!=u['en']:raise ValueError('Original markup differs from saved text: '+u['id'])
    return spans


def validate_styles(u,lang):
    text=u.get(lang) or ''
    sources={s['id']:s for s in u.get('styles',{}).get('en',[])}
    end=0
    for s in sorted(u.get('styles',{}).get(lang,[]),key=lambda s:s['start']):
        if not (isinstance(s['start'],int) and isinstance(s['end'],int) and end<=s['start']<s['end']<=len(text)):
            raise ValueError('Overlapping or invalid emphasis range: '+u['id'])
        end=s['end']
        if s.get('text')!=text[s['start']:s['end']]:raise ValueError('Stale emphasis after text edit: '+u['id'])
        for key in ('bold','italic','underline'):
            if key in s and not isinstance(s[key],bool):raise ValueError('Invalid emphasis style: '+u['id'])
        if 'color' in s and not re.fullmatch(r'#[0-9a-f]{3}(?:[0-9a-f]{3})?|[a-z]+|rgba?\([\d.,%\s]+\)',s['color']):raise ValueError('Invalid emphasis color: '+u['id'])
        for m in TOKEN.finditer(text):
            if m.start()<s['start']<m.end() or m.start()<s['end']<m.end():raise ValueError('Emphasis splits protected token: '+u['id'])
        if lang=='zh' and not (u.get('native_html') and s.get('source') is None):
            original=sources.get(s.get('source'))
            if original is None or any(s.get(k)!=original.get(k) for k in ('bold','italic','underline','color')):
                raise ValueError('Translation emphasis must match source: '+u['id'])


def pdf_styles(content,out):
    """Poppler text styling is used only for exact text/bbox matches."""
    from lxml import etree
    if not shutil.which('pdftohtml'):return {},['PDF emphasis needs pdftohtml or manual PDF inspection.']
    data=subprocess.check_output(['pdftohtml','-q','-xml','-i','-stdout','-zoom','1','-noroundcoord','-fontfullname',content['source']['pdf']])
    (out/'source').mkdir(exist_ok=True)
    (out/'source/formatting.xml').write_bytes(data)
    root=etree.fromstring(data,etree.XMLParser(resolve_entities=False,no_network=True))
    pages={int(p.get('number')):p for p in root.findall('page')}
    fonts={n.get('id'):n for n in root.findall('.//fontspec')}
    result={};warnings=['PDF-drawn underlines are not exposed by Poppler XML; verify against PDF before claiming underline coverage.']
    for b,u in all_units(content):
        if u.get('html') or b['type'] not in ('paragraph','caption','heading'):continue
        chars=[]
        for prov in b.get('source',{}).get('pdf',[]):
            page=pages.get(prov['page_no'])
            if page is None:continue
            box=prov['bbox'];height=float(page.get('height'))
            if box.get('coord_origin')=='BOTTOMLEFT':top,bottom=height-box['t'],height-box['b']
            else:top,bottom=box['t'],box['b']
            for n in page.findall('text'):
                x=float(n.get('left'))+float(n.get('width'))/2;y=float(n.get('top'))+float(n.get('height'))/2
                if not (box['l']-2<=x<=box['r']+2 and top-2<=y<=bottom+2):continue
                font=fonts[n.get('font')];family=font.get('family','').lower();style={}
                if re.search(r'bold|[-]medi$',family):style['bold']=True
                if re.search(r'italic|ital|oblique',family):style['italic']=True
                color=font.get('color','#000000').lower()
                # Link colors are navigation, not prose emphasis.
                if color not in ('#000000','#ffffff') and not n.findall('.//a'):style['color']=color
                chars+=styled_characters(n,inherited=style)+[(' ',{})]
        source=[(ch,s) for ch,s in chars if not ch.isspace()]
        target=[(i,ch) for i,ch in enumerate(u['en']) if not ch.isspace()]
        if ''.join(ch for ch,_ in source).lstrip('•')!=''.join(ch for _,ch in target):
            warnings.append('PDF emphasis text alignment needs review: '+u['id']);continue
        if source and source[0][0]=='•':source=source[1:]
        mapped=[(ch,{}) for ch in u['en']]
        for (i,ch),(_,s) in zip(target,source):mapped[i]=(ch,s)
        for i in range(1,len(mapped)-1):
            if mapped[i][0].isspace() and mapped[i-1][1]==mapped[i+1][1]:mapped[i]=(mapped[i][0],mapped[i-1][1])
        _,result[u['id']]=normalized_styles(mapped)
    return result,warnings


def format_content(args):
    out=Path(args.reader);content=read(out/'content.json')
    units={u['id']:u for _,u in all_units(content)}
    warnings=[];pdf={}
    if any(not u.get('html') and b.get('source',{}).get('pdf') for b,u in all_units(content)):pdf,warnings=pdf_styles(content,out)
    for _,u in all_units(content):
        if u.get('preserve'):continue
        if 'en' in u.get('styles',{}):continue
        try:spans=html_styles(u) if u.get('html') else pdf.get(u['id'],[])
        except ValueError as e:warnings.append(str(e));continue
        if spans:u.setdefault('styles',{})['en']=spans
    if args.patch:
        for uid,entries in read(args.patch).items():
            if uid not in units or not isinstance(entries,list):raise ValueError('Invalid emphasis patch unit: '+uid)
            u=units[uid];text=u.get('zh')
            if text is None:raise ValueError('Translate before aligning emphasis: '+uid)
            sources={s['id']:s for s in u.get('styles',{}).get('en',[])};spans=[]
            for entry in entries:
                if not isinstance(entry,dict) or entry.get('source') not in sources or not isinstance(entry.get('text'),str):raise ValueError('Invalid emphasis selection: '+uid)
                original=sources[entry['source']];phrase=entry['text'];starts=[m.start() for m in re.finditer(re.escape(phrase),text)]
                occurrence=entry.get('occurrence')
                if not phrase or not starts or (len(starts)>1 and occurrence is None):raise ValueError('Ambiguous translation emphasis: '+uid+' '+phrase)
                if occurrence is not None and (not isinstance(occurrence,int) or not 1<=occurrence<=len(starts)):raise ValueError('Invalid emphasis occurrence: '+uid)
                start=starts[(occurrence or 1)-1]
                spans.append({'source':original['id'],'start':start,'end':start+len(phrase),'text':phrase,**{k:v for k,v in original.items() if k not in ('id','start','end','text')}})
            if u.get('styles',{}).get('zh') not in (None,spans) and uid not in args.replace:raise ValueError('Existing emphasis protected: '+uid)
            u.setdefault('styles',{})['zh']=spans
            validate_styles(u,'zh')
    content['format_review']=list(dict.fromkeys(content.get('format_review',[])+warnings))
    save(out/'content.json',content)
    print('Saved emphasis; original and translated text unchanged.')


def crop_pdf(pdf, page_no, bbox, output, scale=3):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(pdf))
    page = doc[page_no - 1]
    w, h = page.get_size()
    l, t, r, b = bbox
    if not (0 <= l < r <= w and 0 <= t < b <= h):
        raise ValueError(f"Invalid TOPLEFT bbox {bbox} for {w}x{h}")
    image = page.render(scale=scale).to_pil()
    image.crop((round(l*scale), round(t*scale), round(r*scale), round(b*scale))).save(output)
    page.close()
    doc.close()


def provenance(item, raw):
    ps = copy.deepcopy(item.get("prov", []))
    for p in ps:
        box = p.get("bbox")
        if box and box.get("coord_origin") == "BOTTOMLEFT":
            h = raw["pages"][str(p["page_no"])]["size"]["height"]
            box.update(t=h-box["t"], b=h-box["b"], coord_origin="TOPLEFT")
    return {"pdf": ps}


def extract(args):
    remote=bool(re.match(r"^https?://", args.input) or re.fullmatch(r"(?:arxiv:)?\d{4}\.\d{4,5}(?:v\d+)?", args.input))
    if remote:
        if not args.output:
            raise ValueError("Remote input needs --output; no existing paper is moved.")
        out = Path(args.output).expanduser().resolve()
        ident = args.input.removeprefix("arxiv:")
        aid=re.search(r'(\d{4}\.\d{4,5}(?:v\d+)?)',ident)
        url = f'https://arxiv.org/pdf/{aid[1]}' if aid and ('arxiv' in ident or not ident.startswith('http')) else ident
        pdf = download(url, out / "source/original.pdf")
        if not pdf.read_bytes().startswith(b'%PDF-'):raise ValueError('Remote source is not a PDF. Supply the local attachment or a direct PDF URL.')
    else:
        pdf = resolve(args.input)
        out = Path(args.output).expanduser().resolve() if args.output else pdf.parent / (pdf.stem + "-reader")
    if (out / "content.json").exists() or html_layer().active(out):
        old = read(out / "content.json")
        if old["source"]["sha256"] != digest(pdf):
            raise ValueError("PDF changed. Use a new --output to preserve existing translations.")
        print(f"Reuse existing content in {out}; no extraction or translation overwritten.")
        return out,False
    (out / "source").mkdir(parents=True, exist_ok=True)
    (out / "assets").mkdir(exist_ok=True)
    write_reader_gitignore(out)
    rawpath = out / "source/docling.json"
    if args.docling_json:
        shutil.copy2(args.docling_json, rawpath)
    else:
        command = [args.docling, "convert", str(pdf), "--to", "json", "--image-export-mode", "referenced",
                   "--output", str(out / "source/docling")]
        if not args.ocr:
            command += ["--no-ocr"]
        artifacts=args.artifacts_path or (str(Path.home()/'.cache/docling/models') if (Path.home()/'.cache/docling/models').is_dir() else None)
        if artifacts:
            command += ["--artifacts-path", artifacts]
        subprocess.run(command, check=True)
        shutil.copy2(out / "source/docling" / (pdf.stem + ".json"), rawpath)
    raw = read(rawpath)
    base=Path(args.docling_json).resolve().parent if args.docling_json else out/'source/docling'
    localize_docling_assets(raw,base,out)
    save(rawpath,raw)
    blocks, section, preserve_section = [], "front", False
    def get(ref):
        _, group, index = ref.split("/")
        return raw[group][int(index)]
    def walk(item):
        nonlocal section,preserve_section
        label = item.get("label", "")
        if label == "page_header" or item.get("content_layer") == "furniture":
            return
        ref = item.get("self_ref", "")
        uid = "pdf-" + ref.strip("#/").replace("/", "-")
        source = provenance(item, raw)
        if label in ("picture", "formula", "table"):
            b = {"id": uid, "type": {"picture":"image", "formula":"equation", "table":"table"}[label],
                 "section": section, "source": source, "units": []}
            for p in source["pdf"]:
                box = p["bbox"]
                path = out / "assets" / f"{uid}-p{p['page_no']}.png"
                crop_pdf(pdf, p["page_no"], [box[k] for k in ("l","t","r","b")], path)
                b.setdefault("images", []).append(str(path.relative_to(out)))
            if label == "formula":
                b["flags"] = ["Original PDF equation crop; no reconstructed mathematics."]
            blocks.append(b)
            for cap in item.get("captions", []):
                walk(get(cap["$ref"]))
            return
        if "text" in item:
            en = item["text"]
            if label == "section_header":
                section = uid
                preserve_section=en.strip().lower() in ('references','bibliography','literature cited')
            blocks.append({"id":uid, "type":"heading" if label in ("title","section_header") else ("reference" if preserve_section else ("caption" if label=="caption" else "paragraph")),
                           "section":section, "level":1 if label=="title" else min(4,item.get("level",2)), "source":source,
                           "units":[unit(uid,en,preserve=preserve_section and label!='section_header')], "list":label=="list_item"})
        for child in item.get("children", []):
            walk(get(child["$ref"]))
    for child in raw["body"]["children"]:
        walk(get(child["$ref"]))
    title=next((u['en'] for b in blocks if b['type']=='heading' and b.get('level')==1 for u in b['units']),pdf.stem)
    with (SKILL/'references/glossary.tsv').open(encoding='utf-8') as f:
        glossary=list(csv.DictReader(f,delimiter='\t'))
    content={"schema_version":1,"title":title,"source":{"pdf":str(pdf),"sha256":digest(pdf),"authority":"local PDF",
             "extraction":"Docling standard","docling_schema_version":raw.get("version")},"blocks":blocks,"glossary":glossary,"corrections":[],"manual_flags":["Review PDF extraction coverage and reading order before translation."]}
    save(out/"content.json",content)
    print(f"Extracted {len(blocks)} PDF blocks to {out}")
    return out,True


def safe_html(element):
    from lxml import etree
    e = copy.deepcopy(element)
    if isinstance(e.tag,str) and e.tag.lower() in ('script','iframe','object','embed','link','style'):
        return ''
    e.tail = None
    for n in list(e.iter()):
        if not isinstance(n.tag, str):
            if n.getparent() is not None:
                n.getparent().remove(n)
            continue
        if n.tag.lower() in ("script","iframe","object","embed","link","style"):
            if n.getparent() is not None:
                n.getparent().remove(n)
            continue
        text_style=emphasis_css(emphasis(n))
        if n.tag in ('a','cite') or n.xpath('ancestor::a|ancestor::cite'):
            text_style=emphasis_css({k:v for k,v in emphasis(n).items() if k!='color'})
        for a in list(n.attrib):
            if a.lower().startswith("on") or a in ("style","id","title"):
                del n.attrib[a]
        if text_style:n.set('style',text_style)
        for a in ("href","src"):
            if a in n.attrib:
                val=n.get(a).strip()
                if val.lower().startswith(("javascript:","vbscript:")):
                    del n.attrib[a]
        if n.tag == "math":
            n.set("xmlns","http://www.w3.org/1998/Math/MathML")
        classes=n.get('class','').split()
        if 'ltx_mathvariant_bold' in classes:n.set('mathvariant','bold')
        if 'ltx_font_mathcaligraphic' in classes:n.set('mathvariant','script')
    return etree.tostring(e,encoding="unicode",method="html")


def page_match(text, pages):
    query=textnorm(text)
    if not query or not pages:
        return {"pdf_pages":[],"match_score":0}
    grams=[query[i:i+20] for i in range(0,len(query)-19,20)] or [query]
    scores=[sum(g in pg for g in grams)/len(grams) for pg in pages]
    best=max(range(len(scores)), key=scores.__getitem__)
    matches=[best+1]
    score=scores[best]
    if best+1<len(pages):
        joined=pages[best]+pages[best+1]
        both=sum(g in joined for g in grams)/len(grams)
        if both>score:
            score=both
            matches.append(best+2)
    return {"pdf_pages":matches,"match_score":round(score,3)}


def align_html(args):
    from lxml import html
    out=Path(args.reader).resolve()
    old=read(out/"content.json")
    if any(u.get("zh") is not None for b in old['blocks'] for u in b.get('units',[])):
        raise ValueError("HTML reconciliation must precede translation; existing translations are protected.")
    pdf=Path(old["source"]["pdf"])
    pdftext=subprocess.check_output(["pdftotext","-layout",str(pdf),"-"],stderr=subprocess.DEVNULL).decode("utf-8",errors="replace")
    version=re.search(r"arXiv:\s*(\d{4}\.\d{4,5}v\d+)",pdftext)
    remote=re.search(r"(\d{4}\.\d{4,5}v\d+)",args.url)
    if version:
        if not remote or remote[1]!=version[1]:
            raise ValueError("Exact PDF arXiv version must occur in HTML URL.")
    elif not args.version_evidence:
        raise ValueError("Publisher/unversioned HTML needs --version-evidence with concrete manual comparison.")
    path=Path(args.html_file) if args.html_file else download(args.url,out/"source/source.html")
    root=html.fromstring(path.read_bytes())
    articles=root.xpath("//article")
    article=articles[0] if articles else root
    for img in article.xpath('.//img'):
        src=img.get('src','')
        name=hashlib.sha256(src.encode()).hexdigest()[:12]+Path(urllib.parse.urlparse(src).path).suffix
        if src.startswith('data:'):
            name += '.png' if not Path(name).suffix else ''
            (out/'assets'/name).write_bytes(base64.b64decode(src.split(',',1)[1]))
        else:download(urllib.parse.urljoin(args.url,src),out/'assets'/name)
        img.set('src','assets/'+name)
        img.set('data-source-url',urllib.parse.urljoin(args.url,src))
    raw=read(out/'source/docling.json')
    pdf_tables={}
    for item in raw.get('tables',[]):
        for cap in item.get('captions',[]):
            group,index=cap['$ref'].split('/')[-2:]
            label=re.search(r'\bTable\s+([A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*)\b',raw[group][int(index)]['text'],re.I)
            if label:
                pdf_tables.setdefault(textnorm(label[0]),[]).append(item)
    pages=[textnorm(' '.join(t['text'] for t in raw['texts'] if any(p['page_no']==int(number) for p in t.get('prov',[])))) for number in sorted(raw['pages'],key=int)]
    biblabels={e.get("id"):" ".join(e.xpath('.//*[contains(@class,"ltx_tag_bibitem")]/text()')) for e in article.xpath('.//*[@id]') if 'ltx_bibitem' in e.get('class','')}
    corrections=[]
    for cite in article.xpath('.//cite'):
        for a in cite.xpath('.//a'):
            label=biblabels.get(a.get('href','').lstrip('#'))
            if label:
                a.text=label
                for child in list(a): a.remove(child)
        cite.text=None
        for a in cite: a.tail='; ' if a is not cite[-1] else None
    if biblabels: corrections.append("Restored author-year citation labels from bibliography; verify against PDF.")
    blocks=[]
    section='front'
    footnotes=[]
    def make_unit(e, uid, preserve=False):
        tokens={}
        def inline(n):
            if n.tag in ('math','a','cite','img') or (n is not e and 'ltx_note' in n.get('class','').split()):
                key=str(len(tokens))
                if 'ltx_note' in n.get('class','').split():
                    fid=n.get('id',f'footnote-{len(footnotes)}')
                    tokens[key]=f'<a class="footnote-ref" href="#{fid}"><sup>1</sup></a>'
                    note=n.xpath('.//*[contains(@class,"ltx_note_content")]')
                    if note:
                        nn=copy.deepcopy(note[0])
                        for x in nn.xpath('.//sup|.//*[contains(@class,"ltx_tag_note")]'): x.drop_tree()
                        footnotes.append((fid,nn,uid,section))
                else:
                    tokens[key]=safe_html(n)
                return '{{'+key+'}}'
            return (n.text or '')+''.join(inline(c)+(c.tail or '') for c in n)
        en=re.sub(r'\s+',' ',inline(e)).strip()
        u=unit(uid,en,original=safe_html(e),tokens=tokens,preserve=preserve)
        spans=html_styles(u) if not preserve else []
        if spans:u['styles']={'en':spans}
        return u
    def add(kind, e, uid=None, preserve=False, **extra):
        uid=uid or e.get('id') or f'html-{len(blocks)}'
        u=make_unit(e,uid,preserve)
        src=page_match(re.sub(TOKEN,'',u['en']),pages)
        src['html_anchor']=e.get('id') or uid
        blocks.append({'id':uid,'type':kind,'section':section,'source':src,'units':[u],**extra})
    def walk(e):
        nonlocal section
        cls=e.get('class','')
        if not isinstance(e.tag,str): return
        if e.tag in ('script','style'): return
        if e.tag in ('section',) or 'ltx_bibliography' in cls:
            section=e.get('id',section)
        if e.tag.startswith('h') and e.tag[1:].isdigit():
            uid=e.getparent().get('id') or ('title' if e.tag=='h1' else f'heading-{len(blocks)}')
            add('heading',e,uid,level=2 if e.tag=='h6' else int(e.tag[1:]))
            return
        if 'ltx_authors' in cls.split() or 'ltx_role_affiliation' in cls.split() or 'ltx_role_corresponding' in cls.split():
            add('metadata',e,preserve=True)
            return
        if 'ltx_role_runninghead' in cls: return
        if 'ltx_bibitem' in cls:
            add('reference',e,preserve=True)
            return
        if e.tag=='figure':
            blocks.append({'id':e.get('id'),'type':'anchor','section':section,'source':{'html_anchor':e.get('id')},'units':[]})
        if e.tag=='img':
            src=e.get('src','')
            uid=e.get('id') or f'image-{len(blocks)}'
            blocks.append({'id':uid,'type':'image','section':section,'images':[src],
                           'source':{'html_anchor':uid,'url':e.get('data-source-url')},'units':[]})
            return
        if e.tag=='table':
            if 'ltx_equation' in cls:
                blocks.append({'id':e.get('id') or f'equation-{len(blocks)}','type':'equation','section':section,
                               'source':{'html_anchor':e.get('id')},'units':[],'math_html':safe_html(e)})
            else:
                if not textnorm(' '.join(e.itertext())) and not e.xpath('.//img'):
                    return
                uid=e.get('id') or f'table-{len(blocks)}'
                owners=e.xpath('ancestor::figure[1]')
                caption=' '.join(owners[0].xpath('.//figcaption//text()')) if owners else ''
                label=re.search(r'\bTable\s+([A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*)\b',caption,re.I)
                matches=pdf_tables.get(textnorm(label[0]),[]) if label else []
                b={'id':uid,'type':'table','section':section,'source':{'html_anchor':uid},'units':[]}
                if len(matches)==1:
                    item=matches[0]
                    b['source'].update(provenance(item,raw),table_label=label[0])
                    for p in b['source']['pdf']:
                        box=p['bbox']
                        name='pdf-'+item['self_ref'].strip('#/').replace('/','-')+f"-p{p['page_no']}.png"
                        path=out/'assets'/name
                        crop_pdf(pdf,p['page_no'],[box[k] for k in ('l','t','r','b')],path)
                        b.setdefault('images',[]).append(str(path.relative_to(out)))
                else:
                    b['flags']=['Attach a verified original PDF table crop; caption label missing or ambiguous.']
                blocks.append(b)
            return
        if e.tag in ('p','figcaption'):
            uid=e.get('id') or (e.getparent().get('id','caption')+f'-caption-{len(blocks)}')
            add('caption' if e.tag=='figcaption' else 'paragraph',e,uid,
                list=bool(e.xpath('ancestor::li')))
            return
        if 'ltx_classification' in cls:
            add('paragraph',e,'keywords')
            return
        for child in e:
            walk(child)
            if child.tail and len(child.tail.strip())>40 and re.search('[A-Za-z]',child.tail):
                tail=html.Element('p')
                tail.text=child.tail
                add('paragraph',tail,(e.get('id') or f'container-{len(blocks)}')+'-tail')
    walk(article)
    for fid,n,owner,origin_section in footnotes:
        section=origin_section
        add('footnote',n,fid)
        note=blocks.pop()
        index=next(i for i,b in enumerate(blocks) if any(u['id']==owner for u in b.get('units',[])))
        blocks.insert(index+1,note)
    shutil.copy2(path,out/'source/source.html') if path.resolve()!=(out/'source/source.html').resolve() else None
    if not (out/'source/pdf-content.json').exists(): save(out/'source/pdf-content.json',old)
    content=copy.deepcopy(old)
    content['blocks']=blocks
    content['title']=blocks[0]['units'][0]['en']
    content['source'].update(html_url=args.url,html_sha256=digest(out/'source/source.html'),html_role='same-version auxiliary; PDF authority',version_evidence=args.version_evidence or version[1])
    content['corrections']=corrections
    content['manual_flags']=['Reconcile ALL PDF text/figures/tables against auxiliary HTML before acceptance.','Inline/display MathML must be visually checked against PDF.']
    save(out/'content.json',content)
    print(f'Aligned {len(blocks)} blocks; PDF recovery/manual review still required.')


def translate(args):
    out=Path(args.reader)
    if html_layer().active(out):html_layer().require_accepted(out)
    content=read(out/'content.json')
    patch=read(args.patch)
    units={u['id']:u for _,u in all_units(content)}
    if not isinstance(patch,dict): raise ValueError('Patch must be an ID-to-string object.')
    for uid,zh in patch.items():
        if uid not in units or not isinstance(zh,str) or not zh.strip(): raise ValueError(f'Invalid patch unit {uid}')
        u=units[uid]
        if u.get('preserve'): raise ValueError(f'{uid} is preserved original text.')
        if Counter(TOKEN.findall(zh))!=Counter(TOKEN.findall(u['en'])): raise ValueError(f'Protected tokens changed in {uid}')
        if u['zh'] is not None and u['zh']!=zh and uid not in args.replace: raise ValueError(f'Existing translation protected: {uid}')
    for uid,zh in patch.items():
        u=units[uid]
        if u['zh']!=zh:u.get('styles',{}).pop('zh',None)
        u['zh']=zh
    save(out/'content.json',content)
    print(f'Saved {len(patch)} translations.')


def expanded(u, lang):
    text=u.get('zh') if lang=='zh' and not u.get('preserve') else u['en']
    if text is None: text='〔待翻譯〕 '+u['en']
    spans=u.get('styles',{}).get(lang,[]) if u.get(lang) is not None else []
    validate_styles(u,lang)
    parts=[];end=0
    for s in sorted(spans,key=lambda s:s['start']):
        parts.append(stdhtml.escape(text[end:s['start']]))
        parts.append('<span class="source-emphasis" style="'+stdhtml.escape(emphasis_css(s),quote=True)+'">'+stdhtml.escape(text[s['start']:s['end']])+'</span>')
        end=s['end']
    parts.append(stdhtml.escape(text[end:]));escaped=''.join(parts)
    def inline_token(match):
        original=u['tokens'][match[1]]
        if original.startswith('<math') and 'display="inline"' in original:
            return '<span class="inline-math">'+original+'</span>'
        return original
    return TOKEN.sub(inline_token,escaped)


def write_reader_gitignore(out, used_assets=()):
    start='# BEGIN paper-reader intermediates'
    end='# END paper-reader intermediates'
    rules=['/source/*','!/source/original.pdf','!/source/reader.json','!/source/accepted-source.json']
    for image in sorted((out/'assets').glob('pdf-*.png')):
        relative=image.relative_to(out).as_posix()
        if relative not in used_assets:rules.append('/'+relative)
    generated=start+'\n'+'\n'.join(rules)+'\n'+end+'\n'
    path=out/'.gitignore'
    existing=path.read_text() if path.exists() else ''
    if start in existing and end in existing:
        updated=re.sub(re.escape(start)+r'.*?'+re.escape(end)+r'\n?',lambda _:generated,existing,flags=re.S)
    else:
        updated=existing+('\n' if existing and not existing.endswith('\n') else '')+generated
    path.write_text(updated,encoding='utf-8')


def render(args):
    out=Path(args.reader)
    if html_layer().active(out):return html_layer().render(args,globals())
    c=read(out/'content.json')
    check(args)
    body=[];toc=[];in_list=False
    for b in c['blocks']:
        is_list=bool(b.get('list'))
        if is_list and not in_list:body.append('<ul class="paper-list">')
        if in_list and not is_list:body.append('</ul>')
        in_list=is_list
        bid=stdhtml.escape(b['id'],quote=True)
        kind=b['type']
        content=''
        for src in b.get('images',[]):
            content+=f'<a class="image-link" href="{stdhtml.escape(src,quote=True)}"><img loading="lazy" src="{stdhtml.escape(src,quote=True)}" alt="Original PDF/HTML visual"></a>'
        if b.get('math_html'): content+=f'<div class="math-scroll">{b["math_html"]}</div>'
        if kind=='table':
            if not b.get('images'):
                content+='<small class="review-note">〔待校對：缺少原始 PDF 表格裁切〕</small>'
        else:
            for u in b.get('units',[]):
                zh=expanded(u,'zh');en=expanded(u,'en')
                if kind=='heading':
                    level=min(4,max(1,b.get('level',2)))
                    if level==1:
                        content+=f'<h1 class="paper-title-en" lang="en">{en}</h1><p class="paper-title-zh" lang="zh-Hant">{zh}</p>'
                    else:
                        english=re.sub(r'^(?:Appendix\s+[A-Z]|\d+(?:\.\d+)*|[A-Z](?:\.\d+)*)\s+','',en)
                        label=f'<span class="heading-zh" lang="zh-Hant">{zh}</span> <span class="heading-en" lang="en">({english})</span>'
                        toc.append(f'<li class="depth-{level}"><a href="#{bid}">{label}</a></li>')
                        content+=f'<h{level}>{label}</h{level}>'
                elif u.get('preserve'):
                    content+=f'<div class="preserved">{u.get("html") or en}</div>'
                else:
                    content+=f'<div class="lang-zh" lang="zh-Hant">{zh}</div><div class="lang-en" lang="en">{en}</div>'
        if b.get('flags'):content+='<small class="review-note">'+stdhtml.escape('；'.join(b['flags']))+'</small>'
        tag='li' if is_list else 'div'
        title_class=' paper-title' if kind=='heading' and b.get('level',2)==1 else ''
        keywords_class=' keywords' if b['id']=='keywords' else ''
        body.append(f'<{tag} id="{bid}" class="block {kind}{title_class}{keywords_class}{" list-item" if is_list else ""}{" thumbnail-row" if b.get("layout")=="thumbnail-row" else ""}">{content}</{tag}>')
    if in_list:body.append('</ul>')
    template=(SKILL/'assets/template.html').read_text()
    qa=read(out/'quality-report.json')
    replacements={'DEFAULT_MODE':'zh','TITLE':stdhtml.escape(c['title']),'BODY':'\n'.join(body),'TOC':'\n'.join(toc),
                  'PDF_URL':urllib.parse.quote(Path(os.path.relpath(Path(c['source']['pdf']).resolve(),out.resolve())).as_posix(),safe='/'),
                  'SOURCE_URL':stdhtml.escape(c['source'].get('html_url',''),quote=True),
                  'QA_NOTICE':f"譯文 {qa['counts']['translated']}/{qa['counts']['translatable']}；自動錯誤 {len(qa['errors'])}。來源、公式與語意校對範圍請見品質報告。"}
    for k,v in replacements.items():template=template.replace('@@'+k+'@@',v)
    (out/'index.html').write_text(template,encoding='utf-8')
    from lxml import html
    document=html.fromstring(template)
    used_assets={urllib.parse.unquote(urllib.parse.urlparse(url).path).removeprefix('./') for url in document.xpath('//@src|//@href')}
    write_reader_gitignore(out,used_assets)
    for name in ['reader.css','reader.js']:shutil.copy2(SKILL/'assets'/name,out/'assets'/name)
    print(out/'index.html')


def check(args):
    from lxml import html
    out=Path(args.reader)
    c=read(out/'content.json')
    report=out/'quality-report.json'
    previous=report if report.exists() else out/'qa.json'
    old=read(previous) if previous.exists() else {}
    errors=[];warnings=list(c.get('manual_flags',[]))+c.get('format_review',[]); ids=[];units=[];refs=[];resources=[]; inventory=Counter()
    for b in c['blocks']:
        ids.append(b['id']);inventory[b['type']]+=1
        resources+=b.get('images',[])
        warnings+=b.get('flags',[])
        if b['type']=='table' and not b.get('images'):
            errors.append({'code':'table_crop_missing','id':b['id']})
        fragments=[b.get('math_html','')]
        for _,u in all_units({'blocks':[b]}):
            units.append(u)
            if not u.get('preserve') and u.get('zh') is None: errors.append({'code':'untranslated','id':u['id']})
            if u.get('zh') is not None and Counter(TOKEN.findall(u['en']))!=Counter(TOKEN.findall(u['zh'])):errors.append({'code':'tokens','id':u['id']})
            for lang in ('en','zh'):
                try:validate_styles(u,lang)
                except (ValueError,KeyError,TypeError) as e:errors.append({'code':'emphasis_range','id':u['id'],'language':lang,'detail':str(e)})
            if not u.get('preserve'):
                source_ids={s['id'] for s in u.get('styles',{}).get('en',[])}
                aligned={s.get('source') for s in u.get('styles',{}).get('zh',[])}
                if source_ids-aligned:warnings.append('Translation emphasis needs alignment: '+u['id'])
                if u.get('native_html') and any(s.get('source') is None for s in u.get('styles',{}).get('zh',[])):
                    warnings.append('Chinese emphasis needs source correspondence: '+u['id'])
            fragments += [u.get('html') or '',*u.get('tokens',{}).values()]
        for s in fragments:
            if not s:continue
            e=html.fromstring('<div>'+s+'</div>')
            refs += e.xpath('.//a/@href')
            resources += e.xpath('.//img/@src')
    for value,count in Counter(ids).items():
        if count>1:errors.append({'code':'duplicate_block_id','id':value})
    for value,count in Counter(u['id'] for u in units).items():
        if count>1:errors.append({'code':'duplicate_unit_id','id':value})
    expected=c.get('expected',{})
    if c.get('_html'):
        # Native HTML can link to section/list containers as well as prose blocks.
        document=html_layer().parse(out,'content.en.html')
        ids.extend(value for value in document.xpath('.//*[@id]/@id') if value not in ids)
    for label in ('Figure','Table'):
        found=[int(m[1]) for b,u in all_units(c) if b['type']=='caption' and (m:=re.match(label+r'\s+(\d+)',u['en']))]
        if label in expected and sorted(found)!=expected[label]:errors.append({'code':'caption_inventory','kind':label,'found':found})
    if 'references' in expected and inventory['reference']!=expected['references']:errors.append({'code':'reference_inventory'})
    if 'equations' in expected and inventory['equation']!=expected['equations']:errors.append({'code':'equation_inventory'})
    for ref in sorted(set(refs)):
        if ref.startswith('#') and ref[1:] not in ids:errors.append({'code':'broken_reference','target':ref})
    for resource in sorted(set(resources)):
        p=Path(resource)
        if p.is_absolute() or '..' in p.parts or '://' in resource:errors.append({'code':'nonlocal_asset','path':resource})
        elif not (out/p).is_file():errors.append({'code':'missing_asset','path':resource})
    for text,count in Counter(u['en'] for b,u in all_units(c) if b['type']=='paragraph' and len(u['en'])>100).items():
        if count>1:warnings.append('Repeated source paragraph: '+text[:90])
    if digest(c['source']['pdf'])!=c['source']['sha256']:errors.append({'code':'authority_changed'})
    translatable=[u for u in units if not u.get('preserve')]
    qa={**old,'status':'needs_manual_review' if not errors else 'incomplete','counts':{'blocks':len(ids),'units':len(units),'translatable':len(translatable),'translated':sum(u['zh'] is not None for u in translatable),'inventory':dict(inventory)},'errors':errors,'manual_checklist':list(dict.fromkeys(warnings)),
        'validation_boundary':'Mechanical checks cover extracted units only; not a semantic/PDF-completeness guarantee.',
        'source_review':old.get('source_review',{}),'manual_reviews':old.get('manual_reviews',[])}
    if c.get('_html'):
        qa['source_errors']=[e for e in errors if e['code']!='untranslated']
        qa['source_status']='incomplete' if qa['source_errors'] else 'needs_manual_review'
        if (out/'source/accepted-source.json').exists():
            try:
                html_layer().require_accepted(out)
                if not qa['source_errors']:qa['source_status']='accepted'
            except ValueError as e:
                qa['source_status']='changed_after_acceptance'
                qa['manual_checklist'].append(str(e))
        qa['translation_status']='complete' if qa['counts']['translated']==len(translatable) else 'pending'
    save(report,qa)
    print(f"QA: {len(errors)} errors; {qa['counts']['translated']}/{len(translatable)} translated")
    return qa


def main():
    p=argparse.ArgumentParser(description=__doc__)
    subs=p.add_subparsers(dest='command',required=True)
    r=subs.add_parser('resolve');r.add_argument('input')
    e=subs.add_parser('extract');e.add_argument('input');e.add_argument('--output');e.add_argument('--docling',default='docling');e.add_argument('--docling-json');e.add_argument('--artifacts-path');e.add_argument('--ocr',action='store_true')
    a=subs.add_parser('align-html');a.add_argument('reader');a.add_argument('--html-file');a.add_argument('--url',required=True);a.add_argument('--version-evidence')
    n=subs.add_parser('pending');n.add_argument('reader');n.add_argument('--section')
    n.add_argument('--limit',type=int,default=10,help='Maximum units per batch (default: 10)')
    n.add_argument('--max-chars',type=int,default=8000,help='JSON character budget; one oversized unit is emitted intact (default: 8000)')
    n.add_argument('--id',action='append',help='Inspect a specific unit, including translated units; repeat for multiple IDs')
    detail=n.add_mutually_exclusive_group()
    detail.add_argument('--compact',dest='compact',action='store_true',default=True,help='Readable token previews and necessary emphasis only (default)')
    detail.add_argument('--full',dest='compact',action='store_false',help='Include original token markup and source metadata; still bounded')
    t=subs.add_parser('translate');t.add_argument('reader');t.add_argument('patch');t.add_argument('--replace',action='append',default=[])
    f=subs.add_parser('format');f.add_argument('reader');f.add_argument('--patch');f.add_argument('--replace',action='append',default=[])
    for name in ['render','check']:
        s=subs.add_parser(name);s.add_argument('reader')
    for name in ['migrate','sync-source','accept-source']:
        s=subs.add_parser(name);s.add_argument('reader')
        if name=='accept-source':s.add_argument('--review-note',required=True)
    cr=subs.add_parser('crop');cr.add_argument('reader');cr.add_argument('--page',type=int,required=True);cr.add_argument('--bbox',type=float,nargs=4,required=True);cr.add_argument('--name',required=True)
    args=p.parse_args()
    if args.command=='pending' and (args.limit<1 or args.max_chars<1):p.error('--limit and --max-chars must be positive')
    if args.command not in ('resolve','pending','translate') and any(importlib.util.find_spec(n) is None for n in ('lxml','pypdfium2')):
        cli=shutil.which(args.docling if hasattr(args,'docling') else 'docling')
        candidate=Path(cli).resolve().parent/'python' if cli else None
        if candidate and candidate.is_file() and str(candidate)!=sys.executable:
            available=subprocess.run([str(candidate),'-c','import lxml, pypdfium2'],capture_output=True).returncode==0
            if available:os.execv(str(candidate),[str(candidate),str(Path(__file__).resolve()),*sys.argv[1:]])
        print('paper-reader: need lxml and pypdfium2; reuse the installed Docling Python environment.',file=sys.stderr)
        return 1
    try:
        if args.command=='resolve':print(resolve(args.input))
        elif args.command=='extract':
            out,new=extract(args)
            if not html_layer().active(out):
                if new:format_content(argparse.Namespace(reader=str(out),patch=None,replace=[]))
                html_layer().migrate(out,globals())
                if new:(out/'content.json').unlink()
        elif args.command=='align-html':
            out=Path(args.reader)
            if html_layer().active(out):
                html_layer().align(args,globals())
            else:
                align_html(args);html_layer().migrate(out,globals())
        elif args.command=='migrate':html_layer().migrate(args.reader,globals())
        elif args.command=='sync-source':html_layer().sync_source(args.reader,globals())
        elif args.command=='accept-source':html_layer().accept(args,globals())
        elif args.command=='translate':translate(args)
        elif args.command=='format':format_content(args)
        elif args.command=='render':render(args)
        elif args.command=='check':return 2 if check(args)['errors'] else 0
        elif args.command=='pending':pending(args)
        elif args.command=='crop':
            if Path(args.name).name!=args.name or not args.name.endswith('.png'):raise ValueError('Crop name must be a local PNG basename.')
            out=Path(args.reader);c=read(out/'content.json');crop_pdf(c['source']['pdf'],args.page,args.bbox,out/'assets'/args.name)
    except (ValueError,OSError,subprocess.CalledProcessError) as e:
        print(f'paper-reader: {e}',file=sys.stderr);return 1
    return 0


if __name__=='__main__':sys.exit(main())
