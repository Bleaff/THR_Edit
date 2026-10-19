"""Preset sidebar: library list, search, genre filter, favorites, and actions."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..domain.presets import UNCATEGORIZED, Genre, Preset
from ..services.preset_manager import GENRE_FILTERS, PresetError, PresetManager

ALL_GENRES = "All genres"


class Prompts:
    """Modal dialogs, isolated so tests can replace them."""

    def ask_text(self, parent: QWidget, title: str, label: str, default: str = "") -> str | None:
        text, ok = QInputDialog.getText(parent, title, label, text=default)
        return text if ok else None

    def confirm(self, parent: QWidget, text: str) -> bool:
        answer = QMessageBox.question(parent, "Confirm", text)
        return answer == QMessageBox.StandardButton.Yes

    def open_file(self, parent: QWidget) -> str | None:
        path, _ = QFileDialog.getOpenFileName(parent, "Import presets", "", "Presets (*.json)")
        return path or None

    def save_file(self, parent: QWidget, default: str) -> str | None:
        path, _ = QFileDialog.getSaveFileName(parent, "Export presets", default, "Presets (*.json)")
        return path or None

    def show_error(self, parent: QWidget, text: str) -> None:
        QMessageBox.warning(parent, "Presets", text)


class PresetBrowser(QWidget):
    load_requested = Signal(object)  # Preset
    save_as_requested = Signal()
    library_changed = Signal()
    message = Signal(str)

    def __init__(self, manager: PresetManager, prompts: Prompts | None = None) -> None:
        super().__init__()
        self.manager = manager
        self.prompts = prompts or Prompts()
        self._connected = False
        self.setMinimumWidth(250)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search presets…")
        self.search.setClearButtonEnabled(True)
        self.genre = QComboBox()
        self.genre.addItems([ALL_GENRES, *GENRE_FILTERS])
        self.favorites = QCheckBox("★ Favorites only")
        self.list = QListWidget()
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        self.load_button = QPushButton("Load to amp")
        self.save_as_button = QPushButton("Save amp as new…")
        self.rename_button = QPushButton("Rename")
        self.duplicate_button = QPushButton("Duplicate")
        self.delete_button = QPushButton("Delete")
        self.favorite_button = QPushButton("★")
        self.favorite_button.setToolTip("Toggle favorite")
        self.import_button = QPushButton("Import…")
        self.export_button = QPushButton("Export…")
        self.load_button.setToolTip(
            "Applies the preset's amp, cab and effect settings. Effect values this app cannot map "
            "yet (reverb time/filter, delay cuts) may be reset by the amp."
        )

        grid = QGridLayout()
        grid.addWidget(self.load_button, 0, 0, 1, 2)
        grid.addWidget(self.save_as_button, 1, 0, 1, 2)
        grid.addWidget(self.rename_button, 2, 0)
        grid.addWidget(self.duplicate_button, 2, 1)
        grid.addWidget(self.delete_button, 3, 0)
        grid.addWidget(self.favorite_button, 3, 1)
        grid.addWidget(self.import_button, 4, 0)
        grid.addWidget(self.export_button, 4, 1)
        layout = QVBoxLayout(self)
        layout.addWidget(self.search)
        layout.addWidget(self.genre)
        layout.addWidget(self.favorites)
        layout.addWidget(self.list, 1)
        layout.addLayout(grid)

        self.search.textChanged.connect(self.refresh)
        self.genre.currentIndexChanged.connect(self.refresh)
        self.favorites.toggled.connect(self.refresh)
        self.list.itemSelectionChanged.connect(self._update_buttons)
        self.list.itemDoubleClicked.connect(lambda _item: self._load())
        self.list.customContextMenuRequested.connect(self._context_menu)
        self.load_button.clicked.connect(self._load)
        self.save_as_button.clicked.connect(self.save_as_requested)
        self.rename_button.clicked.connect(self._rename)
        self.duplicate_button.clicked.connect(self._duplicate)
        self.delete_button.clicked.connect(self._delete)
        self.favorite_button.clicked.connect(self._toggle_favorite)
        self.import_button.clicked.connect(self._import)
        self.export_button.clicked.connect(self._export)

        self.refresh()

    # -- state -------------------------------------------------------------
    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        self._update_buttons()

    def selected(self) -> Preset | None:
        item = self.list.currentItem()
        if item is None:
            return None
        return self.manager.get(item.data(Qt.ItemDataRole.UserRole))

    def refresh(self, select_id: str | None = None) -> None:
        if not isinstance(select_id, str):
            select_id = None
        keep = select_id or (
            self.list.currentItem().data(Qt.ItemDataRole.UserRole)
            if self.list.currentItem()
            else None
        )
        genre_text = self.genre.currentText()
        genre: Genre | str | None = None
        if genre_text == UNCATEGORIZED:
            genre = UNCATEGORIZED
        elif genre_text != ALL_GENRES:
            genre = Genre(genre_text)
        presets = self.manager.search(self.search.text(), genre, self.favorites.isChecked())
        self.list.blockSignals(True)
        self.list.clear()
        for p in presets:
            star = "★ " if p.favorite else ""
            item = QListWidgetItem(f"{star}{p.name}   [{p.genre_label}]")
            item.setData(Qt.ItemDataRole.UserRole, p.id)
            self.list.addItem(item)
            if p.id == keep:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        self._update_buttons()

    def _update_buttons(self) -> None:
        has = self.list.currentItem() is not None
        self.load_button.setEnabled(has and self._connected)
        self.save_as_button.setEnabled(self._connected)
        for b in (
            self.rename_button,
            self.duplicate_button,
            self.delete_button,
            self.favorite_button,
            self.export_button,
        ):
            b.setEnabled(has)

    # -- actions -----------------------------------------------------------
    def _guard(self, action) -> None:  # type: ignore[no-untyped-def]
        try:
            action()
        except (PresetError, ValueError, OSError) as exc:
            self.prompts.show_error(self, str(exc))

    def _load(self) -> None:
        preset = self.selected()
        if preset is not None and self._connected:
            self.load_requested.emit(preset)

    def _rename(self) -> None:
        preset = self.selected()
        if preset is None:
            return
        name = self.prompts.ask_text(self, "Rename preset", "Name:", preset.name)
        if name is not None:
            self._guard(lambda: self._finish(self.manager.rename(preset.id, name).id))

    def _duplicate(self) -> None:
        preset = self.selected()
        if preset is not None:
            self._guard(lambda: self._finish(self.manager.duplicate(preset.id).id))

    def _delete(self) -> None:
        preset = self.selected()
        if preset is None or not self.prompts.confirm(self, f"Delete preset “{preset.name}”?"):
            return

        def do() -> None:
            self.manager.delete(preset.id)
            self._finish(None)

        self._guard(do)

    def _toggle_favorite(self) -> None:
        preset = self.selected()
        if preset is not None:
            self._guard(
                lambda: self._finish(self.manager.set_favorite(preset.id, not preset.favorite).id)
            )

    def _set_genre(self, genre: Genre | None) -> None:
        preset = self.selected()
        if preset is not None:
            self._guard(lambda: self._finish(self.manager.set_genre(preset.id, genre).id))

    def _import(self) -> None:
        path = self.prompts.open_file(self)
        if not path:
            return
        result = self.manager.import_presets(path)
        self._finish(result.added[0].id if result.added else None)
        text = f"Imported {len(result.added)} preset(s), skipped {result.skipped} duplicate(s)."
        if result.errors:
            text += "\n" + "\n".join(result.errors[:5])
            self.prompts.show_error(self, text)
        self.message.emit(text.splitlines()[0])

    def _export(self) -> None:
        preset = self.selected()
        if preset is None:
            return
        shown = [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]
        path = self.prompts.save_file(self, "thr-presets.json")
        if path:
            # Export the whole filtered view; the selected preset is always included.
            ids = shown if preset.id in shown else [preset.id]
            self._guard(
                lambda: self.message.emit(
                    f"Exported {self.manager.export_presets(ids, path)} preset(s)"
                )
            )

    def _finish(self, select_id: str | None) -> None:
        self.refresh(select_id)
        self.library_changed.emit()

    def _context_menu(self, pos: QPoint) -> None:
        if self.list.itemAt(pos) is None:
            return
        menu = QMenu(self)
        load = menu.addAction("Load to amp")
        load.setEnabled(self._connected)
        load.triggered.connect(self._load)
        menu.addAction("Rename…", self._rename)
        menu.addAction("Duplicate", self._duplicate)
        menu.addAction("Toggle favorite", self._toggle_favorite)
        genre_menu = menu.addMenu("Genre")
        for g in Genre:
            genre_menu.addAction(g.value, lambda g=g: self._set_genre(g))
        genre_menu.addAction(UNCATEGORIZED, lambda: self._set_genre(None))
        menu.addSeparator()
        menu.addAction("Delete…", self._delete)
        menu.exec(self.list.mapToGlobal(pos))
