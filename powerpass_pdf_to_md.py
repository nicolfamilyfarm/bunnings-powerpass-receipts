"""Convert PowerPass receipt PDFs to matching UTF-8 Markdown files locally."""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

try:
    from pypdf import PdfReader
except ImportError:
    raise SystemExit('Install the dependency first: py -m pip install "pypdf>=5,<7"')

VERSION = '1'


def convert(source, target, overwrite=False):
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    marker = f'<!-- powerpass-pdf-to-md:{VERSION} source-sha256:{digest} -->'
    if target.exists() and not overwrite:
        if target.read_text(encoding='utf-8').splitlines()[0:1] == [marker]:
            return 'skipped', 0
        raise ValueError(f'{target.name} already exists or source changed; use --overwrite to replace it')

    sections = [marker, '', f'# {source.stem}', '',
                f'Source: [{source.name}]({quote(source.name)})', '']
    # Decode the actual embedded PDF text; no API, GPT or browser is involved.
    with source.open('rb') as stream:
        reader = PdfReader(stream)
        if reader.is_encrypted and not reader.decrypt(''):
            raise ValueError('PDF is password protected')
        if not reader.pages:
            raise ValueError('PDF has no pages')
        page_count = len(reader.pages)
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text(extraction_mode='layout', layout_mode_space_vertically=False) or ''
            text = '\n'.join(line.rstrip() for line in text.splitlines()).strip()
            if not text:
                raise ValueError(f'Page {number} has no extractable text; OCR may be needed')
            # A fenced block retains item/quantity/price column spacing and keeps
            # PDF punctuation from being interpreted as Markdown formatting.
            longest = max((len(x) for x in re.findall(r'`+', text)), default=0)
            fence = '`' * max(3, longest + 1)
            if number > 1:
                sections.extend(['---', ''])
            sections.extend([f'## Page {number}', '', fence + 'text', text, fence, ''])
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.md.tmp')
    temporary.write_text('\n'.join(sections), encoding='utf-8')
    temporary.replace(target)
    return 'converted', page_count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, default=Path(__file__).parent / 'receipts')
    parser.add_argument('--overwrite', action='store_true', help='Replace existing Markdown files')
    args = parser.parse_args()
    folder = args.folder.resolve()
    if not folder.is_dir():
        parser.error(f'Folder does not exist: {folder}')
    sources = sorted(p for p in folder.iterdir()
                     if p.is_file() and p.suffix.lower() == '.pdf' and '.partial.' not in p.name.lower())
    if not sources:
        parser.error(f'No completed PDFs found in {folder}')
    converted = skipped = pages = 0
    failures = []
    for source in sources:
        try:
            status, count = convert(source, source.with_suffix('.md'), args.overwrite)
            converted += status == 'converted'
            skipped += status == 'skipped'
            pages += count
            print(f'{status.upper()}: {source.name}' + (f' ({count} pages)' if count else ''), flush=True)
        except Exception as exc:
            failures.append({'file': source.name, 'error': str(exc)})
            print(f'FAILED: {source.name}: {exc}', file=sys.stderr, flush=True)
    report = {'converted': converted, 'skipped': skipped, 'pages_converted': pages, 'failures': failures}
    (folder / 'markdown_conversion_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'\n{converted} converted, {skipped} skipped, {len(failures)} failed. Markdown files: {folder}')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
