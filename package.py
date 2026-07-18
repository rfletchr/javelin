name = "javelin"

version = "0.5.0"


build_requires = ["dunc-1"]
build_command = "dunc"

requires = ["QtPy", "shotgun_api3", "fast_blurhash", "Fileseq", "QtAwesome"]


def commands():
    import os

    env.PATH.append("{root}/bin")

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


def build():
    import os
    import subprocess

    import dunc

    qrc_path = os.path.join(dunc.get_source_path(), "icons", "icons.qrc")
    out_path = os.path.join(dunc.get_build_path(), "src", "javelin", "ui", "resources_rc.py")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    print(f"[build] compiling Qt resources: {qrc_path} -> {out_path}")
    subprocess.run(["rez", "env", "PySide6", "--", "pyside6-rcc", qrc_path, "-o", out_path], check=True)


def install():
    import dunc

    dunc.install_files(dunc.find_files("src/**/*"), symlink=True)
    dunc.install_files(dunc.find_files("bin/*"), symlink=True)
    # resources_rc.py was generated straight into build_path/src/... by build() above -
    # install it the same way as everything under source_path's src/**/*.
    dunc.install_files(dunc.find_files("src/**/*", root=dunc.get_build_path()), symlink=True)
