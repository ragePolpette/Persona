from __future__ import annotations

from dataclasses import asdict, dataclass

from argon2.low_level import Type, hash_secret_raw


@dataclass(slots=True)
class Argon2Params:
    time_cost: int = 3
    memory_cost_kib: int = 65536
    parallelism: int = 4
    hash_len: int = 32

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


DEFAULT_ARGON2_PARAMS = Argon2Params()


def derive_key(password: str, salt: bytes, params: Argon2Params = DEFAULT_ARGON2_PARAMS) -> bytes:
    return hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=params.time_cost,
        memory_cost=params.memory_cost_kib,
        parallelism=params.parallelism,
        hash_len=params.hash_len,
        type=Type.ID,
    )

