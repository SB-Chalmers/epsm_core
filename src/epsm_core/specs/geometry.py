# File: specs/geometry.py
# Purpose: Geometry input specifications.
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
#   2026-09-06 - Document geometry interfaces, examples, constraints and processing rationale.

"""Geometry input specifications.

Notes
-----
Footprints must already be valid two-dimensional metric polygons. Storey elevations are
explicit, with canonical parts and facade identities. Zoning controls describe
computational subdivision; roof, basement and reviewed party-wall inputs retain physical
meaning.

Examples
--------
Example::

    from epsm_core.specs.geometry import Footprint
    from epsm_core.specs.geometry import GeometrySpec

    geometry = GeometrySpec.from_footprint(
        Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
    )
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_serializer, model_validator
from shapely import STRtree
from shapely.geometry import MultiPolygon, Polygon

from .base import Fraction, Nonnegative, Positive, Ring, Spec


class Footprint(Spec):
    """Validated metric polygon rings representing one physical footprint.

    Attributes
    ----------
    exterior : Ring
        Outer coordinate ring in metric source coordinates; a closing duplicate is optional.
        Required at construction.
    holes : tuple[Ring, ...]
        Interior courtyard rings in the same frame as the exterior.  Default: ``()``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Coordinates must already be in metres. Holes represent courtyards; no CRS
    transformation, outline repair or area scaling happens implicitly.

    Examples
    --------
    Example::

        from epsm_core.specs.geometry import Footprint

        footprint = Footprint.rectangle(10, 8)
    """

    exterior: Ring
    holes: tuple[Ring, ...] = ()

    @model_validator(mode="after")
    def valid_polygon(self):
        """Validate distinct ring vertices and a positive, nonintersecting polygon.

        Returns
        -------
        Self
            Validated footprint.

        Raises
        ------
        ValueError
            Rejected conditions: A ring needs at least three distinct vertices; Footprint must
            be a valid polygon with nonintersecting rings.

        Notes
        -----
        Each ring needs three distinct vertices and net polygon area must exceed 1e-6 m2.
        Pydantic calls this after field validation.

        Examples
        --------
        Example::

            from epsm_core.specs.geometry import Footprint

            footprint = Footprint.rectangle(10, 8)
            assert footprint.valid_polygon() is footprint
        """

        # 1. Validate distinct ring vertices and a positive, nonintersecting polygon.
        for ring in (self.exterior, *self.holes):
            if len(ring) < 3 or len(set(ring)) < 3:
                raise ValueError("A ring needs at least three distinct vertices")
        if not self.polygon.is_valid or self.polygon.area <= 1e-6:
            raise ValueError("Footprint must be a valid polygon with nonintersecting rings")
        return self

    @property
    def polygon(self) -> Polygon:
        """Construct a Shapely polygon from exterior and courtyard rings.

        Returns
        -------
        Polygon
            A new polygon in the supplied coordinate frame.

        Notes
        -----
        No CRS conversion or scaling occurs. The Footprint validator already checks topology at
        construction.

        Examples
        --------
        Example::

            from epsm_core.specs.geometry import Footprint

            assert Footprint.rectangle(10, 8).polygon.area == 80
        """

        return Polygon(self.exterior, self.holes)

    @classmethod
    def rectangle(cls, length_m: float, width_m: float):
        """Construct an axis-aligned metric rectangle anchored at the origin.

        Parameters
        ----------
        length_m : float
            Positive outer footprint dimension in metres.
        width_m : float
            Positive outer footprint dimension in metres.

        Returns
        -------
        Footprint
            Validated rectangular footprint.

        Raises
        ------
        ValueError
            Rejected conditions: Rectangle dimensions must be positive.

        Notes
        -----
        Both dimensions must be positive. Vertices are stored without a repeated closing
        coordinate.

        Examples
        --------
        Example::

            from epsm_core.specs.geometry import Footprint

            assert Footprint.rectangle(10, 8).area_m2 == 80
        """

        if min(length_m, width_m) <= 0:
            raise ValueError("Rectangle dimensions must be positive")
        return cls(exterior=((0, 0), (length_m, 0), (length_m, width_m), (0, width_m)))

    def scaled_to_area(self, area_m2: float):
        """Uniformly scale a footprint and its holes to a positive target area.

        Parameters
        ----------
        area_m2 : float
            Positive target net footprint area in square metres.

        Returns
        -------
        Footprint
            New footprint with the requested net area in m2.

        Raises
        ------
        ValueError
            Rejected conditions: Area must be positive.

        Notes
        -----
        Scaling is about (0, 0), not the centroid. Use only for an intentional geometric
        transformation; it does not reconcile measured geometry to external floor-area estimates
        automatically.

        Examples
        --------
        Example::

            from epsm_core.specs.geometry import Footprint

            assert abs(Footprint.rectangle(10, 8).scaled_to_area(160).area_m2 - 160) < 1e-9
        """

        # 1. Uniformly scale a footprint and its holes to a positive target area.
        if area_m2 <= 0:
            raise ValueError("Area must be positive")
        scale = (area_m2 / self.polygon.area) ** 0.5
        return Footprint(
            exterior=tuple((x * scale, y * scale) for x, y in self.exterior),
            holes=tuple(tuple((x * scale, y * scale) for x, y in r) for r in self.holes),
        )

    @property
    def area_m2(self):
        """Return net plan area after subtracting courtyard holes.

        Returns
        -------
        float
            Area in square metres.

        Notes
        -----
        Assumes coordinates are already metric; no coordinate-system metadata is interpreted.

        Examples
        --------
        Example::

            from epsm_core.specs.geometry import Footprint

            assert Footprint.rectangle(10, 8).area_m2 == 80
        """

        return self.polygon.area

    @property
    def perimeter_m(self):
        """Return total exterior and courtyard boundary length.

        Returns
        -------
        float
            Perimeter in metres, including every hole.

        Notes
        -----
        This is the complete boundary length, not only the outer envelope perimeter.

        Examples
        --------
        Example::

            from epsm_core.specs.geometry import Footprint

            assert Footprint.rectangle(10, 8).perimeter_m == 36
        """

        return self.polygon.length

    @classmethod
    def l_shape(cls, length_m, width_m, cut_length_m, cut_width_m):
        """Construct an L footprint by removing the upper-right rectangle.

        Parameters
        ----------
        length_m : float
            Positive outer footprint dimension in metres.
        width_m : float
            Positive outer footprint dimension in metres.
        cut_length_m : float
            Positive upper-right rectangular cut dimension, smaller than the corresponding outer
            dimension.
        cut_width_m : float
            Positive upper-right rectangular cut dimension, smaller than the corresponding outer
            dimension.

        Returns
        -------
        Footprint
            Validated six-vertex footprint anchored at (0, 0).

        Raises
        ------
        ValueError
            Rejected conditions: L cuts must lie strictly inside the outer rectangle.

        Notes
        -----
        Both cut dimensions must be strictly inside the corresponding outer dimensions, leaving
        positive wings.

        Examples
        --------
        Example::

            from epsm_core.specs.geometry import Footprint

            assert Footprint.l_shape(10, 8, 3, 2).area_m2 == 74
        """

        # 1. Construct an L footprint by removing the upper-right rectangle.
        if not (0 < cut_length_m < length_m and 0 < cut_width_m < width_m):
            raise ValueError("L cuts must lie strictly inside the outer rectangle")
        inner_x, inner_y = length_m - cut_length_m, width_m - cut_width_m
        return cls(
            exterior=(
                (0, 0),
                (length_m, 0),
                (length_m, inner_y),
                (inner_x, inner_y),
                (inner_x, width_m),
                (0, width_m),
            )
        )

    @classmethod
    def u_shape(cls, length_m, width_m, notch_length_m, notch_depth_m):
        """Construct a U footprint with a centred notch opening toward +Y.

        Parameters
        ----------
        length_m : float
            Positive outer footprint dimension in metres.
        width_m : float
            Positive outer footprint dimension in metres.
        notch_length_m : float
            Centred U-notch width or depth in metres, leaving positive wings and base.
        notch_depth_m : float
            Centred U-notch width or depth in metres, leaving positive wings and base.

        Returns
        -------
        Footprint
            Validated eight-vertex footprint.

        Raises
        ------
        ValueError
            Rejected conditions: U notch must leave positive wings and base.

        Notes
        -----
        The notch must be strictly smaller than the outer dimensions; left and right wings are
        symmetric.

        Examples
        --------
        Example::

            from epsm_core.specs.geometry import Footprint

            assert Footprint.u_shape(10, 8, 4, 3).area_m2 == 68
        """

        # 1. Construct a U footprint with a centred notch opening toward +Y.
        if not (0 < notch_length_m < length_m and 0 < notch_depth_m < width_m):
            raise ValueError("U notch must leave positive wings and base")
        left, right = (length_m - notch_length_m) / 2, (length_m + notch_length_m) / 2
        base = width_m - notch_depth_m
        return cls(
            exterior=(
                (0, 0),
                (length_m, 0),
                (length_m, width_m),
                (right, width_m),
                (right, base),
                (left, base),
                (left, width_m),
                (0, width_m),
            )
        )


class RoofSpec(Spec):
    """Explicit roof shape, direction, pitch and thermal topology.

    Attributes
    ----------
    shape : Literal['flat', 'mono_pitch', 'gable', 'hip']
        Roof geometry family; pitched families require a cold attic.  Default: ``'flat'``.
    pitch_deg : Annotated[float, Field(gt=0, lt=80)] | None
        Explicit roof slope angle in degrees; None selects the shape-specific default.
        Greater than 0. Less than 80. Default: ``None``.
    direction_deg : Annotated[float, Field(ge=0, lt=360)] | None
        Ridge azimuth for gables or upslope azimuth for mono-pitch; None infers the dominant
        plan direction. At least 0. Less than 360. Default: ``None``.
    topology : Literal['compact', 'cold_attic'] | None
        Thermal or airflow topology selected from the annotated supported values.  Default:
        ``None``.
    attic_height_m : Positive
        Provisional flat attic extrusion height in metres; pitched generation computes its
        actual shell volume. Strictly positive when supplied. Default: ``1.5``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Flat roofs default to compact, pitched roofs to cold_attic. Pitched roofs require an
    unconditioned attic. Flat roofs reject pitch/direction; hip roofs require the optional
    geometry backend at generation time.

    Examples
    --------
    Example::

        from epsm_core.specs.geometry import RoofSpec

        roof = RoofSpec(shape="gable", pitch_deg=30)
    """

    shape: Literal["flat", "mono_pitch", "gable", "hip"] = "flat"
    pitch_deg: Annotated[float, Field(gt=0, lt=80)] | None = None
    direction_deg: Annotated[float, Field(ge=0, lt=360)] | None = None

    topology: Literal["compact", "cold_attic"] | None = None
    attic_height_m: Positive = 1.5

    @model_validator(mode="after")
    def compatible_shape(self):
        """Resolve default roof topology and reject incompatible shape controls.

        Returns
        -------
        Self
            Roof with explicit compact or cold_attic topology.

        Raises
        ------
        ValueError
            Rejected conditions: Pitched roofs require cold_attic topology; Flat roofs do not
            accept pitch or direction.

        Notes
        -----
        Flat roofs default to compact and disallow pitch/direction. Pitched roofs require
        cold_attic. The validator uses object.__setattr__ to normalize the otherwise frozen
        model.

        Examples
        --------
        Example::

            from epsm_core.specs.geometry import RoofSpec

            assert RoofSpec(shape="gable").topology == "cold_attic"
        """

        # 1. Resolve default roof topology and reject incompatible shape controls.
        if self.topology is None:
            # HACK: Normalize a derived default during validation despite frozen model fields.
            object.__setattr__(
                self, "topology", "compact" if self.shape == "flat" else "cold_attic"
            )
        if self.shape != "flat" and self.topology != "cold_attic":
            raise ValueError("Pitched roofs require cold_attic topology")
        if self.shape == "flat" and (self.pitch_deg is not None or self.direction_deg is not None):
            raise ValueError("Flat roofs do not accept pitch or direction")
        return self

    @property
    def pitch(self):
        """Return explicit pitch or the shape-specific default angle.

        Returns
        -------
        float
            Pitch in degrees.

        Notes
        -----
        Defaults to 10 degrees for mono_pitch and 30 otherwise. The value on a flat roof is
        unused by the flat-roof path.

        Examples
        --------
        Example::

            from epsm_core.specs.geometry import RoofSpec

            assert RoofSpec(shape="mono_pitch").pitch == 10
        """

        # 1. Return explicit pitch or the shape-specific default angle.
        return (
            self.pitch_deg
            if self.pitch_deg is not None
            else (10 if self.shape == "mono_pitch" else 30)
        )


class ApartmentType(Spec):
    """Named apartment area band and desired share of the dwelling mix.

    Attributes
    ----------
    name : str
        Identifier or field name interpreted by the current operation.  Required at
        construction.
    min_area_m2 : Positive
        Lower or upper admissible dwelling area in square metres. Strictly positive when
        supplied. Required at construction.
    max_area_m2 : Positive
        Lower or upper admissible dwelling area in square metres. Strictly positive when
        supplied. Required at construction.
    target_share : Fraction
        Desired fraction of dwelling count assigned to this apartment type. In [0, 1] when
        supplied. Required at construction.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Positive area bounds must be ordered. target_share is a fraction; the enclosing
    ApartmentLayoutSpec requires shares to sum to one.

    Examples
    --------
    Example::

        from epsm_core.specs.geometry import ApartmentType

        typ = ApartmentType(
            name="studio", min_area_m2=20, max_area_m2=35, target_share=1
        )
    """

    name: str
    min_area_m2: Positive
    max_area_m2: Positive
    target_share: Fraction

    @model_validator(mode="after")
    def ordered(self):
        """Require the apartment area interval to be ordered.

        Returns
        -------
        Self
            Validated apartment type.

        Raises
        ------
        ValueError
            Rejected conditions: Apartment minimum area exceeds maximum.

        Notes
        -----
        Equal minimum and maximum areas are allowed; positivity is enforced by the field types.

        Examples
        --------
        Example::

            from epsm_core.specs.geometry import ApartmentType

            typ = ApartmentType(
                name="studio", min_area_m2=20, max_area_m2=35, target_share=1
            )
            assert typ.ordered() is typ
        """

        if self.min_area_m2 > self.max_area_m2:
            raise ValueError("Apartment minimum area exceeds maximum")
        return self


class ApartmentLayoutSpec(Spec):
    """Controls for bounded schematic dwelling and circulation generation.

    Attributes
    ----------
    types : tuple[ApartmentType, ...]
        Uniquely named dwelling area bands whose target shares sum to one.  Default: as
        declared below.
    corridor_width_m : Positive
        Full circulation-strip width in metres around the skeleton network. Strictly
        positive when supplied. Default: ``1.5``.
    core_width_m : Positive
        Default rectangular stair-core dimensions in metres. Strictly positive when
        supplied. Default: ``3``.
    core_length_m : Positive
        Default rectangular stair-core dimensions in metres. Strictly positive when
        supplied. Default: ``5``.
    stair_cores : tuple[Footprint, ...]
        Optional reviewed core footprints in source coordinates.  Default: ``()``.
    min_frontage_m : Positive
        Minimum dwelling boundary length touching the exterior, in metres. Strictly positive
        when supplied. Default: ``1.2``.
    min_access_m : Positive
        Minimum dwelling boundary length touching common circulation, in metres. Strictly
        positive when supplied. Default: ``0.9``.
    max_candidates : int
        Bound on cut positions; the layout search also bounds examined candidates by its
        square. At least 1. At most 10000. Default: ``256``.
    common_heating_setpoint_c : float
        Default common/stairwell heating setpoint when common_use is not supplied.  Default:
        ``18``.
    conserve_residential_loads : bool
        Rescale residential load densities to retain whole-building totals after common
        areas are separated.  Default: ``True``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Types must be uniquely named and shares sum to one within 1e-8. Stair cores are source-
    frame footprints. The search reports achieved counts and can fail; controls do not imply
    a reviewed residential layout.

    Examples
    --------
    Example::

        from epsm_core.specs.geometry import ApartmentLayoutSpec

        layout = ApartmentLayoutSpec(max_candidates=128)
    """

    types: tuple[ApartmentType, ...] = (
        ApartmentType(name="studio", min_area_m2=20, max_area_m2=35, target_share=0.4),
        ApartmentType(name="2rok", min_area_m2=45, max_area_m2=65, target_share=0.4),
        ApartmentType(name="3rok", min_area_m2=70, max_area_m2=90, target_share=0.15),
        ApartmentType(name="4rok", min_area_m2=90, max_area_m2=120, target_share=0.05),
    )
    corridor_width_m: Positive = 1.5
    core_width_m: Positive = 3
    core_length_m: Positive = 5
    stair_cores: tuple[Footprint, ...] = ()
    min_frontage_m: Positive = 1.2
    min_access_m: Positive = 0.9
    max_candidates: Annotated[int, Field(ge=1, le=10000)] = 256
    common_heating_setpoint_c: float = 18
    conserve_residential_loads: bool = True

    @model_validator(mode="after")
    def mixture(self):
        """Require a nonempty uniquely named apartment mix summing to one.

        Returns
        -------
        Self
            Validated layout controls.

        Raises
        ------
        ValueError
            Rejected conditions: Apartment types must be nonempty and uniquely named; Apartment
            target shares must sum to one.

        Notes
        -----
        Share-sum tolerance is 1e-8. These are target shares; the bounded layout search reports
        the achieved mix separately.

        Examples
        --------
        Example::

            from epsm_core.specs.geometry import ApartmentLayoutSpec

            layout = ApartmentLayoutSpec()
            assert layout.mixture() is layout
        """

        # 1. Require a nonempty uniquely named apartment mix summing to one.
        if not self.types or len({t.name for t in self.types}) != len(self.types):
            raise ValueError("Apartment types must be nonempty and uniquely named")
        if abs(sum(t.target_share for t in self.types) - 1) > 1e-8:
            raise ValueError("Apartment target shares must sum to one")
        return self


class ZoningSpec(Spec):
    """Select thermal subdivision and explicit procedural-failure policy.

    Attributes
    ----------
    mode : Literal['whole_building', 'per_storey', 'perimeter_core', 'apartments']
        Selected layout or thermal-zoning algorithm; controls are interpreted by this mode.
        Default: ``'per_storey'``.
    depth_m : Positive
        Perimeter-zone depth in metres, active only in perimeter_core mode. Strictly
        positive when supplied. Default: ``4.5``.
    apartments : ApartmentLayoutSpec
        Schematic residential layout controls used in apartments zoning.  Default:
        ``ApartmentLayoutSpec()``.
    on_failure : Literal['error', 'per_storey']
        Whether procedural failure raises or explicitly substitutes per_storey zoning for
        the building.  Default: ``'error'``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Per-storey is the default. depth_m applies to perimeter_core; apartments controls apply
    to apartments. Inactive controls are omitted from serialization. on_failure='per_storey'
    is an opt-in whole-building substitution.

    Examples
    --------
    Example::

        from epsm_core.specs.geometry import ZoningSpec

        zoning = ZoningSpec(mode="perimeter_core", depth_m=4.5)
    """

    mode: Literal["whole_building", "per_storey", "perimeter_core", "apartments"] = "per_storey"
    depth_m: Positive = 4.5
    apartments: ApartmentLayoutSpec = ApartmentLayoutSpec()
    on_failure: Literal["error", "per_storey"] = "error"

    @model_serializer(mode="wrap")
    def selected_controls(self, handler):
        """Serialize only controls relevant to the selected zoning mode.

        Parameters
        ----------
        handler : callable
            Pydantic serialization handler for the unfiltered model representation.

        Returns
        -------
        dict
            Handler-produced mapping with inactive controls removed.

        Notes
        -----
        Called by Pydantic during serialization. Omitting unused controls prevents irrelevant
        defaults from changing physical hashes.

        Examples
        --------
        Example::

            from epsm_core.specs.geometry import ZoningSpec

            assert "depth_m" not in ZoningSpec().model_dump()
        """

        # 1. Serialize only controls relevant to the selected zoning mode.
        data = handler(self)
        if self.mode != "perimeter_core":
            data.pop("depth_m", None)
        if self.mode != "apartments":
            data.pop("apartments", None)
        if self.mode not in ("perimeter_core", "apartments"):
            data.pop("on_failure", None)
        return data

    @model_validator(mode="after")
    def applicable_controls(self):
        """Reject explicitly incompatible procedural-zoning controls.

        Returns
        -------
        Self
            Validated zoning specification.

        Raises
        ------
        ValueError
            Rejected conditions: depth_m applies only to perimeter_core zoning; Fallback applies
            only to procedural zoning.

        Notes
        -----
        Nondefault depth applies only to perimeter_core. Fallback is accepted only for
        perimeter_core or apartments; the default depth remains tolerated during mode
        replacement.

        Examples
        --------
        Example::

            from epsm_core.specs.geometry import ZoningSpec

            assert ZoningSpec(mode="perimeter_core", depth_m=3).depth_m == 3
        """

        # 1. Reject explicitly incompatible procedural-zoning controls.
        if (
            "depth_m" in self.model_fields_set
            and self.mode != "perimeter_core"
            and self.depth_m != 4.5
        ):
            raise ValueError("depth_m applies only to perimeter_core zoning")
        if self.mode not in ("perimeter_core", "apartments") and self.on_failure != "error":
            raise ValueError("Fallback applies only to procedural zoning")
        return self


class BuildingPart(Spec):
    """One physical footprint column with explicit storey elevations and ownership.

    Attributes
    ----------
    identifier : str
        Stable identifier within the owning collection. Must match pattern
        '^[A-Za-z0-9_-]+$'. Required at construction.
    footprint : Footprint
        Explicit valid two-dimensional metric footprint; no coordinate transformation is
        inferred.  Required at construction.
    storey_elevations_m : tuple[float, ...]
        Increasing grade-relative elevations including the top of the final storey. Minimum
        length 2. Required at construction.
    conditioned : bool
        Whether the physical part or cell belongs to conditioned thermal volume.  Default:
        ``True``.
    roof : RoofSpec | None
        Part-specific roof override or shared roof controls, depending on the owning model.
        Default: ``None``.
    height_status : Literal['measured', 'inferred', 'assumed']
        Evidence classification for supplied heights: measured, inferred or assumed.
        Default: ``'assumed'``.
    outline_kind : Literal['facade', 'roof_edge_proxy', 'illustrative']
        Whether the outline represents a facade, roof-edge proxy or illustrative geometry.
        Default: ``'facade'``.
    outline_reviewed : bool
        Caller-provided review status for the source outline.  Default: ``False``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Elevations begin at uniform grade zero and strictly increase. Footprints are
    canonicalized without coordinate movement. IDs allow letters, digits, underscores and
    hyphens for stable facade names.

    Examples
    --------
    Example::

        from epsm_core.specs.geometry import BuildingPart
        from epsm_core.specs.geometry import Footprint

        part = BuildingPart(
            identifier="main",
            footprint=Footprint.rectangle(10, 8),
            storey_elevations_m=(0, 3, 6),
        )
    """

    identifier: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]+$")]
    footprint: Footprint
    storey_elevations_m: Annotated[tuple[float, ...], Field(min_length=2)]
    conditioned: bool = True
    roof: RoofSpec | None = None
    height_status: Literal["measured", "inferred", "assumed"] = "assumed"
    outline_kind: Literal["facade", "roof_edge_proxy", "illustrative"] = "facade"
    outline_reviewed: bool = False

    @model_validator(mode="after")
    def ordered_storeys(self):
        """Validate elevations and canonicalize footprint identity.

        Returns
        -------
        Self
            Building part with a canonical footprint.

        Raises
        ------
        ValueError
            Rejected conditions: Parts require strictly increasing elevations beginning at
            uniform grade 0.

        Notes
        -----
        Elevations must begin at grade zero and strictly increase. Normalizing ring order
        stabilizes facade IDs without moving coordinates.

        Examples
        --------
        Example::

            from epsm_core.specs.geometry import BuildingPart
            from epsm_core.specs.geometry import Footprint

            part = BuildingPart(
                identifier="main",
                footprint=Footprint.rectangle(10, 8),
                storey_elevations_m=(0, 3, 6),
            )
            assert part.floors == 2
        """

        # 1. Validate elevations and canonicalize footprint identity.
        z = self.storey_elevations_m
        if z[0] != 0 or any(a >= b for a, b in zip(z, z[1:])):
            raise ValueError(
                "Parts require strictly increasing elevations beginning at uniform grade 0"
            )
        from ..preparation import canonical_polygon

        p = canonical_polygon(self.footprint.polygon)
        object.__setattr__(
            self,
            "footprint",
            Footprint(
                exterior=tuple(p.exterior.coords)[:-1],
                holes=tuple(tuple(r.coords)[:-1] for r in p.interiors),
            ),
        )
        return self

    @property
    def floors(self):
        """Count vertical intervals between successive storey elevations.

        Returns
        -------
        int
            Number of above-grade storeys.

        Notes
        -----
        The terminal elevation is the top of the last storey, not an additional floor.

        Examples
        --------
        Example::

            from epsm_core.specs.geometry import BuildingPart
            from epsm_core.specs.geometry import Footprint

            assert (
                BuildingPart(
                    identifier="main",
                    footprint=Footprint.rectangle(10, 8),
                    storey_elevations_m=(0, 3),
                ).floors
                == 1
            )
        """

        return len(self.storey_elevations_m) - 1


class PartyWall(Spec):
    """Evidence describing contact with a neighbouring building at one facade.

    Attributes
    ----------
    facade_id : str
        Stable physical facade identifier from GeometrySpec.facades().  Required at
        construction.
    neighbor_id : str
        External neighbour identity associated with reviewed facade contact.  Required at
        construction.
    neighbor_conditioning : Literal['heated', 'unheated', 'unknown']
        Evidence classification of the neighbour's thermal conditioning.  Required at
        construction.
    contact_confirmed : bool
        Whether physical facade contact has been reviewed and confirmed.  Required at
        construction.
    assumption_source : str
        Source supporting the party-wall boundary approximation.  Required at construction.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Confirmed geometric contact is assumed adiabatic independently of neighbour heating.
    Optional distances bound a rectangular contact in the directed facade plane; omitted
    bounds cover the complete facade. No neighbouring temperature is inferred.

    Examples
    --------
    Example::

        from epsm_core.specs.geometry import PartyWall

        wall = PartyWall(
            facade_id="main.r0.e0",
            neighbor_id="next",
            neighbor_conditioning="heated",
            contact_confirmed=True,
            assumption_source="survey",
        )
    """

    facade_id: str
    neighbor_id: str
    neighbor_conditioning: Literal["heated", "unheated", "unknown"]
    contact_confirmed: bool
    assumption_source: str
    start_m: Nonnegative = 0
    end_m: Positive | None = None
    bottom_m: float | None = None
    top_m: float | None = None

    @model_validator(mode="after")
    def contact_extents(self):
        if self.end_m is not None and self.end_m <= self.start_m:
            raise ValueError("end_m must exceed start_m")
        if self.bottom_m is not None and self.top_m is not None and self.top_m <= self.bottom_m:
            raise ValueError("top_m must exceed bottom_m")
        if not self.assumption_source.strip():
            raise ValueError("Party wall requires an assumption_source")
        return self


class PartyWallNeighbor(Spec):
    """Explicit neighbouring wall extrusion in the target's metric coordinate frame.

    ``top_m`` is a supplied grade-relative eave height, never an inferred roof peak.
    The caller records whether this value and the wall footprint are measured or
    assumed in the contact operation's ``assumption_source``. Missing heights must
    remain outside this representation rather than silently covering a full facade.
    """

    identifier: str
    footprint: Footprint
    bottom_m: float = 0
    top_m: float

    @model_validator(mode="after")
    def positive_height(self):
        if self.top_m <= self.bottom_m:
            raise ValueError("top_m must exceed bottom_m")
        return self


class FootprintCleanupSpec(Spec):
    """Bounded metric simplification; disable explicitly to preserve source rings."""
    enabled: bool = True
    tolerance_m: Nonnegative = 0.01
    max_area_change_fraction: Fraction = 0.001
    max_perimeter_change_fraction: Fraction = 0.01
    max_symmetric_difference_fraction: Fraction = 0.001
    implementation_version: Literal["footprint-cleanup-1", "footprint-cleanup-2"] = "footprint-cleanup-2"


class GeometrySpec(Spec):
    """Physical building parts, metric frame and thermal-geometry controls.

    Attributes
    ----------
    parts : tuple[BuildingPart, ...]
        Nonempty physical ownership parts; sorted by identifier and checked for plan-area
        overlap. Minimum length 1. Required at construction.
    orientation_deg : float
        Clockwise rotation from the metric source frame into the local scene, in degrees. At
        least 0. Less than 360. Default: ``0``.
    zoning : ZoningSpec
        Thermal subdivision and explicit fallback controls.  Default: ``ZoningSpec()``.
    roof : RoofSpec
        Part-specific roof override or shared roof controls, depending on the owning model.
        Default: ``RoofSpec()``.
    basement_depth_m : Nonnegative
        Uniform nonnegative depth below grade in metres; zero disables basement cells.
        Nonnegative when supplied. Default: ``0``.
    basement_conditioned : bool
        Whether the basement contributes conditioned floor area and volume.  Default:
        ``False``.
    source_crs : str
        Provenance label for already metric input coordinates; no transformation is
        performed from this label.  Default: ``'local_metres'``.
    party_walls : tuple[PartyWall, ...]
        Reviewed facade-contact records used for adiabatic boundary approximation.  Default:
        ``()``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Parts are nonempty, uniquely named, sorted and nonoverlapping in plan. At least one
    conditioned volume is required. Coordinate-system labels are provenance; numerical
    coordinates must already be metric.

    Examples
    --------
    Example::

        from epsm_core.specs.geometry import Footprint
        from epsm_core.specs.geometry import GeometrySpec

        geometry = GeometrySpec.from_footprint(
            Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
        )
    """

    parts: Annotated[tuple[BuildingPart, ...], Field(min_length=1)]
    orientation_deg: Annotated[float, Field(ge=0, lt=360)] = 0
    footprint_cleanup: FootprintCleanupSpec = FootprintCleanupSpec()
    zoning: ZoningSpec = ZoningSpec()
    roof: RoofSpec = RoofSpec()
    basement_depth_m: Nonnegative = 0
    basement_conditioned: bool = False
    source_crs: str = "local_metres"
    party_walls: tuple[PartyWall, ...] = ()

    @model_validator(mode="after")
    def valid_parts(self):
        """Validate part ownership, conditioned volume and party-wall identity.

        Returns
        -------
        Self
            Geometry with parts sorted by identifier.

        Raises
        ------
        ValueError
            Rejected conditions: Part identifiers must be unique; Plan-area parts must not
            overlap; use adjacent columns for setbacks; Conditioned basement requires positive
            basement depth; Building requires conditioned volume.

        Notes
        -----
        Plan-area overlap above 1e-8 m2 is rejected, while contact is permitted. A conditioned
        basement needs positive depth. Detailed party-wall contact evidence is checked during
        graph generation.

        Examples
        --------
        Example::

            from epsm_core.specs.geometry import Footprint
            from epsm_core.specs.geometry import GeometrySpec

            geometry = GeometrySpec.from_footprint(
                Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
            )
            assert geometry.valid_parts() is geometry
        """

        # 1. Validate part ownership, conditioned volume and party-wall identity.
        ids = [p.identifier for p in self.parts]
        if len(ids) != len(set(ids)):
            raise ValueError("Part identifiers must be unique")
        object.__setattr__(self, "parts", tuple(sorted(self.parts, key=lambda p: p.identifier)))
        polygons = [p.footprint.polygon for p in self.parts]
        tree = STRtree(polygons)
        for i, p in enumerate(polygons):
            for j in tree.query(p, predicate="intersects"):
                if i < j and p.intersection(polygons[j]).area > 1e-8:
                    raise ValueError(
                        "Plan-area parts must not overlap; use adjacent columns for setbacks"
                    )
        if self.basement_conditioned and not self.basement_depth_m:
            raise ValueError("Conditioned basement requires positive basement depth")
        if not any(p.conditioned for p in self.parts) and not self.basement_conditioned:
            raise ValueError("Building requires conditioned volume")
        return self

    @classmethod
    def from_footprint(
        cls,
        footprint: Footprint | Polygon | MultiPolygon,
        *,
        storey_elevations_m: tuple[float, ...] | None = None,
        storeys: int | None = None,
        storey_height_m: float | None = None,
        height_status: Literal["measured", "inferred", "assumed"] = "assumed",
        outline_kind: Literal["facade", "roof_edge_proxy", "illustrative"] = "facade",
        outline_reviewed: bool = False,
        **options,
    ) -> Self:
        """Extrude explicit storeys from valid metric polygonal geometry.

        Parameters
        ----------
        footprint : Footprint | Polygon | MultiPolygon
            Explicit valid two-dimensional metric footprint; no coordinate transformation is
            inferred.
        storey_elevations_m : tuple[float, ...] | None
            Explicit increasing elevations in metres, beginning at zero and including the final
            top. Default: ``None``.
        storeys : int | None
            Positive number of above-grade storeys; booleans are rejected. Default: ``None``.
        storey_height_m : float | None
            Positive uniform storey height in metres, used with storeys. Default: ``None``.
        height_status : Literal['measured', 'inferred', 'assumed']
            Evidence classification for supplied heights: measured, inferred or assumed.
            Default: ``'assumed'``.
        outline_kind : Literal['facade', 'roof_edge_proxy', 'illustrative']
            Whether the outline represents a facade, roof-edge proxy or illustrative geometry.
            Default: ``'facade'``.
        outline_reviewed : bool
            Caller-provided review status for the source outline. Default: ``False``.
        **options : dict
            Additional GeometrySpec keyword fields, validated by the resulting model.

        Returns
        -------
        Self
            GeometrySpec with canonical, deterministically named parts.

        Raises
        ------
        ValueError
            Rejected conditions: Supply elevations OR storeys and storey_height_m; storeys must
            be a positive integer; Supply positive storey_height_m with storeys; Footprint must
            be valid, nonempty, two-dimensional metric geometry.
        TypeError
            Rejected conditions: Expected Footprint, Polygon or MultiPolygon in metres.

        Notes
        -----
        Supply elevations or storeys plus storey height, never both. Preserves holes and
        disconnected parts; rejects empty, invalid or 3-D input. Does not infer height, repair
        geometry, transform CRS or scale to EPC area. Use explicit BuildingPart records for
        unequal-height wings.

        Examples
        --------
        Example::

            from epsm_core.specs.geometry import Footprint
            from epsm_core.specs.geometry import GeometrySpec

            geometry = GeometrySpec.from_footprint(
                Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
            )
            assert geometry.conditioned_floor_area_m2 == 160
        """
        # 1. Extrude explicit storeys from valid metric polygonal geometry.
        if storey_elevations_m is not None:
            if storeys is not None or storey_height_m is not None:
                raise ValueError("Supply elevations OR storeys and storey_height_m")
        else:
            if isinstance(storeys, bool) or not isinstance(storeys, int) or storeys < 1:
                raise ValueError("storeys must be a positive integer")
            if storey_height_m is None or storey_height_m <= 0:
                raise ValueError("Supply positive storey_height_m with storeys")
            storey_elevations_m = tuple(i * storey_height_m for i in range(storeys + 1))
        from ..preparation import canonical_polygon

        geometry = footprint.polygon if isinstance(footprint, Footprint) else footprint
        if not isinstance(geometry, (Polygon, MultiPolygon)):
            raise TypeError("Expected Footprint, Polygon or MultiPolygon in metres")
        if geometry.is_empty or not geometry.is_valid or geometry.has_z:
            raise ValueError("Footprint must be valid, nonempty, two-dimensional metric geometry")
        polygons = list(geometry.geoms) if isinstance(geometry, MultiPolygon) else [geometry]
        polygons = sorted((canonical_polygon(p) for p in polygons), key=lambda p: p.wkb_hex)
        return cls(
            parts=tuple(
                BuildingPart(
                    identifier="main" if len(polygons) == 1 else f"part_{i}",
                    footprint=Footprint(
                        exterior=tuple(p.exterior.coords)[:-1],
                        holes=tuple(tuple(r.coords)[:-1] for r in p.interiors),
                    ),
                    storey_elevations_m=storey_elevations_m,
                    height_status=height_status,
                    outline_kind=outline_kind,
                    outline_reviewed=outline_reviewed,
                )
                for i, p in enumerate(polygons)
            ),
            **options,
        )

    @property
    def footprints(self):
        """Return footprints in canonical part order.

        Returns
        -------
        tuple of Footprint
            One footprint per physical part.

        Notes
        -----
        Disconnected parts remain separate; this property does not union their boundaries.

        Examples
        --------
        Example::

            from epsm_core.specs.geometry import Footprint
            from epsm_core.specs.geometry import GeometrySpec

            geometry = GeometrySpec.from_footprint(
                Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
            )
            assert len(geometry.footprints) == len(geometry.parts)
        """

        from ..footprint_cleanup import prepared_footprints
        polygons, _ = prepared_footprints(self)
        return tuple(Footprint(exterior=tuple(p.exterior.coords)[:-1], holes=tuple(tuple(r.coords)[:-1] for r in p.interiors)) for p in polygons)

    @property
    def footprint_area_m2(self):
        """Sum net footprint areas of all physical parts.

        Returns
        -------
        float
            Total plan area in m2.

        Notes
        -----
        Includes unconditioned parts, excludes courtyard holes and does not multiply by storey
        count.

        Examples
        --------
        Example::

            from epsm_core.specs.geometry import Footprint
            from epsm_core.specs.geometry import GeometrySpec

            geometry = GeometrySpec.from_footprint(
                Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
            )
            assert geometry.footprint_area_m2 == sum(p.area_m2 for p in geometry.footprints)
        """

        return sum(f.area_m2 for f in self.footprints)

    @property
    def conditioned_floor_area_m2(self):
        """Sum conditioned above-grade floors and any conditioned basement.

        Returns
        -------
        float
            Conditioned gross floor area in m2.

        Notes
        -----
        A conditioned basement contributes one footprint per part even when its above-grade part
        is unconditioned. Attics are excluded.

        Examples
        --------
        Example::

            from epsm_core.specs.geometry import Footprint
            from epsm_core.specs.geometry import GeometrySpec

            geometry = GeometrySpec.from_footprint(
                Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
            )
            area = geometry.conditioned_floor_area_m2
        """

        return sum(
            f.area_m2 * (p.floors * p.conditioned + int(self.basement_conditioned))
            for p, f in zip(self.parts, self.footprints)
        )

    @property
    def conditioned_volume_m3(self):
        """Compute conditioned extrusion volume from footprint areas and heights.

        Returns
        -------
        float
            Conditioned volume in m3.

        Notes
        -----
        Parts begin at grade zero. Cold attics are excluded; basement depth contributes only
        when basement_conditioned is true.

        Examples
        --------
        Example::

            from epsm_core.specs.geometry import Footprint
            from epsm_core.specs.geometry import GeometrySpec

            geometry = GeometrySpec.from_footprint(
                Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
            )
            volume = geometry.conditioned_volume_m3
        """

        # 1. Compute conditioned extrusion volume from footprint areas and heights.
        return sum(
            f.area_m2
            * (
                p.storey_elevations_m[-1] * p.conditioned
                + self.basement_depth_m * self.basement_conditioned
            )
            for p, f in zip(self.parts, self.footprints)
        )

    def roof_for(self, part: BuildingPart) -> RoofSpec:
        """Select a part-specific roof or the shared geometry default.

        Parameters
        ----------
        part : BuildingPart
            Physical ownership part associated with the current footprint.

        Returns
        -------
        RoofSpec
            Effective roof controls for the part.

        Notes
        -----
        An explicit part roof takes precedence. The returned immutable specification is shared,
        not copied.

        Examples
        --------
        Example::

            from epsm_core.specs.geometry import Footprint
            from epsm_core.specs.geometry import GeometrySpec

            geometry = GeometrySpec.from_footprint(
                Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
            )
            assert geometry.roof_for(geometry.parts[0]) is geometry.roof
        """

        return part.roof or self.roof

    def with_party_wall_contacts(self, neighbors, *, tolerance_m=0.0, assumption_source):
        """Return geometry with confirmed collinear neighbouring contact rectangles.

        Neighbours are :class:`PartyWallNeighbor` extrusions in the same metric
        frame. The default accepts exactly touching opposite-facing wall edges.
        An explicitly supplied tolerance (at most 0.1 m) permits a parallel gap;
        proximity without opposing collinear edges never creates a party wall.
        Existing explicit contacts are retained and overlapping patches are united
        during surface generation. Inputs are not modified and no files are read.
        """
        from ..party_walls import detect_contacts

        contacts = detect_contacts(self, neighbors, tolerance_m=tolerance_m,
                                   assumption_source=assumption_source)
        return self.updated(party_walls=(*self.party_walls, *contacts))

    def facades(self):
        """Inspect stable facade IDs and azimuths without engine or weather resources.

        Returns
        -------
        tuple of FacadeInfo
            Original facade geometry and storey metadata.

        Notes
        -----
        Delegates to the geometry catalogue; coordinates stay in the source frame and azimuth
        includes orientation.

        Examples
        --------
        Example::

            from epsm_core.specs.geometry import Footprint
            from epsm_core.specs.geometry import GeometrySpec

            geometry = GeometrySpec.from_footprint(
                Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
            )
            assert len(geometry.facades()) >= 4
        """
        from ..geometry import facade_catalog

        return facade_catalog(self)

    def widget(self, *, facade=None, context=None, height=600):
        """Return an embedded, offline notebook widget; requires the notebook extra.

        Uses the same resolved surfaces as ``view`` without a local HTTP server.
        Close the widget to release frontend resources. This does not simulate.
        """
        from ..notebook import geometry_widget

        return geometry_widget(self, facade=facade, context=context, height=height)

    def view(self, directory=None, *, facade=None, context=None, launch_browser=True):
        """Write and serve a geometry-only preview with optional facade and context.

        Parameters
        ----------
        directory : str or Path or None
            Local artifact directory; consult Notes for creation, overwrite and default-path
            behavior. Default: ``None``.
        facade : FacadeSpec or None
            Window and shading controls; None uses the preview's zero-glazing default. Default:
            ``None``.
        context : ContextSpec or None
            Explicit shading neighbours; existing context is retained by synthetic generation.
            Default: ``None``.
        launch_browser : bool
            Open the default browser when true; the returned server still needs cleanup.
            Default: ``True``.

        Returns
        -------
        ViewerHandle
            Live context-managed loopback preview.

        Notes
        -----
        No weather or construction input is required. Writes preview artifacts, optionally
        launches a browser, and requires explicit handle cleanup.

        Examples
        --------
        Example::

            from epsm_core.specs.geometry import Footprint
            from epsm_core.specs.geometry import GeometrySpec

            geometry = GeometrySpec.from_footprint(
                Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
            )
            with geometry.view("output/review", launch_browser=False) as handle:
                print(handle.url)
        """

        # 1. Write and serve a geometry-only preview with optional facade and context.
        from ..inspection import preview_geometry

        return preview_geometry(
            self, directory, facade=facade, context=context, launch_browser=launch_browser
        )
