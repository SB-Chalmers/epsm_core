# Continuous integration

Pull requests into `dev` or `main` run one `ci` job on Python 3.13
(Node.js 22 for JavaScript). The development job checks this package and its
necessary dependencies; it does not certify the entire EPSM ecosystem.
The executable commands are in [.github/workflows/ci.yml](../.github/workflows/ci.yml).

## Dependency selection during a version transition

The development job installs the Data package at the revision named by EPSM `main`. It
checks out EPSM `main` once, read-only, and captures that checkout's SHA. When
every supported pin in `compatibility.json` satisfies the bounds declared in this
package's `pyproject.toml`, the job installs the supported cohort. When a pin
falls outside a declared bound, as happens while a coordinated release raises
lower bounds before EPSM promotes the new combination, the job installs the whole
cohort named by `compatibility-candidate.json` at the same EPSM SHA, provided
that record satisfies the bounds and names immutable revisions. When neither
record satisfies the bounds, the job fails before installing anything and names
the record and bound that disagree. Publish the candidate record on EPSM `main`
or correct the bound; do not retry unchanged.

The selection depends only on committed content: this pull request's
`pyproject.toml` and the two records at one EPSM `main` SHA. No label, repository
variable or workflow input takes part. The step summary records the EPSM SHA, the
record used, and each dependency's bound, version and revision; the log records
the checked-out revisions after installation. A pass on the candidate cohort is a
development check of this package. It does not verify the candidate combination
and does not replace Release verification. The rule is described in the
handbook's [platform compatibility page](https://github.com/SB-Chalmers/epsm_development/blob/main/docs/platform-compatibility.md#development-checks-during-a-version-transition).

Run **Release verification** explicitly before tagging or publishing a release,
and when a change needs the full engine, database, browser or installed-package
checks. Select one exact dependency cohort and keep that selection through the
release; do not use labels to change the tested dependencies. A merge or branch
synchronization does not publish a release or dispatch another full suite.

Do not retry dependency conflicts or missing credentials unchanged. Fix their
cause, then rerun only the affected checks. Preserve failing evidence.

See the [shared branch and CI policy](https://github.com/SB-Chalmers/epsm_development/blob/main/docs/branches-and-releases.md).
