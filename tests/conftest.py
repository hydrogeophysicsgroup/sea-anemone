import sys
from types import SimpleNamespace


main_module = sys.modules["__main__"]
if not hasattr(main_module, "sesh"):
    main_module.sesh = SimpleNamespace(
        data=None,
        models=None,
        lines=None,
        overview=None,
        save_dir=None,
        forwards=None,
    )
