# PowerPass Receipt Tools

Two Python scripts for downloading Bunnings PowerPass receipts and converting them to Markdown:

| Script | Purpose |
| --- | --- |
| `powerpass_receipts.py` | Downloads receipt batches as PDFs from the Australian PowerPass portal. |
| `powerpass_pdf_to_md.py` | Converts each downloaded PDF into a matching Markdown file. |

Both scripts run locally without GPT, an OpenAI API key, or a paid service. The downloader connects to PowerPass through a visible browser; the converter runs offline.

## Requirements

- Windows with Microsoft Edge installed. The downloader has been tested on this setup.
- Python 3.10 or later. Development and live use included Python 3.12.
- A PowerPass login with access to the account's transactions.
- Internet access for dependency installation and receipt downloads.

Python dependencies:

| Package | Used by | Purpose |
| --- | --- | --- |
| `playwright` | Downloader | Controls Edge, reads results pages, and captures authenticated PDF responses. |
| `pypdf>=5,<7` | Converter | Extracts embedded text from receipt PDFs. |

Everything else used by the scripts is part of Python's standard library. OCR software is not included or required for PowerPass PDFs with embedded text.

## Installation

Place both scripts and this README in the same folder. Open PowerShell in that folder and install the dependencies:

```powershell
py -m pip install playwright "pypdf>=5,<7"
```

The downloader uses the installed Microsoft Edge browser through Playwright's `msedge` channel. It does not use the bundled Chromium browser, so `playwright install chromium` is unnecessary for this setup.

For an isolated Python environment, you can instead use:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install playwright "pypdf>=5,<7"
```

With this approach, replace `py` in the commands below with `.\.venv\Scripts\python.exe`.

## Download receipts

```powershell
py powerpass_receipts.py --start-year 2022
```

1. The script opens a visible Edge window at the PowerPass login page.
2. Log in normally, including any authentication steps requested by PowerPass.
3. Open **Transactions** and choose the intended account.
4. Return to PowerShell and press **Enter** when the script asks.
5. Leave the script's browser window open while it downloads.

The script uses a separate persistent browser profile in `powerpass-browser-profile/`. It does not attach to your everyday Edge window. Later runs can reuse the saved login while the session remains valid. You still need to open Transactions and press Enter on each run.

### What the downloader does

- Searches each calendar year, starting with the required `--start-year` argument and ending on today's local computer date.
- Searches the selected account across **all cards**, including return transactions.
- Uses PowerPass's **Select Pagination** dropdown to visit every results page.
- Waits for the transaction IDs to change after switching pages and stops if a page repeats or is unexpectedly empty.
- Selects all receipts on the current results page and clicks **Print Selected**.
- Saves one combined PDF per results page, rather than one file per individual receipt.
- Checks the PDF header and file size before recording a completed batch.
- Compares the number of visited transactions with the reported total when available.

During printing, it forwards the authenticated browser request and saves the returned PDF bytes before Edge creates a popup-owned temporary download. This handles the report popup closing during delivery and avoids repeated Save As dialogs. Non-PDF responses pass through normally.

The script assumes **fewer than 500 transactions per calendar year**. PowerPass caps search results at 500; the script stops if it reaches that limit because completeness cannot be confirmed. It does not automatically split a year into smaller date ranges.

### Downloader options

| Option | Default | Description |
| --- | --- | --- |
| `--start-year` | Required | First calendar year to search; there is no default. |
| `--end-date` | Today's local computer date | Inclusive cutoff, in `YYYY-MM-DD` format. |
| `--output` | `receipts/` beside the script | Folder for PDFs, progress, and diagnostic files. |
| `--profile` | `powerpass-browser-profile/` beside the script | Dedicated Edge profile folder. |
| `--download-timeout` | `180` | Maximum wait for a PDF response, in seconds. Other UI actions have separate timeouts. |

Examples:

```powershell
# Download a specific period.
py powerpass_receipts.py --start-year 2022 --end-date 2025-12-31

# Save to another folder.
py powerpass_receipts.py --start-year 2022 --output "D:\Bunnings Receipts"

# Allow more time for report generation.
py powerpass_receipts.py --start-year 2022 --download-timeout 300
```

### Resume an interrupted download

Rerun the same command. The script reads `progress.json`, revisits the result pages, and skips recorded batches whose PDFs still pass its basic validation. Keep the progress file with the PDFs.

To avoid revisiting earlier years, start at the year where it stopped:

```powershell
py powerpass_receipts.py --start-year 2024
```

Completed pages within that year are still skipped. Changing the cutoff date or the transactions returned by the portal can create new batches; older PDFs are retained.

**Use a separate output folder for each PowerPass account.** The progress keys identify date ranges and transaction batches; they do not include an account identifier.

## Convert PDFs to Markdown

After downloading, run:

```powershell
py powerpass_pdf_to_md.py
```

The converter scans the `receipts/` folder beside the script and creates a `.md` file next to every completed PDF, using the same base filename. It does not scan subfolders or browser staging files and excludes `.partial.pdf` downloads.

Each Markdown file contains:

- A link to its source PDF.
- A heading for each PDF page, with separators between pages.
- Extracted text in fenced blocks to retain item, quantity, and price column spacing.
- A source hash used to recognize an unchanged PDF on subsequent runs.

This is a text extraction tool. It does not reproduce logos or images, perform OCR, interpret purchases, or transform receipt items into structured Markdown tables. A receipt spanning multiple PDF pages retains multiple page sections.

### Converter options

| Option | Default | Description |
| --- | --- | --- |
| `--folder` | `receipts/` beside the script | Folder containing PDFs to convert. Markdown files are written into the same folder. |
| `--overwrite` | Off | Replace existing Markdown files, including those whose source PDF changed. |

```powershell
# Convert PDFs saved to a custom folder.
py powerpass_pdf_to_md.py --folder "D:\Bunnings Receipts"

# Regenerate all Markdown files.
py powerpass_pdf_to_md.py --overwrite
```

Reruns skip matching conversions. If an existing Markdown file does not match the source hash, conversion fails for that file unless `--overwrite` is supplied. Files with password protection or pages without extractable text are reported as failures. Other files continue converting.

The converter writes `markdown_conversion_report.json` with counts and individual failures. It exits with code `0` when all files succeed or are skipped, `1` when any conversion fails, and `2` for invalid command-line arguments or missing input folders/files.

## Output files

Typical folder structure:

```text
README.md
powerpass_receipts.py
powerpass_pdf_to_md.py
powerpass-browser-profile/
receipts/
  PowerPass_2024_2024-12-31_page-01_<batch-hash>.pdf
  PowerPass_2024_2024-12-31_page-01_<batch-hash>.md
  progress.json
  markdown_conversion_report.json
  failure.txt                     # Created after a downloader failure
  failure.png                     # Captured after failure, when possible
  _browser_downloads/             # Browser staging directory
```

The page number in a PDF filename identifies a **PowerPass results page**, not a physical PDF page. The batch hash identifies the transaction IDs returned on that results page.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `No module named playwright` or missing `pypdf` | Install the dependencies using the same Python interpreter you use to run the scripts. |
| Edge does not launch | Check that Microsoft Edge is installed and that another script run is not using the same profile folder. |
| Login expired or Transactions cannot be found | Close the failed run, rerun, log in, and open Transactions before pressing Enter. |
| Download stops or times out | Read `receipts/failure.txt`. If report generation is slow, increase `--download-timeout` and rerun. |
| Script is waiting after an error | Edge remains open for inspection. Press Enter in PowerShell to close it before starting another run. |
| Repeated pages, missing controls, or unexpected empty results | The portal may have changed. The script stops to avoid silently missing receipts; inspect the error and screenshot. |
| A year reaches 500 transactions | Use a modified downloader supporting smaller ranges or download that year manually; this version cannot confirm completeness at the cap. |
| Markdown conversion reports no extractable text | The PDF may be scanned or image-only and requires a separate OCR workflow. |
| Markdown exists but source changed | Review the existing file, then use `--overwrite` if replacement is intended. |

PDF validation checks the header and minimum size; it does not prove that every receipt rendered correctly. Review the downloaded files for your own records. A later successful run does not remove an older `failure.txt` or `failure.png`.

## Publishing this repository

Commit the scripts and documentation. Keep generated receipts, Markdown, logs, screenshots, and browser profiles out of Git: they can contain account information, purchase details, and saved login sessions.

Suggested `.gitignore` entries for the default folder layout:

```gitignore
receipts/
powerpass-browser-profile/
.venv/
__pycache__/
*.py[cod]
```

If you choose custom output or profile folders inside the repository, add those paths too. Keep browser profile contents private. Git ignore rules do not remove files already committed.

## Scope

These are independent tools for the Australian Bunnings PowerPass portal and are not affiliated with Bunnings. They use your normal authenticated access and require manual login. Changes to the portal's controls, pagination, or PDF delivery may require script updates.
#   b u n n i n g s - p o w e r p a s s - r e c e i p t s  
 