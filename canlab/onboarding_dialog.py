"""First-run onboarding dialog (P2.1).

Shown automatically once on first launch; can be reopened anytime from
the View menu. Four steps: load → frames → AI → DBC.
"""
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
)

from core.i18n import tr
from theme import mono_font


_ONBOARDING_KEY = "onboarding_shown"


def should_show_onboarding() -> bool:
    return not QSettings("CAN-Space", "CAN-Space").value(
        _ONBOARDING_KEY, False, type=bool)


def mark_onboarding_shown() -> None:
    QSettings("CAN-Space", "CAN-Space").setValue(_ONBOARDING_KEY, True)


class OnboardingDialog(QDialog):
    STEPS = (
        ("onboarding.step1_title", "onboarding.step1_body"),
        ("onboarding.step2_title", "onboarding.step2_body"),
        ("onboarding.step3_title", "onboarding.step3_body"),
        ("onboarding.step4_title", "onboarding.step4_body"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("onboarding.title"))
        self.setModal(True)
        self.setMinimumWidth(460)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)

        title = QLabel(tr("onboarding.heading"))
        title.setFont(mono_font(12, bold=True))
        lay.addWidget(title)

        for idx, (key_title, key_body) in enumerate(self.STEPS, start=1):
            step_title = QLabel(f"{idx}. {tr(key_title)}")
            step_title.setFont(mono_font(9, bold=True))
            lay.addWidget(step_title)
            step_body = QLabel(tr(key_body))
            step_body.setFont(mono_font(8))
            step_body.setObjectName("label_dim")
            step_body.setWordWrap(True)
            step_body.setIndent(14)
            lay.addWidget(step_body)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_start = QPushButton(tr("onboarding.start"))
        btn_start.setObjectName("btn_green")
        btn_start.setDefault(True)
        btn_start.clicked.connect(self.accept)
        btn_row.addWidget(btn_start)
        lay.addLayout(btn_row)


def show_onboarding(parent=None) -> None:
    """Open the dialog unconditionally (View menu entry)."""
    OnboardingDialog(parent).exec()


def maybe_show_onboarding(parent=None) -> bool:
    """Auto-show once on first launch. Returns True if shown."""
    if not should_show_onboarding():
        return False
    OnboardingDialog(parent).exec()
    mark_onboarding_shown()
    return True
