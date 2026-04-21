from git_runner import output, run
from openai_commit import clean_commit_message, generate_commit_message
from tui import approve_commit_message


def add(git_args: list[str]):
    return run(["git", "add", *git_args] if git_args else ["git", "add", "."])


def commit(git_args: list[str]):
    if not git_args:
        return run(["git", "commit"])

    if git_args[0] != "--ai":
        return run(["git", "commit", "-m", " ".join(git_args)])

    if len(git_args) > 1:
        print("Usage: gitx c --ai")
        return 1

    diff_result = output(["git", "diff", "--cached"])
    if diff_result.returncode != 0:
        print(diff_result.stderr.strip() or "Failed to read staged diff.")
        return diff_result.returncode

    diff = diff_result.stdout.strip()
    if not diff:
        print("No staged changes. Stage files first with gitx a or git add.")
        return 1

    response = generate_commit_message(diff)
    if not response or not response.output_text:
        return 1

    if response.used_truncated_diff:
        print("Note: staged diff was truncated before generating the commit message.")

    message = clean_commit_message(response.output_text)
    if not message.strip():
        return 1

    approved_message = approve_commit_message(message)
    if approved_message is None:
        print("Commit cancelled.")
        return 1

    return run(["git", "commit", "-m", approved_message])


def push(git_args: list[str]):
    return run(["git", "push", *git_args] if git_args else ["git", "push"])


def clone(git_args: list[str]):
    if not git_args:
        print("Please provide a repository URL to clone.")
        return 1
    return run(["git", "clone", *git_args])


def checkout_branch(git_args: list[str]):
    if not git_args:
        print("Please provide a branch name.")
        return 1
    return run(["git", "checkout", "-b", *git_args])
