from miniagent import cli


def test_shell_permission_network():
    assert cli._classify_shell_permission("pip install requests") == "network"
    assert cli._classify_shell_permission("curl https://example.com") == "network"


def test_shell_permission_git_write():
    assert cli._classify_shell_permission("git add .") == "git-write"
    assert cli._classify_shell_permission("git commit -m test") == "git-write"


def test_shell_permission_file_write():
    assert cli._classify_shell_permission("echo hi > a.txt") == "workspace-write"
    assert cli._classify_shell_permission("New-Item a.txt") == "workspace-write"


def test_shell_permission_destructive():
    assert cli._classify_shell_permission("Remove-Item a.txt") == "destructive"


def test_shell_permission_readonly():
    assert cli._classify_shell_permission("git status") == "read-only"
