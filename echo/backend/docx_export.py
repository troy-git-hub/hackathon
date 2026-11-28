"""Minimal .docx writer. No third-party package; Word and WPS can open it."""
import re
import time
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from echo.backend import paths


def _xml(text):
    return escape(str(text or '').replace('\r', ''))


def build(title, paragraphs):
    body = []
    if title:
        body.append(
            '<w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
            '<w:r><w:rPr><w:b/><w:sz w:val="32"/></w:rPr>'
            '<w:t>' + _xml(title) + '</w:t></w:r></w:p>')
    for para in paragraphs:
        line = str(para or '').strip()
        if not line:
            body.append('<w:p/>')
            continue
        body.append('<w:p><w:r><w:t xml:space="preserve">' + _xml(line) + '</w:t></w:r></w:p>')
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body>' + ''.join(body) +
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr>'
        '</w:body></w:document>')
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>')
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        '</Relationships>')
    return {
        '[Content_Types].xml': content_types,
        '_rels/.rels': rels,
        'word/document.xml': document,
    }


def save(title, text, filename=None):
    folder = Path(paths.config_dir()) / 'exports'
    folder.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r'[\\/:*?"<>|]+', '-', str(title or 'Echo'))[:40] or 'Echo'
    name = filename or (stem + '-' + time.strftime('%Y%m%d-%H%M') + '.docx')
    if not name.endswith('.docx'):
        name += '.docx'
    path = folder / name
    parts = build(title, str(text or '').splitlines())
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for item, xml in parts.items():
            archive.writestr(item, xml.encode('utf-8'))
    return path
