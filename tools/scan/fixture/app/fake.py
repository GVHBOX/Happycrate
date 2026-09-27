import os
from typing import overload

DEAD_CONST = 42


def never_used():
    return 1


def multi_arity(x):
    if x:
        return True, "ok"
    return False, "bad", 1, 2


def nested_inner_consistent(x):
    def inner(y):
        if y:
            return 1, 2
        return 3, 4

    if x:
        return True, "a"
    return False, "b"


def nested_inner_broken(x):
    def inner(y):
        if y:
            return 1, 2
        return 3, 4, 5

    return True, "a"


USED_CONST = 7


def uses_const():
    return USED_CONST, os.name


def repeated_name():
    return 1


def repeated_name():
    return 2


@overload
def overloaded(x: int) -> int:
    ...


@overload
def overloaded(x: str) -> str:
    ...


def overloaded(x):
    return x


def keep_trying(values):
    for item in values:
        try:
            return int(item)
        except ValueError:
            continue
    return 0


def quiet_swallow(path):
    try:
        os.unlink(path)
    except OSError:
        pass
