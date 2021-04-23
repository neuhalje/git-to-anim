import os
import tempfile
from typing import Type, Dict, List

import yaml

UserId = str
RepoId = str


class User(object):

    def __init__(self, user_id: UserId, name: str, email: str):
        self.user_id = user_id
        self.name = name
        self.email = email

    def validate(self, context):
        assert self.email and len(self.email) > 0, "User: email not set"
        assert self.name and len(self.name) > 0, "User: name not set"
        assert self.user_id and len(self.user_id) > 0, "User: user_id not set"


UserRepo = Type[Dict[UserId, User]]


class Remote(object):
    def __init__(self, name: str, repo: RepoId):
        self.repo = repo
        self.name = name

    def validate(self, context):
        assert self.repo and len(self.repo) > 0, "Remote: repo not set"
        assert context.git_repos[self.repo], f"Remote: Context should contain " \
                                             f"repo named {self.repo}"

        assert self.name and len(self.name) > 0, "Remote: name not set"


Remotes = Type[Dict[str, Remote]]


class GitRepo(object):
    def __init__(self, repo_id: RepoId, path: str, bare: bool, user: UserId,
                 remotes: Remotes = None):
        self.repo_id = repo_id
        self.remotes = remotes if remotes else {}
        self.user = user
        self.bare = bare
        self.path = path

    def validate(self, context):
        assert self.repo_id and len(
            self.repo_id) > 0, "GitRepo: repo_id not set"
        assert self.user or self.bare, "GitRepo: user not set for none bare " \
                                       "repo"
        assert self.path, "GitRepo: path not set"

        for r in self.remotes.values():
            r.validate(context)


GitRepos = Type[Dict[RepoId, GitRepo]]


class ExecutionContext(object):
    def __init__(self, user_repo: UserRepo, git_repos: GitRepos):
        self.git_repos = git_repos
        self.user_repo = user_repo

    def validate(self):
        for r in self.git_repos.values():
            r.validate(self)

        for u in self.user_repo.values():
            u.validate(self)


class CommandExecutionResult(object):
    def __init__(self, command, formatted_command:str, stdout: str, stderr:
    str,
                 exit_code: int, pwd: str):
        self.formatted_command = formatted_command
        self.pwd = pwd
        self.stderr = stderr
        self.stdout = stdout
        self.command = command
        self.exit_code = exit_code


class Command(object):
    def __init__(self, cmd: str):
        self.cmd = cmd

    def format(self, context: ExecutionContext, git_repo: GitRepo) -> str:
        user = context.user_repo.get(git_repo.user)
        return self.cmd.format(repo=git_repo, user=user)

    def _ensure_in_dir(self, directory: str):
        if os.path.isfile(directory):
            raise ValueError(f"{directory} is a file!")

        if not os.path.isdir(directory):
            os.mkdir(directory)
        os.chdir(directory)

    def execute(self, wdir: str, context: ExecutionContext,
                git_repo: GitRepo) -> CommandExecutionResult:

        cwd = os.getcwd()
        # git_repo.path can be relative. Ensure we are in wdir
        self._ensure_in_dir(wdir)
        command = self.format(context, git_repo)

        try:
            self._ensure_in_dir(git_repo.path)
            print(command)
        finally:
            os.chdir(cwd)
        return CommandExecutionResult(self, command, "stdout", "stderr", 0,
                                      git_repo.path)


Commands = List[Command]


class CommandSet(object):
    def __init__(self, repo: RepoId, commands: Commands):
        self.repo = repo
        self.commands = commands

    def validate(self, context: ExecutionContext):
        assert self.repo in context.git_repos, f"CommandSet: Cannot find " \
                                               f"repo {self.repo} in  " \
                                               f"context."

    def _format_commands(self, context: ExecutionContext):
        repo = context.git_repos[self.repo]
        return [c.format(context, repo) for c in self.commands]

    def execute(self, wdir: str, context: ExecutionContext):
        repo = context.git_repos[self.repo]
        return [c.execute(wdir, context, repo) for c in self.commands]


CommandSets = List[CommandSet]


class ScriptResult(object):
    def __init__(self, wdir: str, results: List[CommandExecutionResult]):
        self.results = results
        self.wdir = wdir


class Script(object):
    def __init__(self, script_id: str, context: ExecutionContext, commands: \
            CommandSets):
        self.id = script_id
        self.context = context
        self.commands = commands

    def validate(self):
        self.context.validate()
        for c in self.commands:
            c.validate(self.context)

    def execute(self) -> ScriptResult:
        self.validate()
        wdir = tempfile.mkdtemp()

        results = []
        for commandset in self.commands:
            results.extend(commandset.execute(wdir, self.context))

        return ScriptResult(wdir, results)

def load_script(script) -> Script:
    s = yaml.safe_load(script)
    script_id = s["id"]

    user_repo: UserRepo = dict()
    for user_id, user_dict in s["user"].items():
        user_repo[user_id] = User(user_id, user_dict["name"],
                                  user_dict["email"])

    """
    mine:
      path: mine
      bare: N
      user: alice
      remotes:
        - name: origin
          repo: upstream
    """
    git_repos: GitRepos = dict()
    for repo_id, repo_dict in s["repos"].items():
        remotes = dict()

        for r in repo_dict.get("remotes", []):
            remotes[str(r["name"])] = Remote(r["name"], r["repo"])

        git_repos[repo_id] = GitRepo(repo_id,
                                     repo_dict["path"],
                                     repo_dict.get("bare", False),
                                     repo_dict.get("user", None),
                                     remotes)
    current_repo = None
    command_sets = list()

    for cmd in s["commands"]:
        script = cmd["script"]
        # Allow "script: do something"
        if isinstance(script, str):
            script = [script]

        current_repo = cmd.get("context") or current_repo

        assert current_repo, "Context needs to be set"

        command_sets.append(CommandSet(current_repo, [Command(s) for s in
                                                      script]))

    return Script(script_id, ExecutionContext(user_repo, git_repos),
                  command_sets)


if __name__ == '__main__':
    s = load_script(open("tests/example-command.yaml", 'r'))
    s.validate()

    result = s.execute()

    print(f"temp: {result.wdir}")
    for cr  in result.results:
        print(cr.formatted_command)


