import sys

from commands import add, checkout_branch, clone, commit, push
from config import setup_ai_config
from git_runner import run


def print_usage():
    # ANSI colors
    BOLD = "\033[1m"
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"

    usage = f"""
{BOLD}Usage:{RESET}
  {BLUE}gitx{RESET} <command> [args...]
  {BLUE}gitx{RESET} --setup-ai

{BOLD}Commands:{RESET}
  {GREEN}a{RESET} [files...]   {YELLOW}Add files to staging area{RESET} (default: all files)
  {GREEN}s{RESET}              {YELLOW}Show git status{RESET}
  {GREEN}c{RESET} [message]    {YELLOW}Commit with message{RESET} (default: opens editor)
  {GREEN}c --ai{RESET}          {YELLOW}Generate commit message from staged diff{RESET}
  {GREEN}p{RESET} [remote]     {YELLOW}Push to remote{RESET} (default: origin)
  {GREEN}l{RESET}              {YELLOW}Show git log in one line format{RESET}
  {GREEN}pl{RESET}             {YELLOW}Pull from remote{RESET}
  {GREEN}cl{RESET} <repo-url>   {YELLOW}Clone a repository{RESET}
  {GREEN}cb{RESET} <branch-name> {YELLOW}Create and checkout a new branch{RESET}
  {GREEN}--setup-ai{RESET}       {YELLOW}Configure OpenAI API key for AI commits{RESET}
"""
    print(usage.strip())


def main():
    if len(sys.argv) < 2:
        print("Usage: gitx <git-command> [args...] use -h or --help for usage.")
        return 1

    git_command = sys.argv[1]
    git_args = sys.argv[2:]

    if sys.argv[1:] == ["--setup-ai"]:
        return setup_ai_config()

    if git_command in ["-h", "--help"]:
        print_usage()
        return 0

    commands = {
        "a": lambda: add(git_args),
        "s": lambda: run(["git", "status"]),
        "c": lambda: commit(git_args),
        "p": lambda: push(git_args),
        "l": lambda: run(["git", "log", "--oneline"]),
        "pl": lambda: run(["git", "pull"]),
        "cl": lambda: clone(git_args),
        "cb": lambda: checkout_branch(git_args),
    }

    if git_command not in commands:
        print(f"Unknown command: {git_command} \nUse -h or --help for usage.")
        return 1

    return commands[git_command]()
