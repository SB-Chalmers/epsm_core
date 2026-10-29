# File: _version.py
# Purpose: Development version; simulation identities use content hashes.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
# License: MIT; see the project-root LICENSE for the full permission and warranty terms.
# Author: Sanjay Somanath <sanjay.somanath@chalmers.se>
# Project PI: Alexander Hollberg
# Computational Sustainable Design Group
# Research Area of Sustainable Built Environments
# Chalmers University of Technology, Gothenburg
# Date created: 2026-09-06 (documentation-header creation; not original file creation)
# Date modified: 2026-10-21
# Changelog:
#   2026-10-21 - Add public output capability discovery without engine startup.
#   2026-10-20 - Prepare 0.8.0 for the separate Viewer display API.
#   2026-09-06 - Document _version interfaces, examples, constraints and processing rationale.

"""Development version; simulation identities use content hashes.

Notes
-----
The development version is shared by package metadata and compilation reports. Compiler
identities also include raw Python source hashes, so a documentation-only change still
changes the compiler digest.

Examples
--------
Example::

    from epsm_core._version import __version__

    assert isinstance(__version__, str)
"""

__version__ = "0.9.0"
