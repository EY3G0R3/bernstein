## NIST OSCAL assessment-results export

`bernstein compliance oscal [--standard <id>] [--out <file>]` exports the per-control assessment the evidence pack records as a NIST OSCAL v1.1.0 assessment-results document: one finding per registered control with its `satisfied` / `not-satisfied` state against a named threshold, one observation per measured control naming the bundle, and the clause of the chosen standard on every finding. The command refuses to export over a bundle it could not read (#5456).
