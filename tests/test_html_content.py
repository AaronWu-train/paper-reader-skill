import argparse
import copy
import importlib.util
import json
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
from lxml import html

sys.dont_write_bytecode=True
spec=importlib.util.spec_from_file_location('reader',Path(__file__).resolve().parents[1]/'scripts/reader.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)


class HTMLContentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.out=Path(self.tmp.name)/'reader';(self.out/'assets').mkdir(parents=True)
        self.pdf=self.out.parent/'original.pdf';self.pdf.write_bytes(b'authority')
        (self.out/'assets/table.png').write_bytes(b'original table')
        u=r.unit('p1','May improve {{0}}; see {{1}}.',tokens={'0':'<math display="inline"><mi>x</mi></math>','1':'<a href="#T1">Table 1</a>'})
        u['styles']={'en':[{'id':'f0','start':0,'end':3,'text':'May','bold':True}]}
        self.c={'schema_version':1,'title':'Test','source':{'pdf':str(self.pdf),'sha256':r.digest(self.pdf)},'blocks':[
            {'id':'title','type':'heading','level':1,'section':'front','units':[r.unit('title','Test')]},
            {'id':'s1','type':'heading','level':2,'section':'s1','units':[r.unit('s1','1 Introduction')]},
            {'id':'p1','type':'paragraph','section':'s1','units':[u]},
            {'id':'T1','type':'table','section':'s1','images':['assets/table.png'],'units':[]},
            {'id':'caption','type':'caption','section':'s1','units':[r.unit('caption','Table 1: Results.')]},
            {'id':'bib1','type':'reference','section':'refs','units':[r.unit('bib1','A & B < C.',original='<li><em>A &amp; B &lt; C.</em></li>',preserve=True)]}]}
        r.save(self.out/'content.json',self.c);self.legacy=r.digest(self.out/'content.json')
        r.html_layer().migrate(self.out,r.__dict__)
        self.args=argparse.Namespace(reader=str(self.out),review_note='Fixture source verified')

    def tearDown(self):self.tmp.cleanup()
    def accept(self):r.html_layer().accept(self.args,r.__dict__)
    def translate(self,patch_data,replace=[]):
        path=self.out.parent/'patch.json';r.save(path,patch_data)
        r.translate(argparse.Namespace(reader=str(self.out),patch=str(path),replace=replace))
    def hashes(self):return tuple(r.digest(self.out/f) for f in r.html_layer().FILES)
    def complete(self):
        self.accept();self.translate({'title':'測試','s1':'1 緒論','p1':'可能改善 {{0}}；請見 {{1}}。','caption':'表 1：結果。'})
        p=self.out.parent/'emphasis.json';r.save(p,{'p1':[{'source':'f0','text':'可能'}]})
        r.format_content(argparse.Namespace(reader=str(self.out),patch=str(p),replace=[]))

    def test_html_is_canonical_and_legacy_is_unchanged(self):
        self.assertEqual(r.digest(self.out/'content.json'),self.legacy)
        self.assertEqual(r.digest(self.out/'source/legacy-content.json'),self.legacy)
        c=r.read(self.out/'content.json')
        self.assertEqual(c['blocks'][2]['units'][0]['en'],self.c['blocks'][2]['units'][0]['en'])
        self.assertEqual(c['blocks'][2]['units'][0]['styles']['en'],self.c['blocks'][2]['units'][0]['styles']['en'])
        metadata=json.loads((self.out/'source/reader.json').read_text())
        self.assertNotIn('units',json.dumps(metadata['blocks']))
        before=self.hashes();r.html_layer().migrate(self.out,r.__dict__);self.assertEqual(before,self.hashes())

    def test_translation_requires_review_and_never_changes_english(self):
        before=self.hashes()
        with self.assertRaisesRegex(ValueError,'accept-source'):self.translate({'caption':'表說'})
        self.assertEqual(before,self.hashes());self.accept()
        self.translate({'caption':'表說'})
        self.assertEqual(before[0],self.hashes()[0]);self.assertEqual(self.legacy,r.digest(self.out/'content.json'))
        self.assertEqual(r.read(self.out/'content.json')['blocks'][4]['units'][0]['zh'],'表說')

    def test_invalid_patch_is_transactional_and_manual_translation_protected(self):
        self.accept();before=self.hashes()
        with self.assertRaises(ValueError):self.translate({'caption':'表說','p1':'遺失公式'})
        self.assertEqual(before,self.hashes())
        self.translate({'caption':'人工校訂'});before=self.hashes()
        with self.assertRaises(ValueError):self.translate({'caption':'覆寫'})
        self.assertEqual(before,self.hashes());self.translate({'caption':'明確更新'},replace=['caption'])

    def test_english_or_resource_edits_invalidate_acceptance(self):
        self.accept();path=self.out/'content.en.html';original=path.read_text()
        path.write_text(original.replace('1 Introduction','1 Modified'))
        with self.assertRaisesRegex(ValueError,'changed after acceptance'):self.translate({'caption':'表說'})
        path.write_text(original);(self.out/'assets/table.png').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'asset changed'):self.translate({'caption':'表說'})

    def test_protected_formula_or_reference_edits_refused(self):
        path=self.out/'content.zh.html';value=path.read_text()
        for changed in (value.replace('<mi>x</mi>','<mi>y</mi>'),value.replace('href="#T1"','href="#p1"')):
            path.write_text(changed)
            with self.assertRaisesRegex(ValueError,'Protected math/link'):r.read(self.out/'content.json')
        path.write_text(value)

    def test_bilingual_heading_level_and_list_structure_checked(self):
        path=self.out/'content.zh.html';value=path.read_text()
        path.write_text(value.replace('<h2 ','<h3 ').replace('</h2>','</h3>'))
        with self.assertRaisesRegex(ValueError,'structure differs'):r.read(self.out/'content.json')

    def test_active_html_and_source_layout_refused(self):
        path=self.out/'content.en.html';value=path.read_text()
        for bad in (value.replace('</article>','<script>alert(1)</script></article>'),value.replace('<p id="p1"','<p style="position:fixed" id="p1"'),value.replace('src="assets/table.png"','src="https://example.com/image.png"')):
            path.write_text(bad)
            with self.assertRaises(ValueError):r.read(self.out/'content.json')
        path.write_text(value)

    def test_render_is_repeatable_offline_and_read_only_for_content(self):
        self.complete();before=self.hashes()
        r.save(self.out/'quality-report.json',{'manual_reviews':[{'scope':'semantic fixture review'}]})
        with patch('urllib.request.urlopen',side_effect=AssertionError('render must stay offline')):
            r.render(self.args);first=r.digest(self.out/'index.html')
            q=r.read(self.out/'quality-report.json');q['manual_reviews'].append({'scope':'more evidence'});r.save(self.out/'quality-report.json',q)
            r.render(self.args);self.assertEqual(first,r.digest(self.out/'index.html'))
        self.assertEqual(before,self.hashes())
        doc=html.parse(str(self.out/'index.html'))
        self.assertEqual(len(doc.xpath('//main//img')),1)
        self.assertEqual(len(doc.xpath('//main//math')),2)
        self.assertEqual(len(doc.xpath('//h2/span[@class="lang-en"]')),1)
        self.assertEqual(len(doc.xpath('//h2/span[@class="lang-zh"]')),1)
        self.assertEqual(doc.xpath('//main//h1')[0].text_content(),'Test')
        self.assertEqual(doc.xpath('//main//h2/span[@class="lang-zh"]')[0].text_content(),'1 緒論（Introduction）')
        self.assertEqual(doc.xpath('//*[@id="toc"]//a[@href="#s1"]/span[@class="lang-zh"]')[0].text_content(),'1 緒論（Introduction）')
        self.assertEqual(len(doc.xpath('//main//a[@class="image-link"]')),1)
        ids=doc.xpath('//*[@id]/@id');self.assertEqual(len(ids),len(set(ids)))
        self.assertNotIn('@@',(self.out/'index.html').read_text())

    def test_pending_source_can_render_in_english(self):
        r.render(self.args)
        self.assertIn('data-mode="en"',(self.out/'index.html').read_text())
        self.assertEqual(r.check(self.args)['counts']['translated'],0)
        self.assertEqual(r.check(self.args)['counts']['translatable'],4)

    def test_bad_source_cannot_replace_existing_reader(self):
        r.render(self.args);before=r.digest(self.out/'index.html')
        (self.out/'assets/table.png').unlink()
        with self.assertRaisesRegex(ValueError,'Fix content errors'):r.render(self.args)
        self.assertEqual(before,r.digest(self.out/'index.html'))

    def test_local_image_dimensions_reserve_layout_without_editing_content(self):
        from PIL import Image
        Image.new('RGB',(80,40),'white').save(self.out/'assets/table.png')
        before=self.hashes();r.render(self.args)
        image=html.parse(str(self.out/'index.html')).xpath('//main//img')[0]
        self.assertEqual((image.get('width'),image.get('height')),('80','40'))
        self.assertEqual(image.get('loading'),'lazy');self.assertEqual(before,self.hashes())

    def test_partial_pair_cannot_be_silently_overwritten(self):
        (self.out/'content.zh.html').unlink();before=r.digest(self.out/'content.en.html')
        with self.assertRaises(ValueError):r.html_layer().migrate(self.out,r.__dict__)
        self.assertEqual(before,r.digest(self.out/'content.en.html'))

    def test_source_scaffold_and_existing_translation_protection(self):
        path=self.out/'content.en.html'
        path.write_text(path.read_text().replace('</article>','<p id="new">New paragraph.</p></article>'))
        before=r.digest(path);r.html_layer().sync_source(self.out,r.__dict__)
        self.assertEqual(before,r.digest(path))
        c=r.read(self.out/'content.json');self.assertEqual(c['blocks'][-1]['units'][0]['en'],'New paragraph.')
        self.assertIsNone(c['blocks'][-1]['units'][0]['zh'])
        self.accept();self.translate({'new':'新段落。'})
        before=self.hashes()
        with self.assertRaises(ValueError):r.html_layer().sync_source(self.out,r.__dict__)
        self.assertEqual(before,self.hashes())

    def test_html_reconciliation_before_acceptance(self):
        r.save(self.out/'source/docling.json',{'pages':{},'texts':[],'tables':[]})
        source=self.out.parent/'source.html';source.write_text('<article><h1>Verified title</h1><section id="intro"><h2>Introduction</h2><p id="body">Complete source text.</p></section></article>')
        args=argparse.Namespace(reader=str(self.out),url='https://arxiv.org/html/2108.03298v2',html_file=str(source),version_evidence=None)
        with patch('subprocess.check_output',return_value=b'arXiv:2108.03298v2\nComplete source text.'):
            r.html_layer().align(args,r.__dict__)
        self.assertEqual(r.read(self.out/'content.json')['title'],'Verified title')
        self.assertEqual(self.legacy,r.digest(self.out/'content.json'))
        self.accept();before=self.hashes()
        with self.assertRaises(ValueError):r.html_layer().align(args,r.__dict__)
        self.assertEqual(before,self.hashes())

    def test_plain_html_emphasis_needs_no_custom_prose_syntax(self):
        en='<article lang="en" data-content-version="1"><h1 id="title">Title</h1><p id="p">A <strong>claim</strong>.</p><section id="notes"><p id="note">See <a href="#notes">notes</a>.</p></section></article>'
        zh=en.replace('lang="en"','lang="zh-Hant"').replace('>Title<','>標題<').replace('A <strong>claim</strong>.','一項<strong>主張</strong>。')
        (self.out/'content.en.html').write_text(en);(self.out/'content.zh.html').write_text(zh)
        q=r.check(self.args);self.assertEqual(q['errors'],[])
        self.assertTrue(any('emphasis needs alignment' in warning for warning in q['manual_checklist']))
        r.render(self.args)
        self.assertEqual(html.parse(str(self.out/'index.html')).xpath('//*[@id="p"]/span[@class="lang-zh"]/strong/text()'),['主張'])

    def test_inline_breaks_and_subscripts_remain_protected(self):
        en='<article lang="en" data-content-version="1"><p id="p" data-unit="true">H<sub>2</sub>O<br>continued</p></article>'
        zh=en.replace('lang="en"','lang="zh-Hant"').replace('data-unit="true"','data-unit="true" data-translation="pending"')
        (self.out/'content.en.html').write_text(en);(self.out/'content.zh.html').write_text(zh)
        self.accept();self.translate({'p':'H{{0}}O{{1}}續文'})
        r.render(self.args);doc=html.parse(str(self.out/'index.html'))
        self.assertEqual(doc.xpath('//*[@id="p"]/span[@class="lang-zh"]//sub/text()'),['2'])
        self.assertEqual(len(doc.xpath('//*[@id="p"]/span[@class="lang-zh"]//br')),1)

    def test_scripts_inside_math_are_also_rejected(self):
        path=self.out/'content.en.html';path.write_text(path.read_text().replace('<mi>x</mi>','<mi>x</mi><script>alert(1)</script>'))
        with self.assertRaisesRegex(ValueError,'Unsupported HTML element'):r.read(self.out/'content.json')

    def test_new_extraction_uses_only_html_and_resume_keeps_it_unchanged(self):
        raw={'version':'test','pages':{},'body':{'children':[{'$ref':'#/texts/0'},{'$ref':'#/texts/1'}]},'texts':[
            {'label':'title','text':'Actual title','self_ref':'#/texts/0','prov':[]},
            {'label':'text','text':'Full paragraph.','self_ref':'#/texts/1','prov':[]}]}
        path=self.out.parent/'docling.json';r.save(path,raw);out=self.out.parent/'new-reader'
        argv=['reader.py','extract',str(self.pdf),'--output',str(out),'--docling-json',str(path)]
        with patch('sys.argv',argv):self.assertEqual(r.main(),0)
        self.assertFalse((out/'content.json').exists());self.assertTrue((out/'source/legacy-content.json').exists())
        self.assertEqual(r.read(out/'content.json')['title'],'Actual title')
        before=tuple(r.digest(out/f) for f in r.html_layer().FILES)
        with patch('sys.argv',argv),patch('subprocess.run',side_effect=AssertionError('resume must not run Docling')):self.assertEqual(r.main(),0)
        self.assertEqual(before,tuple(r.digest(out/f) for f in r.html_layer().FILES))

    def test_pending_native_section_includes_nested_sections(self):
        en='<article lang="en" data-content-version="1"><section id="main"><h2 id="head">Heading</h2><section id="child"><p id="inner">Inside.</p></section></section><p id="outside">Outside.</p></article>'
        zh=en.replace('lang="en"','lang="zh-Hant"')
        (self.out/'content.en.html').write_text(en)
        (self.out/'content.zh.html').write_text(zh.replace('<h2 id="head"','<h2 data-translation="pending" id="head"').replace('<p id=','<p data-translation="pending" id='))
        output=io.StringIO()
        with patch('sys.argv',['reader.py','pending',str(self.out),'--section','main']),redirect_stdout(output):self.assertEqual(r.main(),0)
        self.assertEqual([u['id'] for u in json.loads(output.getvalue())],['head','inner'])

    def test_preserved_reference_text_and_semantic_emphasis_survive(self):
        c=r.read(self.out/'content.json');u=c['blocks'][-1]['units'][0]
        self.assertEqual(u['en'],'A & B < C.')
        self.assertEqual(len(html.fromstring(u['html']).xpath('.//em')),1)
        self.assertEqual(r.check(self.args)['counts']['translatable'],4)

    def test_simple_authored_html_and_nested_numbered_lists(self):
        source='<article lang="en" data-content-version="1"><section id="s"><h2 id="heading">Heading</h2><ol start="3"><li id="item">Item<ul><li id="nested">Nested</li></ul></li></ol><p id="p">Text.</p></section></article>'
        target=source.replace('lang="en"','lang="zh-Hant"').replace('>Heading<',' data-translation="pending">Heading<').replace('>Text.<',' data-translation="pending">Text.<').replace('>Item<',' data-translation="pending">Item<').replace('>Nested<',' data-translation="pending">Nested<')
        (self.out/'content.en.html').write_text(source);(self.out/'content.zh.html').write_text(target)
        self.accept();before=(self.out/'content.en.html').read_text()
        self.translate({'p':'文字。','item':'項目','nested':'子項目'})
        self.assertEqual(html.fromstring(before).xpath('.//ol/@start'),html.parse(str(self.out/'content.en.html')).xpath('//ol/@start'))
        self.assertEqual(len(html.parse(str(self.out/'content.zh.html')).xpath('//section/ol/li/ul/li')),1)
        self.assertEqual(before,(self.out/'content.en.html').read_text())
        self.assertEqual(r.read(self.out/'content.json')['blocks'][1]['units'][0]['zh'],'項目')
        r.render(self.args)
        doc=html.parse(str(self.out/'index.html'))
        self.assertEqual(doc.xpath('//*[@id="item"]/span[@class="lang-zh"]/text()'),['項目'])
        self.assertEqual(doc.xpath('//*[@id="nested"]/span[@class="lang-zh"]/text()'),['子項目'])


if __name__=='__main__':unittest.main()
