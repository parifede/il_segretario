from segretario.vault.wikilinks import extract_wikilink_targets


def test_extracts_plain_wikilink_targets():
    text = "Link [[Project Alpha]] and [[People/Ada Lovelace]]."

    assert extract_wikilink_targets(text) == ["Project Alpha", "People/Ada Lovelace"]


def test_extracts_target_from_aliased_wikilinks():
    text = "See [[Project Alpha|the project]] and [[Notes/Index|index]]."

    assert extract_wikilink_targets(text) == ["Project Alpha", "Notes/Index"]


def test_ignores_empty_wikilinks():
    text = "Empty [[]] and alias-only [[|Alias]] are ignored."

    assert extract_wikilink_targets(text) == []
