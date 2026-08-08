import enum

import nuke

from javelin import ContextClasses
from javelin.errors import NotSavedError, WriteNodeError


class KnobNames(enum.StrEnum):
    Identifier = "__write_node"
    TemplateName = "__write_node_template_name"
    Extension = "__write_node_exension"
    OutputName = "__write_node_output_name"


def is_write_node(node: nuke.Node):
    """
    Does the node have the full required knob set?
    """
    if not isinstance(node, (nuke.Group, nuke.Gizmo)):
        return False

    knobs = node.knobs()
    for knob_name in KnobNames:
        if not knob_name in knobs:
            return False

    return True


def is_session_saved():
    return nuke.root().name != "Root"


def is_session_modified():
    return nuke.root().modified()


def get_version_number(node: nuke.Node, context: ContextClasses):
    if not is_session_saved:
        raise NotSavedError

    path = nuke.root().name()

    fields = {}

    for workfile_def in context.definition.workfiles:
        fields = workfile_def.template.fullmatch(path)
        if not fields:
            continue

    if not fields:
        raise WriteNodeError(f"unable to resolve workfile template for: {path}")

    return fields["version"]
