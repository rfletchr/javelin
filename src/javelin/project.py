from __future__ import annotations

import os
import platform
import tomllib
import typing

from javelin import templates as templateslib
from javelin import utils as utilslib


class ProjectManager:
    @classmethod
    def from_environment(cls):
        return cls.from_directory(os.environ["JAVELIN_FACILITY_DIRECTORY"])

    @classmethod
    def from_directory(cls, facility_dir: str):
        config_file = os.path.join(facility_dir, "config", "pipeline.toml")
        with open(config_file, "rb") as f:
            config = tomllib.load(f)

        projects_dir = typing.cast(str, config["projects_dir"][platform.system().lower()])

        return cls(facility_dir, projects_dir)

    def __init__(self, facility_dir: str, projects_dir: str):
        self.__facillity_dir = facility_dir
        self.__projects_dir = projects_dir

    @property
    def projects_dir(self) -> str:
        return self.__projects_dir

    @property
    def facility_dir(self) -> str:
        return self.__facillity_dir

    def project_name_from_path(self, path: str) -> str:
        """
        Get the name of the project the path is a member of.
        """
        if not os.path.commonpath([path, self.__projects_dir]):
            raise ValueError(f"Path {path} is not within the projects directory")

        rel_path = os.path.relpath(path, self.__projects_dir)
        return rel_path.split(os.path.sep)[0]

    def init_path(self, project_name: str) -> str:
        return os.path.join(self.__projects_dir, project_name, "pipeline", "init.py")

    def get_project(self, name: str):
        return Project.from_directory(self, os.path.join(self.__projects_dir, name))


class Project:
    @classmethod
    def from_environmet(cls):
        pipeline = ProjectManager.from_environment()

        project_name = os.environ.get("JAVELIN_PROJECT_NAME")
        if not project_name:
            raise ValueError("JAVELIN_PROJECT_NAME environment variable not set")

        return pipeline.get_project(project_name)

    @classmethod
    def from_directory(cls, manager: ProjectManager, directory: str):
        init_path = manager.init_path(os.path.basename(directory))
        if not os.path.exists(init_path):
            raise FileNotFoundError(f"no init.py found in {directory}")

        module = utilslib.load_module_from_path(init_path)
        return typing.cast(Project, getattr(module, "init")(manager, directory))

    def __init__(
        self,
        manager: ProjectManager,
        directory: str,
        templates: dict[str, templateslib.PathTemplate],
        context_definitions: tuple[ContextDefinition, ...],
    ):
        self.__pipeline = manager
        self.__directory = directory
        self.__name = os.path.basename(directory)
        self.__templates = templates
        self.__context_definitions = context_definitions

    def templates(self):
        return self.__templates.copy()

    def context_from_path(self, path: str) -> ContextClasses:
        for definition in self.__context_definitions:
            if match := definition.template.match(path):
                return definition.cls(definition=definition, **match)

        raise ValueError(f"path: {path} doesn't match a context in this project.")

    def context_from_fields(self, data: dict):
        if data.get("project") != self.__name:
            raise ValueError(f"project: {data.get('project')} doesn't match this project: {self.__name}")

        for definition in self.__context_definitions:
            if definition.template.keys.issubset(data.keys()):
                data = {k: v for k, v in data.items() if v and k in definition.template.keys}
                return definition.cls(definition=definition, **data)

        raise ValueError(f"no context matches the data: {data}")

    def resolve_template_relpath(self, rel: str):
        if os.path.isabs(rel):
            return rel

        return os.path.join(self.__directory, "pipeline", "templates", rel)

    def list_workfiles(self, context: ContextClasses, workfile_definition: WorkfileDefinition):
        result = []
        for path, fields in workfile_definition.template.glob(context.fields()):
            result.append(
                Workfile(
                    name=fields["name"],
                    version=fields["version"],
                    path=path,
                    context=context,
                )
            )
        return result

    def __str__(self) -> str:
        return self.__name


class AssetContext(typing.NamedTuple):
    definition: ContextDefinition
    project: str
    asset_type: str
    asset: str
    task: str

    def fields(self):
        return {
            "project": self.project,
            "asset_type": self.asset_type,
            "asset": self.asset,
            "task": self.task,
        }


class ShotContext(typing.NamedTuple):
    definition: ContextDefinition
    project: str
    sequence: str
    shot: str
    task: str

    def fields(self):
        return {
            "project": self.project,
            "sequence": self.sequence,
            "shot": self.shot,
            "task": self.task,
        }


class EpisodicShotContext(typing.NamedTuple):
    definition: ContextDefinition
    project: str
    episode: str
    sequence: str
    shot: str
    task: str

    def fields(self):
        return {
            "project": self.project,
            "episode": self.episode,
            "sequence": self.sequence,
            "shot": self.shot,
            "task": self.task,
        }


class Workfile(typing.NamedTuple):
    name: str
    version: int
    path: str
    context: ContextClasses


ContextClasses = AssetContext | ShotContext | EpisodicShotContext


class WorkfileDefinition(typing.NamedTuple):
    label: str
    template: templateslib.PathTemplate
    name_pattern: str
    template_files: dict[str, str]


class PublishDefinition(typing.NamedTuple):
    label: str
    template: templateslib.PathTemplate
    group_by: str | None = None


class ContextDefinition(typing.NamedTuple):
    cls: type[ContextClasses]
    template: templateslib.PathTemplate
    workfiles: tuple[WorkfileDefinition, ...]
    publishes: tuple[PublishDefinition, ...]
