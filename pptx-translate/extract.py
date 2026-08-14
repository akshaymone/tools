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

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="extract.py",
        description="Extract text from PPTX to Markdown (Offline)",
    )
    parser.add_argument("-i", "--input", required=True, metavar="PATH",
                        help="Input .pptx file or folder containing .pptx files")
    parser.add_argument("-o", "--output", default="./extracted", metavar="PATH",
                        help="Output folder or .md file (default: ./extracted)")
    parser.add_argument("--skip-images", action="store_true",
                        help="Skip OCR of embedded images")
    parser.add_argument("--confidence", type=int, default=60, metavar="0-100",
                        help="Minimum Tesseract OCR confidence")
    parser.add_argument("--min-text-height", type=int, default=18, metavar="PX",
                        help="Min pixel height of OCR text block")
    parser.add_argument("--lang", default="kor", metavar="LANG",
                        help="Tesseract OCR language code (default: kor)")
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

    from translator.pptx_handler import PPTXHandler
    handler = PPTXHandler(
        skip_images=args.skip_images,
        confidence=args.confidence,
        ocr_lang=args.lang,
        min_text_height=args.min_text_height,
    )

    failed = []
    for pptx_file in tqdm(pptx_files, desc="Extracting", unit="file"):
        if input_path.is_file() and output_path.suffix.lower() == ".md":
            out_file = output_path
        elif input_path.is_file():
            out_file = output_path / (pptx_file.stem + ".md")
        else:
            rel = pptx_file.relative_to(input_path)
            out_file = output_path / rel.with_suffix(".md")
            
        out_file.parent.mkdir(parents=True, exist_ok=True)
        log.info(f"-> {pptx_file.name}")
        try:
            handler.extract_file(pptx_file, out_file)
            log.info(f"   Saved: {out_file}")
        except Exception as exc:
            log.error(f"   FAILED [{pptx_file.name}]: {exc}", exc_info=args.verbose)
            failed.append(pptx_file)

    success = len(pptx_files) - len(failed)
    log.info(f"\nDone. {success}/{len(pptx_files)} file(s) extracted successfully.")
    if failed:
        sys.exit(1)

if __name__ == "__main__":
    main()
