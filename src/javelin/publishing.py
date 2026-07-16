import dataclasses
import typing

import shotgun_api3

from javelin import AssetContext, ContextClasses, EpisodicShotContext, ShotContext

ConnectionFactory = typing.Callable[[], shotgun_api3.Shotgun]

class AssetFields:
    Code = "code"
    Type = "sg_asset_type"



@dataclasses.dataclass
class NewPublishItem:
    context: ContextClasses
    publish_name: str
    publish_type: str
    version_number: int
    version_id: int | None = None
    comment: str | None = None


def resolve_context_entities(contexts: list[ContextClasses], connection_factory: ConnectionFactory) -> list[dict]:
    """
    Resolves the context entities for a list of contexts.

    Args:
        contexts (list[ContextClasses]): The list of contexts to resolve.
        connection_factory (ConnectionFactory): A callable that returns a Shotgun connection.

    Returns:
        list[dict]: A list of resolved context entities.
    """
    connection = connection_factory()

    # break the contexts to make them easier to 'key'
    asset_contexts = {}
    shot_contexts = {}
    episodic_shot_contexts = {}

    for context in contexts:
        if isinstance(context, AssetContext):
            key = (context.project, context.asset, context.asset_type, context.task)
            asset_contexts[key] = context
        elif isinstance(context, ShotContext):
            key = (context.project, context.shot, context.task)
            shot_contexts[key] = context
        elif isinstance(context, EpisodicShotContext):
            key = (context.project, context.episode, context.shot, context.task)
            episodic_shot_contexts[key] = context
        else:
            raise TypeError(f"unsupported context type: {type(context)}")

    asset_task_entities: dict[tuple[str,...], dict] = {}

    if asset_contexts:
        assets_filter = {
            "filter_operator": "any",
            "filters": [
                {"filter_operator": "all", "filters": task_filters_for_context(context)}
                for context in asset_contexts.values()
            ],
        }

        tasks = typing.cast(
            list[dict],
            connection.find(
                "Task",
                filters=assets_filter,
                fields=["entity.Asset.code", "entity.Asset.sg_asset_type", "content", "project.Tank_name"],
            ),
        )
        for task_entity in tasks:
            key = (
                task_entity["project.Tank_name"],
                task_entity["entity.Asset.code"],
                task_entity["entity.Asset.sg_asset_type"],
                task_entity["content"],
            )
            asset_task_entities[key] = {"id": task_entity["id"], "type":"Task"}

    shot_task_entities: dict[tuple[str, ...], dict] = {}
    if shot_contexts:
        shots_filter = {

        }
        tasks = typing.cast(
            list[dict],
            connection.find(
                "Task",
                filters=shots_filter,
                fields=["entity.Shot.code", "content", "project.Tank_name", "entity.Shot.sg_sequence.Sequence.code"],
            ),
        )
        for task_entity in tasks:
            key = (
                task_entity["project.Tank_name"],
                task_entity["entity.Shot.code"],
                task_entity["entity.Shot.sg_sequence.Sequence.code"],
                task_entity["content"],
            )
            shot_task_entities[key] = {"id": task_entity["id"], "type": "Task"}

    episodic_shot_task_entities: dict[tuple[str, ...], dict] = {}
    if episodic_shot_contexts:
        episodic_shots_filter = {

        }
        tasks = typing.cast(
            list[dict],
            connection.find(
                "Task",
                filters=episodic_shots_filter,
                fields=["entity.Shot.code", "content", "project.Tank_name"],
            ),
        )
        for task_entity in tasks:
            key = (
                task_entity["project.Tank_name"],
                task_entity["entity.Shot.code"],
                task_entity["entity.Shot.sg_sequence.Sequence.code"],
                task_entity["content"],
            )
            episodic_shot_task_entities[key] = {"id": task_entity["id"], "type": "Task"}



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
