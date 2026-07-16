# Engineering-agent retrospective v9

> Scope: sequential GPIO state, source differential oracles, SDHCI public
> accessor validation, masked W1C loop proof, and zero-shot 7/12 readiness.

## 1. What worked

The model connected source semantics, RIS extensions, three code generators,
runtime runners, readiness gates, and mutation tests.  It correctly refused to
count the original 5/12 as sufficient evidence after discovering that the
GPIO callback oracle interpreted the same summary it was checking.  The added
source differential showed that the old result survived a stronger gate.

The model also separated two superficially similar parser failures.  NPCM's
diagnostic disappeared when the exact ARM target was retained; Dove and HLWD
still failed the semantic SDHCI contract and were not promoted.  For Altera,
it recognized a narrow W1C drain pattern and attached an environment
assumption instead of treating all `while` loops as bounded.

## 2. Problems observed

### 2.1 A self-referential oracle can certify the same mistake

The C12 callback runner and interpreter both consumed Formal RIS.  This was
valuable backend evidence but could not detect an incorrect summary.  A
separate implementation of `gpio-mmio.c` behavior and targeted mutations were
required to close that gap.

### 2.2 Reaching 7/12 initially hid a return-value bug

Altera compiled and its W1C runtime passed while `gpio_chip.get` still returned
the raw DATA register.  The missing behavior was outside the first oracle's
scope.  Source inspection found that a direct read in `return` had no RIS
result node.  This demonstrates that aggregate readiness and a focused oracle
do not replace callback-by-callback semantic review.

### 2.3 A local fix could have broken helper inlining

Adding `Return` to every direct-read function would have propagated callee
returns into callers as premature exits.  The first obvious patch was therefore
unsafe across function boundaries.  The final change explicitly consumes
inlined returns and propagates their value only when the call occurs in the
caller's return expression.

### 2.4 Loop bounds depend on environment semantics

Writing the observed pending bits to a W1C register clears the current
snapshot, but a device can raise a new bit concurrently.  `max_iterations=1`
is valid only under the recorded quiescence assumption.  Without that
assumption the source loop is not statically bounded.

### 2.5 Compile context and semantic support are independent

Retaining `--target=arm-linux-gnueabi` fixed an NPCM clang error, but target
correctness did not justify accepting all SDHCI drivers.  A structural source
contract was still needed to exclude private accessors and external callbacks.

## 3. Capability boundary

The model is effective at proposing cross-layer mechanisms and using tests,
source inspection, and matrices to converge.  It is not reliable as the final
semantic judge.  In this stage it could have stopped at 7/12 before noticing
the Altera return bug, and a direct implementation of the apparent fix could
have introduced an interprocedural control-flow regression.

Reliable use therefore requires independent source oracles, mutations chosen
to falsify the claimed mechanism, negative controls, exact compile contexts,
full-corpus regression, and explicit environment assumptions.  The claim must
remain narrower than the generated code: sequential register interaction is
covered here; concurrent IRQ arrival, subsystem lifecycle, and real hardware
state machines are not.
