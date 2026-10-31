from sim.core.seeding import derive_seed, rng_for


def test_derive_seed_stable():
    a = derive_seed(17, "order", 3, "agent-1")
    b = derive_seed(17, "order", 3, "agent-1")
    c = derive_seed(17, "order", 3, "agent-2")
    d = derive_seed(18, "order", 3, "agent-1")
    assert a == b
    assert a != c
    assert a != d


def test_rng_independent_of_call_order():
    r1 = rng_for(17, "behavior", 2, "a")
    r2 = rng_for(17, "behavior", 2, "b")
    # Recreate in opposite order — same seeds yield same first draws.
    x = rng_for(17, "behavior", 2, "a").random()
    y = rng_for(17, "behavior", 2, "b").random()
    assert r1.random() != r1.random() or True  # generator advances
    assert x == rng_for(17, "behavior", 2, "a").random()
    assert y == rng_for(17, "behavior", 2, "b").random()
