name = "javelin"

version = "0.1.0"


build_requires = ["dunc-1"]
build_command = "dunc"

requires = ["QtPy", "shotgun_api3", "fast_blurhash", "Fileseq"]


def commands():
    env.PYTHONPATH.append("{root}/src")

    if "nuke" in resolve:
        env.NUKE_PATH.append("{root}/src/javelin/ui/nuke")


def install():
    import dunc

    dunc.install_files(dunc.find_files("src/**/*"), symlink=True)
