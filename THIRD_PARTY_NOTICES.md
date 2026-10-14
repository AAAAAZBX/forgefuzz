# Third-party components

ForgeFuzz integrates with, but does not vendor, these sibling projects:

- `triton-fuzzer-main`, configured through `triton_root`;
- `fuzz_code_generation`, configured through `ascendc_root`.

Generated case bundles may contain source templates and headers copied at run time
from the configured AscendC project. Before redistributing a case bundle, verify
the license and redistribution terms of that configured upstream checkout and of
the Ascend CANN toolchain. Neither upstream checkout currently exposes a top-level
`LICENSE` file in the validated workspace, so ForgeFuzz cannot infer or grant
rights for those files.
