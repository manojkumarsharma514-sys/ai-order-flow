from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QButtonGroup
from PyQt6.QtCore import pyqtSignal


TABS = ["Dashboard", "Positions", "Orders", "Analytics", "Journal", "Settings"]


class TopNav(QWidget):
    """Top tab bar (logo + tabs), replacing the old left sidebar —
    matches the reference layout's header navigation."""

    tab_clicked = pyqtSignal(str)

    def __init__(self):
        super().__init__()

        self.setFixedHeight(46)

        self.setStyleSheet("""
        QWidget{
            background:#161616;
            border-bottom:1px solid #1E222D;
        }

        QLabel#logo{
            color:#00FF88;
            font-size:15px;
            font-weight:bold;
        }

        QPushButton{
            background:transparent;
            color:#999;
            border:none;
            border-bottom:2px solid transparent;
            padding:12px 16px;
            font-size:13px;
            font-weight:600;
        }

        QPushButton:hover{
            color:white;
        }

        QPushButton:checked{
            color:#00FF88;
            border-bottom:2px solid #00FF88;
        }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(4)

        logo = QLabel("🤖 AI OrderFlow Pro")
        logo.setObjectName("logo")
        layout.addWidget(logo)

        layout.addSpacing(24)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)

        for i, name in enumerate(TABS):

            btn = QPushButton(name.upper())
            btn.setCheckable(True)

            btn.clicked.connect(lambda checked, n=name: self.tab_clicked.emit(n))

            self.group.addButton(btn, i)
            layout.addWidget(btn)

            if i == 0:
                btn.setChecked(True)

        layout.addStretch()
