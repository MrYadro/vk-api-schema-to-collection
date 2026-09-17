import dataclasses
import functools

from core import build as _core_build


@dataclasses.dataclass(frozen=True)
class BuildContext:
    schema_dir: object
    api_version: str
    name: str
    descriptions: object
    include_all: bool


@dataclasses.dataclass(frozen=True)
class FormatSpec:
    name: str
    default_out: str
    stats_keys: tuple
    model_based: bool
    build: object
    write: object
    supports_merge: bool = False
    load_existing: object = None
    prune_orphans: object = None
    keep_old_items: bool = True
    matches: object = None
    validate: object = None


@functools.lru_cache(maxsize=None)
def build_collection(ctx):
    return _core_build(ctx.schema_dir, ctx.api_version, ctx.name, ctx.descriptions, ctx.include_all)


from formats import openapi as _openapi
from formats import opencollection as _opencollection
from formats import hoppscotch as _hoppscotch
from formats import insomnia as _insomnia
from formats import postman as _postman
from formats import postman_v3 as _postman_v3

FORMATS = {
    "tree": _opencollection.TREE_SPEC,
    "bundled": _opencollection.BUNDLED_SPEC,
    "postman": _postman.POSTMAN_SPEC,
    "hoppscotch": _hoppscotch.HOPPSCOTCH_SPEC,
    "insomnia": _insomnia.INSOMNIA_SPEC,
    "openapi": _openapi.OPENAPI_SPEC,
    "postman-v3": _postman_v3.POSTMAN_V3_SPEC,
}
