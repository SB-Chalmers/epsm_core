"""Parametric footprint shapes (rectangle, L, U, O).

A :class:`FootprintShape` is lightweight *authoring* metadata describing how a
building's footprint was generated.  It carries a small, unified parameter set
— an outer bounding box (``length`` × ``width``) plus a single "cut" rectangle
(``cut_length`` × ``cut_width``) whose meaning depends on ``shape_type``:

* ``"rectangle"`` — no cut.
* ``"L"`` — remove the top-right corner rectangle.
* ``"U"`` — remove a centred notch from the top edge.
* ``"O"`` — central courtyard void (*reserved*: geometry not yet implemented).

The actual geometry is produced by :meth:`FootprintShape.footprint_pts`, which
returns a single counter-clockwise ring of ``[x, y]`` points ready to hand to
:class:`~pbgenerator.building.Building`.  The raw footprint always remains the
geometric source of truth; the shape is optional provenance recorded alongside
it (and surfaced as ML feature columns).

Example::

    from pbgenerator import Building, FootprintShape, cmf_1960
    shape = FootprintShape.l_shape(length=30, width=18, cut_length=12, cut_width=8)
    b = Building(name="blk", params=cmf_1960(4, "FTX"),
                 footprint_pts=shape.footprint_pts(), location=loc, shape=shape)
"""
from __future__ import annotations

from dataclasses import dataclass

SHAPE_TYPES = ("rectangle", "L", "U", "O")


@dataclass(frozen=True)
class FootprintShape:
    """Unified parametric description of a building footprint.

    All dimensions are in metres.  ``length`` is the outer extent in *x*,
    ``width`` the outer extent in *y*; ``cut_length`` / ``cut_width`` are the
    extents of the removed (or, for ``"O"``, voided) rectangle.
    """

    shape_type: str
    length: float
    width: float
    cut_length: float = 0.0
    cut_width: float = 0.0

    def __post_init__(self) -> None:
        if self.shape_type not in SHAPE_TYPES:
            raise ValueError(
                f"shape_type must be one of {SHAPE_TYPES}, got {self.shape_type!r}"
            )
        if self.length <= 0 or self.width <= 0:
            raise ValueError("length and width must be positive")
        if self.shape_type == "rectangle":
            if self.cut_length or self.cut_width:
                raise ValueError("rectangle takes no cut dimensions")
        else:
            if not (0 < self.cut_length < self.length):
                raise ValueError("cut_length must be in (0, length)")
            if not (0 < self.cut_width < self.width):
                raise ValueError("cut_width must be in (0, width)")

    # -- constructors ------------------------------------------------------

    @classmethod
    def rectangle(cls, length: float, width: float) -> "FootprintShape":
        """A plain rectangle of ``length`` × ``width``."""
        return cls("rectangle", length, width)

    @classmethod
    def l_shape(cls, length: float, width: float,
                cut_length: float, cut_width: float) -> "FootprintShape":
        """An L-shape: a rectangle with the top-right corner removed."""
        return cls("L", length, width, cut_length, cut_width)

    @classmethod
    def u_shape(cls, length: float, width: float,
                cut_length: float, cut_width: float) -> "FootprintShape":
        """A U-shape: a rectangle with a centred notch cut from the top edge."""
        return cls("U", length, width, cut_length, cut_width)

    @classmethod
    def o_shape(cls, length: float, width: float,
                cut_length: float, cut_width: float) -> "FootprintShape":
        """An O-shape (courtyard).

        *Reserved*: the parameters are recorded, but courtyard geometry (a
        polygon with an inner hole) is not yet supported by the geometry
        pipeline, so :meth:`footprint_pts` raises ``NotImplementedError``.
        """
        return cls("O", length, width, cut_length, cut_width)

    # -- geometry ----------------------------------------------------------

    def footprint_pts(self) -> list[list[float]]:
        """Return the footprint as a single counter-clockwise ``[x, y]`` ring."""
        l, w = self.length, self.width
        cl, cw = self.cut_length, self.cut_width
        if self.shape_type == "rectangle":
            return [[0.0, 0.0], [l, 0.0], [l, w], [0.0, w]]
        if self.shape_type == "L":
            return [
                [0.0, 0.0], [l, 0.0], [l, w - cw],
                [l - cl, w - cw], [l - cl, w], [0.0, w],
            ]
        if self.shape_type == "U":
            x1 = (l - cl) / 2.0
            x2 = (l + cl) / 2.0
            return [
                [0.0, 0.0], [l, 0.0], [l, w], [x2, w],
                [x2, w - cw], [x1, w - cw], [x1, w], [0.0, w],
            ]
        # "O"
        raise NotImplementedError(
            "O-shape courtyard geometry is not yet supported (needs polygon-hole "
            "support in build_rooms); the shape parameters are still recorded."
        )


__all__ = ["FootprintShape", "SHAPE_TYPES"]
