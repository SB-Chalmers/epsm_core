# File: specs/facade.py
# Purpose: Facade input specifications.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
# License: MIT; see the project-root LICENSE for the full permission and warranty terms.
# Author: Sanjay Somanath <sanjay.somanath@chalmers.se>
# Project PI: Alexander Hollberg
# Computational Sustainable Design Group
# Research Area of Sustainable Built Environments
# Chalmers University of Technology, Gothenburg
# Date created: 2026-09-06 (documentation-header creation; not original file creation)
# Date modified: 2026-09-06
# Changelog:
#   2026-09-06 - Document facade interfaces, examples, constraints and processing rationale.

"""Facade input specifications.

Notes
-----
Window dimensions and WWR constraints are explicit inputs. Whole-facade overrides
precede storey-specific overrides, and None means inherit. Model validation handles
bounds and uniqueness; placement resolves actual wall feasibility and shading geometry.

Examples
--------
Example::

    from epsm_core.specs.facade import FacadeSpec
    from epsm_core.specs.facade import GlazingSpec

    facade = FacadeSpec(
        default_wwr=0.2,
        glazing=GlazingSpec(u_value_w_m2k=1.2, solar_heat_gain_coefficient=0.5),
    )
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .base import Fraction, Nonnegative, Positive, Spec


class GlazingSpec(Spec):
    """Simple-glazing thermal and solar properties.

    Attributes
    ----------
    u_value_w_m2k : Positive
        Positive glazing thermal transmittance in W/(m2 K). Strictly positive when supplied.
        Required at construction.
    solar_heat_gain_coefficient : Fraction
        Dimensionless solar heat-gain fraction of the simple glazing system. In [0, 1] when
        supplied. Required at construction.
    visible_transmittance : Fraction
        Visible-light transmittance as a fraction in [0, 1]. In [0, 1] when supplied.
        Default: ``0.65``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    U-value must be positive; solar gain and visible transmittance are fractions in [0, 1].
    This does not specify glass thickness or mass.

    Examples
    --------
    Example::

        from epsm_core.specs.facade import GlazingSpec

        glazing = GlazingSpec(u_value_w_m2k=1.2, solar_heat_gain_coefficient=0.5)
    """

    u_value_w_m2k: Positive
    solar_heat_gain_coefficient: Fraction
    visible_transmittance: Fraction = 0.65


class WindowPattern(Spec):
    """Preferred and bounded metric window dimensions for one WWR range.

    Attributes
    ----------
    width_m : Positive
        Preferred or bounded window width in metres; BalconySpec uses width_m for slab span.
        Strictly positive when supplied. Default: ``1.2``.
    min_width_m : Positive
        Preferred or bounded window width in metres; BalconySpec uses width_m for slab span.
        Strictly positive when supplied. Default: ``0.6``.
    max_width_m : Positive
        Preferred or bounded window width in metres; BalconySpec uses width_m for slab span.
        Strictly positive when supplied. Default: ``2``.
    sill_m : Nonnegative
        Preferred or bounded height of the sill above the storey floor, in metres.
        Nonnegative when supplied. Default: ``0.9``.
    min_sill_m : Nonnegative
        Preferred or bounded height of the sill above the storey floor, in metres.
        Nonnegative when supplied. Default: ``0.6``.
    max_sill_m : Nonnegative
        Preferred or bounded height of the sill above the storey floor, in metres.
        Nonnegative when supplied. Default: ``1.1``.
    height_m : Positive | None
        Height or height bound in metres; context height is measured above its base
        elevation. Strictly positive when supplied. Default: ``None``.
    min_height_m : Positive
        Height or height bound in metres; context height is measured above its base
        elevation. Strictly positive when supplied. Default: ``0.6``.
    max_height_m : Positive | None
        Height or height bound in metres; context height is measured above its base
        elevation. Strictly positive when supplied. Default: ``None``.
    spacing_m : Positive
        Preferred or maximum window-centre spacing in metres. Strictly positive when
        supplied. Default: ``3.5``.
    max_spacing_m : Positive
        Preferred or maximum window-centre spacing in metres. Strictly positive when
        supplied. Default: ``4.5``.
    gap_m : Positive
        Minimum clear horizontal distance between adjacent windows, in metres. Strictly
        positive when supplied. Default: ``0.2``.
    head_m : Positive
        Minimum opaque clearance above a window, in metres. Strictly positive when supplied.
        Default: ``0.2``.
    end_m : Positive
        Directed metric boundary endpoints; _m fields retain source-frame coordinates.
        Strictly positive when supplied. Default: ``0.1``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Preferred width/sill and spacing are validated against bounds. Head, end and gap margins
    retain opaque wall between openings; wall-specific feasibility is checked during
    placement.

    Examples
    --------
    Example::

        from epsm_core.specs.facade import WindowPattern

        pattern = WindowPattern()
    """

    width_m: Positive = 1.2
    min_width_m: Positive = 0.6
    max_width_m: Positive = 2
    sill_m: Nonnegative = 0.9
    min_sill_m: Nonnegative = 0.6
    max_sill_m: Nonnegative = 1.1
    height_m: Positive | None = None
    min_height_m: Positive = 0.6
    max_height_m: Positive | None = None
    spacing_m: Positive = 3.5
    max_spacing_m: Positive = 4.5
    gap_m: Positive = 0.2
    head_m: Positive = 0.2
    end_m: Positive = 0.1

    @model_validator(mode="after")
    def bounds(self):
        """Validate preferred dimensions against window-pattern bounds.

        Returns
        -------
        Self
            Validated pattern.

        Raises
        ------
        ValueError
            Rejected conditions: Preferred width must lie within bounds; Preferred sill must lie
            within bounds; Window height bounds are reversed; Preferred spacing exceeds maximum.

        Notes
        -----
        Width and sill preferences must lie inside their ranges; height bounds and spacing must
        be ordered. Wall-specific feasibility is checked during window placement.

        Examples
        --------
        Example::

            from epsm_core.specs.facade import WindowPattern

            assert WindowPattern().bounds().width_m == 1.2
        """

        # 1. Validate preferred dimensions against window-pattern bounds.
        if not self.min_width_m <= self.width_m <= self.max_width_m:
            raise ValueError("Preferred width must lie within bounds")
        if not self.min_sill_m <= self.sill_m <= self.max_sill_m:
            raise ValueError("Preferred sill must lie within bounds")
        if self.max_height_m is not None and self.min_height_m > self.max_height_m:
            raise ValueError("Window height bounds are reversed")
        if self.spacing_m > self.max_spacing_m:
            raise ValueError("Preferred spacing exceeds maximum")
        return self


class WindowLayoutSpec(Spec):
    """Select scaled, dimension-driven or WWR-constrained window placement.

    Attributes
    ----------
    mode : Literal['scaled', 'dimensions', 'wwr']
        Selected layout or thermal-zoning algorithm; controls are interpreted by this mode.
        Default: ``'scaled'``.
    pattern : Literal['auto', 'low', 'mid', 'high']
        Regular expression for WarningRule, or low/mid/high/auto window family for
        WindowLayoutSpec.  Default: ``'auto'``.
    low_threshold : Fraction
        WWR thresholds used for automatic selection of low, mid or high window patterns. In
        [0, 1] when supplied. Default: ``0.15``.
    high_threshold : Fraction
        WWR thresholds used for automatic selection of low, mid or high window patterns. In
        [0, 1] when supplied. Default: ``0.6``.
    low : WindowPattern
        Dimension preferences used for the corresponding WWR regime.  Default: as declared
        below.
    mid : WindowPattern
        Dimension preferences used for the corresponding WWR regime.  Default:
        ``WindowPattern()``.
    high : WindowPattern
        Dimension preferences used for the corresponding WWR regime.  Default: as declared
        below.
    sill_height_m : Nonnegative | None
        Explicit sill height in metres or fraction of wall height; the two forms are
        mutually exclusive. Nonnegative when supplied. Default: ``None``.
    sill_height_ratio : Fraction | None
        Explicit sill height in metres or fraction of wall height; the two forms are
        mutually exclusive. In [0, 1] when supplied. Default: ``None``.
    window_width_m : Positive | None
        Explicit window width, height or centre spacing in metres, required together in
        dimensions mode. Strictly positive when supplied. Default: ``None``.
    window_height_m : Positive | None
        Explicit window width, height or centre spacing in metres, required together in
        dimensions mode. Strictly positive when supplied. Default: ``None``.
    center_spacing_m : Positive | None
        Explicit window width, height or centre spacing in metres, required together in
        dimensions mode. Strictly positive when supplied. Default: ``None``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Scaled mode creates a centred WWR-scaled rectangle. Dimension mode requires explicit
    width, height and centre spacing. WWR mode searches feasible dimensions. Sill metres and
    sill ratio are mutually exclusive.

    Examples
    --------
    Example::

        from epsm_core.specs.facade import WindowLayoutSpec

        layout = WindowLayoutSpec(
            mode="dimensions",
            window_width_m=1.2,
            window_height_m=1.4,
            center_spacing_m=3,
        )
    """

    mode: Literal["scaled", "dimensions", "wwr"] = "scaled"
    pattern: Literal["auto", "low", "mid", "high"] = "auto"
    low_threshold: Fraction = 0.15
    high_threshold: Fraction = 0.60
    low: WindowPattern = WindowPattern(
        width_m=0.8,
        min_width_m=0.3,
        max_width_m=1.2,
        sill_m=1.4,
        min_sill_m=1.2,
        max_sill_m=1.8,
        height_m=0.8,
        min_height_m=0.3,
        max_height_m=1.2,
    )
    mid: WindowPattern = WindowPattern()
    high: WindowPattern = WindowPattern(
        width_m=1.5,
        min_width_m=0.6,
        max_width_m=3,
        sill_m=0.05,
        min_sill_m=0.05,
        max_sill_m=0.3,
        gap_m=0.05,
        head_m=0.05,
        end_m=0.05,
    )
    sill_height_m: Nonnegative | None = None
    sill_height_ratio: Fraction | None = None
    window_width_m: Positive | None = None
    window_height_m: Positive | None = None
    center_spacing_m: Positive | None = None

    @model_validator(mode="after")
    def inputs(self):
        """Validate layout mode requirements and mutually exclusive sill inputs.

        Returns
        -------
        Self
            Validated window layout.

        Raises
        ------
        ValueError
            Rejected conditions: Specify sill height in metres OR as a ratio; Window pattern
            thresholds must be ordered within (0,.95); Dimension mode requires window width,
            height and centre spacing.

        Notes
        -----
        Thresholds must satisfy 0 < low < high < 0.95. Dimension mode requires width, height and
        centre spacing; sill metres and ratio cannot both be supplied.

        Examples
        --------
        Example::

            from epsm_core.specs.facade import WindowLayoutSpec

            assert WindowLayoutSpec().inputs().mode == "scaled"
        """

        # 1. Validate layout mode requirements and mutually exclusive sill inputs.
        if self.sill_height_m is not None and self.sill_height_ratio is not None:
            raise ValueError("Specify sill height in metres OR as a ratio")
        if not 0 < self.low_threshold < self.high_threshold < 0.95:
            raise ValueError("Window pattern thresholds must be ordered within (0,.95)")
        if self.mode == "dimensions" and any(
            v is None for v in (self.window_width_m, self.window_height_m, self.center_spacing_m)
        ):
            raise ValueError("Dimension mode requires window width, height and centre spacing")
        return self


class OverhangSpec(Spec):
    """Shading-only horizontal projection above windows or a complete facade run.

    Attributes
    ----------
    depth_m : Nonnegative
        Nonnegative outward shading projection in metres; zero disables geometry.
        Nonnegative when supplied. Default: ``0``.
    offset_above_m : Nonnegative
        Vertical offset above a logical window head or facade top, in metres. Nonnegative
        when supplied. Default: ``0``.
    side_extension_m : Nonnegative
        Overhang extension beyond each window/run end, in metres. Nonnegative when supplied.
        Default: ``0``.
    continuous : bool
        Apply an overhang along the exposed facade run rather than per logical window.
        Default: ``False``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    All dimensions are nonnegative. Zero depth disables geometry. Continuous overhangs
    follow exposed facade tops; per-window overhangs follow logical opening heads.

    Examples
    --------
    Example::

        from epsm_core.specs.facade import OverhangSpec

        overhang = OverhangSpec(depth_m=0.6)
    """

    depth_m: Nonnegative = 0
    offset_above_m: Nonnegative = 0
    side_extension_m: Nonnegative = 0
    continuous: bool = False


class BalconySpec(Spec):
    """Facade-anchored shading slab with optional side and front screens.

    Attributes
    ----------
    facade_id : str
        Stable physical facade identifier from GeometrySpec.facades().  Required at
        construction.
    storeys : tuple[Annotated[int, Field(ge=0)], ...]
        Zero-based storey indices; for balconies an empty tuple applies to all storeys. At
        least 0. Default: ``()``.
    start_m : Nonnegative
        Directed metric boundary endpoints; _m fields retain source-frame coordinates.
        Nonnegative when supplied. Default: ``0``.
    width_m : Positive
        Preferred or bounded window width in metres; BalconySpec uses width_m for slab span.
        Strictly positive when supplied. Required at construction.
    depth_m : Positive
        Positive outward slab projection in metres. Strictly positive when supplied.
        Required at construction.
    elevation_above_floor_m : Nonnegative
        Balcony slab elevation above the storey floor, in metres. Nonnegative when supplied.
        Default: ``0``.
    side_screen_height_m : Nonnegative
        Optional vertical balcony screen height in metres; zero omits the screen.
        Nonnegative when supplied. Default: ``0``.
    front_screen_height_m : Nonnegative
        Optional vertical balcony screen height in metres; zero omits the screen.
        Nonnegative when supplied. Default: ``0``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    storeys is zero-based; an empty tuple means every storey. Generation validates facade
    identity, storey existence and width within the original facade length.

    Examples
    --------
    Example::

        from epsm_core.specs.facade import BalconySpec

        balcony = BalconySpec(facade_id="main.r0.e0", width_m=3, depth_m=1.5)
    """

    facade_id: str
    storeys: tuple[Annotated[int, Field(ge=0)], ...] = ()
    start_m: Nonnegative = 0
    width_m: Positive
    depth_m: Positive
    elevation_above_floor_m: Nonnegative = 0
    side_screen_height_m: Nonnegative = 0
    front_screen_height_m: Nonnegative = 0


class FacadeOverride(Spec):
    """Optional setting overrides for one facade or facade/storey pair.

    Attributes
    ----------
    facade_id : str
        Stable physical facade identifier from GeometrySpec.facades().  Required at
        construction.
    storey : Annotated[int, Field(ge=0)] | None
        Zero-based above-grade storey; None selects a facade-wide value. At least 0.
        Default: ``None``.
    glazing : GlazingSpec | None
        Simple-glazing properties, or an optional override where None means inherit.
        Default: ``None``.
    wwr : Fraction | None
        Requested window-to-wall area fraction; facade validation requires values below
        0.95. In [0, 1] when supplied. Default: ``None``.
    layout : WindowLayoutSpec | None
        Window placement controls, or optional override inheriting from the facade default.
        Default: ``None``.
    reveal_depth_m : Nonnegative | None
        Outward shading-fin depth in metres; glazing remains coplanar with the wall.
        Nonnegative when supplied. Default: ``None``.
    overhang : OverhangSpec | None
        Shading-only overhang geometry controls.  Default: ``None``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    None means inherit. A whole-facade override applies before a storey-specific override.
    The owning BuildingSpec validates references against its facade catalogue.

    Examples
    --------
    Example::

        from epsm_core.specs.facade import FacadeOverride

        override = FacadeOverride(facade_id="main.r0.e0", storey=0, wwr=0.3)
    """

    facade_id: str
    storey: Annotated[int, Field(ge=0)] | None = None
    glazing: GlazingSpec | None = None
    wwr: Fraction | None = None
    layout: WindowLayoutSpec | None = None
    reveal_depth_m: Nonnegative | None = None
    overhang: OverhangSpec | None = None


class FacadeSpec(Spec):
    """Default glazing, layout, solar controls and facade-specific overrides.

    Attributes
    ----------
    default_wwr : Fraction
        Requested window-to-wall area fraction; facade validation requires values below
        0.95. In [0, 1] when supplied. Required at construction.
    glazing : GlazingSpec
        Simple-glazing properties, or an optional override where None means inherit.
        Required at construction.
    overrides : tuple[FacadeOverride, ...]
        Facade-wide and facade/storey settings applied in increasing specificity.  Default:
        ``()``.
    solar_shading_factor : Fraction
        Incident solar multiplier applied independently of geometric shading. In [0, 1] when
        supplied. Default: ``1``.
    layout : WindowLayoutSpec
        Window placement controls, or optional override inheriting from the facade default.
        Default: ``WindowLayoutSpec()``.
    reveal_depth_m : Nonnegative
        Outward shading-fin depth in metres; glazing remains coplanar with the wall.
        Nonnegative when supplied. Default: ``0``.
    overhang : OverhangSpec
        Shading-only overhang geometry controls.  Default: ``OverhangSpec()``.
    balconies : tuple[BalconySpec, ...]
        Facade-anchored shading slabs and optional screens.  Default: ``()``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Facade/storey override keys must be unique, and every WWR stays below 0.95.
    solar_shading_factor multiplies incident solar independently of geometric shading and is
    not a geometric opening fraction.

    Examples
    --------
    Example::

        from epsm_core.specs.facade import FacadeSpec
        from epsm_core.specs.facade import GlazingSpec

        facade = FacadeSpec(
            default_wwr=0.2,
            glazing=GlazingSpec(u_value_w_m2k=1.2, solar_heat_gain_coefficient=0.5),
        )
    """

    default_wwr: Fraction
    glazing: GlazingSpec
    overrides: tuple[FacadeOverride, ...] = ()
    solar_shading_factor: Fraction = 1
    layout: WindowLayoutSpec = WindowLayoutSpec()
    reveal_depth_m: Nonnegative = 0
    overhang: OverhangSpec = OverhangSpec()
    balconies: tuple[BalconySpec, ...] = ()

    @model_validator(mode="after")
    def unique(self):
        """Validate unique facade/storey overrides and an opaque-frame WWR margin.

        Returns
        -------
        Self
            Validated facade specification.

        Raises
        ------
        ValueError
            Rejected conditions: Duplicate facade/storey overrides; WWR must be < 0.95 to retain
            an opaque frame.

        Notes
        -----
        Every WWR must be below 0.95; Fraction fields enforce the lower bound. Facade ID
        existence is checked against a complete BuildingSpec.

        Examples
        --------
        Example::

            from epsm_core.specs.facade import FacadeSpec
            from epsm_core.specs.facade import GlazingSpec

            facade = FacadeSpec(
                default_wwr=0.2,
                glazing=GlazingSpec(u_value_w_m2k=1.2, solar_heat_gain_coefficient=0.5),
            )
            assert facade.unique() is facade
        """

        # 1. Validate unique facade/storey overrides and an opaque-frame WWR margin.
        ids = [(o.facade_id, o.storey) for o in self.overrides]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate facade/storey overrides")
        if max([self.default_wwr, *(o.wwr for o in self.overrides if o.wwr is not None)]) >= 0.95:
            raise ValueError("WWR must be < 0.95 to retain an opaque frame")
        return self

    def value_for(self, name, facade_id, storey=None):
        """Resolve a facade value from default, whole-facade and storey overrides.

        Parameters
        ----------
        name : str
            Identifier or field name interpreted by the current operation.
        facade_id : str
            Stable physical facade identifier from GeometrySpec.facades().
        storey : int or None
            Zero-based above-grade storey; None selects a facade-wide value. Default: ``None``.

        Returns
        -------
        object
            Effective value for the requested facade setting.

        Notes
        -----
        None in an override means inherit. Storey-specific values win over facade-wide values.
        name must identify a supported field; wwr maps to default_wwr on the base specification.

        Examples
        --------
        Example::

            from epsm_core.specs.facade import FacadeSpec
            from epsm_core.specs.facade import GlazingSpec

            facade = FacadeSpec(
                default_wwr=0.2,
                glazing=GlazingSpec(u_value_w_m2k=1.2, solar_heat_gain_coefficient=0.5),
            )
            assert facade.value_for("wwr", "main.r0.e0") == facade.default_wwr
        """

        # 1. Resolve a facade value from default, whole-facade and storey overrides.
        value = getattr(self, "default_wwr" if name == "wwr" else name)
        for level in (None, storey) if storey is not None else (None,):
            for o in self.overrides:
                if o.facade_id == facade_id and o.storey == level:
                    candidate = getattr(o, name)
                    if candidate is not None:
                        value = candidate
        return value

    def wwr_for(self, facade_id, storey=None):
        """Resolve the window-to-wall ratio for a facade and optional storey.

        Parameters
        ----------
        facade_id : str
            Stable physical facade identifier from GeometrySpec.facades().
        storey : int or None
            Zero-based above-grade storey; None selects a facade-wide value. Default: ``None``.

        Returns
        -------
        float
            Effective dimensionless glazing fraction.

        Notes
        -----
        Uses the same default, facade-wide, then storey-specific precedence as value_for.

        Examples
        --------
        Example::

            from epsm_core.specs.facade import FacadeSpec
            from epsm_core.specs.facade import GlazingSpec

            facade = FacadeSpec(
                default_wwr=0.2,
                glazing=GlazingSpec(u_value_w_m2k=1.2, solar_heat_gain_coefficient=0.5),
            )
            assert facade.wwr_for("main.r0.e0") == facade.default_wwr
        """

        return self.value_for("wwr", facade_id, storey)
