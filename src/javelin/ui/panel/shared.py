from __future__ import annotations

import enum
import logging
import os
import pathlib
import typing

import fast_blurhash
from qtpy import QtCore, QtGui, QtWidgets

from javelin.ui import icons as icon_assets
from javelin.ui.database import Database
from javelin.ui.promise import Promise

ItemDataRole = QtCore.Qt.ItemDataRole
IndexType = QtCore.QModelIndex | QtCore.QPersistentModelIndex

__all__ = ["BurninStamp", "ModelRoles", "StampWidget", "WidgetDelegate", "get_theme_icon"]

_STAMP_IMAGE_SIZE = QtCore.QSize(186, 140)

logger = logging.getLogger(__name__)


class ModelRoles(enum.IntEnum):
    @staticmethod
    def _generate_next_value_(name, start, count, last_values):  # noqa: ARG004
        return ItemDataRole.UserRole + count + 1

    ProjectNameRole = enum.auto()
    ThumbnailEntityRole = enum.auto()
    BlurhashRole = enum.auto()
    GenerationRole = enum.auto()

    NameRole = enum.auto()
    LinkedEntityNameRole = enum.auto()
    StatusRole = enum.auto()

    VersionNumberRole = enum.auto()
    PublishVersionsRole = enum.auto()
    IsPublishGroupRole = enum.auto()
    PathRole = enum.auto()

    ProjectInstanceRole = enum.auto()
    CustomFilterRole = enum.auto()
    ContextFieldsRole = enum.auto()


class StampWidget(QtWidgets.QWidget):
    def populate(self, index: IndexType) -> None:
        raise NotImplementedError

    def sizeHint(self, /) -> QtCore.QSize:
        return _STAMP_IMAGE_SIZE


class ImageWidget(QtWidgets.QWidget):
    def __init__(self, size: QtCore.QSize, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.__size_hint = size
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        self.__pixmap: QtGui.QPixmap | None = None

    def sizeHint(self, /) -> QtCore.QSize:
        return self.__size_hint

    def setPixmap(self, pixmap: QtGui.QPixmap) -> None:
        self.__pixmap = pixmap
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        if self.__pixmap is not None:
            painter = QtGui.QPainter(self)

            pixmap = self.__pixmap.scaledToWidth(self.rect().width(), QtCore.Qt.TransformationMode.SmoothTransformation)
            pixmap_rect = pixmap.rect()
            pixmap_rect.moveCenter(self.rect().center())

            painter.drawPixmap(pixmap_rect, pixmap)


def get_theme_icon(name: str, fallback: QtWidgets.QStyle.StandardPixmap | None = None) -> QtGui.QIcon:
    """Look up `name` in the desktop's icon theme, falling back to a Qt standard icon.

    QIcon.fromTheme only resolves on platforms with a freedesktop icon theme (mainly Linux); the
    fallback keeps icons working on Windows/macOS or bare setups without one configured.
    """
    icon = QtGui.QIcon.fromTheme(name)
    if icon.isNull() and fallback is not None:
        icon = QtWidgets.QApplication.style().standardIcon(fallback)
    return icon


class IconWidget(QtWidgets.QWidget):
    """Renders a QIcon scaled to fill the widget's height, keeping aspect ratio."""

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Expanding)
        self.__icon: QtGui.QIcon | None = None

    def sizeHint(self, /) -> QtCore.QSize:
        return QtCore.QSize(48, 48)

    def setIcon(self, icon: QtGui.QIcon) -> None:
        self.__icon = icon
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        if self.__icon is None or self.__icon.isNull():
            return

        painter = QtGui.QPainter(self)
        self.__icon.paint(painter, event.rect(), QtCore.Qt.AlignmentFlag.AlignCenter)


class BurninStamp(StampWidget):
    """Top-bar / image / bottom-bar layout shared by the concrete stamp widgets."""

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)

        self.image_widget = ImageWidget(_STAMP_IMAGE_SIZE)
        self.image_widget.setObjectName("image_widget")

        self.top_layout = QtWidgets.QHBoxLayout()
        self.top_layout.setContentsMargins(0, 0, 0, 0)
        self.top_layout.setSpacing(0)

        top_widget = QtWidgets.QWidget()
        top_widget.setObjectName("top_widget")
        top_widget.setLayout(self.top_layout)
        top_widget.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Minimum)

        self.bottom_layout = QtWidgets.QHBoxLayout()
        self.bottom_layout.setContentsMargins(0, 0, 0, 0)
        self.bottom_layout.setSpacing(0)

        bottom_widget = QtWidgets.QWidget()
        bottom_widget.setObjectName("bottom_widget")
        bottom_widget.setLayout(self.bottom_layout)
        bottom_widget.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Minimum)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(top_widget)
        layout.addWidget(self.image_widget)
        layout.addWidget(bottom_widget)

        self.setStyleSheet(
            """
            BurninStamp {
                background-color: palette(dark);
            }
            BurninStamp > QWidget#top_widget,
            BurninStamp > QWidget#bottom_widget {
                background-color: rgba(24, 24, 24, 255);
            }
            BurninStamp QLabel[stampRole="primary"] {
                font-weight: 600;
                padding: 2px;
                color: rgba(255, 255, 255, 0.8);
            }
            BurninStamp QLabel[stampRole="secondary"] {
                font-size: 12px;
                font-weight: 300;
                padding: 2px;
                color: rgba(255, 255, 255, 0.8);
            }
            """
        )

    def _make_label(self, role: typing.Literal["primary", "secondary"], object_name: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel()
        label.setObjectName(object_name)
        label.setProperty("stampRole", role)
        return label


class StampListView(QtWidgets.QListView):
    """Icon-mode grid of stamps. The stamp's sizeHint width is a guide: each row fits as many
    cells as the guide allows, the cells stretch equally to fill the leftover width, and the
    stamp renders at its hinted size centered in its cell."""

    def __init__(self, stamp: StampWidget, parent: QtWidgets.QWidget | None = None, empty_text: str | None = None):
        super().__init__(parent)
        self.setItemDelegate(WidgetDelegate(stamp, self))
        self.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
        self.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
        self.setFlow(QtWidgets.QListView.Flow.LeftToRight)
        self.setSpacing(10)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        # Rows always fit the viewport by construction (see WidgetDelegate.sizeHint), so a
        # horizontal scrollbar can only ever appear transiently mid-resize, before the
        # delayed relayout runs — which reads as flicker. Never show it.
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.__empty_text = empty_text or "Nothing Found"

    def paintEvent(self, e: QtGui.QPaintEvent, /) -> None:
        super().paintEvent(e)
        if not self.model() or not self.model().rowCount():
            painter = QtGui.QPainter(self.viewport())
            painter.drawText(self.viewport().rect(), QtCore.Qt.AlignmentFlag.AlignCenter, self.__empty_text)


class WidgetDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, stamp: StampWidget, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self._stamp = stamp
        if parent is not None:
            self._stamp.setParent(parent)
        self._stamp.hide()
        self._palette = QtWidgets.QApplication.palette()

    def cardRect(self, cell: QtCore.QRect) -> QtCore.QRect:
        """The stamp keeps its hinted size regardless of how wide its cell stretched: the
        card is centered and leftover cell width becomes empty space around it, so embedded
        images never distort. Only shrinks when the cell is narrower than the hint."""
        hint = self._stamp.sizeHint()
        width = max(1, min(hint.width(), cell.width() - 6))
        height = max(1, min(hint.height(), cell.height() - 6))
        card = QtCore.QRect(0, 0, width, height)
        card.moveCenter(cell.center())
        return card

    def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionViewItem, index: IndexType) -> None:
        rect = self.cardRect(option.rect)

        bg_color = self._palette.color(QtGui.QPalette.ColorRole.Dark)
        painter.fillRect(rect.translated(2, 2), bg_color)

        self._stamp.setFixedSize(rect.size())
        self._stamp.populate(index)

        # `self._stamp.render(painter, rect.topLeft())` positions its output using the
        # widget's own top-level window context, which is wrong once the view isn't at
        # its window's origin (e.g. another widget stacked above it). Grabbing to a
        # plain QPixmap first sidesteps that: a pixmap has no window context, so
        # drawPixmap() places it using only the painter's own coordinates.
        stamp_pixmap = self._stamp.grab()
        painter.drawPixmap(rect, stamp_pixmap)

        # if the item is selected then draw a highlight rect around it
        if option.state & QtWidgets.QStyle.StateFlag.State_Selected:
            color = self._palette.color(QtGui.QPalette.ColorRole.Highlight)
            border_pen = QtGui.QPen(color, 2)

        else:
            border_pen = QtGui.QPen(self._palette.color(QtGui.QPalette.ColorRole.Dark), 2)

        painter.setPen(border_pen)
        painter.drawRect(rect)

    def sizeHint(self, option: QtWidgets.QStyleOptionViewItem, index: IndexType) -> QtCore.QSize:
        size = index.data(ItemDataRole.SizeHintRole)
        if size is not None:
            return size

        hint = self._stamp.sizeHint()
        view = self.parent()
        if not isinstance(view, QtWidgets.QListView):
            return hint

        # The hint width is a guide, not a fixed size: fit as many columns as the guide
        # allows, then split the leftover width between them so each row fills the
        # viewport. Relies on ResizeMode.Adjust re-laying-out (and re-querying this
        # hint) whenever the viewport resizes. QListView's icon-mode wrap condition is
        # strict (`x + width + spacing < viewport`), hence the -1s: an exact fit wraps.
        model = view.model()
        if model is not None and model.rowCount() <= 1:
            # Nothing to share a row with, so there's no leftover width to distribute:
            # stretching a lone item would just blow it up to the full viewport width.
            return hint

        spacing = view.spacing()
        available = view.viewport().width()
        columns = max(1, (available - spacing - 1) // (hint.width() + spacing))

        # Fewer items than columns would leave the row's leftover width undistributed,
        # so the odd items sit off-center; let them share the full row instead.
        if model is not None:
            columns = max(1, min(columns, model.rowCount()))

        width = max(1, (available - spacing * (columns + 1) - 1) // columns)
        return QtCore.QSize(width, hint.height())


class MimeDataHandler:
    def mimeTypes(self) -> list[str]:
        raise NotImplementedError

    def mimeData(self, indexes: typing.Sequence[IndexType]) -> QtCore.QMimeData:
        raise NotImplementedError


class GenerationalItemModel(QtGui.QStandardItemModel):
    def __init__(self, parent: QtCore.QObject | None = None, mime_handler: MimeDataHandler | None = None):
        super().__init__(parent)
        self._generation = 0
        self._mime_handler = mime_handler

    def checkGeneration(self, generation: int) -> bool:
        return self._generation == generation

    def setItems(self, items: typing.Sequence[QtGui.QStandardItem]) -> None:
        self._generation += 1
        self.clear()
        for item in items:
            self.appendRow(item)

    def data(self, index: IndexType, role: int = ItemDataRole.DisplayRole) -> typing.Any:
        if role == ModelRoles.GenerationRole:
            return self._generation
        return super().data(index, role)

    def mimeTypes(self) -> list[str]:
        if self._mime_handler is not None:
            return self._mime_handler.mimeTypes()
        return super().mimeTypes()

    def mimeData(self, indexes: typing.Sequence[QtCore.QModelIndex]) -> QtCore.QMimeData:
        if self._mime_handler is not None:
            return self._mime_handler.mimeData(indexes)
        return super().mimeData(indexes)


class ImageProviderModel(QtCore.QIdentityProxyModel):
    def __init__(self, projects_dir: str, parent: QtCore.QObject | None = None):
        super().__init__(parent)
        self.__cache = {}
        self.__projects_dir = projects_dir
        self.__pool = QtCore.QThreadPool(maxThreadCount=4)

    def data(self, index: IndexType, role: int = ItemDataRole.DisplayRole) -> typing.Any:
        if not index.isValid():
            return None

        source_model = self.sourceModel()
        if not source_model:
            return

        source_index = self.mapToSource(index)

        if role == ItemDataRole.DecorationRole:
            project_name = source_model.data(source_index, ModelRoles.ProjectNameRole)
            entity = source_model.data(source_index, ModelRoles.ThumbnailEntityRole)
            if not project_name or not entity:
                return None
            path = self.getImagePath(project_name, entity["type"], entity["id"])
            if path in self.__cache:
                return self.__cache[path]

            blurhash = source_model.data(source_index, ModelRoles.BlurhashRole)
            generation = source_model.data(source_index, ModelRoles.GenerationRole)

            image = self.decode(blurhash or "K65=eFtRB.PXbIrXA^WB;e", 16, 16)
            pixmap = QtGui.QPixmap.fromImage(image)
            self.__cache[path] = pixmap

            promise = Promise(self, self.loadImage, path, index.row(), generation).then(
                lambda i, p=path, g=generation, r=source_index.row(): self.onImageLoaded(p, r, g, i)
            )
            self.__pool.start(promise)
            return self.__cache[path]
        else:
            return source_model.data(source_index, role)

    def loadImage(self, path: str, row: int, generation: int):
        model = self.sourceModel()
        if isinstance(model, GenerationalItemModel) and not model.checkGeneration(generation):
            return QtGui.QImage()

        image = QtGui.QImage(path)
        return image

    def decode(self, blurhash: str, width: int, height: int, punch: float = 1.0) -> QtGui.QImage:
        """Decode a blurhash string into an RGB888 QImage of the given size."""
        if len(blurhash) < 6:
            return QtGui.QImage()

        pixels = fast_blurhash.decode(blurhash, width, height, punch)
        bytes_per_line = width * 3
        image = QtGui.QImage(pixels, width, height, bytes_per_line, QtGui.QImage.Format.Format_RGB888)
        return image.copy()

    def getImagePath(
        self,
        project_name: str,
        entity_type: str,
        entity_id: int,
    ):
        return os.path.join(
            self.__projects_dir, project_name, "init", "thumbnails", f"{entity_type}_{entity_id}.jpg"
        )

    def onImageLoaded(self, path: str, row: int, generation: int, image: QtGui.QImage):
        if image.isNull():
            return

        model = self.sourceModel()
        if isinstance(model, GenerationalItemModel) and not model.checkGeneration(generation):
            return

        pixmap = QtGui.QPixmap.fromImage(image)

        self.__cache[path] = pixmap
        self.dataChanged.emit(self.index(row, 0), self.index(row, 0))


class SharedData(typing.NamedTuple):
    status_code_to_name: dict[str, str]
    status_code_to_color: dict[str, QtGui.QColor]

    @classmethod
    def from_db(cls, db: Database):
        logger.info("Loading shared data from database.")
        connection = db.get_connection()

        statuses = typing.cast(list[dict], connection.find("Status", [], ["code", "name", "bg_color"]))

        status_code_to_name = {status["code"]: status["name"] for status in statuses}
        status_code_to_color = {}
        for status in statuses:
            bg_color_str = status["bg_color"]
            if not bg_color_str:
                continue

            members = [int(s) for s in bg_color_str.split(",")]
            status_code_to_color[status["code"]] = QtGui.QColor(*members)

        return cls(status_code_to_name, status_code_to_color)


class IconProviderModel(QtCore.QIdentityProxyModel):
    """Supplies DecorationRole icons from Qt's file icon provider, keyed off each row's PathRole.

    Extensions with a bundled PNG in rock.qt.icons/ (e.g. nk.png, exr.png) use that instead of the
    generic system icon.
    """

    __ICONS_DIR = pathlib.Path(icon_assets.__file__).resolve().parent

    def __init__(self, parent: QtCore.QObject | None = None):
        super().__init__(parent)
        self.__provider = QtWidgets.QFileIconProvider()
        self.__cache: dict[str, QtGui.QIcon] = {}
        self.__fmt_map = {"cdl": "cc", "cub": "cc"}

    def data(self, index: IndexType, role: int = ItemDataRole.DisplayRole) -> typing.Any:
        if not index.isValid():
            return None

        source_model = self.sourceModel()
        if not source_model:
            return None

        source_index = self.mapToSource(index)

        if role == ItemDataRole.DecorationRole:
            path = source_model.data(source_index, ModelRoles.PathRole)
            if not path:
                return source_model.data(source_index, role)

            extension = QtCore.QFileInfo(path).suffix().lower()
            extension = self.__fmt_map.get(extension, extension)
            cache_key = extension or path

            if cache_key not in self.__cache:
                self.__cache[cache_key] = self.__loadIcon(extension, path)
            return self.__cache[cache_key]

        return source_model.data(source_index, role)

    def __loadIcon(self, extension: str, path: str) -> QtGui.QIcon:
        custom_icon_path = self.__ICONS_DIR / f"{extension}.png"
        if custom_icon_path.is_file():
            return QtGui.QIcon(str(custom_icon_path))
        return self.__provider.icon(QtCore.QFileInfo(path))

    def mimeTypes(self) -> list[str]:
        source_model = self.sourceModel()
        return source_model.mimeTypes() if source_model else []

    def mimeData(self, indexes: typing.Sequence[QtCore.QModelIndex]) -> QtCore.QMimeData:
        source_model = self.sourceModel()
        if not source_model:
            return super().mimeData(indexes)
        return source_model.mimeData([self.mapToSource(index) for index in indexes])
