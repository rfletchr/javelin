from __future__ import annotations

import logging
import os
import typing

from javelin import templates as templateslib
from javelin import utils as utilslib

logger = logging.getLogger(__name__)

PROJECT_PATH_ENV_VAR = "JAVELIN_PROJECT_PATH"


def list_projects(projects_dir: str) -> list[str]:
    """List the names of projects under `projects_dir` that have an init/init.py."""
    result = []
    for name in sorted(os.listdir(projects_dir)):
        if os.path.exists(_init_path(projects_dir, name)):
            result.append(name)
    return result


def _init_path(projects_dir: str, project_name: str) -> str:
    return os.path.join(projects_dir, project_name, "init", "init.py")


class Project:
    @classmethod
    @utilslib.log_timing(logger)
    def from_directory(cls, directory: str) -> Project:
        init_path = _init_path(os.path.dirname(directory), os.path.basename(directory))
        if not os.path.exists(init_path):
            raise FileNotFoundError(f"no init.py found in {directory}")

        module = utilslib.load_module_from_path(init_path)
        return typing.cast(Project, getattr(module, "init")(directory))

    @classmethod
    def from_name(cls, projects_dir: str, name: str) -> Project:
        return cls.from_directory(os.path.join(projects_dir, name))

    @classmethod
    def from_environment(cls) -> Project:
        directory = os.environ[PROJECT_PATH_ENV_VAR]
        return cls.from_directory(directory)

    def __init__(
        self,
        directory: str,
        templates: dict[str, templateslib.PathTemplate],
        context_definitions: tuple[ContextDefinition, ...],
        commands: tuple[CommandDefinition, ...],
    ):
        self.__directory = directory
        self.__name = os.path.basename(os.path.normpath(directory))
        self.__templates = templates
        self.__context_definitions = context_definitions
        self.__commands = commands

    @property
    def directory(self) -> str:
        return self.__directory

    def commands(self):
        return self.__commands

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

        return os.path.join(self.__directory, "init", "templates", rel)

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


class CommandDefinition(typing.NamedTuple):
    label: str
    command: list[str]
    icon: str | None = None


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
