from __future__ import annotations
import os
import re
import copy
from extractor.formal import walk_leaf_ops
from extractor.spec import TypeMap, PrimitiveMap, StateMap, CallbackMap, PUBLIC_CALLBACK_TYPES
from ..subsystem_runner import (portable_sdhci_accessor_only,
                               portable_virtio_state_only)
from .constants import MODELED_STATE_FIELDS
from ..common import (ops_to_c, local_decls, value_var_names,
                     replace_expr_var, addr_to_c, lowering_receipt,
                     ris_op_digest, lowering_recipes,
                     transaction_runtime_prelude, transaction_digest,
                     detect_transaction_transports,
                     transaction_runtime_prelude_filtered)

def normalize_text(text: str, safe_function_calls: set[str] | None = None
                    ) -> tuple[str, bool]:
    """Lower source-private member expressions to the generated device state.

    The replacement is deliberately conservative and is reported as an
    unsupported semantic binding, so the module can be compiled/tested without
    readiness falsely claiming exact reconstruction.
    """
    unsupported = False
    original = text
    # String/character literals can leak into a recovered expression through
    # macro-expanded logging calls. They are never meaningful MMIO values.
    text = re.sub(r'"(?:\\.|[^"\\])*"', "0", text)
    text = re.sub(r"'(?:\\.|[^'\\])*'", "0", text)
    unsupported |= text != original
    text = re.sub(r"\bd->hwirq\b", "irqd_to_hwirq(d)", text)
    hpi_root = (r"\b[A-Za-z_]\w*"
                r"(?:(?:->|\.)[A-Za-z_]\w*)*?"
                r"(?:->|\.)hpi")
    text = re.sub(hpi_root + r"(?:->|\.)base\b", "base", text)
    text = re.sub(hpi_root + r"(?:->|\.)regstep\b",
                  "__state_hpi_regstep", text)
    text = re.sub(
        r"\b[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*?"
        r"(?:->|\.)sie_num\b", "__state_sie_num", text)
    text = re.sub(
        r"\b[A-Za-z_]\w*->(?:base|mmio|reg|regs|ioaddr|[A-Za-z_]\w*_base)\b",
        "base", text)
    text = re.sub(r"\b[A-Za-z_]\w*_base\b", "base", text)
    for field in MODELED_STATE_FIELDS:
        text = re.sub(
            rf"\b[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*"
            rf"(?:->|\.){re.escape(field)}\b",
            f"__state_{field}", text)
    text = re.sub(r"\bnum_gpios\b", "__state_ngpio", text)
    safe_calls = {
        "BIT", "GENMASK", "FIELD_GET", "FIELD_PREP", "test_bit", "sizeof",
        "lower_32_bits", "upper_32_bits", "cpu_to_le32", "le32_to_cpu",
        "cpu_to_le16", "le16_to_cpu", "irqd_to_hwirq",
        "readb", "readw", "readl", "readq",
        "ioread8", "ioread16", "ioread32", "ioread64",
        "readb_relaxed", "readw_relaxed", "readl_relaxed", "readq_relaxed",
    }
    call_re = re.compile(r"\b([A-Za-z_]\w*)\s*\([^()]*\)")
    def replace_call(match):
        nonlocal unsupported
        if (match.group(1) in safe_calls
                or match.group(1) in (safe_function_calls or set())):
            return match.group(0)
        unsupported = True
        return "0"
    for _ in range(8):
        replaced = call_re.sub(replace_call, text)
        if replaced == text:
            break
        text = replaced
    if re.fullmatch(r"\s*scoped_guard\s*\(.*\)\s*", text):
        text = "1"
    # Statement-like iteration macros are not C expressions.  A partially
    # recovered AST may expose one as a Cond guard; keep the backend buildable
    # with an explicit unsupported marker instead of emitting `if (for (...))`.
    if re.search(r"\bfor_each_[A-Za-z_]\w*\s*\(", text):
        unsupported = True
        text = "0"
    # Remaining source-private fields have no DeviceSpec binding yet.  Use a
    # neutral value and force backend readiness false via the marker.
    complex_member_re = re.compile(
        r"\b[A-Za-z_]\w*(?:\[[^]]+\])?"
        r"(?:(?:->|\.)[A-Za-z_]\w*(?:\[[^]]+\])?)+")
    if complex_member_re.search(text):
        unsupported = True
        text = complex_member_re.sub("0", text)
    member_re = re.compile(
        r"\b[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)+(?:\[[^]]+\])?")
    if member_re.search(text):
        unsupported = True
        text = member_re.sub("0", text)
    array_re = re.compile(
        r"\b[A-Za-z_]\w*\[[^]]+\](?:(?:->|\.)[A-Za-z_]\w*)*")
    if array_re.search(text):
        unsupported = True
        text = array_re.sub("0", text)
    # Adjacent logical-and plus a normalized unary address-of can leave an
    # invalid `&&0`/`&& (` fragment.  This only occurs after the pointee was
    # already classified as unsupported source-private state.
    repaired = re.sub(r"^\s*&&\s*(?=0|\()", "", text)
    repaired = re.sub(r"([(<>=!?:,])\s*&&\s*(?=0|\()", r"\1 ", repaired)
    unsupported |= repaired != text
    text = repaired
    # A normalized address-of member may become `== &0`; remove only unary
    # address-of, never a legitimate bitwise `value & 0` expression.
    text = re.sub(r"^\s*&\s*0\b", "0", text)
    text = re.sub(r"(?<=[=(,])\s*&\s*0\b", " 0", text)
    text = re.sub(r"(?P<op>==|!=|\?|:)\s*&\s*0\b",
                  lambda match: match.group("op") + " 0", text)
    # A source-private upper bound normalized to zero must not be passed to
    # the kernel GENMASK constant assertions as `0 - 1`.
    repaired = re.sub(
        r"\bGENMASK\s*\(\s*0\s*-\s*1\s*,\s*[^)]+\)", "0", text)
    unsupported |= repaired != text
    text = repaired
    if re.search(r"\b0\s*->", text):
        unsupported = True
        text = "0"
    depth = 0
    balanced = True
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                balanced = False
                break
    if depth != 0 or not balanced:
        unsupported = True
        text = "0"
    if re.search(r"(?:&&|\|\||==|!=|<=|>=|[+\-*/%&|^<>=!])\s*$", text):
        unsupported = True
        text = "0"
    # Residual source fragments from macro-expanded diagnostics or incomplete
    # ternaries are not valid standalone C expressions.
    if re.search(r'["\'\\%;{}]|\+\+|--|\?|:', text):
        unsupported = True
        text = "0"
    return text, unsupported

def bind_state_text(text: str, state_prefix: str | None) -> str:
    if not state_prefix:
        return text
    return re.sub(r"\b__state_([A-Za-z_]\w*)\b",
                  rf"{state_prefix}->\1", text)

def normalize_expr(expr, state_prefix: str | None = None,
                    safe_function_calls: set[str] | None = None):
    if not isinstance(expr, dict):
        return expr, False
    out = copy.deepcopy(expr)
    if "Var" in out:
        out["Var"], changed = normalize_text(
            out["Var"], safe_function_calls)
        out["Var"] = bind_state_text(out["Var"], state_prefix)
        return out, changed
    changed = False
    if "BinOp" in out:
        out["BinOp"]["left"], a = normalize_expr(
            out["BinOp"].get("left"), state_prefix, safe_function_calls)
        out["BinOp"]["right"], b = normalize_expr(
            out["BinOp"].get("right"), state_prefix, safe_function_calls)
        changed = a or b
    elif "Ite" in out:
        out["Ite"]["guard"], a = normalize_expr(
            out["Ite"].get("guard"), state_prefix, safe_function_calls)
        out["Ite"]["then"], b = normalize_expr(
            out["Ite"].get("then"), state_prefix, safe_function_calls)
        out["Ite"]["else"], c = normalize_expr(
            out["Ite"].get("else"), state_prefix, safe_function_calls)
        changed = a or b or c
    elif "Bits" in out:
        out["Bits"]["expr"], changed = normalize_expr(
            out["Bits"].get("expr"), state_prefix, safe_function_calls)
    return out, changed

def normalize_transaction_expr(expr, state_prefix, safe_function_calls,
                                transport=None):
    """Bind common regmap handles to the generated Linux private state."""
    if (state_prefix and isinstance(expr, dict) and "Var" in expr):
        if transport == "mfd" and "->" in expr["Var"]:
            return {"Var": f"{state_prefix}->mfd"}, True
        if re.search(r"(?:->|\.)?(?:map|regmap)$", expr["Var"]):
            return {"Var": f"{state_prefix}->regmap"}, True
        if re.search(r"(?:->|\.)client$", expr["Var"]):
            return {"Var": f"{state_prefix}->client"}, True
    return normalize_expr(expr, state_prefix, safe_function_calls)

def normalize_ops(ops, state_prefix: str | None = None,
                   safe_function_calls: set[str] | None = None,
                   contract_digests: dict[str, str] | None = None,
                   contract_recipes: dict[str, dict] | None = None):
    if contract_digests is None:
        contract_digests = {}
        for original in walk_leaf_ops(ops):
            body = (original.get("Read") or original.get("Write")
                    or original.get("ReadModifyWrite")
                    or original.get("TransactionRead")
                    or original.get("TransactionWrite")
                    or original.get("TransactionUpdate"))
            if body and body.get("op_id"):
                digest = body.get("_backend_contract_digest")
                if not digest:
                    digest = (ris_op_digest(original)
                              if not any(name in original for name in
                                         ("TransactionRead", "TransactionWrite",
                                          "TransactionUpdate"))
                              else transaction_digest(original))
                contract_digests[body["op_id"]] = digest
    if contract_recipes is None:
        contract_recipes = lowering_recipes(ops)
    out = copy.deepcopy(ops)
    changed = False
    for op in out:
        if "Cond" in op:
            op["Cond"]["guard"], c = normalize_expr(
                op["Cond"].get("guard"), state_prefix, safe_function_calls)
            op["Cond"]["then_ops"], a = normalize_ops(
                op["Cond"].get("then_ops", []), state_prefix,
                safe_function_calls, contract_digests, contract_recipes)
            op["Cond"]["else_ops"], b = normalize_ops(
                op["Cond"].get("else_ops") or [], state_prefix,
                safe_function_calls, contract_digests, contract_recipes)
            changed |= a or b or c
        elif "Loop" in op:
            op["Loop"]["guard"], g = normalize_expr(
                op["Loop"].get("guard"), state_prefix,
                safe_function_calls)
            op["Loop"]["count"], c = normalize_expr(
                op["Loop"].get("count"), state_prefix, safe_function_calls)
            if op["Loop"].get("bound_expr") is not None:
                op["Loop"]["bound_expr"], b = normalize_expr(
                    op["Loop"].get("bound_expr"), state_prefix,
                    safe_function_calls)
            else:
                b = False
            op["Loop"]["body"], a = normalize_ops(
                op["Loop"].get("body", []), state_prefix,
                safe_function_calls, contract_digests, contract_recipes)
            changed |= a or b or c or g
        elif "Seq" in op:
            op["Seq"]["ops"], a = normalize_ops(
                op["Seq"].get("ops", []), state_prefix,
                safe_function_calls, contract_digests, contract_recipes)
            changed |= a
        elif "Return" in op:
            op["Return"]["value"], a = normalize_expr(
                op["Return"].get("value"), state_prefix,
                safe_function_calls)
            changed |= a
        else:
            transaction_body = (op.get("TransactionRead")
                                or op.get("TransactionWrite")
                                or op.get("TransactionUpdate"))
            if transaction_body is not None:
                op_id = transaction_body.get("op_id")
                if op_id in contract_digests:
                    transaction_body["_backend_contract_digest"] = contract_digests[op_id]
                transaction_body["target"], a = normalize_transaction_expr(
                    transaction_body.get("target"), state_prefix,
                    safe_function_calls, transaction_body.get("transport"))
                changed |= a
                transaction_body["selector"], a = normalize_transaction_expr(
                    transaction_body.get("selector"), state_prefix,
                    safe_function_calls)
                changed |= a
                payload = transaction_body.get("payload") or {}
                scalar = payload.get("Scalar")
                if scalar and scalar.get("value") is not None:
                    scalar["value"], a = normalize_expr(
                        scalar.get("value"), state_prefix, safe_function_calls)
                    changed |= a
                buffer_body = payload.get("Buffer")
                if buffer_body:
                    buffer_body["buffer"], a = normalize_expr(
                        buffer_body.get("buffer"), state_prefix,
                        safe_function_calls)
                    changed |= a
                    buffer_body["count"], a = normalize_expr(
                        buffer_body.get("count"), state_prefix,
                        safe_function_calls)
                    changed |= a
                for key in ("mask", "value"):
                    if key in transaction_body:
                        transaction_body[key], a = normalize_expr(
                            transaction_body.get(key), state_prefix,
                            safe_function_calls)
                        changed |= a
                continue
            body = op.get("Read") or op.get("Write") or op.get("ReadModifyWrite")
            if "StateRead" in op:
                body = op["StateRead"]
                if body.get("var"):
                    body["var"], a = normalize_text(
                        body["var"], safe_function_calls)
                    body["var"] = bind_state_text(body["var"], state_prefix)
                    changed |= a
                continue
            if "StateWrite" in op:
                body = op["StateWrite"]
                body["value"], a = normalize_expr(
                    body.get("value"), state_prefix, safe_function_calls)
                changed |= a
                continue
            if not body:
                continue
            op_id = body.get("op_id")
            if op_id in contract_digests:
                # Backend normalization operates on a deep copy.  Carry the
                # digest of the canonical pre-normalization operation only on
                # that copy, so receipts remain bound to the generation
                # contract without mutating or caching inside Formal RIS.
                body["_backend_contract_digest"] = contract_digests[op_id]
            if op_id in contract_recipes:
                body["_backend_lowering_recipe"] = copy.deepcopy(
                    contract_recipes[op_id])
            addr = body.get("addr", {})
            if "Computed" in addr:
                addr["Computed"], a = normalize_expr(
                    addr["Computed"], state_prefix, safe_function_calls)
                changed |= a
            if "Read" in op and body.get("var"):
                body["var"], a = normalize_text(
                    body["var"], safe_function_calls)
                body["var"] = bind_state_text(body["var"], state_prefix)
                changed |= a
                if (body["var"] in {"true", "false"}
                        or re.fullmatch(r"[A-Z][A-Za-z0-9_]*",
                                        body["var"] or "")):
                    body["var"] = ""
                    changed = True
            key = "value" if "Write" in op else "transform" if "ReadModifyWrite" in op else None
            if key:
                body[key], a = normalize_expr(
                    body.get(key), state_prefix, safe_function_calls)
                changed |= a
    return out, changed

def normalize_module_ops(
        module: dict, state_prefix: str | None = None,
        safe_function_calls: set[str] | None = None,
        backend_ops: list | None = None):
    """Normalize a backend view without changing primitive ownership.

    A backend may select the bound-resource success path or otherwise rewrite
    control structure before emission.  Lowering recipes are nevertheless a
    contract over the canonical module, so derive them before that rewrite
    and carry them explicitly through normalization and C emission.
    """
    canonical_ops = module.get("ops", [])
    contract_recipes = lowering_recipes(canonical_ops)
    if backend_ops is not None:
        for op_id, recipe in lowering_recipes(backend_ops).items():
            contract_recipes.setdefault(op_id, recipe)
    safe_ops, changed = normalize_ops(
        canonical_ops if backend_ops is None else backend_ops,
        state_prefix, safe_function_calls,
        contract_recipes=contract_recipes)
    return safe_ops, changed, contract_recipes
