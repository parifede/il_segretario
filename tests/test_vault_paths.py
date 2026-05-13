from segretario.vault.paths import classify_vault_path


def test_raw_elaborati_is_skipped():
    policy = classify_vault_path("raw/elaborati/meeting.txt")

    assert policy.skip is True
    assert policy.local_only is True
    assert policy.export_allowed is False


def test_self_paths_are_local_only():
    policy = classify_vault_path("self/preferences.md")

    assert policy.skip is False
    assert policy.local_only is True
    assert policy.export_allowed is False


def test_output_paths_are_local_only_by_default():
    policy = classify_vault_path("output/personal_reports/summary.md")

    assert policy.skip is False
    assert policy.local_only is True
    assert policy.export_allowed is False


def test_self_profile_writes_require_explicit_update_and_confirmation():
    policy = classify_vault_path("self/profile.md", operation="write")

    assert policy.requires_explicit_profile_update is True
    assert policy.requires_confirmation is True


def test_privacy_map_is_no_export():
    policy = classify_vault_path("meta/privacy_map.local.json")

    assert policy.local_only is True
    assert policy.no_export is True
    assert policy.export_allowed is False


def test_vault_path_rejects_parent_traversal():
    try:
        classify_vault_path("knowledge/../self/profile.md")
    except ValueError as exc:
        assert "parent traversal" in str(exc)
    else:
        raise AssertionError("expected ValueError for parent traversal")
