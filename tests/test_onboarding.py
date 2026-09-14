"""Tests for P2.1 first-run onboarding dialog."""
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QSettings


def _clean_key():
    qs = QSettings("CAN-Space", "CAN-Space")
    original = qs.value("onboarding_shown", None)
    qs.remove("onboarding_shown")
    return qs, original


def _restore_key(qs, original):
    if original is None:
        qs.remove("onboarding_shown")
    else:
        qs.setValue("onboarding_shown", original)


def test_first_run_flag_roundtrip():
    from canlab.onboarding_dialog import (
        should_show_onboarding, mark_onboarding_shown,
    )
    qs, original = _clean_key()
    try:
        assert should_show_onboarding() is True
        mark_onboarding_shown()
        assert should_show_onboarding() is False
    finally:
        _restore_key(qs, original)


def test_onboarding_dialog_builds_with_four_steps(qtbot):
    from canlab.onboarding_dialog import OnboardingDialog
    dlg = OnboardingDialog()
    qtbot.add_widget(dlg)
    assert len(OnboardingDialog.STEPS) == 4
    assert dlg.windowTitle() != ""


def test_onboarding_step_keys_exist_in_both_languages():
    from canlab.core.i18n import _ZH, _EN
    from canlab.onboarding_dialog import OnboardingDialog
    for key_title, key_body in OnboardingDialog.STEPS:
        assert key_title in _ZH and key_title in _EN, key_title
        assert key_body in _ZH and key_body in _EN, key_body
        assert _ZH[key_title] and _EN[key_title]
        assert _ZH[key_body] and _EN[key_body]
