from __future__ import annotations

import dataclasses
import logging
import os
import platform
import threading
import time
import typing
from concurrent.futures import ThreadPoolExecutor

import shotgun_api3

from javelin.project import AssetContext, ContextClasses, EpisodicShotContext, ShotContext
from javelin.utils import log_timing

logger = logging.getLogger("javelin.publish")

ConnectionFactory = typing.Callable[[], shotgun_api3.Shotgun]

_LOCAL_STORAGE_PATH_FIELD = {
    "Windows": "windows_path",
    "Darwin": "mac_path",
    "Linux": "linux_path",
}


@dataclasses.dataclass
class PublishItem:
    path: str
    publish_name: str
    published_file_type: str
    root_name: str = "primary"
    task_entity: dict[str, typing.Any] | None = None
    version_entity: dict[str, typing.Any] | None = None
    depends_on: list[PublishItem | int] = dataclasses.field(default_factory=list)
    thumbnail_path: str | None = None
    sg_fields: dict[str, typing.Any] = dataclasses.field(default_factory=dict)


class ContextEntities(typing.NamedTuple):
    """The ShotGrid project/entity/task entity refs a ContextClasses resolves to."""

    project: dict[str, typing.Any]
    entity: dict[str, typing.Any]
    task: dict[str, typing.Any]


def batch_register_publishes(
    connection_factory: ConnectionFactory,
    context: ContextClasses,
    version_number: int,
    comment: str,
    items: list[PublishItem],
    created_by: dict[str, typing.Any] | None,
    background_thumbnails: bool = True,
) -> dict[str, dict[str, typing.Any]]:
    """
    Register multiple publishes in as few round trips as possible.

    Resolves shared data (context entities, published file types, storage roots) once
    upfront, then creates all PublishedFile entities in a single batch call. Dependencies
    are linked in a second batch call after all entities exist.

    Returns a mapping of path -> created PublishedFile entity dict.
    """
    t_start = time.perf_counter()

    ensure_dependency_items_in_batch(items)

    type_names = {item.published_file_type for item in items}
    dep_ids = {dep for item in items for dep in item.depends_on if isinstance(dep, int)}
    root_names = {item.root_name for item in items}

    with ThreadPoolExecutor() as executor:
        f_context = executor.submit(resolve_context_entities, connection_factory, context)
        f_deps = executor.submit(ensure_dependency_ids_exist, connection_factory, dep_ids)
        f_types = executor.submit(_resolve_published_file_types, connection_factory, type_names)
        f_roots = executor.submit(_resolve_storage_roots, connection_factory, root_names)
        context_entities = f_context.result()
        f_deps.result()
        type_map = f_types.result()
        storage_map = f_roots.result()

    batch_data = [
        {
            "request_type": "create",
            "entity_type": "PublishedFile",
            "data": _build_publish_data(
                context_entities, version_number, comment, item, type_map, storage_map, created_by
            ),
        }
        for item in items
    ]

    results = _sg_batch(connection_factory, batch_data, label=f"create {len(items)} PublishedFiles")

    path_to_entity: dict[str, dict[str, typing.Any]] = {r["path"]["local_path"]: r for r in results}

    _register_dependencies(connection_factory, path_to_entity, items)

    if background_thumbnails:
        threading.Thread(
            target=_upload_thumbnails,
            args=(connection_factory, path_to_entity, items),
            daemon=True,
        ).start()
        logger.debug("thumbnail uploads started in background")
    else:
        _upload_thumbnails(connection_factory, path_to_entity, items)

    logger.debug("total: %.3fs", time.perf_counter() - t_start)

    return path_to_entity


def _sg_find(
    connection_factory: ConnectionFactory,
    entity_type: str,
    filters: list,
    fields: list[str],
) -> list[dict[str, typing.Any]]:
    return connection_factory().find(entity_type, filters, fields)  # type: ignore[return-value]


def _sg_find_one(
    connection_factory: ConnectionFactory,
    entity_type: str,
    filters: list,
    fields: list[str],
) -> dict[str, typing.Any] | None:
    return connection_factory().find_one(entity_type, filters, fields)  # type: ignore[return-value]


def _sg_batch(
    connection_factory: ConnectionFactory,
    requests: list[dict[str, typing.Any]],
    label: str = "batch",
) -> list[dict[str, typing.Any]]:
    with log_timing(logger, label):
        result = connection_factory().batch(requests)  # type: ignore[return-value]
    return result  # type: ignore[return-value]


def task_filters_for_context(context: ContextClasses) -> list[list]:
    filters = [
        ["project.Project.tank_name", "is", context.project],
        ["content", "is", context.task],
    ]
    if isinstance(context, AssetContext):
        filters += [
            ["entity.Asset.code", "is", context.asset],
            ["entity.Asset.sg_asset_type", "is", context.asset_type],
        ]
    elif isinstance(context, EpisodicShotContext):
        filters += [
            ["entity.Shot.code", "is", context.shot],
            ["entity.Shot.sg_sequence.Sequence.code", "is", context.sequence],
            ["entity.Shot.sg_sequence.Sequence.episode.Episode.code", "is", context.episode],
        ]
    elif isinstance(context, ShotContext):
        filters += [
            ["entity.Shot.code", "is", context.shot],
            ["entity.Shot.sg_sequence.Sequence.code", "is", context.sequence],
        ]
    else:
        raise TypeError(f"unsupported context type: {type(context)}")
    return filters


@log_timing(logger)
def resolve_context_entities(connection_factory: ConnectionFactory, context: ContextClasses) -> ContextEntities:
    """
    Translate a javelin ContextClasses into its ShotGrid project/entity/task entity refs,
    the same trio tank's Context.project/entity/task expose.
    Raises ValueError if no matching Task exists in ShotGrid.
    """
    task = _sg_find_one(connection_factory, "Task", task_filters_for_context(context), ["project", "entity"])
    if task is None:
        raise ValueError(f"no ShotGrid Task found for context: {context}")
    return ContextEntities(
        project=task["project"],
        entity=task["entity"],
        task={"type": "Task", "id": task["id"]},
    )


def ensure_dependency_items_in_batch(items: list[PublishItem]) -> None:
    unknown = [dep for item in items for dep in item.depends_on if isinstance(dep, PublishItem) and dep not in items]
    if unknown:
        paths = ", ".join(dep.path for dep in unknown)
        raise ValueError(f"depends_on references PublishItems not in this batch: {paths}")


@log_timing(logger)
def ensure_dependency_ids_exist(connection_factory: ConnectionFactory, dep_ids: set[int]) -> None:
    """Raise ValueError if any dep_ids do not exist as PublishedFile records in ShotGrid."""
    if not dep_ids:
        return
    found = _sg_find(connection_factory, "PublishedFile", [["id", "in", list(dep_ids)]], ["id"])
    missing = dep_ids - {r["id"] for r in found}
    if missing:
        raise ValueError(f"depends_on references unknown PublishedFile ids: {sorted(missing)}")


@log_timing(logger)
def _resolve_storage_roots(
    connection_factory: ConnectionFactory,
    root_names: set[str],
) -> dict[str, tuple[str, dict[str, typing.Any]]]:
    """
    Resolve root names to (root_path, local_storage_entity) tuples via ShotGrid's LocalStorage
    entities, producing the same shape tank's pipeline_configuration used to produce so
    PublishedFile.path records stay tank-compatible.
    Raises ValueError for any root name not found, or missing a path for this platform.
    """
    path_field = _LOCAL_STORAGE_PATH_FIELD[platform.system()]
    found = _sg_find(connection_factory, "LocalStorage", [["code", "in", list(root_names)]], ["code", path_field])
    found_map = {r["code"]: r for r in found}
    missing = root_names - found_map.keys()
    if missing:
        raise ValueError(f"unknown local storage roots: {sorted(missing)}, available: {sorted(found_map)}")

    result: dict[str, tuple[str, dict[str, typing.Any]]] = {}
    for name in root_names:
        entity = found_map[name]
        root_path = entity[path_field]
        if not root_path:
            raise ValueError(f"LocalStorage {name!r} has no {path_field} configured")
        result[name] = (root_path, {"type": "LocalStorage", "id": entity["id"]})
    return result


@log_timing(logger)
def _resolve_published_file_types(
    connection_factory: ConnectionFactory,
    type_names: set[str],
) -> dict[str, dict[str, typing.Any]]:
    """
    Resolve published file type name strings to ShotGrid entity dicts.
    Raises ValueError listing any names not found in ShotGrid.
    """
    found = _sg_find(connection_factory, "PublishedFileType", [["code", "in", list(type_names)]], ["code"])
    found_map = {r["code"]: r for r in found}
    missing = type_names - found_map.keys()
    if missing:
        raise ValueError(f"unknown published file types: {sorted(missing)}")
    return found_map


def _build_publish_data(
    context_entities: ContextEntities,
    version_number: int,
    comment: str,
    item: PublishItem,
    type_map: dict[str, dict[str, typing.Any]],
    storage_map: dict[str, tuple[str, dict[str, typing.Any]]],
    created_by: dict[str, typing.Any] | None,
) -> dict[str, typing.Any]:
    """
    Build the ShotGrid field dict for a single PublishedFile create.
    Raises if item.path is not under its resolved root.
    """
    root_path, storage = storage_map[item.root_name]
    path_cache = _path_to_path_cache(root_path, item.path)

    data: dict[str, typing.Any] = {}
    data.update(item.sg_fields)  # applied first so standard fields always win

    data["code"] = os.path.basename(item.path)
    data["name"] = item.publish_name
    data["description"] = comment
    data["version_number"] = version_number
    data["project"] = context_entities.project
    data["entity"] = context_entities.entity
    data["task"] = item.task_entity if item.task_entity is not None else context_entities.task
    data["published_file_type"] = type_map[item.published_file_type]
    data["path"] = {"relative_path": path_cache, "local_storage": storage}
    data["path_cache"] = path_cache

    if item.version_entity is not None:
        data["version"] = item.version_entity

    if created_by is not None:
        data["created_by"] = created_by

    return data


def _path_to_path_cache(root_path: str, path: str) -> str:
    """
    Compute the storage-relative forward-slash path (path_cache).
    Raises ValueError if path is not under root_path.
    """
    norm_root = os.path.normpath(root_path)
    norm_path = os.path.normpath(path)
    if not norm_path.startswith(norm_root + os.sep):
        raise ValueError(f"path {path!r} is not under root {root_path!r}")
    relative = norm_path[len(norm_root) :].lstrip(os.sep)
    return relative.replace(os.sep, "/")


@log_timing(logger)
def _upload_thumbnails(
    connection_factory: ConnectionFactory,
    path_to_entity: dict[str, dict[str, typing.Any]],
    items: list[PublishItem],
) -> None:
    items_with_thumbnails = [item for item in items if item.thumbnail_path is not None]
    if not items_with_thumbnails:
        return

    def upload(item: PublishItem) -> None:
        entity = path_to_entity[item.path]
        connection_factory().upload_thumbnail("PublishedFile", entity["id"], item.thumbnail_path)  # type: ignore[arg-type]

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(upload, item) for item in items_with_thumbnails]
        for f in futures:
            f.result()


@log_timing(logger)
def _register_dependencies(
    connection_factory: ConnectionFactory,
    path_to_entity: dict[str, dict[str, typing.Any]],
    items: list[PublishItem],
) -> None:
    """
    Create PublishedFileDependency records for all items in a single batch call.
    PublishItem deps are resolved via path_to_entity; int deps are treated as existing SG ids.
    """
    batch_data = []
    for item in items:
        published_file = path_to_entity[item.path]
        for dep in item.depends_on:
            if isinstance(dep, PublishItem):
                dependent = path_to_entity[dep.path]
            else:
                dependent = {"type": "PublishedFile", "id": dep}
            batch_data.append(
                {
                    "request_type": "create",
                    "entity_type": "PublishedFileDependency",
                    "data": {
                        "published_file": published_file,
                        "dependent_published_file": dependent,
                    },
                }
            )
    if batch_data:
        _sg_batch(connection_factory, batch_data, label=f"create {len(batch_data)} PublishedFileDependencies")
