# EPSM Core

<!-- EPSM introduction: Pocket CAD -->
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/welcome/epsm_core-dark.png">
  <img src="docs/assets/welcome/epsm_core.png" width="160" height="160" alt="EPSM Core — Physical building geometry: the same open cell with its base active.">
</picture>

Start with a building. EPSM Core helps you author its physical geometry, inspect
material quantities and record renovation states. It supplies the shared building
model used across EPSM and runs EnergyPlus simulations when you are ready.

**[Explore the EPSM platform →](https://github.com/SB-Chalmers/epsm/blob/main/docs/platform.md)**
<!-- /EPSM introduction -->

[![CI](https://img.shields.io/badge/CI-GitHub_Actions-2088FF?logo=githubactions&logoColor=white)](https://github.com/SB-Chalmers/epsm_core/actions/workflows/ci.yml) [![Releases](https://img.shields.io/badge/releases-GitHub-181717?logo=github&logoColor=white)](https://github.com/SB-Chalmers/epsm_core/releases) [![Issues](https://img.shields.io/badge/issues-GitHub-181717?logo=github&logoColor=white)](https://github.com/SB-Chalmers/epsm_core/issues)

## Getting started

Requires Python 3.11+ and Git. Access to the EPSM dependency repositories is
required for the source installation below.

```sh
git clone https://github.com/SB-Chalmers/epsm_core.git
cd epsm_core
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install "epsm_data @ git+https://github.com/SB-Chalmers/epsm_data.git@main"
python -m pip install -e .
```

```python
from epsm_core import Building

building = Building(preset="illustrative-reference")
print(building)
print(building.quantities().by_material())
```

The preset contains illustrative teaching inputs. For a simulation, supply your
own building assumptions, a local EPW and an EnergyPlus 24.2 installation.
Interactive browser and notebook display uses the separate `epsm_viewer` package.

## Documentation

- [Detailed guide](docs/guide.md)
- [Physical building authoring](docs/physical-building.md)
- [Notebook lessons](demo/README.md)
- [Usage and simulation](docs/usage.md)
- [API reference](docs/api.md)

## License

[MIT](LICENSE).

## People and support

Developed at Chalmers University of Technology as part of the EPSM research platform.

**Funding**: Swedish Energy Agency (Project ID: P2024-04053)

**Partners**:

- Lindholmen Science Park AB
- Sinom AB
- Stiftelsen Chalmers Industriteknik

**Team**:

- **Lead Developer**: Sanjay Somanath
- **Principal Investigator**: Alexander Hollberg
- **Contributors**: Yinan Yu, Dag Wästberg

<p align="center">
  <img src="docs/assets/welcome/logos.png" width="100%" alt="Chalmers University of Technology, Chalmers Industriteknik, Sinom, Lindholmen Science Park and Swedish Energy Agency logos">
</p>
