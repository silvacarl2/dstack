import botocore.exceptions

from dstack._internal.core.backends.aws.compute import AWSCompute
from dstack._internal.core.backends.aws.config import AWSConfig
from dstack._internal.core.backends.base import Backend
from dstack._internal.core.errors import BackendInvalidCredentialsError


class AwsBackend(Backend):
    NAME = "aws"

    def __init__(self, config: AWSConfig):
        self.config = config
        self._compute = AWSCompute(self.config)
        self._check_credentials()

    def compute(self) -> AWSCompute:
        return self._compute

    def _check_credentials(self):
        try:
            # TODO
            self.list_repo_heads()
        except (botocore.exceptions.ClientError, botocore.exceptions.NoCredentialsError):
            raise BackendInvalidCredentialsError()
