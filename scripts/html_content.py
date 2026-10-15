"""Canonical bilingual HTML. The sidecar stores provenance, not duplicate prose."""
from __future__ import annotations
import copy
import json
import os
import re
import tempfile
from pathlib import Path
from lxml import etree, html

FILES = ('content.en.html', 'content.zh.html')
KINDS = {'heading', 'paragraph', 'caption', 'metadata', 'reference', 'footnote', 'image', 'table', 'equation', 'anchor'}
TAGS = {'article','section','h1','h2','h3','h4','p','ul','ol','li','figure','figcaption','div','span','strong','em','u','sup','sub','a','img','br','cite','code','pre'}
MATH_TAGS = {'math','semantics','annotation','annotation-xml','mrow','mi','mn','mo','mtext','mspace','ms','msub','msup','msubsup','munder','mover','munderover','mfrac','msqrt','mroot','mfenced','mtable','mtr','mtd','menclose','mpadded','mphantom','mstyle','mmultiscripts','mprescripts','none','maligngroup','malignmark'}
MATH_ATTRS = {'xmlns','display','alttext','intent','encoding','mathvariant','mathcolor','mathbackground','mathsize','dir','stretchy','fence','separator','accent','accentunder','lspace','rspace','minsize','maxsize','largeop','movablelimits','form','linethickness','numalign','denomalign','bevelled','notation','width','height','depth','voffset','align','rowalign','columnalign','rowspacing','columnspacing','rowlines','columnlines','columnspan','rowspan','frame','framespacing','equalrows','equalcolumns','displaystyle','scriptlevel','scriptsizemultiplier','scriptminsize','open','close','separators','subscriptshift','superscriptshift','style'}
CLASSES = {'metadata','caption','reference','footnote','anchor','math-block','inline-math','thumbnail-row','source-emphasis','footnote-ref','bibliography-number','preserved'}
MATH_CLASSES = {'ltx_equation','ltx_eqn_table','ltx_eqn_row','ltx_eqn_cell','ltx_eqn_center_padleft','ltx_eqn_center_padright','ltx_eqn_center','ltx_eqn_eqno','ltx_align_baseline','ltx_align_center','ltx_align_right','ltx_Math','ltx_math_unparsed','ltx_mathvariant_bold','ltx_font_mathcaligraphic'}
TOKEN = re.compile(r'\{\{(\d+)\}\}')
ID = re.compile(r'[A-Za-z0-9_.:-]+\Z')
STRUCTURAL = {'ul','ol','section','figure'}


def active(out):
    return any((Path(out)/name).exists() for name in FILES)


def serialize(node):
    return etree.tostring(node, encoding='unicode', method='html', with_tail=False)


def comparable(node):
    n=copy.deepcopy(node)
    for child in n.iter():
        attrs=sorted(child.attrib.items());child.attrib.clear();child.attrib.update(attrs)
    return serialize(n)


def source_fragment(value):
    try:return html.fragment_fromstring(value)
    except etree.ParserError:return html.fragment_fromstring(value,create_parent='span')


def atomic(path, text):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as f:
        f.write(text);temporary=f.name
    os.replace(temporary,path)


def safe_url(value, resource=False):
    from urllib.parse import urlsplit, unquote
    if any(ord(c)<32 for c in value) or '\\' in value:return False
    parts=urlsplit(value)
    if parts.scheme or parts.netloc:
        return not resource and parts.scheme in ('https','http','mailto') and not value.startswith('//')
    path=Path(unquote(parts.path))
    return not path.is_absolute() and '..' not in path.parts


def style_of(node, engine):
    s=engine['emphasis'](node)
    for key in ('bold','italic','underline'):
        if node.get('data-'+key) in ('true','false'):s[key]=node.get('data-'+key)=='true'
    if node.get('data-source-color'):s['color']=node.get('data-source-color').lower()
    return s


def clean(element, engine):
    """Strip source layout; keep text, effective emphasis, links and original math."""
    e=copy.deepcopy(element);e.tail=None
    for n in list(e.iter()):
        if not isinstance(n.tag,str):
            if n.getparent() is not None:n.getparent().remove(n)
            continue
        tag=n.tag.lower();in_math=tag in MATH_TAGS or bool(n.xpath('ancestor::math'))
        math_layout=tag in ('table','tbody','tr','td') and bool(e.xpath('.//math'))
        if tag in ('script','style','iframe','object','embed','link'):
            if n.getparent() is not None:n.getparent().remove(n)
            else:raise ValueError('Active content is not supported')
            continue
        style=style_of(n,engine)
        if tag in ('a','cite') or n.xpath('ancestor::a|ancestor::cite'):style.pop('color',None)
        classes=[c for c in n.get('class','').split() if c in CLASSES or (in_math or math_layout) and c in MATH_CLASSES]
        original=dict(n.attrib);n.attrib.clear()
        for key,value in original.items():
            if key in ('href','src') and safe_url(value,key=='src'):n.set(key,value)
            elif key in ('alt','start','value','data-token','data-emphasis','data-source'):n.set(key,value)
            elif in_math and key in MATH_ATTRS and key!='style':n.set(key,value)
            elif math_layout and key in ('colspan','rowspan'):n.set(key,value)
        if classes:n.set('class',' '.join(classes))
        if 'ltx_tag_bibitem' in original.get('class','').split():n.set('class','bibliography-number')
        if style:
            if in_math or math_layout:n.set('style',engine['emphasis_css'](style))
            else:
                for key in ('bold','italic','underline'):
                    if key in style:n.set('data-'+key,'true' if style[key] else 'false')
                if style.get('color'):n.set('data-source-color',style['color'])
        if tag in ('b','i'):n.tag={'b':'strong','i':'em'}[tag]
        elif tag not in TAGS and not in_math and not math_layout:n.tag='span'
    return e


def unit_data(node, engine):
    chars=[];tokens={};explicit=[]
    def walk(n,inherited):
        style={**inherited,**style_of(n,engine)};start=len(chars)
        protected=n is not node and (n.get('data-token') is not None or n.tag in ('math','a','cite','img','sup','sub','code','br'))
        if protected:
            key=n.get('data-token',str(len(tokens)))
            if key in tokens:raise ValueError('Duplicate protected token: '+key)
            fragment=n
            if n.get('data-token') is not None:
                if len(n)!=1 or (n.text or '').strip():raise ValueError('Protected token needs exactly one element')
                fragment=n[0]
            tokens[key]=comparable(fragment)
            chars.extend((ch,style) for ch in '{{'+key+'}}')
        else:
            chars.extend((ch,style) for ch in n.text or '')
            for child in n:
                walk(child,style);chars.extend((ch,style) for ch in child.tail or '')
        if n.get('data-emphasis') and len(chars)>start:
            props={k:v for _,s in chars[start:] for k,v in s.items() if v}
            explicit.append({'id':n.get('data-emphasis'),'start':start,'end':len(chars),'source':n.get('data-source'),**props})
    walk(node,{})
    text=''.join(ch for ch,_ in chars);spans=[]
    if explicit:
        for s in sorted(explicit,key=lambda x:x['start']):
            s['text']=text[s['start']:s['end']]
            if s['source'] is None:s.pop('source')
            spans.append(s)
    else:
        for i,(ch,style) in enumerate(chars):
            props={k:v for k,v in style.items() if v}
            if not props:continue
            if spans and spans[-1]['end']==i and {k:v for k,v in spans[-1].items() if k not in ('id','start','end')}==props:spans[-1]['end']=i+1
            else:spans.append({'id':f'f{len(spans)}','start':i,'end':i+1,**props})
        for s in spans:s['text']=text[s['start']:s['end']]
    return text,tokens,spans


def parse(out,name):
    path=Path(out)/name
    if not path.is_file():raise ValueError('Both content.en.html and content.zh.html are required')
    roots=html.fragments_fromstring(path.read_text(encoding='utf-8'),parser=html.HTMLParser(encoding='utf-8',no_network=True))
    if len(roots)!=1 or not isinstance(roots[0],etree._Element) or roots[0].tag!='article':raise ValueError(name+' must contain exactly one article')
    root=roots[0]
    if root.get('data-content-version')!='1':raise ValueError('Unsupported HTML content version')
    ids=[]
    for n in root.iter():
        if not isinstance(n.tag,str):raise ValueError('HTML comments are not content')
        in_math=n.tag in MATH_TAGS or bool(n.xpath('ancestor::math'))
        layout=n.tag in ('table','tbody','tr','td') and (n.get('data-original-math')=='true' or bool(n.xpath('ancestor::*[@data-original-math="true"]')))
        if n.tag not in TAGS and n.tag not in MATH_TAGS and not layout:raise ValueError('Unsupported HTML element: '+n.tag)
        if n.tag in ('h1','h2','h3','h4','p','li','figcaption','figure') and not n.get('id') and not in_math and not layout and not n.xpath('ancestor::*[@data-unit]'):
            raise ValueError('Content block needs a stable ID: '+n.tag)
        allowed={'id','lang','class','href','src','alt','start','value','data-content-version','data-kind','data-section','data-unit','data-preserve','data-translation','data-token','data-emphasis','data-source','data-source-color','data-bold','data-italic','data-underline','data-original-math'}
        for k,v in n.attrib.items():
            if k.lower().startswith('on') or k not in allowed and not (in_math and k in MATH_ATTRS) and not (layout and k in ('style','colspan','rowspan')):raise ValueError('Unsupported HTML attribute: '+k)
            if k=='style' and (not (in_math or layout) or any(key.strip().lower() not in ('font-weight','font-style','text-decoration-line','color') for key in re.findall(r'([^;:]+):',v)) or re.search(r'url\s*\(|expression',v,re.I)):raise ValueError('Unsupported source layout style')
            if k in ('href','src') and not safe_url(v,k=='src'):raise ValueError('Unsafe or nonlocal URL: '+v)
            if k=='data-source-color' and not re.fullmatch(r'#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?|[a-zA-Z]+|rgba?\([\d.,%\s]+\)',v):raise ValueError('Invalid emphasis color')
        if any(c not in CLASSES and not ((in_math or layout) and c in MATH_CLASSES) for c in n.get('class','').split()):raise ValueError('Unsupported source class')
        if n.get('id'):
            if not ID.fullmatch(n.get('id')):raise ValueError('Invalid ID: '+n.get('id'))
            ids.append(n.get('id'))
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate HTML ID')
    if root.get('lang')!=('en' if name==FILES[0] else 'zh-Hant'):raise ValueError('Wrong content language')
    return root


def nodes(root):
    result=[]
    for n in root.iterdescendants():
        if n.get('data-kind'):
            if n.get('data-kind') not in KINDS:raise ValueError('Unsupported content kind')
            result.append(n)
        elif n.get('id') and (n.tag in ('h1','h2','h3','h4','p','li','figcaption','figure') or n.tag=='math' and n.get('display')=='block' or 'math-block' in n.get('class','').split()) and not n.xpath('ancestor::*[@data-unit]'):result.append(n)
    return result


def kind_of(n):
    if n.get('data-kind'):return n.get('data-kind')
    if n.tag.startswith('h') and n.tag[1:].isdigit():return 'heading'
    if n.tag=='figure':return 'image'
    if n.tag=='figcaption':return 'caption'
    if n.tag=='math' or 'math-block' in n.get('class','').split():return 'equation'
    return next((c for c in ('metadata','reference','footnote','caption') if c in n.get('class','').split()),'paragraph')


def skeleton(root):
    n=copy.deepcopy(root)
    for e in list(n.iter()):
        e.tail=None
        e.attrib.pop('lang',None);e.attrib.pop('data-translation',None)
        if e.tag=='img':e.attrib.pop('alt',None)
        if e.get('data-unit') or e.get('id') and kind_of(e) in ('heading','paragraph','caption','metadata','reference','footnote') and e.tag in ('h1','h2','h3','h4','p','li','figcaption'):
            e.text=None
            for child in list(e):
                if child.tag not in STRUCTURAL:e.remove(child)
        elif not (e.text or '').strip():e.text=None
    return comparable(n)


def prose_part(node):
    result=copy.deepcopy(node)
    for child in list(result):
        if child.tag in STRUCTURAL:result.remove(child)
    return result


def load(out,engine):
    out=Path(out);meta=json.loads((out/'source/reader.json').read_text(encoding='utf-8'))
    en=parse(out,FILES[0]);zh=parse(out,FILES[1]);ens=nodes(en);zhs=nodes(zh)
    if skeleton(en)!=skeleton(zh):raise ValueError('Bilingual HTML structure differs')
    if [(n.get('id'),kind_of(n)) for n in ens]!=[(n.get('id'),kind_of(n)) for n in zhs]:raise ValueError('Bilingual block IDs/order/types differ')
    c=copy.deepcopy(meta['document']);c['blocks']=[]
    relative=c['source'].get('pdf_relative')
    if relative and (out/relative).is_file():c['source']['pdf']=str((out/relative).resolve())
    for a,b in zip(ens,zhs):
        uid=a.get('id');kind=kind_of(a)
        if not uid:raise ValueError('Content block needs an ID')
        block={'id':uid,'type':kind,'section':a.get('data-section') or next(iter(a.xpath('ancestor::section[1]/@id')),'front'),**copy.deepcopy(meta.get('blocks',{}).get(uid,{})),'units':[]}
        if a.tag.startswith('h') and a.tag[1:].isdigit():block['level']=int(a.tag[1:])
        if a.tag=='li' or a.xpath('ancestor::li'):block['list']=True
        if kind in ('image','table','equation','anchor'):
            aa=copy.deepcopy(a);bb=copy.deepcopy(b)
            for n in (aa,bb):
                for cap in n.xpath('.//figcaption'):cap.getparent().remove(cap)
                for im in n.xpath('.//img'):im.attrib.pop('alt',None)
            if comparable(aa)!=comparable(bb):raise ValueError('Shared figure/table/equation structure changed: '+uid)
            images=a.xpath('.//img/@src')
            if images:block['images']=images
            maths=a.xpath('./*[@data-original-math="true"]')
            if not maths and kind=='equation' and not images:maths=[a] if a.tag=='math' else a.xpath('./math')
            if maths:block['math_html']=''.join(serialize(n) for n in maths)
        else:
            aus=[a] if a.get('data-unit') or not a.xpath('.//*[@data-unit]') else a.xpath('.//*[@data-unit]')
            bus=[b] if b.get('data-unit') or not b.xpath('.//*[@data-unit]') else b.xpath('.//*[@data-unit]')
            if [n.get('id') or uid for n in aus]!=[n.get('id') or uid for n in bus]:raise ValueError('Bilingual unit IDs differ')
            for x,y in zip(aus,bus):
                en_text,tokens,en_styles=unit_data(prose_part(x),engine);zh_text,ztokens,zh_styles=unit_data(prose_part(y),engine)
                if tokens!=ztokens:raise ValueError('Protected math/link content changed: '+(x.get('id') or uid))
                preserved=x.get('data-preserve')=='true';pending=y.get('data-translation')=='pending'
                if preserved and comparable(x)!=comparable(y):raise ValueError('Preserved original changed: '+uid)
                styles={'en':en_styles}
                if not pending and not preserved and zh_styles:styles['zh']=[{k:v for k,v in s.items() if k!='id'} for s in zh_styles]
                u={'id':x.get('id') or uid,'en':en_text,'zh':None if pending or preserved else zh_text,'tokens':tokens,'preserve':preserved,'html':serialize(x),'styles':styles,'native_html':True}
                if not preserved:
                    for lang in ('en','zh'):engine['validate_styles'](u,lang)
                block['units'].append(u)
        c['blocks'].append(block)
    titles=en.xpath('.//h1')
    if titles:
        title=copy.deepcopy(titles[0])
        for annotation in title.xpath('.//annotation|.//annotation-xml'):annotation.getparent().remove(annotation)
        c['title']=' '.join(''.join(title.itertext()).split())
    c['_html']=True
    return c


def fragment(u,lang,engine):
    import html as escaping
    text=u.get('zh') if lang=='zh' and not u.get('preserve') else u['en']
    if text is None:text=u['en']
    spans=u.get('styles',{}).get(lang,[]) if lang=='en' or u.get('zh') is not None else u.get('styles',{}).get('en',[])
    pieces=[];end=0
    def escaped(value):return escaping.escape(value,quote=False)
    for i,s in enumerate(sorted(spans,key=lambda s:s['start'])):
        body=escaped(text[s['start']:s['end']])
        for key,tag in [('underline','u'),('italic','em'),('bold','strong')]:
            if s.get(key):body=f'<{tag}>{body}</{tag}>'
        attrs={'data-emphasis':s.get('id',f'f{i}')}
        if lang=='zh' and u.get('zh') is not None:attrs['data-source']=s.get('source',s.get('id',f'f{i}'))
        if s.get('color'):attrs['data-source-color']=s['color']
        attr=' '.join(k+'="'+escaping.escape(v,quote=True)+'"' for k,v in attrs.items())
        pieces.extend([escaped(text[end:s['start']]),f'<span {attr}>{body}</span>']);end=s['end']
    pieces.append(escaped(text[end:]));value=''.join(pieces)
    def token(m):
        normalized=clean(source_fragment(u['tokens'][m[1]]),engine)
        return '<span data-token="'+m[1]+'">'+serialize(normalized)+'</span>'
    return TOKEN.sub(token,value)


def set_inner(node,value):
    node.text=None
    for child in list(node):node.remove(child)
    for child in html.fragments_fromstring(value):
        if isinstance(child,str):
            if len(node):node[-1].tail=(node[-1].tail or '')+child
            else:node.text=(node.text or '')+child
        else:node.append(child)


def set_prose(node,value):
    nested=[child for child in node if child.tag in STRUCTURAL]
    set_inner(node,value)
    for child in nested:node.append(child)


def image_dimensions(path):
    try:
        from PIL import Image
        with Image.open(path) as im:return im.size
    except (ImportError,OSError,ValueError):
        # Formats without an intrinsic-size reader still load eagerly in the browser.
        return None


def documents(c,engine):
    import html as escaping
    roots=[]
    for lang in ('en','zh'):
        root=html.Element('article',lang='en' if lang=='en' else 'zh-Hant',attrib={'data-content-version':'1'});listing=None
        for b in c['blocks']:
            kind=b['type'];is_list=b.get('list') and kind not in ('image','table','equation','anchor')
            if is_list and listing is None:listing=etree.SubElement(root,'ul')
            if not is_list:listing=None
            tag='li' if is_list else ('h'+str(min(4,max(1,b.get('level',2)))) if kind=='heading' else ('figure' if kind in ('image','table') else ('div' if kind in ('equation','anchor') else 'p')))
            n=etree.SubElement(listing if listing is not None else root,tag,id=b['id'],attrib={'data-kind':kind,'data-section':b.get('section','front')})
            classes=[]
            if kind in ('metadata','caption','reference','footnote','anchor'):classes.append(kind)
            if kind=='equation':classes.append('math-block')
            if b.get('layout')=='thumbnail-row':classes.append('thumbnail-row')
            if classes:n.set('class',' '.join(classes))
            for src in b.get('images',[]):etree.SubElement(n,'img',src=src,alt='Original PDF/HTML visual')
            if b.get('math_html'):
                original=clean(source_fragment(b['math_html']),engine);original.set('data-original-math','true');n.append(original)
            for u in ([] if kind=='table' else b.get('units',[])):
                target=n if len(b.get('units',[]))==1 and u['id']==b['id'] else etree.SubElement(n,'span',id=u['id'])
                target.set('data-unit','true')
                if u.get('preserve'):
                    target.set('data-preserve','true')
                    original=clean(source_fragment(u.get('html') or '<span>'+engine['expanded'](u,'en')+'</span>'),engine)
                    for key,value in original.attrib.items():
                        if key.startswith('data-') and key!='data-unit':target.set(key,value)
                    value=escaping.escape(original.text or '',quote=False)+''.join(serialize(x)+escaping.escape(x.tail or '',quote=False) for x in original)
                    set_inner(target,value)
                else:
                    if lang=='zh' and u.get('zh') is None:target.set('data-translation','pending')
                    set_inner(target,fragment(u,lang,engine))
        root.text='\n'
        for child in root:
            child.tail='\n'
            if child.tag in ('ul','ol'):
                child.text='\n'
                for item in child:item.tail='\n'
        roots.append(root)
    return roots


def write(out,c,engine):
    out=Path(out);changed=[True,True]
    if active(out) and c.get('_html'):
        changed=[False,False]
        roots=[parse(out,name) for name in FILES];current=load(out,engine)
        old={u['id']:u for b,u in engine['all_units'](current)}
        for language_index,(root,lang) in enumerate(zip(roots,('en','zh'))):
            indexed={n.get('id'):n for n in root.iter() if n.get('id')}
            for b,u in engine['all_units'](c):
                if u.get('preserve'):continue
                if u['id'] not in indexed:raise ValueError('Unit structure changed; edit source HTML explicitly')
                previous=old[u['id']]
                if u.get(lang)==previous.get(lang) and u.get('styles',{}).get(lang,[])==previous.get('styles',{}).get(lang,[]):continue
                changed[language_index]=True
                target=indexed[u['id']];set_prose(target,fragment(u,lang,engine))
                if lang=='zh':
                    if u.get('zh') is None:target.set('data-translation','pending')
                    else:target.attrib.pop('data-translation',None)
    else:roots=documents(c,engine)
    meta={'version':1,'document':{k:v for k,v in c.items() if k not in ('blocks','_html')},'blocks':{b['id']:{k:v for k,v in b.items() if k not in ('id','type','section','units','images','math_html','table_html','archived_units','archived_images')} for b in c['blocks']}}
    meta['document']['source']=copy.deepcopy(meta['document']['source'])
    meta['document']['source']['pdf_relative']=os.path.relpath(Path(c['source']['pdf']).resolve(),out.resolve())
    # Validate all candidate changes before writing either language.
    with tempfile.TemporaryDirectory() as tmp:
        stage=Path(tmp);(stage/'source').mkdir()
        for name,root,is_changed in zip(FILES,roots,changed):
            value=serialize(root)+'\n' if is_changed else (out/name).read_text(encoding='utf-8')
            (stage/name).write_text(value,encoding='utf-8')
        (stage/'source/reader.json').write_text(json.dumps(meta,ensure_ascii=False),encoding='utf-8')
        load(stage,engine)
        for name in FILES:
            value=(stage/name).read_text(encoding='utf-8')
            if not (out/name).exists() or (out/name).read_text(encoding='utf-8')!=value:atomic(out/name,value)
        atomic(out/'source/reader.json',json.dumps(meta,ensure_ascii=False,indent=2)+'\n')


def migrate(out,engine):
    out=Path(out)
    if active(out):load(out,engine);print('Reuse canonical HTML; no migration overwritten.');return
    legacy=out/'content.json';c=json.loads(legacy.read_text(encoding='utf-8'))
    archive=out/'source/legacy-content.json'
    if not archive.exists():atomic(archive,legacy.read_text(encoding='utf-8'))
    write(out,c,engine)
    print('Saved content.en.html and content.zh.html; legacy JSON preserved.')


def sync_source(out,engine):
    out=Path(out)
    if (out/'source/accepted-source.json').exists():raise ValueError('Source scaffolding must precede acceptance')
    if (out/FILES[1]).exists():
        target=parse(out,FILES[1])
        if any(kind_of(n) in ('heading','paragraph','caption','metadata','reference','footnote') and n.get('data-preserve')!='true' and n.get('data-translation')!='pending' for n in nodes(target)):
            raise ValueError('Existing translations protected; source scaffolding cannot replace them')
    root=parse(out,FILES[0]);root.set('lang','zh-Hant')
    for n in nodes(root):
        if kind_of(n) in ('heading','paragraph','caption','metadata','reference','footnote'):
            units=[n] if n.get('data-unit') or not n.xpath('.//*[@data-unit]') else n.xpath('.//*[@data-unit]')
            for unit in units:
                if unit.get('data-preserve')!='true':unit.set('data-translation','pending')
    # Keep the English bytes intact. Validate the fresh scaffold before publishing.
    with tempfile.TemporaryDirectory() as tmp:
        stage=Path(tmp);(stage/'source').mkdir()
        (stage/FILES[0]).write_bytes((out/FILES[0]).read_bytes())
        (stage/FILES[1]).write_text(serialize(root)+'\n',encoding='utf-8')
        (stage/'source/reader.json').write_bytes((out/'source/reader.json').read_bytes())
        load(stage,engine)
    atomic(out/FILES[1],serialize(root)+'\n')
    print('Chinese scaffold synchronized; English unchanged, all prose pending.')


def require_accepted(out):
    import hashlib
    out=Path(out);path=out/'source/accepted-source.json'
    if not path.exists():raise ValueError('Verify/render English, then run accept-source before translation')
    approved=json.loads(path.read_text(encoding='utf-8'))
    current=hashlib.sha256((out/FILES[0]).read_bytes()).hexdigest()
    if current!=approved['english_sha256']:raise ValueError('English content changed after acceptance; review and accept it again')
    metadata=json.loads((out/'source/reader.json').read_text(encoding='utf-8'))
    source=metadata['document']['source'];pdf=Path(source['pdf'])
    if source.get('pdf_relative') and (out/source['pdf_relative']).is_file():pdf=out/source['pdf_relative']
    if hashlib.sha256(pdf.read_bytes()).hexdigest()!=approved['pdf_sha256']:raise ValueError('Authority PDF changed after acceptance')
    for name,fingerprint in approved['assets'].items():
        if not (out/name).is_file() or hashlib.sha256((out/name).read_bytes()).hexdigest()!=fingerprint:raise ValueError('Accepted asset changed: '+name)


def accept(args,engine):
    import hashlib
    out=Path(args.reader);c=load(out,engine);qa=engine['check'](args)
    structural=[e for e in qa['errors'] if e['code']!='untranslated']
    if structural:raise ValueError('Fix source errors before acceptance')
    assets=set(parse(out,FILES[0]).xpath('.//img/@src'))
    approved={'english_sha256':engine['digest'](out/FILES[0]),'pdf_sha256':c['source']['sha256'],'assets':{name:engine['digest'](out/name) for name in sorted(assets)},'review_note':args.review_note}
    atomic(out/'source/accepted-source.json',json.dumps(approved,ensure_ascii=False,indent=2)+'\n')
    qa['source_review']={**qa.get('source_review',{}),'html_content_acceptance':approved}
    qa['source_status']='accepted'
    engine['save'](out/'quality-report.json',qa)
    print('English source accepted; prose and assets protected during translation.')


def align(args,engine):
    import argparse
    import shutil
    out=Path(args.reader);c=load(out,engine)
    if (out/'source/accepted-source.json').exists():raise ValueError('HTML reconciliation must precede English source acceptance')
    if any(u.get('zh') is not None and not u.get('preserve') for b,u in engine['all_units'](c)):raise ValueError('HTML reconciliation must precede translation')
    with tempfile.TemporaryDirectory() as tmp:
        stage=Path(tmp)/'reader'
        shutil.copytree(out,stage,ignore=shutil.ignore_patterns(*FILES,'index.html'))
        c.pop('_html',None);engine['save'](stage/'content.json',c)
        normalized=copy.copy(args);normalized.reader=str(stage)
        engine['align_html'](normalized)
        new=engine['read'](stage/'content.json')
        engine['format_content'](argparse.Namespace(reader=str(stage),patch=None,replace=[]))
        new=engine['read'](stage/'content.json')
        # Validate normalized content before copying source/assets into the destination.
        write(stage,new,engine)
        for directory in ('source','assets'):
            shutil.copytree(stage/directory,out/directory,dirs_exist_ok=True)
        metadata=json.loads((out/'source/reader.json').read_text(encoding='utf-8'))
        metadata['document']['source']['pdf_relative']=os.path.relpath(Path(new['source']['pdf']).resolve(),out.resolve())
        atomic(out/'source/reader.json',json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
        for name in FILES:atomic(out/name,(stage/name).read_text(encoding='utf-8'))


def render(args,engine):
    import html as escaping
    import urllib.parse
    import shutil
    out=Path(args.reader);c=load(out,engine);qa=engine['check'](args)
    structural=[e for e in qa['errors'] if e['code']!='untranslated']
    if structural:raise ValueError('Fix content errors before rendering: '+', '.join(sorted({e['code'] for e in structural})))
    en=parse(out,FILES[0]);zh=parse(out,FILES[1]);zmap={n.get('id'):n for n in zh.iter() if n.get('id')};root=copy.deepcopy(en);toc=[]
    for n in list(root.iter()):
        if n.get('data-unit') or n.get('id') in zmap and kind_of(n) in ('heading','paragraph','caption','metadata','reference','footnote') and n.tag in ('h1','h2','h3','h4','p','li','figcaption') and not n.xpath('.//*[@data-unit]'):
            if n.tag=='h1':n.set('lang','en');continue
            if n.get('data-preserve')=='true':continue
            z=zmap[n.get('id')];english=prose_part(n);chinese=prose_part(z);nested=[child for child in n if child.tag in STRUCTURAL];n.text=None
            for child in list(n):n.remove(child)
            for original,lang in ((chinese,'zh'),(english,'en')):
                span=etree.SubElement(n,'span',attrib={'class':'lang-'+lang,'lang':'zh-Hant' if lang=='zh' else 'en'});span.text=original.text
                for child in original:span.append(copy.deepcopy(child))
            for child in nested:n.append(child)
            if n.tag in ('h2','h3','h4'):
                if ''.join(chinese.itertext())!=''.join(english.itertext()):
                    english_label=re.sub(r'^(?:Appendix\s+[A-Z]|\d+(?:\.\d+)*|[A-Z](?:\.\d+)*)\s+','',''.join(english.itertext()))
                    suffix=etree.SubElement(n[0],'span',attrib={'class':'heading-en','lang':'en'});suffix.text='（'+english_label+'）'
                item=html.Element('li',attrib={'class':'depth-'+n.tag[1:]});link=etree.SubElement(item,'a',href='#'+n.get('id'))
                for original,lang in ((chinese,'zh'),(english,'en')):
                    label=etree.SubElement(link,'span',attrib={'class':'lang-'+lang});label.text=''.join(original.itertext())
                    if lang=='zh':
                        for suffix in n[0].xpath('./span[@class="heading-en"]'):label.append(copy.deepcopy(suffix))
                toc.append(serialize(item))
    for n in list(root.iter()):
        styles=[]
        if n.get('data-source-color'):styles.append('color:'+n.get('data-source-color'))
        for key,values in (('bold',('font-weight:400','font-weight:700')),('italic',('font-style:normal','font-style:italic')),('underline',('text-decoration-line:none','text-decoration-line:underline'))):
            if n.get('data-'+key) in ('true','false'):styles.append(values[n.get('data-'+key)=='true'])
        if styles:n.set('style',';'.join(styles))
        if n.get('data-kind'):n.set('class',' '.join(dict.fromkeys(['block',n.get('data-kind'),*n.get('class','').split()])))
        if n.tag=='h1':n.set('class',n.get('class','')+' paper-title')
        if n.tag=='img':
            size=image_dimensions(out/n.get('src'))
            n.set('loading','lazy' if size else 'eager')
            if size:n.set('width',str(size[0]));n.set('height',str(size[1]))
        if n.tag=='img' and (n.xpath('ancestor::figure') or any('equation' in p.get('class','').split() for p in n.iterancestors())) and not n.xpath('ancestor::a'):
            parent=n.getparent();link=html.Element('a',href=n.get('src'),attrib={'class':'image-link'});link.tail=n.tail;n.tail=None;parent.replace(n,link);link.append(n)
        if n.tag=='math' and n.get('display')=='inline' and n.getparent().get('class')!='inline-math':
            parent=n.getparent();wrap=html.Element('span',attrib={'class':'inline-math'});wrap.tail=n.tail;n.tail=None;parent.replace(n,wrap);wrap.append(n)
        for key in list(n.attrib):
            if key.startswith('data-'):del n.attrib[key]
    template=(engine['SKILL']/'assets/template.html').read_text(encoding='utf-8')
    default='zh' if qa['counts']['translated']==qa['counts']['translatable'] else 'en'
    source=c['source'];body=''.join(serialize(n) for n in root)
    replacements={'TITLE':escaping.escape(c['title']),'BODY':body,'TOC':'\n'.join(toc),'PDF_URL':urllib.parse.quote(Path(os.path.relpath(Path(source['pdf']).resolve(),out.resolve())).as_posix(),safe='/'),'SOURCE_URL':escaping.escape(source.get('html_url',''),quote=True),'QA_NOTICE':f"譯文 {qa['counts']['translated']}/{qa['counts']['translatable']}。來源與語意校對範圍請見品質報告。",'DEFAULT_MODE':default}
    for k,v in replacements.items():template=template.replace('@@'+k+'@@',v)
    template=template.replace('href="content.json"','href="content.en.html"').replace('段落資料','英文內容')
    if not source.get('html_url'):template=template.replace('<a href="">輔助 HTML 來源</a>','')
    (out/'assets').mkdir(exist_ok=True);atomic(out/'index.html',template)
    for name in ('reader.css','reader.js'):shutil.copy2(engine['SKILL']/'assets'/name,out/'assets'/name)
    engine['write_reader_gitignore'](out,html.fromstring(template).xpath('//@src|//@href'))
    print(out/'index.html')
