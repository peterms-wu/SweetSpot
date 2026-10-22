"""Model registry by (name, version) (feature 008 research R4; tasks T003)."""

import argparse

import pytest

from sweetspot.forecast.models import CURRENT_MODEL, REGISTRY, build_model, current_model, model_class, register


class _Toy:
    name = "toy-model"
    version = "1.0.0"
    tw_only_params = frozenset({"a"})

    def __init__(self, a: int = 1):
        self.a = a

    @classmethod
    def from_params(cls, raw):
        unknown = set(raw) - {"a"}
        if unknown:
            raise ValueError(f"toy 沒有這些參數：{unknown}")
        return cls(**{k: int(v) for k, v in raw.items()})

    @property
    def params(self):
        return {"a": self.a}


class _Toy2(_Toy):
    version = "1.10.0"
    tw_only_params = frozenset({"a", "b"})

    def __init__(self, a: int = 1, b: int = 0):
        super().__init__(a)
        self.b = b

    @classmethod
    def from_params(cls, raw):
        unknown = set(raw) - {"a", "b"}
        if unknown:
            raise ValueError(f"toy 沒有這些參數：{unknown}")
        return cls(**{k: int(v) for k, v in raw.items()})

    @property
    def params(self):
        return {"a": self.a, "b": self.b}


@pytest.fixture
def toys():
    register(_Toy)
    register(_Toy2)
    yield
    REGISTRY.pop("toy-model", None)


def test_registry_is_keyed_by_name_and_version(toys):
    assert set(REGISTRY["toy-model"]) == {"1.0.0", "1.10.0"}
    assert model_class("toy-model", "1.0.0") is _Toy
    assert model_class("toy-model") is _Toy2                      # latest by numeric version, not by string order


def test_build_model_takes_a_version_or_the_latest(toys):
    assert build_model("toy-model", {"a": "3"}, version="1.0.0").params == {"a": 3}
    assert isinstance(build_model("toy-model", {"a": "3"}), _Toy2)
    assert isinstance(build_model("toy-model@1.0.0", {}), _Toy)


def test_unknown_version_lists_the_available_ones(toys):
    with pytest.raises(ValueError, match=r"1\.0\.0.*1\.10\.0"):
        build_model("toy-model", {}, version="2.0.0")
    with pytest.raises(ValueError, match="未知的模型"):
        build_model("no-such-model", {})


def test_current_model_uses_the_declared_version():
    name, version, params = CURRENT_MODEL
    model = current_model()
    assert (model.name, model.version, model.params) == (name, version, dict(params))


def test_seasonal_record_versions_are_both_registered():
    assert {"1.0.0", "1.1.0"} <= set(REGISTRY["seasonal-record"])
    assert build_model("seasonal-record@1.0.0", {}).version == "1.0.0"
    assert build_model("seasonal-record@1.1.0", {}).version == "1.1.0"


def test_a_bare_current_name_means_the_current_version():
    name, version, _ = CURRENT_MODEL
    assert build_model(name, {}).version == version


def _args(model=None, params=()):
    return argparse.Namespace(model=model, param=list(params))


def test_model_from_args_accepts_name_at_version(toys):
    from sweetspot.commands import model_from_args

    assert model_from_args(_args()).version == CURRENT_MODEL[1]
    model = model_from_args(_args("toy-model@1.0.0", ["a=5"]))
    assert (model.version, model.params) == ("1.0.0", {"a": 5})
    old = model_from_args(_args(f"{CURRENT_MODEL[0]}@1.0.0"))
    assert old.version == "1.0.0"
    assert set(old.params) <= set(CURRENT_MODEL[2]) | {"min_sales", "half_life", "hazard_history"}


def test_compare_reads_tw_only_params_of_the_results_version(toys):
    from sweetspot.forecast.backtest.compare import _tw_only_params

    assert _tw_only_params({"name": "toy-model", "version": "1.0.0"}) == frozenset({"a"})
    assert _tw_only_params({"name": "toy-model", "version": "1.10.0"}) == frozenset({"a", "b"})
    assert _tw_only_params({"name": "toy-model", "version": "9.9.9"}) == frozenset()


# --- feature 008 US4: the switch (tasks T030) --------------------------------------------------------------------

def test_current_model_is_1_1_0_and_1_0_0_stays_reachable():
    assert CURRENT_MODEL == ("seasonal-record", "1.1.0", {"min_sales": 1, "half_life": 2, "hazard_history": "TW+US",
                                                           "low_base": "new-split", "shrink": 0.5})
    assert current_model().version == "1.1.0"
    from sweetspot.commands import model_from_args

    old = model_from_args(_args("seasonal-record@1.0.0"))
    assert (old.version, old.params) == ("1.0.0", {"min_sales": 1, "half_life": 2, "hazard_history": "TW+US"})
