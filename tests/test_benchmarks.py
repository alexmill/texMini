from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from benchmarks import benchmark


class BenchmarkFixtureTest(unittest.TestCase):
    def test_directory_size_counts_hard_links_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.write_bytes(b"x" * 8192)
            os.link(source, root / "linked")

            self.assertEqual(benchmark.directory_size(root), 8192)
            self.assertEqual(benchmark.directory_size(root, allocated=True), source.stat().st_blocks * 512)

    def test_random_package_fixture_is_seeded_and_unique(self) -> None:
        first = benchmark.random_package_selection()
        second = benchmark.random_package_selection()

        self.assertEqual(first, second)
        self.assertEqual(len(first), 10)
        self.assertEqual(len(set(first)), 10)

    def test_bibliography_fixture_has_seeded_overdispersed_length(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            benchmark.write_fixture("bibliography", destination)
            bibliography = (destination / "references.bib").read_text(encoding="utf-8")
            source = (destination / "bibliography.tex").read_text(encoding="utf-8")
            count = benchmark.bibliography_entry_count()

        self.assertGreaterEqual(count, 8)
        self.assertEqual(bibliography.count("@article{"), count)
        self.assertEqual(source.count("\\cite{"), count)

    def test_common_and_random_package_fixtures_are_separate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            common = destination / "common"
            random_packages = destination / "random"
            benchmark.write_fixture("common", common)
            benchmark.write_fixture("random-packages", random_packages)

            common_source = (common / "common.tex").read_text(encoding="utf-8")
            random_source = (random_packages / "random-packages.tex").read_text(encoding="utf-8")

        self.assertIn("Common packages", common_source)
        self.assertIn(",".join(benchmark.random_package_selection()), random_source)


if __name__ == "__main__":
    unittest.main()
