"""
translator/text_engine.py

Wraps argostranslate for offline Korean → English translation.

Model lifecycle
---------------
1. Check if ko→en model is already installed in argostranslate's local store.
   If yes → load it, no network needed.
2. If not installed, check for a cached .argosmodel file in the standard
   argostranslate data directory (left over from a previous download).
   If found → install from file, no network needed.
3. If nothing is cached locally → download from the argostranslate registry
   (requires internet, one-time only).  Raises a clear error if offline.

Once you have successfully run the tool with internet once,
all future runs are 100% offline.
"""

import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Cache so we only initialise once per process
_engine_instance: Optional["TextEngine"] = None


class TextEngine:
    FROM_CODE = "ko"
    TO_CODE = "en"

    def __init__(self) -> None:
        self._translation = self._load_or_install()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_or_install(self):
        """Return an argostranslate ITranslation object, installing if needed."""
        import argostranslate.translate as at_translate

        # Step 1 — already installed in local registry?
        translation = self._find_installed(at_translate)
        if translation:
            log.info("ko→en model already installed — running fully offline.")
            return translation

        # Step 2 — cached .argosmodel file on disk from a previous download?
        cached_path = self._find_cached_model_file()
        if cached_path:
            log.info(f"Found cached model file: {cached_path}")
            log.info("Installing from local file (no network needed) ...")
            self._install_from_file(cached_path)
            translation = self._find_installed(at_translate)
            if translation:
                log.info("Model installed from cache. All future runs are fully offline.")
                return translation
            log.warning("Installing from cached file did not register the model; will try download.")

        # Step 3 — download (needs internet, one-time only)
        log.info(
            "ko→en translation model not found locally. "
            "Downloading from argostranslate registry (one-time only) ..."
        )
        try:
            self._download_and_install()
        except Exception as exc:
            raise RuntimeError(
                "Could not download the ko→en model.\n"
                "  → Make sure you are connected to the internet for the FIRST run.\n"
                "  → After a successful download, all future runs work offline.\n"
                f"  → Original error: {exc}"
            ) from exc

        translation = self._find_installed(at_translate)
        if translation is None:
            raise RuntimeError(
                "Failed to load ko→en translation model even after installation. "
                "Try running again with internet enabled."
            )
        log.info("Model downloaded and installed. All future runs are fully offline.")
        return translation

    def _find_installed(self, at_translate) -> Optional[object]:
        """
        Use get_translation_from_codes() — the stable public API in
        argostranslate >= 1.x.  The older Language.translations attribute
        was removed in newer releases.
        """
        try:
            translation = at_translate.get_translation_from_codes(
                self.FROM_CODE, self.TO_CODE
            )
            return translation  # returns None if not installed
        except Exception as exc:
            log.debug(f"get_translation_from_codes failed ({exc}), falling back.")

        # Fallback: walk installed languages (older argostranslate < 1.9)
        try:
            installed = at_translate.get_installed_languages()
            from_lang = next(
                (l for l in installed if l.code == self.FROM_CODE), None
            )
            if from_lang is None:
                return None
            translations = getattr(from_lang, "translations", None)
            if translations is None:
                return None
            return next(
                (t for t in translations if t.to_lang.code == self.TO_CODE),
                None,
            )
        except Exception as exc:
            log.debug(f"Fallback language walk also failed: {exc}")
            return None

    def _find_cached_model_file(self) -> Optional[Path]:
        """
        Look for a previously downloaded .argosmodel file in argostranslate's
        data directory.  These are left on disk after a download, so if the
        user ran with internet once, we can reinstall from the file offline.
        """
        try:
            import argostranslate.settings as at_settings
            data_dir = Path(at_settings.data_dir)
        except Exception:
            # Fallback locations used by argostranslate on Windows / Linux
            data_dir = Path(os.environ.get("APPDATA", str(Path.home()))) / "argos-translate"

        # Search common subdirectories
        search_dirs = [
            data_dir,
            data_dir / "packages",
            data_dir / "downloads",
        ]
        pattern = f"*{self.FROM_CODE}*{self.TO_CODE}*.argosmodel"
        for d in search_dirs:
            if d.is_dir():
                matches = list(d.glob(pattern))
                if matches:
                    return matches[0]
        return None

    def _install_from_file(self, model_path: Path) -> None:
        """Install a .argosmodel package from a local file path."""
        import argostranslate.package as at_pkg
        at_pkg.install_from_path(str(model_path))

    def _download_and_install(self) -> None:
        """Download the ko→en package from the argostranslate online registry."""
        import argostranslate.package as at_pkg

        at_pkg.update_package_index()
        available = at_pkg.get_available_packages()
        pkg = next(
            (
                p
                for p in available
                if p.from_code == self.FROM_CODE and p.to_code == self.TO_CODE
            ),
            None,
        )
        if pkg is None:
            raise RuntimeError(
                f"No argostranslate package found for {self.FROM_CODE}→{self.TO_CODE}. "
                "Check https://argos-translate.readthedocs.io for available language pairs."
            )
        pkg.install()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def translate(self, text: str) -> str:
        """
        Translate *text* from Korean to English.
        Returns the original text unchanged on empty input or translation failure.
        """
        if not text or not text.strip():
            return text
        try:
            result: str = self._translation.translate(text.strip())
            return result
        except Exception as exc:  # noqa: BLE001
            log.warning(f"Translation error for {text[:40]!r}: {exc}")
            return text

    def translate_lines(self, lines: list[str]) -> list[str]:
        """Translate a list of text lines, preserving order and empty strings."""
        return [self.translate(line) if line.strip() else line for line in lines]


def get_engine() -> "TextEngine":
    """Module-level singleton so the model is only loaded once."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = TextEngine()
    return _engine_instance


if __name__ == "__main__":
    # Quick smoke-test: python -m translator.text_engine
    logging.basicConfig(level=logging.INFO)
    eng = TextEngine()
    samples = [
        "안녕하세요",
        "데이터 흐름도",
        "시스템 아키텍처 개요",
        "입력 데이터 처리 모듈",
    ]
    print("=== Translation smoke-test ===")
    for s in samples:
        print(f"  [{s}] → [{eng.translate(s)}]")
