import os
import subprocess
import sys
import tempfile
from copy import copy
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


class RemoteWrapper(Remote):

    @staticmethod
    def wrap(r: Remote, context, wdir: str) -> Remote:
        return RemoteWrapper(r.name, r.repo, context, wdir)

    def __init__(self, name: str, repo: RepoId, context, wdir: str):
        super().__init__(name, repo)
        self.context = context
        self.wdir = wdir

    def remote_path(self):
        return os.path.join(self.wdir, self.context.git_repos[self.repo].path)

    def repository(self):
        return self.context.git_repos[self.repo]


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
        if self.user:
            assert self.user in context.user_repo, "{self.user} should be in user repo"


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
    def __init__(self, command, formatted_command: str, stdout: str,
                 stderr: str, exit_code: int, pwd: str):
        self.formatted_command = formatted_command
        self.pwd = pwd
        self.stderr = stderr
        self.stdout = stdout
        self.command = command
        self.exit_code = exit_code

    def __repr__(self) -> str:
        return f"{self.formatted_command} -> {self.exit_code} : {self.stdout}"


class Command(object):
    def __init__(self, cmd: str):
        self.cmd = cmd

    def format(self, context: ExecutionContext, git_repo: GitRepo) -> str:
        user = context.user_repo.get(git_repo.user)
        repo = git_repo
        user = user
        git_repos = context.git_repos
        users = context.user_repo

        return eval("f'{}'".format(self.cmd))

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
            result = subprocess.run(command, shell=True, capture_output=True)
            return CommandExecutionResult(self, command, result.stdout.decode(
                sys.stdout.encoding),
                                          result.stderr.decode(
                                              sys.stderr.encoding),
                                          result.returncode, git_repo.path)
        finally:
            os.chdir(cwd)


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
        repo = copy(context.git_repos[self.repo])
        remotes = {}
        for rid in repo.remotes:
            remotes[rid] = RemoteWrapper.wrap(repo.remotes[rid], context, wdir)
        repo.remotes = remotes
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


class Renderer(object):
    __TO_DOT="""
if [[ ${PWD} == "/tmp/"* ]];then
                echo 'digraph git {'
                echo 'graph [bgcolor=transparent]'

                git rev-list -g --all --pretty='tformat:  "%H" [label="%h"]; "%H-msg" [label="%s" margin="0" shape="none" ]; "%H" -> "%H-msg" [K="0.0" arrowhead="none" style="dotted" dir="backward"]; {rank=same "%H" "%H-msg"}'|grep -v ^commit|sort|uniq

                echo
                git show-ref -s | while read ref; do
                    git log --pretty='tformat:  %H -> { %P };' $ref | sed 's/[0-9a-f][0-9a-f]*/\"&\"/g'
                done | sort | uniq
                echo

                # branch label
                git branch -l  --format='"%(refname:lstrip=2)" [label="%(refname:lstrip=2)" shape="cds" style="filled" fillcolor="darkgoldenrod1" ]; "%(refname:lstrip=2)" -> "%(objectname)"  [arrowhead="none"];{rank=same "%(refname:lstrip=2)" "%(objectname)"};'

                git branch -l -r  --format='"%(refname:lstrip=2)" [label="%(refname:lstrip=2)" shape="cds" style="filled,dashed" fillcolor="darkgoldenrod1" ]; "%(refname:lstrip=2)" -> "%(objectname)"  [arrowhead="none"];{rank=same "%(refname:lstrip=2)" "%(objectname)"};'

                git tag -l  --format='"%(objectname)" [label="Tag: %(refname:lstrip=2)" shape="box" style="filled" ]; "%(object)" -> "%(objectname)" [arrowhead="none"];{rank=same "%(objectname)" "%(object)"};'

                # ranking
                echo "}"
            else
                echo "ERROR: Will only run in /tmp but repo='${PWD}'" >&1
                exit 1
            fi
    """

    def __init__(self):
        self.to_dot = Command(self.__TO_DOT)
        self.steps = []

    def pre_exec(self, wdir: str, context: ExecutionContext,
                git_repo: GitRepo):
        pass

    def post_exec(self, wdir: str, context: ExecutionContext,
                git_repo: GitRepo):
        r = self.to_dot.execute(wdir, context, git_repo)
        self.steps.append(r.stdout)

    def render(self) -> str:
        return ""


if __name__ == '__main__':
    s = load_script(open("tests/example-git-command.yaml", 'r'))
    s.validate()

    result = s.execute()

    print(f"temp: {result.wdir}")
    for cr in result.results:
        print(cr)
