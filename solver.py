"""Polar-Bear-Router — a fill-only-empty cover on the certified champion base.

Layering: the full certified champion stack runs first (imported from
``_champion_base``). This delta serves its OWN plan ONLY when the champion stack
returns EMPTY on an order, then attempts a lean, CHAIN-CORRECT best-of-fee-tiers
Uniswap V3 fill. Because it fires only on a champion-empty result, it can only lift
a champion-0 to a delivery — it never regresses or drops a champion-served order.

Thesis: the champion's own skip-fill helpers (``_McSolver``/``_py_improve``) are
pinned to BASE addresses (``_MC_QUOTER``/``_MC_ROUTER`` = Base), so on **Ethereum**
its multicall cover mis-targets and some ETH orders fall through EMPTY. This delta
uses the correct QuoterV2 + SwapRouter per chain, so it can cover those.
"""
from __future__ import annotations

import logging

from _champion_base import SOLVER_CLASS as _Base
from minotaur_subnet.shared.types import ExecutionPlan, Interaction

logger = logging.getLogger(__name__)

_BRAND = "Polar-Bear-Router"
_AUTHOR = "wisedev0103"

# Chain-correct Uniswap V3 infrastructure (QuoterV2 + SwapRouter). encode_exact_
# input_single auto-selects V1 (Ethereum, with deadline) vs V2 (Base) by chain_id.
_QUOTER = {
    1: "0x61fFE014bA17989E743c5F6cB21bF9697530B21e",     # Ethereum QuoterV2
    8453: "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a",  # Base QuoterV2
}
_ROUTER = {
    1: "0xE592427A0AEce92De3Edee1F18E0157C05861564",     # Ethereum SwapRouter (V1)
    8453: "0x2626664c2603336E57B271c5C0b26F421741e481",  # Base SwapRouter02 (V2)
}
_FEES = (100, 500, 3000, 10000)


class PolarBearRouter(_Base):
    """Champion stack + a chain-correct fill-only-empty cover delta."""

    def metadata(self):
        m = super().metadata()
        try:
            import dataclasses
            if dataclasses.is_dataclass(m):
                return dataclasses.replace(m, name=_BRAND, author=_AUTHOR)
        except Exception:
            pass
        rep = getattr(m, "_replace", None)
        if callable(rep):
            try:
                return rep(name=_BRAND, author=_AUTHOR)
            except Exception:
                pass
        try:
            m.name = _BRAND
        except Exception:
            pass
        return m

    # ── cover helpers ────────────────────────────────────────────────────────
    def _pbr_params(self, intent, state):
        try:
            norm = getattr(self, "_normalized_swap_params", None)
            p = norm(intent, state) if callable(norm) else {}
            if not p:
                p = dict(getattr(state, "raw_params", None) or {})
            tin = str(p.get("input_token", "") or "")
            tout = str(p.get("output_token", "") or "")
            amt = int(p.get("input_amount", 0) or 0)
            mino = int(p.get("min_output_amount", 0) or 0)
            if amt <= 0 or not tin or not tout or tin.lower() == tout.lower():
                return None
            return p, tin, tout, amt, mino
        except Exception:
            return None

    def _pbr_w3(self, cid):
        try:
            gw = getattr(self, "_get_web3", None)
            return gw(cid) if callable(gw) else None
        except Exception:
            return None

    def _pbr_best_quote(self, w3, cid, tin, tout, amt):
        """Best QuoterV2 exactInputSingle output across fee tiers, or (0, None)."""
        from eth_utils import to_checksum_address as _ck
        quoter = _ck(_QUOTER[cid])
        best, best_fee = 0, None
        for fee in _FEES:
            try:
                data = ("0xc6a5026a"
                        + tin[2:].rjust(64, "0").lower()
                        + tout[2:].rjust(64, "0").lower()
                        + format(int(amt), "064x")
                        + format(int(fee), "064x")
                        + format(0, "064x"))
                res = w3.eth.call({"to": quoter, "data": data})
                b = bytes(res)
                if len(b) >= 32:
                    out = int.from_bytes(b[:32], "big")
                    if out > best:
                        best, best_fee = out, fee
            except Exception:
                continue
        return best, best_fee

    def _pbr_recipient(self, state, p):
        try:
            ar = getattr(self, "_apex_recipient", None)
            r = ar(state, p) if callable(ar) else ""
        except Exception:
            r = ""
        if not r:
            r = (str(p.get("receiver", "") or "")
                 or getattr(state, "contract_address", "")
                 or getattr(state, "owner", ""))
        return r

    def _pbr_deadline(self, snapshot):
        try:
            ad = getattr(self, "_apex_deadline", None)
            if callable(ad):
                return int(ad(snapshot))
        except Exception:
            pass
        return 9999999999

    def _pbr_cover(self, intent, state, snapshot):
        pp = self._pbr_params(intent, state)
        if pp is None:
            return None
        p, tin, tout, amt, mino = pp
        cid = int(getattr(state, "chain_id", 0) or 0)
        if cid not in _QUOTER:
            return None
        w3 = self._pbr_w3(cid)
        if w3 is None:
            return None
        best, best_fee = self._pbr_best_quote(w3, cid, tin, tout, amt)
        if best_fee is None or best <= 0 or best < mino:
            return None
        recip = self._pbr_recipient(state, p)
        if not recip:
            return None
        deadline = self._pbr_deadline(snapshot)
        from eth_utils import to_checksum_address as _ck
        from common.abi_utils import encode_approve
        from strategies.dex_aggregator.v3_codec import encode_exact_input_single
        router = _ck(_ROUTER[cid])
        approve = encode_approve(router, int(amt))
        swap = encode_exact_input_single(
            _ck(tin), _ck(tout), int(best_fee), _ck(recip), deadline,
            int(amt), int(mino), 0, cid,
        )
        ix = [
            Interaction(target=_ck(tin), value="0", call_data=approve, chain_id=cid),
            Interaction(target=router, value="0", call_data=swap, chain_id=cid),
        ]
        return ExecutionPlan(
            intent_id=intent.app_id, interactions=ix, deadline=deadline,
            nonce=state.nonce, metadata={"solver": "polar-bear-cover", "chain_id": cid},
        )

    def generate_plan(self, intent, state, snapshot=None):
        base = super().generate_plan(intent, state, snapshot)
        if base is not None and getattr(base, "interactions", None):
            return base  # champion served it — never touch (no regression)
        try:
            cover = self._pbr_cover(intent, state, snapshot)
            if cover is not None and getattr(cover, "interactions", None):
                logger.warning("[polar-bear] covered a champion-empty order")
                return cover
        except Exception:
            logger.exception("[polar-bear] cover failed")
        return base


SOLVER_CLASS = PolarBearRouter


class _PymsnoSplit3(PolarBearRouter):
    """pymsno pymsno-split3: never-regress delta on the certified champion.
    Serves its own plan only when it strictly improves on the champion's;
    defers to the champion on any doubt."""

    def metadata(self):
        base = super().metadata()
        try:
            import dataclasses as _dc
            if _dc.is_dataclass(base):
                return _dc.replace(base, name="pymsno-split3")
        except Exception:
            pass
        rep = getattr(base, "_replace", None)
        if callable(rep):
            try:
                return rep(name="pymsno-split3")
            except Exception:
                pass
        return base

    def _py_params(self, intent, state):
        try:
            norm = getattr(self, "_normalized_swap_params", None)
            p = norm(intent, state) if callable(norm) else {}
            if not p:
                p = dict(getattr(state, "raw_params", None) or {})
            tin = str(p.get("input_token", "") or "")
            tout = str(p.get("output_token", "") or "")
            amt = int(p.get("input_amount", 0) or 0)
            mino = int(p.get("min_output_amount", 0) or 0)
            if amt <= 0 or not tin or not tout or tin.lower() == tout.lower():
                return None
            return p, tin, tout, amt, mino
        except Exception:
            return None

    def _py_ctx(self, state):
        try:
            gw = getattr(self, "_get_web3", None)
            cid = int(getattr(state, "chain_id", 0) or 0)
            w3 = gw(cid or 8453) if callable(gw) else None
            return (w3, cid) if w3 is not None else None
        except Exception:
            return None

    def _py_tier_outs(self, w3, tin, tout, amt):
        try:
            from eth_abi import decode as _d
            import mc_data as _md
            calls = [(_md._MC_QUOTER, self._mc_qdata(tin, tout, amt, f)) for f in _md._MC_FEES]
            res = self._mc_run(w3, calls)
            outs = {}
            if res:
                for i, f in enumerate(_md._MC_FEES):
                    ok, rb = res[i]
                    if ok and len(rb) >= 32:
                        try:
                            o = int(_d(_md._MC_QOUT, bytes(rb))[0])
                            if o > 0:
                                outs[f] = o
                        except Exception:
                            pass
            return outs
        except Exception:
            return {}

    def _py_base_out(self, w3, base, tin, tout, amt):
        try:
            from eth_abi import decode as _d
            import mc_data as _md
            if base is None or not getattr(base, "interactions", None):
                return 0
            bc = self._mc_base_call(base, tin, tout, amt)
            if not bc or bc == "empty":
                return 0
            r = self._mc_run(w3, [bc])
            if r and r[0][0] and len(r[0][1]) >= 32:
                return int(_d(_md._MC_QOUT, bytes(r[0][1]))[0])
        except Exception:
            return 0
        return 0

    def _py_recip_deadline(self, state, snapshot, p):
        try:
            ar = getattr(self, "_apex_recipient", None)
            recip = ar(state, p) if callable(ar) else ""
        except Exception:
            recip = ""
        if not recip:
            recip = str(p.get("receiver", "") or "") or getattr(state, "contract_address", "") or getattr(state, "owner", "")
        try:
            ad = getattr(self, "_apex_deadline", None)
            deadline = int(ad(snapshot)) if callable(ad) else 9999999999
        except Exception:
            deadline = 9999999999
        return recip, deadline

    def _py_single_ix(self, tin, tout, amt, mino, fee, recip, deadline, cid):
        from eth_utils import to_checksum_address as _ck
        from common.abi_utils import encode_approve
        from strategies.dex_aggregator.v3_codec import encode_exact_input_single
        import mc_data as _md
        router = _ck(_md._MC_ROUTER)
        call = encode_exact_input_single(_ck(tin), _ck(tout), int(fee), _ck(recip), deadline, amt, mino, 0, cid)
        return [Interaction(target=_ck(tin), value="0", call_data=encode_approve(router, amt), chain_id=cid),
                Interaction(target=router, value="0", call_data=call, chain_id=cid)]

    _PY_RATIOS = (0.5, 0.35, 0.65, 0.25, 0.75)

    def _py_improve(self, intent, state, snapshot, base):
        pp = self._py_params(intent, state)
        ctx = self._py_ctx(state)
        if pp is None or ctx is None:
            return None
        p, tin, tout, amt, mino = pp
        w3, cid = ctx
        tiers = self._py_tier_outs(w3, tin, tout, amt)
        if len(tiers) < 2:
            return None
        beat = self._py_base_out(w3, base, tin, tout, amt) or max(tiers.values())
        top = sorted(tiers.items(), key=lambda kv: kv[1], reverse=True)[:2]
        fa, fb = top[0][0], top[1][0]
        import mc_data as _md
        best_total, best_split = 0, None
        for r in self._PY_RATIOS:
            aA = amt * int(r * 1000) // 1000
            aB = amt - aA
            if aA <= 0 or aB <= 0:
                continue
            q = self._mc_run(w3, [(_md._MC_QUOTER, self._mc_qdata(tin, tout, aA, fa)),
                                  (_md._MC_QUOTER, self._mc_qdata(tin, tout, aB, fb))])
            if not q or not q[0][0] or not q[1][0]:
                continue
            from eth_abi import decode as _d
            try:
                total = int(_d(_md._MC_QOUT, bytes(q[0][1]))[0]) + int(_d(_md._MC_QOUT, bytes(q[1][1]))[0])
            except Exception:
                continue
            if total > best_total:
                best_total, best_split = total, (aA, aB)
        if best_split is None or best_total <= beat or best_total < mino:
            return None
        aA, aB = best_split
        recip, deadline = self._py_recip_deadline(state, snapshot, p)
        if not recip:
            return None
        ixA = self._py_single_ix(tin, tout, aA, 0, fa, recip, deadline, cid)
        ixB = self._py_single_ix(tin, tout, aB, 0, fb, recip, deadline, cid)
        ix = [ixA[0], ixA[1], ixB[1]]
        return ExecutionPlan(intent_id=intent.app_id, interactions=ix, deadline=deadline,
                             nonce=state.nonce, metadata={"solver": "pymsno-split3", "chain_id": cid})

    def generate_plan(self, intent, state, snapshot=None):
        base = super().generate_plan(intent, state, snapshot)
        try:
            mine = self._py_improve(intent, state, snapshot, base)
            if mine is not None and getattr(mine, "interactions", None):
                return mine
        except Exception:
            pass
        return base


SOLVER_CLASS = _PymsnoSplit3
