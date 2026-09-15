"""clause.md: the fixed template, its parser, and the bundled default rubric.

Code owns everything exact in a rubric (pillar names, weights, score bands).
The free-text criteria and hard rules are carried through verbatim for the
planner to interpret — see gitcrawl/plan/.
"""

from gitcrawl.rubric.models import Band, PillarSpec, Rubric, RubricError
from gitcrawl.rubric.parse import load_default_rubric, load_rubric, parse_rubric

__all__ = ["Band", "PillarSpec", "Rubric", "RubricError", "load_default_rubric", "load_rubric", "parse_rubric"]
