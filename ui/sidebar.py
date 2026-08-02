from PyQt6.QtWidgets import QWidget
from PyQt6.QtWidgets import QListWidget
from PyQt6.QtWidgets import QVBoxLayout
from PyQt6.QtWidgets import QLabel


class Sidebar(QWidget):

    def __init__(self):
        super().__init__()

        self.setFixedWidth(220)

        self.setStyleSheet("""
        QWidget{
            background:#181818;
            border-right:1px solid #333;
        }

        QLabel{
            color:#00FF88;
            font-size:18px;
            font-weight:bold;
            padding:15px;
        }

        QListWidget{
            background:#181818;
            border:none;
            color:white;
            font-size:14px;
            outline:none;
        }

        QListWidget::item{
            padding:14px;
        }

        QListWidget::item:selected{
            background:#00C853;
            color:black;
            border-radius:5px;
        }

        QListWidget::item:hover{
            background:#2b2b2b;
        }
        """)

        layout = QVBoxLayout(self)

        title = QLabel("MENU")

        self.menu = QListWidget()

        self.menu.addItems([
            "🏠 Dashboard",
            "📈 Markets",
            "⭐ Watchlist",
            "📒 Orders",
            "💼 Positions",
            "📚 Order Book",
            "📊 Recent Trades",
            "🤖 AI Scanner",
            "📝 Journal",
            "⚠ Risk Manager",
            "⚙ Settings"
        ])

        self.menu.setCurrentRow(0)

        layout.addWidget(title)

        layout.addWidget(self.menu)