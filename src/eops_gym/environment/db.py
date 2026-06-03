"""Domain database base class."""

from typing import Any

from pydantic import BaseModel

from eops_gym.utils.hash_utils import get_pydantic_hash
from eops_gym.utils.io_utils import PathLike, dump_file, load_file


class DB(BaseModel):
    """Base class for all domain databases.

    A domain DB is a pydantic model whose fields are *collections* — each a
    ``dict[record_id, Record]``. Held entirely in memory; tools mutate it in
    place and the evaluator hashes it for DB-match.
    """

    @classmethod
    def load(cls, path: PathLike) -> "DB":
        """Load the database from a JSON file."""
        return cls.model_validate(load_file(path))

    def dump(self, path: PathLike, **kwargs: Any) -> None:
        """Dump the database to a JSON file."""
        dump_file(path, self.model_dump(), **kwargs)

    def get_hash(self) -> str:
        """Stable hash of the full DB state (used for DB-match)."""
        return get_pydantic_hash(self)
