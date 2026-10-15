import argparse
import importlib.util
import json
import os
import tempfile
import unittest
import sys
import io
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
sys.dont_write_bytecode=True

spec=importlib.util.spec_from_file_location('reader',Path(__file__).resolve().parents[1]/'scripts/reader.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.pdf=self.root/'original.pdf';self.pdf.write_bytes(b'test authority fingerprint')
        self.out=self.root/'reader';(self.out/'assets').mkdir(parents=True)
        self.c={'title':'Test','source':{'pdf':str(self.pdf),'sha256':r.digest(self.pdf)},'blocks':[
            {'id':'S1','type':'heading','section':'S1','level':2,'units':[r.unit('S1','Introduction')]},
            {'id':'p1','type':'paragraph','section':'S1','units':[r.unit('p1','May improve {{0}}.',tokens={'0':'<math><mi>x</mi></math>'})]},
            {'id':'p2','type':'paragraph','section':'S1','units':[r.unit('p2','Another paragraph.')]}]}
        r.save(self.out/'content.json',self.c)
    def tearDown(self):self.tmp.cleanup()
    def apply(self,data,replace=[]):
        r.save(self.root/'patch.json',data)
        r.translate(argparse.Namespace(reader=str(self.out),patch=str(self.root/'patch.json'),replace=replace))
    def test_patch_transaction_and_token_conservation(self):
        before=r.digest(self.out/'content.json')
        with self.assertRaises(ValueError):self.apply({'p2':'有效段落','p1':'可能改善，公式遺失。'})
        self.assertEqual(before,r.digest(self.out/'content.json'))
        self.apply({'p1':'可能改善 {{0}}。'})
        self.assertEqual(r.read(self.out/'content.json')['blocks'][1]['units'][0]['zh'],'可能改善 {{0}}。')
    def test_existing_manual_translation_protected(self):
        self.apply({'p2':'手動校訂文字'})
        before=r.digest(self.out/'content.json')
        with self.assertRaises(ValueError):self.apply({'p2':'其他文字'})
        self.assertEqual(before,r.digest(self.out/'content.json'))
        self.apply({'p2':'使用者要求的更新'},replace=['p2'])
    def test_render_does_not_retranslate_or_fetch(self):
        self.apply({'S1':'緒論','p1':'可能改善 {{0}}。','p2':'另一段。'})
        r.save(self.out/'quality-report.json',{'manual_reviews':[{'scope':'test review'}]})
        before=r.digest(self.out/'content.json')
        with patch('urllib.request.urlopen',side_effect=AssertionError('render must be offline')):
            r.render(argparse.Namespace(reader=str(self.out)))
        self.assertEqual(before,r.digest(self.out/'content.json'))
        self.assertEqual(r.read(self.out/'quality-report.json')['manual_reviews'][0]['scope'],'test review')
        doc=(self.out/'index.html').read_text()
        self.assertIn('data-mode="zh"',doc);self.assertNotIn('@@',doc)
        self.assertTrue((self.out/'assets/reader.css').exists())
        from lxml import html
        link=html.fromstring(doc).xpath('//header/a[@class="pdf-button"]')[0]
        self.assertEqual(link.get('href'),'../original.pdf')
        self.assertEqual(link.get('target'),'_blank')
    def test_source_hash_and_broken_link_checks(self):
        self.c['blocks'][1]['units'][0]['tokens']['0']='<a href="#missing">1</a>'
        r.save(self.out/'content.json',self.c)
        self.pdf.write_bytes(b'changed')
        q=r.check(argparse.Namespace(reader=str(self.out)))
        codes={e['code'] for e in q['errors']}
        self.assertIn('authority_changed',codes);self.assertIn('broken_reference',codes)
    def test_legacy_quality_report_preserves_manual_reviews(self):
        original={'manual_reviews':[{'scope':'manual review'}],'source_review':{'version':'verified'}}
        r.save(self.out/'qa.json',original)
        r.check(argparse.Namespace(reader=str(self.out)))
        report=r.read(self.out/'quality-report.json')
        self.assertEqual(report['manual_reviews'],original['manual_reviews'])
        self.assertEqual(report['source_review'],original['source_review'])
    def test_resolve_without_library_layout(self):
        folder=self.root/'unrelated downloads';folder.mkdir()
        pdf=folder/'A study.PDF';pdf.write_bytes(b'pdf')
        prev=Path.cwd()
        try:
            os.chdir(self.root)
            self.assertEqual(r.resolve('unrelated downloads/A study.PDF'),pdf.resolve())
            self.assertEqual(r.resolve(str(folder)),pdf.resolve())
            with self.assertRaisesRegex(ValueError,'PDF path not found'):
                r.resolve('missing-citekey')
            (folder/'another.pdf').write_bytes(b'pdf')
            with self.assertRaisesRegex(ValueError,'found 2'):r.resolve(str(folder))
            self.assertEqual(r.resolve(str(pdf)),pdf.resolve())
        finally:os.chdir(prev)

    def test_default_output_keeps_sibling_pdfs_independent(self):
        raw={'version':'test','pages':{},'body':{'children':[]}}
        rawpath=self.root/'docling.json';r.save(rawpath,raw)
        second=self.root/'another.PDF';second.write_bytes(b'another PDF')
        for pdf in (self.pdf,second):
            out,new=r.extract(argparse.Namespace(input=str(pdf),output=None,docling_json=str(rawpath)))
            self.assertTrue(new)
            self.assertEqual(out,pdf.resolve().parent/(pdf.stem+'-reader'))
            self.assertEqual(r.read(out/'content.json')['source']['pdf'],str(pdf.resolve()))
            self.assertEqual(r.read(out/'content.json')['glossary'],[])
            reused,new=r.extract(argparse.Namespace(input=str(pdf),output=None,docling_json=str(rawpath)))
            self.assertEqual(reused,out);self.assertFalse(new)

    def test_arxiv_named_local_pdf_is_not_a_remote_id(self):
        pdf=self.root/'2303.04137.pdf';pdf.write_bytes(b'local PDF')
        rawpath=self.root/'docling.json'
        r.save(rawpath,{'version':'test','pages':{},'body':{'children':[]}})
        prev=Path.cwd()
        try:
            os.chdir(self.root)
            with patch.object(r,'download',side_effect=AssertionError('local file must not download')):
                out,new=r.extract(argparse.Namespace(input=pdf.name,output=None,docling_json=str(rawpath)))
            self.assertTrue(new)
            self.assertEqual(out,pdf.resolve().parent/'2303.04137-reader')
        finally:os.chdir(prev)

    def test_remote_arxiv_keeps_requested_version_and_explicit_output(self):
        rawpath=self.root/'docling.json'
        r.save(rawpath,{'version':'test','pages':{},'body':{'children':[]}})
        args=argparse.Namespace(input='arxiv:2303.04137v5',output=None,docling_json=str(rawpath))
        with self.assertRaisesRegex(ValueError,'needs --output'):r.extract(args)
        args.output=str(self.root/'downloaded')
        def download(url,dest):
            self.assertEqual(url,'https://arxiv.org/pdf/2303.04137v5')
            dest.parent.mkdir(parents=True);dest.write_bytes(b'%PDF-1.4 fixture');return dest
        with patch.object(r,'download',side_effect=download):
            out,new=r.extract(args)
        self.assertTrue(new)
        self.assertEqual(r.read(out/'content.json')['source']['pdf'],str(out/'source/original.pdf'))

    def test_wrong_html_version_refused_without_writes(self):
        before=r.digest(self.out/'content.json')
        with patch('subprocess.check_output',return_value=b'arXiv:2303.04137v5'):
            with self.assertRaises(ValueError):
                r.align_html(argparse.Namespace(reader=str(self.out),url='https://arxiv.org/html/2303.04137v4',html_file=None,version_evidence=None))
        self.assertEqual(before,r.digest(self.out/'content.json'))
    def test_table_images_only_and_legacy_cells_preserved(self):
        self.apply({'S1':'緒論','p1':'可能改善 {{0}}。','p2':'另一段。'})
        c=r.read(self.out/'content.json')
        cell=r.unit('cell','UNRELIABLE TABLE CELL')
        cell['zh']='既有表格翻譯'
        c['blocks'].append({'id':'T1','type':'table','section':'S1','images':['assets/table.png'],
                            'table_html':'<table><td>UNRELIABLE TABLE CELL</td></table>','units':[cell]})
        (self.out/'assets/table.png').write_bytes(b'original table crop')
        r.save(self.out/'content.json',c)
        before=r.digest(self.out/'content.json')
        q=r.check(argparse.Namespace(reader=str(self.out)))
        self.assertEqual(q['errors'],[])
        self.assertEqual(q['counts']['translatable'],3)
        r.render(argparse.Namespace(reader=str(self.out)))
        doc=(self.out/'index.html').read_text()
        self.assertEqual(doc.count('src="assets/table.png"'),1)
        self.assertNotIn('<table',doc)
        self.assertNotIn('UNRELIABLE TABLE CELL',doc)
        self.assertNotIn('既有表格翻譯',doc)
        self.assertEqual(before,r.digest(self.out/'content.json'))
        c['blocks'][-1]['units'][0]['zh']=None
        r.save(self.out/'content.json',c)
        output=io.StringIO()
        with patch('sys.argv',['reader.py','pending',str(self.out)]),redirect_stdout(output):
            self.assertEqual(r.main(),0)
        self.assertEqual(json.loads(output.getvalue()),[])
    def test_missing_table_crop_is_error_without_html_fallback(self):
        self.c['blocks']=[{'id':'T1','type':'table','section':'S1','units':[],
                           'table_html':'<table><td>DO NOT RECONSTRUCT</td></table>'}]
        r.save(self.out/'content.json',self.c)
        q=r.check(argparse.Namespace(reader=str(self.out)))
        self.assertIn({'code':'table_crop_missing','id':'T1'},q['errors'])
        r.render(argparse.Namespace(reader=str(self.out)))
        doc=(self.out/'index.html').read_text()
        self.assertIn('缺少原始 PDF 表格裁切',doc)
        self.assertNotIn('DO NOT RECONSTRUCT',doc)
    def test_pdf_table_extraction_keeps_crop_and_separate_caption(self):
        raw={'version':'test','pages':{'1':{'size':{'height':100}}},
             'body':{'children':[{'$ref':'#/tables/0'}]},
             'tables':[{'self_ref':'#/tables/0','label':'table',
                        'prov':[{'page_no':1,'bbox':{'l':10,'t':10,'r':90,'b':30,'coord_origin':'TOPLEFT'}}],
                        'data':{'table_cells':[{'text':'Unreliable cells'}]},'captions':[{'$ref':'#/texts/0'}]}],
             'texts':[{'self_ref':'#/texts/0','label':'caption','text':'Table 1: Results.','prov':[]}]}
        rawpath=self.root/'docling.json';r.save(rawpath,raw)
        (self.out/'content.json').unlink()
        def crop(pdf,page,bbox,path):Path(path).write_bytes(b'crop')
        with patch.object(r,'crop_pdf',side_effect=crop):
            r.extract(argparse.Namespace(input=str(self.pdf),output=str(self.out),docling_json=str(rawpath)))
        c=r.read(self.out/'content.json');table,caption=c['blocks']
        self.assertEqual(table['units'],[]);self.assertNotIn('table_html',table)
        self.assertTrue((self.out/table['images'][0]).exists())
        self.assertEqual(caption['units'][0]['en'],'Table 1: Results.')
        self.assertFalse(caption['units'][0]['preserve'])
        self.assertEqual(r.read(self.out/'source/docling.json')['tables'][0]['data'],raw['tables'][0]['data'])
    def test_html_tables_match_pdf_caption_not_order(self):
        raw={'pages':{'1':{'size':{'height':100}}},'texts':[], 'tables':[]}
        for i in range(2):
            raw['texts'].append({'text':f'Table {i+1}: Results.','prov':[{'page_no':1}]})
            raw['tables'].append({'self_ref':f'#/tables/{i}','captions':[{'$ref':f'#/texts/{i}'}],
                                  'prov':[{'page_no':1,'bbox':{'l':10,'t':10+i*30,'r':90,'b':30+i*30,'coord_origin':'TOPLEFT'}}]})
        r.save(self.out/'source/docling.json',raw)
        source=self.root/'source.html'
        source.write_text('<article><h1>Test</h1><table><td></td></table>'+''.join(
            f'<figure id="T{i}"><table id="table{i}"><td>Unreliable cells</td></table><figcaption>Table {i}: Results.</figcaption></figure>'
            for i in (2,1,3))+'</article>')
        def crop(pdf,page,bbox,path):Path(path).write_bytes(str(bbox).encode())
        with patch('subprocess.check_output',return_value=b'arXiv:2108.03298v2'),patch.object(r,'crop_pdf',side_effect=crop):
            r.align_html(argparse.Namespace(reader=str(self.out),url='https://arxiv.org/html/2108.03298v2',html_file=str(source),version_evidence=None))
        tables=[b for b in r.read(self.out/'content.json')['blocks'] if b['type']=='table']
        self.assertEqual([b['id'] for b in tables],['table2','table1','table3'])
        self.assertEqual([tables[i]['source']['pdf'][0]['bbox']['t'] for i in (0,1)],[40,10])
        for b in tables:self.assertEqual(b['units'],[]);self.assertNotIn('table_html',b)
        self.assertFalse(tables[2].get('images'))
        self.assertIn({'code':'table_crop_missing','id':'table3'},r.check(argparse.Namespace(reader=str(self.out)))['errors'])
    def test_active_html_content_removed(self):
        from lxml import html
        result=r.safe_html(html.fromstring('<div onclick="alert(1)"><script>alert(1)</script><a href="javascript:alert(1)">x</a></div>'))
        for v in ['onclick','<script','javascript:']:self.assertNotIn(v,result)
    def test_emphasis_scope_and_protected_math(self):
        u=r.unit('p','A bold normal both {{0}} end.',original='<p>A <b>bold <span class="ltx_font_medium">normal</span> <i>both</i></b> <u style="color:#d24;position:fixed">'+self.c['blocks'][1]['units'][0]['tokens']['0']+'</u> end.</p>',tokens={'0':'<math><mi>x</mi></math>'})
        u['styles']={'en':r.html_styles(u)}
        result=r.expanded(u,'en')
        from lxml import html
        root=html.fromstring(result)
        self.assertEqual(root.text_content(),'A bold normal both x end.')
        spans=root.xpath('.//span[@class="source-emphasis"]')
        self.assertEqual([s.text_content() for s in spans],['bold','both','x'])
        self.assertNotIn('font-weight',spans[-1].get('style'))
        self.assertIn('font-style:italic',spans[1].get('style'))
        self.assertIn('text-decoration-line:underline',spans[-1].get('style'))
        self.assertIn('color:#d24',spans[-1].get('style'))
        self.assertEqual(len(root.xpath('.//math')),1)
    def test_safe_emphasis_css_and_link_color(self):
        from lxml import html
        result=r.safe_html(html.fromstring('<p style="color:#12ab34;font-style:italic;position:fixed;background:url(https://x)"><a style="color:red" href="#p1"><span style="color:red">Ref</span></a><math><mi style="--ltx-fg-color:#FF0000">x</mi></math></p>'))
        for value in ['position','background','url(','color:red']:self.assertNotIn(value,result)
        self.assertIn('color:#12ab34',result);self.assertIn('color:#ff0000',result)
    def test_format_patch_is_transactional_and_text_preserved(self):
        u=self.c['blocks'][2]['units'][0]
        u['en']='Another paragraph.';u['html']='<p><b>Another</b> paragraph.</p>';u['zh']='另一段，另一段。'
        r.save(self.out/'content.json',self.c)
        args=argparse.Namespace(reader=str(self.out),patch=str(self.root/'format.json'),replace=[])
        r.save(args.patch,{'p2':[{'source':'f0','text':'另一段'}]})
        before=r.digest(self.out/'content.json')
        with self.assertRaises(ValueError):r.format_content(args)
        self.assertEqual(before,r.digest(self.out/'content.json'))
        r.save(args.patch,{'p2':[{'source':'f0','text':'另一段','occurrence':2}]})
        r.format_content(args)
        saved=r.read(self.out/'content.json')['blocks'][2]['units'][0]
        self.assertEqual(saved['zh'],u['zh']);self.assertEqual(saved['en'],u['en'])
        self.assertEqual(saved['styles']['zh'][0]['start'],4)
        saved['zh']='中文已手改，範圍失效。'
        with self.assertRaises(ValueError):r.expanded(saved,'zh')
    def test_pdf_font_styles_need_exact_alignment(self):
        self.c['blocks'][2]['source']={'pdf':[{'page_no':1,'bbox':{'l':10,'t':90,'r':90,'b':80,'coord_origin':'BOTTOMLEFT'}}]}
        data=b'<pdf2xml><page number="1" height="100"><fontspec id="0" family="NimbusRomNo9L-Medi" color="#000000"/><text left="10" top="10" width="70" height="10" font="0">Another paragraph.</text></page></pdf2xml>'
        with patch('shutil.which',return_value='pdftohtml'),patch('subprocess.check_output',return_value=data):
            found,_=r.pdf_styles(self.c,self.out)
            self.assertTrue(found['p2'][0]['bold'])
            self.c['blocks'][2]['units'][0]['en']='Changed text.'
            found,warnings=r.pdf_styles(self.c,self.out)
        self.assertNotIn('p2',found)
        self.assertTrue(any('p2' in w for w in warnings))
    def test_pending_chapter_includes_subsections(self):
        self.c['blocks'][1]['section']='S1.SS1'
        self.c['blocks'][2]['section']='S2'
        r.save(self.out/'content.json',self.c)
        output=io.StringIO()
        with patch('sys.argv',['reader.py','pending',str(self.out),'--section','S1']),redirect_stdout(output):
            self.assertEqual(r.main(),0)
        self.assertEqual([u['id'] for u in json.loads(output.getvalue())],['S1','p1'])

if __name__=='__main__':unittest.main()
