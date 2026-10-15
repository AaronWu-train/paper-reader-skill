import argparse
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode=True
spec=importlib.util.spec_from_file_location('reader',Path(__file__).resolve().parents[1]/'scripts/reader.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)


class PendingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.out=self.root/'reader';(self.out/'assets').mkdir(parents=True)
        pdf=self.root/'paper.pdf';pdf.write_bytes(b'fixture PDF')
        self.math='<math><semantics><mi>x</mi><annotation encoding="application/x-tex">'+('x+'*1000)+'y</annotation></semantics></math>'
        blocks=[]
        for i in range(25):
            u=r.unit(f'p{i}','May improve {{0}}; see {{1}}.',original='<p>May improve a formula; see Section 1.</p>',tokens={'0':self.math,'1':'<a href="#p0">Section 1</a>'})
            if i==0:u['styles']={'en':[{'id':'f0','start':0,'end':3,'text':'May','bold':True}]}
            blocks.append({'id':u['id'],'section':'S1','type':'paragraph','source':{'pdf':[{'page_no':1}]},'units':[u]})
        r.save(self.out/'content.json',{'title':'Fixture','source':{'pdf':str(pdf),'sha256':r.digest(pdf)},'blocks':blocks})

    def tearDown(self):self.tmp.cleanup()

    def pending(self,*args):
        stdout=io.StringIO();stderr=io.StringIO()
        with patch('sys.argv',['reader.py','pending',str(self.out),*args]),redirect_stdout(stdout),redirect_stderr(stderr):
            status=r.main()
        return status,stdout.getvalue(),stderr.getvalue()

    def test_default_is_bounded_and_compact_without_mutation(self):
        before=r.digest(self.out/'content.json')
        status,raw,summary=self.pending()
        batch=json.loads(raw)
        self.assertEqual(status,0);self.assertEqual(len(batch),10)
        self.assertLessEqual(len(raw.rstrip('\n')),8000)
        self.assertNotIn(self.math,raw);self.assertNotIn('source',batch[0])
        self.assertEqual(batch[0]['tokens']['1'],{'kind':'a','text':'Section 1'})
        self.assertTrue(batch[0]['tokens']['0']['preview_only'])
        self.assertEqual(batch[0]['styles'],[{'id':'f0','text':'May','bold':True}])
        self.assertNotIn('styles',batch[1]);self.assertIn('10 of 25',summary)
        self.assertEqual(before,r.digest(self.out/'content.json'))

    def test_character_budget_counts_serialized_metadata_and_unicode(self):
        c=r.read(self.out/'content.json');c['blocks'][0]['units'][0]['en']='中文引號 " {{0}} {{1}}'
        r.save(self.out/'content.json',c)
        first=json.loads(self.pending('--limit','1')[1])[0]
        budget=len(json.dumps([first],ensure_ascii=False,separators=(',',':')))
        status,raw,summary=self.pending('--max-chars',str(budget))
        self.assertEqual(status,0);self.assertEqual(json.loads(raw),[first])
        self.assertEqual(len(raw.rstrip('\n')),budget)
        self.assertNotIn('exceeds',summary)
        _,raw,summary=self.pending('--max-chars','1')
        self.assertEqual(json.loads(raw),[first]);self.assertIn('emitted intact',summary)

    def test_full_id_lookup_and_invalid_arguments(self):
        status,raw,_=self.pending('--id','p0','--full')
        entry=json.loads(raw)[0]
        self.assertEqual(status,0);self.assertEqual(entry['tokens']['0'],self.math)
        self.assertEqual(entry['source'],{'pdf':[{'page_no':1}]})
        status,raw,summary=self.pending('--id','missing')
        self.assertEqual(status,1);self.assertEqual(raw,'');self.assertIn('missing',summary)
        for option in ('--limit','--max-chars'):
            for value in ('0','-1'):
                with self.assertRaises(SystemExit) as exc:self.pending(option,value)
                self.assertEqual(exc.exception.code,2)

    def test_html_section_selection_is_bounded_and_includes_descendants(self):
        r.html_layer().migrate(self.out,r.__dict__)
        from lxml import etree
        for name in r.html_layer().FILES:
            root=r.html_layer().parse(self.out,name)
            section=etree.Element('section',id='chapter');nested=etree.SubElement(section,'section',id='subsection')
            # Stored data-section differs; DOM ancestry still selects the units.
            for uid in ('p0','p1','p2'):nested.append(root.xpath('.//*[@id=$id]',id=uid)[0])
            root.append(section)
            (self.out/name).write_text(r.html_layer().serialize(root))
        status,raw,_=self.pending('--section','chapter','--limit','2')
        self.assertEqual(status,0);self.assertEqual([u['id'] for u in json.loads(raw)],['p0','p1'])
        status,raw,_=self.pending('--section','does-not-exist')
        self.assertEqual(status,0);self.assertEqual(json.loads(raw),[])

    def test_batches_resume_and_emphasis_applies_in_both_storage_formats(self):
        # The same pending CLI serves legacy JSON and canonical HTML readers.
        for mode in ('legacy','html'):
            with self.subTest(mode=mode):
                if mode=='html':
                    c=r.read(self.out/'content.json')
                    for _,u in r.all_units(c):u['zh']=None;u.get('styles',{}).pop('zh',None)
                    r.save(self.out/'content.json',c)
                    r.html_layer().migrate(self.out,r.__dict__)
                    r.html_layer().accept(argparse.Namespace(reader=str(self.out),review_note='Synthetic fixture source'),r.__dict__)
                english=r.digest(self.out/'content.en.html') if mode=='html' else None
                seen=[]
                while True:
                    status,raw,_=self.pending('--limit','4','--max-chars','2000')
                    self.assertEqual(status,0);batch=json.loads(raw)
                    if not batch:break
                    ids=[u['id'] for u in batch];self.assertFalse(set(ids)&set(seen));seen+=ids
                    translations={u['id']:'可能改善 {{0}}；見 {{1}}。' for u in batch}
                    emphasis={u['id']:[{'source':'f0','text':'可能'}] for u in batch if u.get('styles')}
                    path=self.root/'translation.json';r.save(path,translations)
                    r.translate(argparse.Namespace(reader=str(self.out),patch=str(path),replace=[]))
                    if emphasis:
                        # Recoverable inspection between translation and saved format application.
                        inspected=json.loads(self.pending('--id','p0')[1])[0]
                        self.assertEqual(inspected['zh'],translations['p0'])
                        path=self.root/'emphasis.json';r.save(path,emphasis)
                        r.format_content(argparse.Namespace(reader=str(self.out),patch=str(path),replace=[]))
                self.assertEqual(seen,[f'p{i}' for i in range(25)])
                c=r.read(self.out/'content.json');first=c['blocks'][0]['units'][0]
                self.assertEqual(first['tokens']['0'],self.math)
                self.assertEqual(first['styles']['zh'][0]['text'],'可能')
                if english:self.assertEqual(english,r.digest(self.out/'content.en.html'))


if __name__=='__main__':unittest.main()
