from sim.db.cache import make_cache_key


def test_cache_key_canonical():
    a = make_cache_key(
        model="stub-llm",
        model_digest="v1",
        role="system2",
        request={"b": 2, "a": 1},
        options={"temperature": 0.7, "seed": 99},
    )
    b = make_cache_key(
        model="stub-llm",
        model_digest="v1",
        role="system2",
        request={"a": 1, "b": 2},
        options={"seed": 99, "temperature": 0.7},
    )
    c = make_cache_key(
        model="stub-llm",
        model_digest="v1",
        role="system2",
        request={"a": 1, "b": 2},
        options={"seed": 100, "temperature": 0.7},
    )
    assert a == b
    assert a != c
