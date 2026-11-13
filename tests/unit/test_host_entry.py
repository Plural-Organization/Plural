import importlib
import importlib.util
from importlib import resources
from pathlib import Path
from typing import cast


def load_host_entry() -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    path = Path(__file__).parents[2] / "scripts" / "host_entry.py"
    spec = importlib.util.spec_from_file_location("host_entry", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    names = cast("tuple[str, ...]", module.SELFTEST_MODULES)
    data = cast("tuple[tuple[str, str], ...]", module.SELFTEST_DATA)
    return names, data


def test_every_file_the_frozen_host_checks_for_exists_in_the_source() -> None:
    # The frozen host lists its data files by hand; a moved file would pass every source test and
    # only go missing from the built binary.
    modules, data = load_host_entry()
    for module in modules:
        importlib.import_module(module)
    for package, name in data:
        assert resources.files(package).joinpath(name).is_file(), f"{package}/{name}"
