"""Check bilingual figure and table caption validation."""

import unittest

from translate.validate_md import check_caption_bilingual


class BilingualCaptionTests(unittest.TestCase):
    def test_accepts_inline_and_separate_caption_translations(self):
        examples = [
            "Figure 1. Architecture / 图 1：架构",
            "Figure 1. Architecture\n\n图 1：架构",
            "> Figure 2: Architecture\n>\n> 图 2：架构",
            "Table III: Results\n\n表 III：结果",
            "Fig. 3 : Results\n\n**图 3：结果**",
            "```text\nFigure 4. Example source caption\n```",
        ]
        for example in examples:
            with self.subTest(example=example):
                self.assertEqual(check_caption_bilingual(example.splitlines()), [])

    def test_rejects_missing_or_unrelated_caption_translations(self):
        examples = [
            "Figure 1. Architecture",
            "Figure 1. Architecture\n\n图 2：另一张图",
            "Figure 1. Architecture\n\n表 1：另一张表",
            "Figure 1. Architecture\n\nUnrelated paragraph.\n\n图 1：架构",
            "Table III: Results\n\n表 IV：其他结果",
        ]
        for example in examples:
            with self.subTest(example=example):
                self.assertTrue(check_caption_bilingual(example.splitlines()))


if __name__ == "__main__":
    unittest.main()
