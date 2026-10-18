# MediaShelf.py — DVD Shelf
import sys
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from PySide6.QtCore import Qt, QSize, QUrl, QRect, Signal
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QListWidget, QListWidgetItem, QLabel,
    QStackedWidget, QTextEdit, QSplitter
)

# ---------- Constants ----------
CASE_W, CASE_H = 160, 240

POSTER_NAMES = [
    "poster.jpg", "poster.jpeg", "poster.png",
    "folder.jpg", "folder.jpeg", "folder.png",
    "cover.jpg", "cover.png",
]

VIDEO_EXTS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".m4v",".rmvb",
    ".webm", ".flv", ".mpg", ".mpeg", ".ts", ".m2ts",
}


# ---------- Data model ----------
@dataclass
class MediaItem:
    path: Path
    name: str
    poster_path: Path | None
    nfo_path: Path | None
    video_files: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


# ---------- Scanning helpers ----------
def find_poster(folder: Path) -> Path | None:
    files = {f.name.lower(): f for f in folder.iterdir() if f.is_file()}
    for name in POSTER_NAMES:
        if name in files:
            return files[name]
    for f in folder.iterdir():
        if f.is_file() and f.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            if f.stem.lower() in {"poster", "folder", "cover"}:
                return f
    return None


def find_nfo(folder: Path) -> Path | None:
    nfos = [f for f in folder.iterdir()
            if f.is_file() and f.suffix.lower() == ".nfo"]
    if not nfos:
        return None
    folder_name = folder.name.lower()
    for f in nfos:
        if f.stem.lower() == folder_name:
            return f
    for f in nfos:
        if f.stem.lower() in {"movie", "tvshow", "show"}:
            return f
    return nfos[0]


def parse_nfo(path: Path) -> dict:
    try:
        root = ET.parse(path).getroot()
        data = {}
        for child in root:
            if len(child) == 0:
                text = (child.text or "").strip()
                if text:
                    data[child.tag.lower()] = text
        return data
    except Exception:
        return {}


def scan_directory(root: Path) -> list[MediaItem]:
    items = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        files = [f for f in entry.iterdir() if f.is_file()]
        videos = sorted(f for f in files if f.suffix.lower() in VIDEO_EXTS)
        poster = find_poster(entry)
        nfo = find_nfo(entry)
        meta = parse_nfo(nfo) if nfo else {}
        items.append(MediaItem(
            path=entry,
            name=entry.name,
            poster_path=poster,
            nfo_path=nfo,
            video_files=videos,
            metadata=meta,
        ))
    return items


# ---------- DVD case rendering ----------
def make_case_pixmap(poster_path, title: str) -> QPixmap:
    canvas = QPixmap(CASE_W, CASE_H)
    canvas.fill(Qt.transparent)
    p = QPainter(canvas)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)

    # Case base
    p.setBrush(QColor("#181818"))
    p.setPen(QColor("#000000"))
    p.drawRoundedRect(0, 0, CASE_W, CASE_H, 6, 6)

    # Use poster if available
    if poster_path and poster_path.exists():
        poster = QPixmap(str(poster_path))
        if not poster.isNull():
            inner = QRect(4, 4, CASE_W - 8, CASE_H - 8)
            scaled = poster.scaled(inner.size(),
                                   Qt.KeepAspectRatioByExpanding,
                                   Qt.SmoothTransformation)
            x = max(0, (scaled.width() - inner.width()) // 2)
            y = max(0, (scaled.height() - inner.height()) // 2)
            cropped = scaled.copy(x, y, inner.width(), inner.height())
            p.drawPixmap(inner.topLeft(), cropped)
            p.end()
            return canvas

    # Fallback: Blockbuster-style case with folder name
    p.fillRect(0, 0, 10, CASE_H, QColor("#1f3a93"))       # spine
    p.fillRect(10, 0, CASE_W - 10, 36, QColor("#f0c419")) # top banner
    p.setPen(QColor("#1a1a1a"))
    p.setFont(QFont("Sans", 8, QFont.Bold))
    p.drawText(QRect(14, 0, CASE_W - 20, 36), Qt.AlignCenter, "DVD")

    p.setPen(QColor("#ffffff"))
    p.setFont(QFont("Sans", 11, QFont.Bold))
    p.drawText(QRect(18, 50, CASE_W - 26, CASE_H - 100),
               Qt.AlignCenter | Qt.TextWordWrap, title)

    p.setPen(QColor("#666666"))
    p.setFont(QFont("Sans", 7))
    p.drawText(QRect(0, CASE_H - 20, CASE_W, 16), Qt.AlignCenter, "NO POSTER")

    p.end()
    return canvas


# ---------- Shelf view ----------
class ShelfView(QWidget):
    dvd_clicked = Signal(object)  # MediaItem

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.btn_open = QPushButton("Open Folder...")
        self.lbl_path = QLabel("No folder selected")
        self.lbl_path.setStyleSheet("color:#888;")
        top.addWidget(self.btn_open)
        top.addWidget(self.lbl_path, 1)
        layout.addLayout(top)

        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(CASE_W, CASE_H))
        self.list.setGridSize(QSize(CASE_W + 40, CASE_H + 60))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setSpacing(8)
        self.list.setWordWrap(True)
        layout.addWidget(self.list, 1)

        self.items: list[MediaItem] = []

        self.btn_open.clicked.connect(self.pick_folder)
        self.list.itemClicked.connect(self.on_click)

    def pick_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select media folder")
        if not folder:
            return
        self.lbl_path.setText(folder)
        self.load_folder(Path(folder))

    def load_folder(self, root: Path):
        self.list.clear()
        self.items = scan_directory(root)
        for item in self.items:
            pix = make_case_pixmap(item.poster_path, item.name)
            li = QListWidgetItem(QIcon(pix), item.name)
            li.setTextAlignment(Qt.AlignHCenter)
            li.setSizeHint(QSize(CASE_W + 40, CASE_H + 60))
            self.list.addItem(li)

    def on_click(self, list_item):
        row = self.list.row(list_item)
        if 0 <= row < len(self.items):
            self.dvd_clicked.emit(self.items[row])


# ---------- Detail view ----------
class DetailView(QWidget):
    back_requested = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.btn_back = QPushButton("\u2190 Back")
        self.title_lbl = QLabel()
        self.title_lbl.setStyleSheet("font-size:16px;font-weight:bold;")
        top.addWidget(self.btn_back)
        top.addWidget(self.title_lbl, 1)
        layout.addLayout(top)

        splitter = QSplitter(Qt.Horizontal)

        # Left: poster
        left = QWidget()
        left_lay = QVBoxLayout(left)
        self.poster_lbl = QLabel()
        self.poster_lbl.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.poster_lbl.setMinimumWidth(260)
        left_lay.addWidget(self.poster_lbl)
        left_lay.addStretch(1)

        # Middle: metadata
        self.meta_txt = QTextEdit()
        self.meta_txt.setReadOnly(True)

        # Right: file list
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.addWidget(QLabel("Files (double-click to play)"))
        self.file_list = QListWidget()
        right_lay.addWidget(self.file_list, 1)

        splitter.addWidget(left)
        splitter.addWidget(self.meta_txt)
        splitter.addWidget(right)
        splitter.setSizes([300, 400, 300])
        layout.addWidget(splitter, 1)

        self.btn_back.clicked.connect(self.back_requested.emit)
        self.file_list.itemDoubleClicked.connect(self.open_file)

    def load(self, item: MediaItem):
        self.title_lbl.setText(item.name)

        # Poster
        if item.poster_path and item.poster_path.exists():
            pix = QPixmap(str(item.poster_path))
            if not pix.isNull():
                pix = pix.scaled(280, 420, Qt.KeepAspectRatio,
                                 Qt.SmoothTransformation)
                self.poster_lbl.setPixmap(pix)
            else:
                self.poster_lbl.setText("No poster")
        else:
            self.poster_lbl.setText("No poster")

        # Metadata
        self.meta_txt.setHtml(self._format_meta(item))

        # File list
        self.file_list.clear()
        for f in item.video_files:
            li = QListWidgetItem(f.name)
            li.setData(Qt.UserRole, str(f))
            self.file_list.addItem(li)

    def _format_meta(self, item: MediaItem) -> str:
        m = item.metadata
        if not m:
            return "<i>No metadata (no NFO file found).</i>"
        order = ["title", "originaltitle", "year", "runtime", "rating",
                 "genre", "director", "studio", "plot"]
        rows = []
        for key in order:
            if key in m:
                rows.append(f"<b>{key.title()}:</b> {self._esc(m[key])}")
        for k, v in m.items():
            if k not in order:
                rows.append(f"<b>{k.title()}:</b> {self._esc(v)}")
        return "<br>".join(rows)

    def _esc(self, s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def open_file(self, list_item):
        path = list_item.data(Qt.UserRole)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))


# ---------- Main window ----------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DVD Shelf")
        self.resize(1200, 800)

        self.stack = QStackedWidget()
        self.shelf = ShelfView()
        self.detail = DetailView()
        self.stack.addWidget(self.shelf)   # index 0
        self.stack.addWidget(self.detail)  # index 1
        self.setCentralWidget(self.stack)

        self.shelf.dvd_clicked.connect(self.show_detail)
        self.detail.back_requested.connect(
            lambda: self.stack.setCurrentIndex(0)
        )

    def show_detail(self, item: MediaItem):
        self.detail.load(item)
        self.stack.setCurrentIndex(1)


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()