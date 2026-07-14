import logging
import os

from qtpy import QtCore, QtGui, QtWidgets

from javelin import ProjectManager
from javelin.ui.controller import BaseController
from javelin.ui.database import Database

ItemDataRole = QtCore.Qt.ItemDataRole


logger = logging.getLogger(__name__)


class ProjectItem(QtGui.QStandardItem):
    @staticmethod
    def fields() -> list[str]:
        return ["name", "tank_name"]

    def __init__(self, entity: dict):
        super().__init__(entity["name"])
        self.setEditable(False)
        self.setData(entity, ItemDataRole.UserRole)


class ProjectsView(QtWidgets.QWidget):
    projectChanged = QtCore.Signal(QtCore.QModelIndex)  # type: ignore

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.projects_combo = QtWidgets.QComboBox()

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.projects_combo)
        self.setLayout(layout)

        self.projects_combo.currentIndexChanged.connect(self.onValueChanged)

    def onValueChanged(self, int_index: int):
        index = self.projects_combo.model().index(int_index, 0)
        self.projectChanged.emit(index)

    def setModel(self, model):
        self.projects_combo.setModel(model)

    def selectRow(self, row: int):
        self.projects_combo.setCurrentIndex(row)


class ProjectsController(BaseController):
    projectChanged = QtCore.Signal(dict)  # type: ignore

    def __init__(
        self, project_manager: ProjectManager, database: Database, view: ProjectsView | None = None, parent=None
    ):
        super().__init__(parent=parent)
        self.project_manager = project_manager
        self.database = database
        self.view = view or ProjectsView()

        self.model = QtGui.QStandardItemModel(self)
        self.view.setModel(self.model)

        self.view.projectChanged.connect(self.onProjectChanged)

    def onProjectChanged(self, index: QtCore.QModelIndex):
        if not index.isValid():
            return
        project = index.data(ItemDataRole.UserRole)

        logger.info("Project changed: %s", project["tank_name"])
        self.projectChanged.emit(project)

    def populate(self):
        self.setBusy(True)
        (
            self.database.find(
                self,
                "Project",
                [["tank_name", "is_not", None]],
                ProjectItem.fields(),
                order=[{"field_name": "name", "direction": "asc"}],
            )
            .then(self._onQueryCompleted)
            .and_finally(lambda: self.setBusy(False))
        )

    def selectProjectByName(self, tank_name: str) -> bool:
        for row in range(self.model.rowCount()):
            entity = self.model.item(row).data(ItemDataRole.UserRole)
            if entity["tank_name"] == tank_name:
                self.view.selectRow(row)
                return True

        logger.warning("No project found matching tank_name: %s", tank_name)
        return False

    def _onQueryCompleted(self, rows: list[dict]):
        self.model.clear()
        for project_entity in rows:
            name = project_entity["tank_name"]
            if not os.path.exists(os.path.join(self.project_manager.projects_dir, name)):
                continue
            try:
                self.project_manager.get_project(project_entity["tank_name"])
            except FileNotFoundError:
                logger.warning(f"project: {name} has no init file.")
                continue
            except Exception:
                logger.exception(f"Failed to get project: {name}")
                continue

            self.model.appendRow(ProjectItem(project_entity))
        logger.info("Populated %d projects.", self.model.rowCount())
