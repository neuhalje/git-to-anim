# Git to Anim

It should better be called "script to anim". This tooling will run shell scripts in various git repositories and create graphs (snapshots) of the repositories.

The idea is to use these images as input for my [Git from the inside](https://github.com/neuhalje/presentation_git-from-the-inside) talk.

## Example

```yaml
id : abc   # Not used yet
user:      # They are used in the repositories
  alice:
    name: Alice
    email: alice@example.com
  bob:
    name: Bob
    email: bob@example.com
repos:
  upstream:
    path: upstream.git
    bare: Y
  mine:
    path: mine
    bare: N
    user: alice
    remotes:
      - name: origin
        repo: upstream
  bobs:
    path: bob
    bare: N
    user: bob
    remotes:
      - name: origin
        repo: upstream
commands:
  - script:                                            # Shell script
    - echo hallo
    - echo on line 2
    context: mine                                      # In which repo?
  - script:
    - echo hallo2, also in alice context               # The context carries over if not set
    - pwd
  - context: bobs
    script:
      - "echo hello from bob: {repo.user}"             # The repository can be accessed! Each step is a python f-string
      - "echo hello from bob: is bare== {repo.bare}"
  - context: upstream
    script:
      - "echo hello from bob: {repo.user}"
      - "echo hello from bob: is bare== {repo.bare}"

```

# TODO
- [ ] Create the actual images
- [ ] Add comments for each step
- [ ] Add tests
