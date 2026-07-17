# C16: enforced generation attestation

## Problem

C14 introduced exactly-once lowering receipts, but two gaps prevented the
generation contract from being an end-to-end gate:

- `build_generation_contract()` wrote cached digests back into canonical
  Formal RIS.  A later Formal mutation could therefore retain a stale digest
  and pass verification.
- The real LLM workflow included the contract in its prompt but did not run the
  verifier after initial synthesis or compile/QEMU/trace repair.  An LLM
  candidate with zero receipts could still be compiled and executed.

The receipt oracle also remains a first-stage accounting proof: a correct
comment can still be placed beside an incorrect C statement.  C16 does not
claim to solve that AST-semantic problem.

## Pure canonical contract

`ris_op_digest()` is now a pure function of the current register operation. It
does not trust `contract_digest` or mutate Formal RIS.  The digest includes the
full semantic body except operation identity and source provenance, and also
includes lowering-relevant `byte_order` and `write_semantics` evidence.

Generation-contract construction deep-copies its claim scope and evidence, so
editing the returned JSON cannot mutate the canonical Formal document.

Some deterministic backends normalize source-private expressions on deep
copies.  They now attach the freshly computed canonical digest only to that
backend-private copy before normalization.  The private field is excluded from
semantic hashing and never appears in Formal RIS.  This preserves canonical
contract identity without restoring the stale-cache bug.

## Frozen-contract CLI

The lowering oracle now has a command-line interface accepting:

```text
--formal canonical.formal.json
--contract generation-contract.json
--generated candidate.c
--output lowering-report.json
```

Exit status is fail-closed:

- `0`: Formal, frozen contract and candidate receipts all agree;
- `2`: the candidate has missing, duplicate, unknown, rejected or drifted
  receipts;
- `3`: the frozen contract no longer matches Formal or verifier input is
  invalid.

Reports bind the attestation to SHA-256 hashes of the frozen contract and
generated candidate.

## Atomic LLM candidate workflow

Every LLM revision now follows one path:

```text
LLM reply
  -> hidden candidate in the final driver directory
  -> sanitizer
  -> optional instrumentation
  -> frozen-contract verifier
  -> atomic rename to MODULE.c only on success
```

Transport retry and semantic retry are separate.  A rejected candidate and its
prompt, reply and JSON report are preserved in `iter_log`; the currently
accepted source file is unchanged.  Verifier infrastructure failure stops the
workflow instead of being sent to the LLM as a repairable code error.

The gate runs after:

- initial synthesis;
- every compile repair;
- every QEMU repair;
- every trace repair;
- `skip_synth` input validation;
- successful compile, QEMU and final trace acceptance.

Successful E2E runs write `iter_log/final-lowering.json`; its generated-file
SHA-256 therefore binds the final accepted source to the frozen contract.

Compile repair no longer creates an uncompiled candidate after the final
allowed compile attempt.  QEMU and trace repairs re-enter the full verified
compile loop instead of potentially running an older module.

## Verification and boundary

The regression suite includes contract purity, Formal value/address mutation,
stale digest, provenance, byte order, frozen-contract drift, CLI exit status,
candidate hash, atomic promotion and all-rejected-candidate preservation.

The 19-driver deterministic matrix retains the C15 readiness result: harness
5/19, bare-metal 5/19, Linux 3/19 and all-backend 3/19.  Thus the pure digest
fix does not hide backend normalization drift or create a readiness regression.

C16 proves receipt bijection and contract identity.  It does not prove that the
C statement implements the receipt.  The next verifier must structurally bind
each operation to a unique generated-C AST anchor and check primitive, width,
endianness, address, value/RMW transform, guard, ordering and extra hardware
accesses.  Formal RIS `Call` is still required for callsite completeness.
