"""Download PowerPass receipt batches through a visible, manually logged-in Edge."""
import argparse
import asyncio
import hashlib
import json
import re
import traceback
from datetime import date
from pathlib import Path

from playwright.async_api import async_playwright

URL = "https://www.bunningspowerpass.com.au/pwrpass/f?p=111:PP_LOGIN"
REPORT = "#report_rpttrans"
LINKS = REPORT + " a[href*='PRINT_SINGLE']"


def valid_pdf(path):
    if not path.is_file() or path.stat().st_size <= 100:
        return False
    with path.open('rb') as stream:
        return stream.read(5) == b'%PDF-'


async def rows(page):
    # Stable transaction IDs, excluding expiring session and checksum parameters.
    hrefs = await page.locator(LINKS).evaluate_all("els => els.map(e => e.getAttribute('href'))")
    ids = []
    for href in hrefs:
        match = re.search(r'P30_SINGLE_PRINT_PARAMS:([^%&]+)', href)
        if not match:
            raise RuntimeError('Receipt link format changed; stopping rather than guessing.')
        ids.append(match.group(1))
    return ids


async def download_batch(context, page, destination, timeout):
    # Capture the authenticated PDF response before Chromium creates a download
    # artifact owned by a popup that may immediately disappear.
    future = asyncio.get_running_loop().create_future()
    existing = set(context.pages)
    pattern = 'https://www.bunningspowerpass.com.au/**'
    temporary = destination.with_suffix('.partial.pdf')

    async def capture(route):
        request = route.request
        if request.resource_type not in ('document', 'xhr', 'fetch'):
            await route.continue_()
            return
        response = None
        try:
            # Forward the exact request, including its method, form data and
            # authenticated cookies. Do not submit a second Print request.
            response = await route.fetch(timeout=timeout * 1000)
            body = await response.body()
            if body.startswith(b'%PDF-'):
                if response.status != 200 or len(body) <= 100:
                    raise RuntimeError(f'Invalid PDF response (HTTP {response.status}).')
                temporary.write_bytes(body)
                temporary.replace(destination)
                # A 204 leaves the transaction page in place and avoids handing
                # the attachment to Edge's popup-owned temporary file machinery.
                try:
                    await route.fulfill(status=204, body=b'')
                except Exception:
                    # A closed popup cannot invalidate the bytes already saved.
                    pass
                if not future.done():
                    future.set_result(destination)
            else:
                await route.fulfill(response=response)
        except Exception as exc:
            if not future.done():
                future.set_exception(RuntimeError(f'PDF response capture failed: {exc}'))
            try:
                await route.abort()
            except Exception:
                pass
        finally:
            if response is not None:
                await response.dispose()

    await context.route(pattern, capture)
    try:
        print('    Capturing authenticated PDF response…', flush=True)
        # Receipt generation can take longer than the normal 30-second action
        # timeout. The capture future below owns the download wait; Playwright
        # must not additionally wait for a download-only navigation here.
        await page.get_by_role('button', name='Print Selected', exact=True).click(no_wait_after=True)
        try:
            await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                f'No PDF response completed within {timeout} seconds. '
                'This batch has not been recorded as saved.') from exc
        if not valid_pdf(destination):
            raise RuntimeError(f'Download is not a PDF: {destination}')
        print(f'    PDF verified: {destination.stat().st_size:,} bytes', flush=True)
    finally:
        await context.unroute(pattern, capture)
        for current in list(context.pages):
            if current not in existing:
                await current.close()


async def run(args):
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    profile = Path(args.profile).resolve()
    manifest_path = out / 'progress.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            str(profile), channel='msedge', headless=False, accept_downloads=True,
            downloads_path=str(out / '_browser_downloads'))
        # Some report popups call window.close() immediately after initiating the
        # attachment. Keep PowerPass popups alive until save_as has completed.
        # init scripts run before the popup's own scripts; a page-event handler
        # alone is too late. Normal browser close buttons still work.
        await context.add_init_script("""
            if (location.hostname === 'www.bunningspowerpass.com.au' && window.opener) {
                window.close = function () {};
            }
        """)
        page = context.pages[0] if context.pages else await context.new_page()
        page.set_default_timeout(30000)
        await page.goto(URL)
        print('\nLog in in the Edge window and open Transactions.')
        print('Choose the intended account. This script searches ALL cards for that account.')
        await asyncio.to_thread(input, 'When ready, press Enter here: ')
        await page.locator('#SEARCH').wait_for()
        try:
            for year in range(args.start_year, args.end_date.year + 1):
                end = min(date(year, 12, 31), args.end_date)
                await page.locator('#P30_TRX_SEARCH_OPTION_0').check()
                await page.locator('#P30_SC_PERIOD_1').check()
                for label, value in [('From', date(year, 1, 1)), ('To', end)]:
                    field = page.get_by_role('textbox', name=label, exact=True)
                    await field.fill(value.strftime('%d/%m/%Y'))
                    await field.press('Escape')
                    await field.press('Tab')
                async with page.expect_navigation(wait_until='domcontentloaded'):
                    await page.locator('#SEARCH').click()
                await page.locator(REPORT).wait_for()
                current_ids = await rows(page)
                if not current_ids:
                    text = await page.locator(REPORT).inner_text()
                    if not re.search(r'no (data|transactions|records|rows)', text, re.I):
                        raise RuntimeError(f'{year}: no receipt links, but no explicit empty-result message.')
                    print(f'{year}: no transactions')
                    continue
                pagination = page.get_by_role('combobox', name='Select Pagination', exact=True)
                options = []
                if await pagination.count():
                    options = await pagination.locator('option').evaluate_all(
                        'els => els.map(e => ({value:e.value, label:e.textContent}))')
                expected = None
                if options:
                    match = re.search(r'of\s+(\d+)', options[0]['label'])
                    if match:
                        expected = int(match.group(1))
                print(f'{year}: {expected or len(current_ids)} transactions, {len(options) or 1} result pages')
                seen = set()
                for number in range(1, (len(options) or 1) + 1):
                    if number > 1:
                        old = current_ids
                        await pagination.select_option(options[number - 1]['value'])
                        await page.wait_for_function(
                            "old => Array.from(document.querySelectorAll(" + json.dumps(LINKS) + "))"
                            ".map(e => e.getAttribute('href').match(/P30_SINGLE_PRINT_PARAMS:([^%&]+)/)[1]).join('|') !== old",
                            arg='|'.join(old))
                    current_ids = await rows(page)
                    if not current_ids or seen.intersection(current_ids):
                        raise RuntimeError(f'{year}: repeated or empty page {number}; stopping to avoid missing receipts.')
                    seen.update(current_ids)
                    digest = hashlib.sha256('|'.join(current_ids).encode()).hexdigest()[:16]
                    key = f'{year}:{end.isoformat()}:{digest}'
                    filename = f'PowerPass_{year}_{end.isoformat()}_page-{number:02d}_{digest}.pdf'
                    destination = out / filename
                    if key in manifest and valid_pdf(out / manifest[key]['file']):
                        print(f'  Page {number}: already saved')
                        continue
                    selector = page.locator('#checkbox-select')
                    await selector.uncheck()
                    await selector.check()
                    checks = page.locator('#report_table_rpttrans tbody input[type=checkbox]')
                    unchecked = await checks.evaluate_all('els => els.filter(e => !e.checked).length')
                    if unchecked:
                        raise RuntimeError('Select-all did not select every receipt on this page.')
                    print(f'  Page {number}: downloading {len(current_ids)} receipts…')
                    await download_batch(context, page, destination, args.download_timeout)
                    manifest[key] = {'file': filename, 'count': len(current_ids), 'transaction_ids': current_ids}
                    temporary = manifest_path.with_suffix('.tmp')
                    temporary.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
                    temporary.replace(manifest_path)
                    print(f'  Saved {filename}')
                if expected is not None and len(seen) != expected:
                    raise RuntimeError(f'{year}: visited {len(seen)} receipts; expected {expected}.')
                if len(seen) >= 500:
                    raise RuntimeError(f'{year}: reached the 500 limit; completeness cannot be confirmed.')
            print(f'\nComplete. PDFs and progress log: {out}')
        except Exception:
            (out / 'failure.txt').write_text(traceback.format_exc(), encoding='utf-8')
            try:
                await page.screenshot(path=str(out / 'failure.png'), full_page=True)
            except Exception:
                pass
            print('\nStopped. Completed PDFs are preserved. See failure.txt; rerun to resume.', flush=True)
            await asyncio.to_thread(input, 'Edge remains open for inspection. Press Enter to close: ')
            raise
        finally:
            await context.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start-year', type=int, required=True, help='First calendar year to search (required)')
    parser.add_argument('--end-date', type=date.fromisoformat, default=date.today())
    parser.add_argument('--output', default=str(Path(__file__).parent / 'receipts'))
    parser.add_argument('--profile', default=str(Path(__file__).parent / 'powerpass-browser-profile'))
    parser.add_argument('--download-timeout', type=int, default=180)
    args = parser.parse_args()
    if args.start_year > args.end_date.year:
        parser.error('Start year must not be later than end date.')
    asyncio.run(run(args))
