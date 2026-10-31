import pytest

from ccdeck import cli, config
from ccdeck.config import ConfigError

BASE = """
hosts:
  vm: {ssh: user@vm}
accounts:
  personal: {config_dir: ~/.claude}
  work: {config_dir: ~/.claude-work, env: {ANTHROPIC_API_KEY: sk-x}}
sessions:
  - {name: a, host: local, dir: ~/a, account: personal}
"""


def parse(text):
    import yaml
    return config.parse(yaml.safe_load(text))


def test_parses_full_config():
    cfg = parse(BASE)
    assert set(cfg.hosts) == {"local", "vm"}
    assert cfg.hosts["vm"].ssh == "user@vm"
    assert cfg.accounts["work"].env == {"ANTHROPIC_API_KEY": "sk-x"}
    assert cfg.sessions[0].name == "a"
    assert cfg.refresh == 3 and cfg.detach_key == "C-q"


def test_empty_accounts_uses_default():
    cfg = parse("sessions: [{name: a, dir: /x}]")
    assert list(cfg.accounts) == ["default"]
    assert cfg.accounts["default"].config_dir == "~/.claude"
    assert cfg.sessions[0].account == "default"


def test_refresh_minimum():
    assert parse("refresh: 0.1").refresh == 1


@pytest.mark.parametrize("text,needle", [
    ("sessions: [{name: a, host: nope, dir: /x}]", "unknown host 'nope'"),
    (BASE + "  - {name: b, dir: /x, account: ghost}", "unknown account 'ghost'"),
    (BASE + "  - {name: b, account: work}", "session 'b': missing 'dir'"),
    ("hosts: {vm: {claude: x}}", "host 'vm': missing 'ssh'"),
    (BASE + "  - {name: a, dir: /y, account: work}", "session 'a': duplicate"),
    (BASE + "  - {name: 'bad name', dir: /y, account: work}", "invalid name"),
])
def test_validation_errors(text, needle):
    with pytest.raises(ConfigError) as e:
        parse(text)
    assert needle in str(e.value)
    assert "\n" not in str(e.value)


def test_invalid_config_cli_prints_one_line(env, capsys):
    env.write_config("sessions: [\n  - {name: a\n")
    assert cli.main(["ls"]) == 2
    err = capsys.readouterr().err.strip()
    assert err.startswith("ccdeck: invalid YAML") and "\n" not in err

    env.write_config("sessions: [{name: a, host: mars, dir: /x}]")
    assert cli.main(["ls"]) == 2
    assert capsys.readouterr().err.strip() == "ccdeck: session 'a': unknown host 'mars'"


def test_init_writes_example_that_loads(env, capsys):
    assert cli.main(["init"]) == 0
    assert env.config.exists()
    cfg = config.load()
    assert cfg.sessions == [] and "personal" in cfg.accounts
    assert cli.main(["init"]) == 0
    assert "already exists" in capsys.readouterr().out
