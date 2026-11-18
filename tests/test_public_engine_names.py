"""The engine pieces other repos import (engineering_db box/sticks) have public names.

They are the same objects as the underscore functions: renaming or removing one here is a
break for a library caller pinned to this repo, so it must fail in this suite first."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from narvi import generate, placement


def test_public_names_are_the_engine_functions():
    assert placement.longest_segment is placement._longest_segment
    assert generate.make_leg is generate._make_leg
    assert generate.single_well is generate._single_well
    assert generate.place_uturns is generate._place_uturns
