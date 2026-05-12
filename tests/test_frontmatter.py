from segretario.vault.frontmatter import parse_frontmatter, render_frontmatter


def test_parse_frontmatter_returns_metadata_and_body():
    text = """---
title: Meeting Notes
tags:
  - ai
  - wiki
---
# Notes
Body text.
"""

    metadata, body = parse_frontmatter(text)

    assert metadata == {"title": "Meeting Notes", "tags": ["ai", "wiki"]}
    assert body == "# Notes\nBody text.\n"


def test_parse_frontmatter_without_header_returns_empty_metadata():
    metadata, body = parse_frontmatter("# Plain Note\n")

    assert metadata == {}
    assert body == "# Plain Note\n"


def test_render_frontmatter_round_trips_yaml_header():
    rendered = render_frontmatter(
        {"title": "Knowledge", "tags": ["vault"]},
        "# Knowledge\n",
    )

    assert rendered.startswith("---\n")
    assert "title: Knowledge\n" in rendered
    assert "tags:\n- vault\n" in rendered
    assert rendered.endswith("---\n# Knowledge\n")
