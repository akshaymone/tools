"""
pptx-translate — Offline Korean → English PowerPoint Translator
Usage: python translate.py -i <file_or_folder> -o <output>
"""

import argparse
import logging
import sys
from pathlib import Path

from tqdm import tqdm


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        level=level,
    )


def collect_pptx_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() != ".pptx":
            raise ValueError(f"Not a .pptx file: {input_path}")
        return [input_path]
    if input_path.is_dir():
        files = sorted(input_path.rglob("*.pptx"))
        if not files:
            raise ValueError(f"No .pptx files found under: {input_path}")
        return files
    raise ValueError(f"Path does not exist: {input_path}")


def resolve_output(input_path: Path, pptx_file: Path, output_path: Path) -> Path:
    """Compute the destination path for a given source file."""
    if input_path.is_file():
        if output_path.suffix.lower() == ".pptx":
            return output_path
        return output_path / pptx_file.name
    rel = pptx_file.relative_to(input_path)
    return output_path / rel


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="translate.py",
        description="Offline Korean → English PPTX translator (Tesseract + Argostranslate)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python translate.py -i report.pptx -o report_en.pptx
  python translate.py -i ./docs/ -o ./translated/
  python translate.py -i slides.pptx --dry-run
  python translate.py -i slides.pptx --skip-images --verbose
  python translate.py -i ./docs/ --confidence 70 --verbose
        """,
    )
    parser.add_argument("-i", "--input", required=True, metavar="PATH",
                        help="Input .pptx file or folder containing .pptx files")
    parser.add_argument("-o", "--output", default="./translated", metavar="PATH",
                        help="Output file or folder (default: ./translated)")
    parser.add_argument("--skip-images", action="store_true",
                        help="Skip OCR + translation of embedded images")
    parser.add_argument("--confidence", type=int, default=60, metavar="0-100",
                        help="Minimum Tesseract OCR confidence to accept a word (default: 60)")
    parser.add_argument("--lang", default="kor", metavar="LANG",
                        help="Tesseract OCR language code (default: kor). "
                             "Use 'kor+eng' if slides mix both languages.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be translated without writing any files")
    parser.add_argument("--verbose", action="store_true",
                        help="Enable debug-level logging")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    setup_logging(args.verbose)
    log = logging.getLogger(__name__)

    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()

    try:
        pptx_files = collect_pptx_files(input_path)
    except ValueError as exc:
        log.error(str(exc))
        sys.exit(1)

    log.info(f"Found {len(pptx_files)} file(s) to process.")
    if args.dry_run:
        log.info("DRY RUN — no files will be written.")

    log.info("Loading translation engine (ko → en) ...")
    try:
        from translator.text_engine import TextEngine
        engine = TextEngine()
    except Exception as exc:
        log.error(f"Translation engine failed to load: {exc}")
        log.error("Ensure you have internet access for the first model download.")
        sys.exit(1)

    from translator.pptx_handler import PPTXHandler
    handler = PPTXHandler(
        engine=engine,
        skip_images=args.skip_images,
        confidence=args.confidence,
        ocr_lang=args.lang,
        dry_run=args.dry_run,
    )

    failed = []
    for pptx_file in tqdm(pptx_files, desc="Translating", unit="file"):
        out_file = resolve_output(input_path, pptx_file, output_path)
        log.info(f"-> {pptx_file.name}")
        try:
            handler.translate_file(pptx_file, out_file)
            if not args.dry_run:
                log.info(f"   Saved: {out_file}")
        except Exception as exc:
            log.error(f"   FAILED [{pptx_file.name}]: {exc}", exc_info=args.verbose)
            failed.append(pptx_file)

    success = len(pptx_files) - len(failed)
    log.info(f"\nDone. {success}/{len(pptx_files)} file(s) translated successfully.")
    if failed:
        log.warning("Failed files:")
        for f in failed:
            log.warning(f"  {f}")
        sys.exit(1)


if __name__ == "__main__":
    main()
