import subprocess


def run(cmd: str | list[str]):
    return subprocess.call(cmd)


def output(cmd: str | list[str]):
    return subprocess.run(cmd, check=False, capture_output=True, text=True)
