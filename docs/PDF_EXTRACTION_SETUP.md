# PDF Extraction Setup Guide

## Overview

ARISP uses [marker-pdf](https://github.com/VikParuchuri/marker) to convert research PDFs to Markdown while preserving code syntax and mathematical equations.

## Requirements

- **Python 3.10+** (marker-pdf uses modern type hints)
- ~2GB disk space for ML models (one-time download)
- 8GB+ RAM recommended for processing large PDFs

## Installation

### 1. Upgrade to Python 3.10+ (if needed)

```bash
# Check current Python version
python --version

# If < 3.10, run the migration script
./scripts/migrate_to_python310.sh
```

### 2. Install marker-pdf

marker-pdf is included in `requirements.txt`:

```bash
pip install -r requirements.txt
```

## First Run Behavior

**On first use, marker-pdf will download ~1.7GB of ML models:**

- Layout detection model (~1.35GB)
- Text recognition model (~1.34GB)
- Table recognition model (~201MB)
- OCR error detection model (~258MB)
- Text detection model (~73MB)

**This is a one-time download** - models are cached in:
```
~/Library/Caches/datalab/models/
```

**First run may timeout** - The 5-minute default timeout may not be enough for model downloads. The system will gracefully fall back to abstract-only extraction.

**Subsequent runs are faster** - Once models are cached, PDF conversion takes ~5-10 seconds per page.

## Known Limitations

### 1. macOS Apple Silicon Compatibility

marker-pdf may crash on certain PDFs when using Apple Silicon GPUs:

```
torch.AcceleratorError: index ... is out of bounds
```

**Workaround:** The system automatically falls back to abstract-only extraction when PDF conversion fails. This is graceful degradation, not a failure.

### 2. PDF Conversion Timeout

Large PDFs (40+ pages) may timeout during conversion (default 300s). The system handles this gracefully:

```json
{"event": "pdf_conversion_timeout", "level": "error"}
{"event": "pdf_pipeline_failed_fallback_to_abstract", "level": "warning"}
```

## Testing

### Quick Test (Abstract-Only Mode)

Without marker-pdf or for quick testing:

```bash
python -m src.cli run --config config/phase2_e2e_test.yaml
```

Result: Papers processed with abstract text only (no PDF content).

### Full PDF Extraction Test

After installing marker-pdf:

```bash
python -m src.cli run --config config/test_pdf_extraction.yaml
```

Expected on first run:
1. Model downloads (~3-5 minutes)
2. PDF download success
3. Possible timeout on model download
4. Fallback to abstract

Expected on subsequent runs:
1. Fast PDF download
2. Fast PDF conversion (models cached)
3. Successful extraction with full PDF content

## Troubleshooting

### "marker_single: command not found"

marker-pdf not installed or not in PATH:

```bash
# Reinstall marker-pdf
pip install --upgrade marker-pdf

# Verify installation
marker_single --help
```

### "No such option: --batch_multiplier"

Outdated code - this was fixed in commit fixing marker-pdf API compatibility.

### Models re-downloading every time

Check cache directory permissions:

```bash
ls -la ~/Library/Caches/datalab/models/
```

Models should persist across runs.

### PDF conversion always failing

This is expected behavior for:
- Very large PDFs (50+ pages)
- PDFs with complex layouts
- Certain PDF formats on Apple Silicon

The system gracefully degrades to abstract-only mode.

## Configuration

Adjust PDF settings in your config file:

```yaml
settings:
  pdf_settings:
    temp_dir: "./temp_pdf"
    keep_pdfs: false  # Set true to inspect downloaded PDFs
    max_file_size_mb: 50  # Reject PDFs larger than this
    timeout_seconds: 300  # Increase for large PDFs
```

## Performance Expectations

| Metric | Value |
|--------|-------|
| Model download (first run) | ~3-5 minutes |
| PDF download (per paper) | ~1-2 seconds |
| PDF conversion (per page) | ~5-10 seconds |
| Memory usage (peak) | ~4-6 GB |
| Disk space (models) | ~1.7 GB |

## Production Recommendations

1. **Pre-download models** before deploying to production
2. **Increase timeout** for large PDF batches (600s+)
3. **Monitor failures** - some PDFs will always fail (by design)
4. **Accept degradation** - abstract-only mode is acceptable fallback
5. **Consider alternatives** for critical PDF extraction needs

## Alternative PDF Extractors

If marker-pdf issues persist, consider:

- [PyMuPDF](https://pymupdf.readthedocs.io/) - Faster but less accurate
- [Camelot](https://camelot-py.readthedocs.io/) - Better for tables
- [Nougat](https://github.com/facebookresearch/nougat) - Academic papers (slow)
- Cloud APIs - Google Document AI, AWS Textract

## Support

For marker-pdf specific issues:
- GitHub: https://github.com/VikParuchuri/marker/issues
- Check system compatibility before reporting bugs

For ARISP issues:
- Check logs: `./output/<topic>/` directory
- Verify graceful degradation working
- Report if abstract fallback fails
