#!/usr/bin/env python3
import sys
import subprocess

def run(cmd):
    return subprocess.call(cmd, shell=True)


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

{BOLD}Commands:{RESET}
  {GREEN}a{RESET} [files...]   {YELLOW}Add files to staging area{RESET} (default: all files)
  {GREEN}s{RESET}              {YELLOW}Show git status{RESET}
  {GREEN}c{RESET} [message]    {YELLOW}Commit with message{RESET} (default: opens editor)
  {GREEN}p{RESET} [remote]     {YELLOW}Push to remote{RESET} (default: origin)
  {GREEN}l{RESET}              {YELLOW}Show git log in one line format{RESET}
"""
    print(usage.strip())

def main():
    if len(sys.argv) < 2:
        print("Usage: gitx <git-command> [args...] use -h or --help for usage.")
        sys.exit(1)

    git_command = sys.argv[1]
    git_args = sys.argv[2:]
    
    commands = {
        "a": lambda: run(["git", "add", *git_args] if git_args else ["git", "add", "."]),
        "s": lambda: run(["git", "status"]),
        "c": lambda: run(["git", "commit", "-m", " ".join(git_args)] if git_args else ["git", "commit"]),
        "p": lambda: run(["git", "push", *git_args] if git_args else ["git", "push"]),
        "l": lambda: run(["git", "log", "--oneline"]),
    }
    
    # See if help flag or no flags
    if git_command in ["-h", "--help"]:
        print_usage()
        sys.exit(0)
    
    if git_command not in commands:
        print(f"Unknown command: {git_command} \nUse -h or --help for usage.")
        sys.exit(1)
        
    sys.exit(commands[git_command]())

if __name__ == "__main__":
    sys.exit(main())