import subprocess


def run(cmd):
    return subprocess.call(cmd)


def output(cmd):
    return subprocess.run(cmd, check=False, capture_output=True, text=True)
