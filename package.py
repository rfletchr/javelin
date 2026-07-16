name = "javelin"

version = "0.1.0"


build_requires = ["dunc-1"]
build_command = "dunc"

requires = ["QtPy", "shotgun_api3", "fast_blurhash", "Fileseq"]


def commands():
    import os

    env.PYTHONPATH.append("{root}/src")

    project_dir = os.environ.get("JAVELIN_PROJECT_PATH", "")

    ocio_file = os.path.join(project_dir, "init", "ocio", "config.ocio")
    if os.path.exists(ocio_file):
        env.OCIO = ocio_file

    if "nuke" in resolve:
        env.NUKE_PATH.append("{root}/src/javelin/nuke")

        gizmo_dir = os.path.join(project_dir, "init", "nuke", "gizmos")
        if os.path.exists(gizmo_dir):
            env.NUKE_PATH.append(gizmo_dir)


def install():
    import dunc

    dunc.install_files(dunc.find_files("src/**/*"), symlink=True)
