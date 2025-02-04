import os
from os import PathLike
from pathlib import Path
from typing import Dict, List, Optional, Type, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from dstack._internal.api.repos import load_repo
from dstack._internal.cli.errors import CLIError
from dstack._internal.core.error import RepoNotInitializedError
from dstack._internal.core.repo.remote import RepoError
from dstack._internal.core.userconfig import RepoUserConfig
from dstack._internal.utils.common import get_dstack_dir
from dstack.api.hub import HubClient, HubClientConfig

Model = TypeVar("Model", bound=BaseModel)


# TODO: Move ConfigManager functionality to CLIConfigManager
class ConfigManager:
    def __init__(self, home: PathLike = "~/.dstack"):
        self.home = Path(home).expanduser().resolve()
        self._cache: Dict[str, BaseModel] = {}

    @property
    def ssh_config_path(self) -> Path:
        return _mkdir_parent(self.home / "ssh" / "config")

    def ssh_control_path(self, run_name: str) -> Path:
        return _mkdir_parent(self.home / "ssh" / "controls" / run_name)

    def dstack_key_path(self, repo_dir: Optional[PathLike] = None) -> Path:
        return _mkdir_parent(self.home / "ssh" / "id_rsa")

    @property
    def repos(self) -> Path:
        return self.home / "repos"

    def repo_user_config_path(self, repo_dir: PathLike) -> Path:
        """
        :param repo_dir: target repo directory path (default is cwd)
        :returns: a path to a local repo config
        """
        repo_dir = Path(Path(repo_dir).expanduser()).resolve()
        return self.repos / f"{'.'.join(repo_dir.parts[1:])}.yaml"

    def repo_user_config(self, repo_dir: PathLike) -> RepoUserConfig:
        try:
            return self._cached_read(self.repo_user_config_path(repo_dir), RepoUserConfig)
        except FileNotFoundError:
            raise RepoNotInitializedError("No repo user config found")

    def save_repo_user_config(self, repo_dir: PathLike, value: RepoUserConfig):
        self._cached_write(self.repo_user_config_path(repo_dir), value, mkdir=True)

    @staticmethod
    def write(path: PathLike, model: BaseModel, *, mkdir: bool = False, **kwargs):
        path = Path(path)
        if mkdir:
            path.parent.mkdir(exist_ok=True, parents=True)
        with path.open("w") as f:
            yaml.dump(model.dict(**kwargs), f)

    @staticmethod
    def read(path: PathLike, model: Type[Model], *, non_empty: bool = True) -> Model:
        try:
            with open(path, "r") as f:
                return model(**yaml.load(f, yaml.SafeLoader))
        except FileNotFoundError:
            if non_empty:
                raise
        return model()

    def _cached_read(self, path: PathLike, model: Type[Model], *, non_empty: bool = True) -> Model:
        key = str(Path(path).resolve())
        if key not in self._cache:
            self._cache[key] = self.read(path, model, non_empty=non_empty)
        return self._cache[key]

    def _cached_write(self, path: PathLike, model: BaseModel, *, mkdir: bool = False, **kwargs):
        key = str(Path(path).resolve())
        self._cache[key] = model
        self.write(path, model, mkdir=mkdir, **kwargs)


config = ConfigManager()


class CLIProjectConfig(BaseModel):
    name: str
    url: str
    token: str
    default: Optional[bool]


class CLIConfig(BaseModel):
    projects: List[CLIProjectConfig] = []


class CLIConfigManager:
    def __init__(self, dstack_dir: Optional[Path] = None):
        if dstack_dir is None:
            dstack_dir = get_dstack_dir()
        self.dstack_dir = dstack_dir
        self.config_filepath = self.dstack_dir / "config.yml"
        if not self.config_filepath.exists():
            self.config_filepath = self.dstack_dir / "config.yaml"
        try:
            with open(self.config_filepath, "r") as f:
                config = yaml.load(f.read(), yaml.FullLoader)
            self.config = CLIConfig.parse_obj(config)
        except (FileNotFoundError, ValidationError):
            self.config = CLIConfig()

    def save(self):
        self.dstack_dir.mkdir(parents=True, exist_ok=True)
        with open(self.config_filepath, "w+") as f:
            f.write(yaml.dump(self.config.dict()))

    def configure_project(self, name: str, url: str, token: str, default: bool):
        if default:
            for project in self.config.projects:
                project.default = False
        for project in self.config.projects:
            if project.name == name:
                project.url = url
                project.token = token
                project.default = default or project.default
                return
        self.config.projects.append(
            CLIProjectConfig(name=name, url=url, token=token, default=default)
        )
        if len(self.config.projects) == 1:
            self.config.projects[0].default = True

    def delete_project(self, name: str):
        self.config.projects = [p for p in self.config.projects if p.name != name]

    def get_project_config(self, name: str) -> Optional[CLIProjectConfig]:
        for project in self.config.projects:
            if project.name == name:
                return project
        return None

    def get_default_project_config(self) -> Optional[CLIProjectConfig]:
        for project in self.config.projects:
            if project.default:
                return project
        return None


def get_hub_client_from_config(
    project_config: CLIProjectConfig, repo_dir: PathLike = os.getcwd(), local_repo: bool = False
):
    try:
        repo = load_repo(repo_dir, local_repo)
    except RepoError as e:
        raise CLIError(e.message)
    hub_client_config = HubClientConfig(url=project_config.url, token=project_config.token)
    hub_client = HubClient(config=hub_client_config, project=project_config.name, repo=repo)
    return hub_client


def get_hub_client(
    project_name: Optional[str] = None, repo_dir: PathLike = os.getcwd(), local_repo: bool = False
) -> HubClient:
    cli_config_manager = CLIConfigManager()
    if project_name is not None:
        project_config = cli_config_manager.get_project_config(project_name)
        if project_config is None:
            raise CLIError(
                f"The '{project_name}' project is not configured. Call `dstack config`."
            )
    else:
        project_config = cli_config_manager.get_default_project_config()
        if project_config is None:
            raise CLIError(
                f"No default project is configured. Call `dstack start` or `dstack config`."
            )
    hub_client = get_hub_client_from_config(project_config, repo_dir, local_repo)
    return hub_client


def _mkdir_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
