"""Check automatic TOC language separation and rendered spacing."""

import unittest

import markdown

from md_to_pdf.convert import CSS, WeasyHTML, _toc_with_heading_breaks


class BilingualTocTests(unittest.TestCase):
    def test_preserves_language_breaks_in_nested_entries(self):
        source = (
            "# A long English title <br><br> 一个较长的中文标题\n\n"
            "## Short / 简短\n\n"
            "### Another long title <br> 另一个较长的标题\n"
        )
        md = markdown.Markdown(extensions=["toc"])
        md.convert(source)
        toc = _toc_with_heading_breaks(md.toc, md.toc_tokens)
        self.assertIn("A long English title <br> 一个较长的中文标题", toc)
        self.assertIn("Another long title <br> 另一个较长的标题", toc)
        self.assertIn("Short / 简短", toc)
        self.assertEqual(toc.count("<li>"), 3)
        self.assertEqual(toc.count('<a href="#'), 3)

    def test_toc_language_spacing_matches_a_single_line_break(self):
        def render_lines(toc):
            document = WeasyHTML(
                string=f'<style>{CSS}</style><div class="toc">{toc}</div>'
            ).render()
            self.assertEqual(len(document.pages), 1)
            return [
                box.position_y
                for box in document.pages[0]._page_box.descendants()
                if type(box).__name__ == "LineBox" and box.element_tag == "li"
            ]

        reference = render_lines("<ul><li><a>English<br>中文</a></li></ul>")
        self.assertEqual(len(reference), 2)
        for separator in ["<br>", "<br><br>", "<br /> <BR/> <br>"]:
            with self.subTest(separator=separator):
                md = markdown.Markdown(extensions=["toc"])
                body = md.convert(f"# English{separator}中文")
                toc = _toc_with_heading_breaks(md.toc, md.toc_tokens)
                lines = render_lines(toc)
                self.assertEqual(len(lines), 2)
                self.assertAlmostEqual(
                    lines[1] - lines[0], reference[1] - reference[0], places=4
                )
                self.assertIn(separator, body)

    def test_retains_explicit_toc_labels_and_plain_documents(self):
        md = markdown.Markdown(extensions=["toc", "attr_list"])
        md.convert(
            "## English <br> 中文 {: data-toc-label='Custom label'}\n\n"
            "## Plain heading\n"
        )
        self.assertEqual(_toc_with_heading_breaks(md.toc, md.toc_tokens), md.toc)
        self.assertIn("Custom label", md.toc)


if __name__ == "__main__":
    unittest.main()
