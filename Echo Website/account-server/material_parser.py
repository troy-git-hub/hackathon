"""Untrusted document extraction worker: isolated process, bounded time and memory."""
import base64
import io
import json
import sys
import zipfile
from pathlib import PurePath

MAX_TEXT=30000

def extract(filename,raw):
    ext=PurePath(filename.lower()).suffix
    warnings=[];pages=1
    if ext in ('.txt','.md'):
        try:content=raw.decode('utf-8-sig')
        except UnicodeDecodeError:raise ValueError('请将文本保存为UTF-8后上传。')
        if '\x00' in content:raise ValueError('文件不是受支持的文本。')
    elif ext=='.docx':
        if not raw.startswith(b'PK'):raise ValueError('DOCX文件头无效。')
        from xml.etree import ElementTree as ET
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos=archive.infolist()
            if len(infos)>200 or sum(i.file_size for i in infos)>12*1024*1024:raise ValueError('DOCX解压体积或内部文件数超限。')
            if any('vbaproject' in i.filename.lower() for i in infos):raise ValueError('不支持包含宏的文件。')
            if any(i.filename.startswith('word/media/') for i in infos):warnings.append('DOCX中的图片未转录；含图试题请另传图片并核对公式、图表。')
            data=archive.read('word/document.xml')
            if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():raise ValueError('不支持XML外部实体。')
            tree=ET.fromstring(data)
            content='\n'.join(''.join(p.itertext()) for p in tree.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'))
    elif ext=='.pdf':
        if not raw.startswith(b'%PDF-'):raise ValueError('PDF文件头无效。')
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(raw),strict=True)
        if reader.is_encrypted:raise ValueError('请先解除PDF密码再上传。')
        pages=len(reader.pages)
        if not 1<=pages<=20:raise ValueError('PDF最多20页，请先拆分试卷。')
        parts=[]
        for index,page in enumerate(reader.pages):
            stream=page.get_contents()
            if stream is not None and len(stream.get_data())>2*1024*1024:raise ValueError('PDF页面内容流过大，请简化或拆页。')
            part=page.extract_text() or ''
            parts.append('[第'+str(index+1)+'页]\n'+part)
            if len(part.strip())<10:warnings.append('第'+str(index+1)+'页没有足够的可提取文字，可能是扫描页。')
            if sum(map(len,parts))>MAX_TEXT:break
        content='\n\n'.join(parts)
        if not any(len(p.strip())>20 for p in parts):
            return {'text':'','pages':pages,'status':'needs_ocr','warnings':['扫描PDF尚未执行OCR。可上传单页图片进行手动视觉解析，或粘贴已识别文字。']}
        warnings.append('PDF本次仅提取文字，复杂公式和图表可能缺失，请对照原件核对。')
    elif ext in ('.png','.jpg','.jpeg'):
        if len(raw)>1024*1024:raise ValueError('图片最多1MiB。')
        from PIL import Image
        Image.MAX_IMAGE_PIXELS=12_000_000
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in ('PNG','JPEG') or image.width*image.height>12_000_000:raise ValueError('图片格式或尺寸超限。')
            image.verify()
        return {'text':'','pages':1,'status':'image','warnings':['图片尚未调用AI识别；点击解析后使用视觉模型，按token结算。']}
    else:raise ValueError('仅支持PDF、TXT、Markdown、DOCX、PNG和JPEG。')
    if len(content)>MAX_TEXT:warnings.append('资料超过30000字，仅保留前30000字；后续AI分析仍有单次范围限制。')
    content=content[:MAX_TEXT].replace('\x00','').strip()
    if not content:raise ValueError('没有提取到文字，请检查文件或使用文本校正。')
    return {'text':content,'pages':pages,'status':'ready','warnings':warnings[:20]}

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    try:
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_AS,(96*1024*1024,96*1024*1024))
            resource.setrlimit(resource.RLIMIT_CPU,(8,8))
        except ImportError:pass
        data=json.loads(sys.stdin.buffer.read(5*1024*1024))
        raw=base64.b64decode(data['content_base64'],validate=True)
        if not 1<=len(raw)<=3*1024*1024:raise ValueError('文件为空或超过3MiB。')
        result=extract(data['filename'],raw)
        print(json.dumps({'ok':True,**result},ensure_ascii=False))
    except (ValueError,KeyError,zipfile.BadZipFile,MemoryError,RuntimeError) as exc:
        print(json.dumps({'ok':False,'error':str(exc)[:200] or '文件超出安全解析限制。'},ensure_ascii=False))
    except Exception:
        print(json.dumps({'ok':False,'error':'无法解析该文件，请重新导出或上传纯文本。'},ensure_ascii=False))

if __name__=='__main__':main()
