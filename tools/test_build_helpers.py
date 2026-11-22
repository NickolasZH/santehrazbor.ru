import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build  # noqa: E402


class YearPlaceholder(unittest.TestCase):
    def test_year_from_updated(self):
        meta = {"date": date(2025, 3, 1), "updated": date(2026, 11, 2)}
        self.assertEqual(build.apply_year_placeholder("Модели {{year}}", meta), "Модели 2026")

    def test_year_from_date_when_no_updated(self):
        meta = {"date": "2025-03-01"}
        self.assertEqual(build.apply_year_placeholder("в {{year}} году", meta), "в 2025 году")

    def test_fields_in_apply_placeholders(self):
        meta = {"date": date(2026, 1, 1), "title": "T {{year}}", "seo_title": "S {{year}}",
                "description": "D {{year}}", "seo_description": "SD {{year}}"}
        build.apply_placeholders("текст", meta, "x.md", {})
        self.assertEqual([meta[k] for k in ("title", "seo_title", "description", "seo_description")],
                         ["T 2026", "S 2026", "D 2026", "SD 2026"])


class Korotko(unittest.TestCase):
    def test_two_sentences_clean(self):
        body = ("Текст.\n\n> **Коротко, если некогда читать.** Берите **латунь** и [картридж](/x/). "
                "Второе предложение. Третье не нужно.\n\nДальше.")
        self.assertEqual(build.extract_korotko(body), "Берите латунь и картридж. Второе предложение.")

    def test_no_block(self):
        self.assertEqual(build.extract_korotko("просто текст"), "")

    def test_limit(self):
        body = "> **Коротко.** " + "Слово " * 30 + "конец. Ещё " + "слово " * 40 + "конец."
        self.assertLessEqual(len(build.extract_korotko(body)), 300)


if __name__ == "__main__":
    unittest.main()
