"""Content packs: each module here is one pack's behaviour (swarmworld/world/packs/<pack>.py); its data lives in
swarmworld/data/packs/<pack>/. Every module is imported, sorted by name, when swarmworld.world.actions is first
imported, so its registrations (see swarmworld/world/registry.py) are in place before the world runs."""

from .. import actions as _actions  # noqa: F401  the core verbs register first, whichever module is imported first
from ..registry import import_modules

LOADED = import_modules(__path__, __name__)  # the packs installed, by name
