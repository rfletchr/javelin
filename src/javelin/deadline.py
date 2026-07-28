from __future__ import annotations
import typing
import dataclasses
import tempfile
import subprocess
import fnmatch
import json
import os

ENV_BLACKLIST = (
    "USER",
    "USERNAME",
    "HOME",
    "DISPLAY",
    "NUKE_TEMP_DIR",
    "MAYA_APP_DIR",
)

DEFAULT_PATTERNS = (
    "MAYA*",
    "REZ_*",
    "NUKE*",
    "PYTHONPATH*",
    "LD_LIBRARY_PATH",
    "PATH",
    "PROJECT_PATH",
)


class NukeInfo(typing.TypedDict):
    SceneFile: str
    Version: str
    WriteNode: str


class ShotgridVersionInfo(typing.TypedDict):
    VersionId: str
    MovFile: str


class JobInfo(typing.TypedDict):
    Plugin: str
    Frames: str
    Name: str

    Comment: typing.NotRequired[str]
    Department: typing.NotRequired[str]
    ChunkSize: typing.NotRequired[int]
    Priority: typing.NotRequired[int]
    Group: typing.NotRequired[str]
    Pool: typing.NotRequired[str]
    ForceReloadPlugin: typing.NotRequired[bool]
    LimitGroups: typing.NotRequired[str]

    ExtraInfo0: typing.NotRequired[str]
    ExtraInfo1: typing.NotRequired[str]
    ExtraInfo2: typing.NotRequired[str]
    ExtraInfo3: typing.NotRequired[str]
    ExtraInfo4: typing.NotRequired[str]
    ExtraInfo5: typing.NotRequired[str]
    ExtraInfo6: typing.NotRequired[str]
    ExtraInfo7: typing.NotRequired[str]
    ExtraInfo8: typing.NotRequired[str]
    ExtraInfo9: typing.NotRequired[str]

    Environment: typing.NotRequired[dict[str, str]]
    OutputFilenames: typing.NotRequired[list[str]]
    ExtraInfoKeyValues: typing.NotRequired[dict[str, str]]


@dataclasses.dataclass(eq=False)
class DeadlineJob:
    job_info: JobInfo
    plugin_info: NukeInfo | ShotgridVersionInfo
    depends_on: list[DeadlineJob] = dataclasses.field(default_factory=list)


def write_info_file(filepath: str, info_dict: dict[str, str | int | float | bool]):
    """
    write the given info_dict to disk in deadlines info file format
    Args:
        filepath: the output file
        info_dict: the data to write

    Returns:

    """
    with open(filepath, mode="w") as file:
        file.writelines([f"{k}={v}\n" for k, v in info_dict.items()])


def prepare_job_info(job_info: JobInfo) -> dict[str, str | int | float | bool]:
    result: dict[str, object] = {k: v for k, v in job_info.items() if v is not None}

    if "ForceReloadPlugin" in result:
        result["ForceReloadPlugin"] = "1" if result["ForceReloadPlugin"] else "0"

    if "Environment" in result and isinstance(result["Environment"], dict):
        env = typing.cast(dict, result.pop("Environment"))
        filtered_env = {k: v for k, v in env.items() if k not in ENV_BLACKLIST}

        for i, (k, v) in enumerate(filtered_env.items()):
            result[f"EnvironmentKeyValue{i}"] = f"{k}={v}"

    if "OutputFilenames" in result and isinstance(result["OutputFilenames"], list):
        outputs = typing.cast(list[str], result.pop("OutputFilenames"))
        for index, output in enumerate(outputs):
            result[f"OutputFilename{index}"] = output

    if "ExtraInfoKeyValues" in result and isinstance(result["ExtraInfoKeyValues"], dict):
        extra = typing.cast(dict, result.pop("ExtraInfoKeyValues"))
        for i, (k, v) in enumerate(extra.items()):
            result[f"ExtraInfoKeyValue{i}"] = f"{k}={v}"

    return result  # type: ignore


def _topological_sort(jobs: list[DeadlineJob]) -> list[DeadlineJob]:
    visited: set[DeadlineJob] = set()
    result: list[DeadlineJob] = []

    def visit(job: DeadlineJob) -> None:
        if job in visited:
            return
        visited.add(job)
        for dep in job.depends_on:
            visit(dep)
        result.append(job)

    for job in jobs:
        visit(job)

    return result


def _parse_job_id(output: bytes) -> str:
    for line in output.decode("utf-8").splitlines():
        if line.startswith("JobID="):
            return line[len("JobID=") :].strip()
    raise RuntimeError("Could not parse JobID from deadlinecommand output.")


def submit(
    deadline_jobs: list[DeadlineJob],
    batch_name: str | None = None,
    deadline_command: str | None = None,
) -> list[DeadlineJob]:
    # deadlinecommand <job_info> <plugin_info> — one job at a time so real job IDs
    # can be passed as JobDependencies to subsequent jobs.
    cmd = deadline_command or "deadlinecommand"
    submitted_ids: dict[DeadlineJob, str] = {}

    with tempfile.TemporaryDirectory() as temp_dir:
        for index, job in enumerate(_topological_sort(deadline_jobs)):
            job_info_path = f"{temp_dir}/job_{index}_info.txt"
            plugin_info_path = f"{temp_dir}/job_{index}_plugin.txt"

            job_info = prepare_job_info(job.job_info)

            if batch_name:
                job_info["BatchName"] = batch_name

            dep_ids = [submitted_ids[dep] for dep in job.depends_on]
            if dep_ids:
                job_info["JobDependencies"] = ",".join(dep_ids)

            plugin_info = typing.cast(dict, job.plugin_info)
            write_info_file(job_info_path, job_info)
            write_info_file(plugin_info_path, plugin_info)

            try:
                result = subprocess.run(
                    [cmd, job_info_path, plugin_info_path],
                    check=True,
                    capture_output=True,
                )
            except subprocess.CalledProcessError as e:
                error_message = e.stderr.decode("utf-8") if e.stderr else "No error details available."
                raise RuntimeError(f"Failed to submit Deadline job '{job.job_info['Name']}': {error_message}") from e

            submitted_ids[job] = _parse_job_id(result.stdout)

    return submitted_ids


def get_filtered_env(
    match_exprs: list[str] | tuple[str, ...] | None = None,
) -> dict[str, str]:
    match_exprs = match_exprs or DEFAULT_PATTERNS
    env = os.environ.copy()

    for key in list(env.keys()):
        if not any(fnmatch.fnmatch(key, pattern) for pattern in match_exprs):
            del env[key]

    return env


def resolve_rez_env(
    packages: list[str],
    match_exprs: list[str] | tuple[str, ...] | None = None,
) -> dict[str, str]:

    # Project Path is used by some rez packages to determine the correct environment.
    project_path = _get_project_path()
    if project_path:
        os.environ["PROJECT_PATH"] = project_path

    match_exprs = match_exprs or DEFAULT_PATTERNS
    result = subprocess.check_output(
        [
            "rez",
            "env",
            *packages,
            "--",
            "python",
            "-c",
            "import os,json,sys; json.dump(dict(os.environ), sys.stdout)",
        ]
    )
    env: dict[str, str] = json.loads(result)
    return {k: v for k, v in env.items() if k not in ENV_BLACKLIST and any(fnmatch.fnmatch(k, p) for p in match_exprs)}


def _get_project_path():
    try:
        import tank

        engine = typing.cast(tank.platform.Engine, tank.platform.current_engine())
        if not engine:
            return None

        sgtk = typing.cast(tank.Sgtk, engine.sgtk)
        return sgtk.project_path

    except Exception:
        return None


if __name__ == "__main__":
    import os

    env = get_filtered_env(DEFAULT_PATTERNS)
    print("Filtered Environment Variables:")
    for key, value in env.items():
        print(f"  {key}: {value}")
