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


class _PymsnoNative(PolarBearRouter):
    """pymsno pymsno-native: never-regress delta on the certified champion.
    Serves its own plan only when it strictly improves on the champion's;
    defers to the champion on any doubt."""

    def metadata(self):
        base = super().metadata()
        try:
            import dataclasses as _dc
            if _dc.is_dataclass(base):
                return _dc.replace(base, name="pymsno-native")
        except Exception:
            pass
        rep = getattr(base, "_replace", None)
        if callable(rep):
            try:
                return rep(name="pymsno-native")
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

    _NAT_QUOTER = {1: "0x61fFE014bA17989E743c5F6cB21bF9697530B21e",
                   8453: "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"}
    _NAT_ROUTER = {1: "0xE592427A0AEce92De3Edee1F18E0157C05861564",
                   8453: "0x2626664c2603336E57B271c5C0b26F421741e481"}
    _NAT_MIDS = {1: ("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
                     "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"),
                 8453: ("0x4200000000000000000000000000000000000006",
                        "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")}
    _NAT_FEES = (500, 3000, 100, 10000)

    def _nat_direct(self, w3, cid, tin, tout, amt):
        from eth_utils import to_checksum_address as _ck
        q = _ck(self._NAT_QUOTER[cid])
        ti = (tin[2:] if tin.startswith("0x") else tin).lower()
        to = (tout[2:] if tout.startswith("0x") else tout).lower()
        best, bf = 0, None
        for fee in self._NAT_FEES:
            data = ("c6a5026a" + ti.rjust(64, "0") + to.rjust(64, "0")
                    + format(amt, "064x") + format(int(fee), "064x") + "0" * 64)
            try:
                ret = bytes(w3.eth.call({"to": q, "data": "0x" + data}))
                out = int.from_bytes(ret[:32], "big") if len(ret) >= 32 else 0
            except Exception:
                out = 0
            if out > best:
                best, bf = out, fee
        return best, bf

    def _nat_hop(self, w3, cid, tin, tout, amt):
        from eth_utils import to_checksum_address as _ck
        from eth_abi import encode as _e
        q = _ck(self._NAT_QUOTER[cid])
        tinb = bytes.fromhex(tin[2:] if tin.startswith("0x") else tin)
        toutb = bytes.fromhex(tout[2:] if tout.startswith("0x") else tout)
        best, bp = 0, None
        for mid in self._NAT_MIDS[cid]:
            if mid.lower() in (tin.lower(), tout.lower()):
                continue
            midb = bytes.fromhex(mid[2:])
            for f1 in self._NAT_FEES:
                for f2 in self._NAT_FEES:
                    path = tinb + int(f1).to_bytes(3, "big") + midb + int(f2).to_bytes(3, "big") + toutb
                    data = bytes.fromhex("cdca1753") + _e(["bytes", "uint256"], [path, amt])
                    try:
                        ret = bytes(w3.eth.call({"to": q, "data": "0x" + data.hex()}))
                        out = int.from_bytes(ret[:32], "big") if len(ret) >= 32 else 0
                    except Exception:
                        out = 0
                    if out > best:
                        best, bp = out, path
        return best, bp

    def _py_improve(self, intent, state, snapshot, base):
        # NEVER-REGRESS BY CONSTRUCTION. We only act when the full champion
        # (including its own cover) returned NO plan. On an order the champion
        # served we cannot know its ACTUAL on-chain output at plan-time — the
        # old code compared our quote to _py_base_out (a naive single-pool
        # re-quote), which UNDERESTIMATES a smart champion and made us override
        # + deliver less => regression. So we fill only blind spots the champion
        # drops, with a rich native search (direct single across fees + 2-hop).
        if base is not None and getattr(base, "interactions", None):
            return None
        try:
            pp = self._py_params(intent, state)
            ctx = self._py_ctx(state)
            if pp is None or ctx is None:
                return None
            p, tin, tout, amt, mino = pp
            w3, cid = ctx
            if cid not in self._NAT_QUOTER:
                return None
            d_out, d_fee = self._nat_direct(w3, cid, tin, tout, amt)
            m_out, m_path = self._nat_hop(w3, cid, tin, tout, amt)
            best = max(d_out, m_out)
            if best <= 0 or best < mino:
                return None  # no valid fill for this dropped order
            from eth_utils import to_checksum_address as _ck
            from common.abi_utils import encode_approve
            from strategies.dex_aggregator.v3_codec import encode_exact_input, encode_exact_input_single
            recip, deadline = self._py_recip_deadline(state, snapshot, p)
            if not recip:
                return None
            router = _ck(self._NAT_ROUTER[cid])
            if d_out >= m_out and d_fee is not None:
                call = encode_exact_input_single(_ck(tin), _ck(tout), int(d_fee), _ck(recip), deadline, amt, mino, 0, cid)
            else:
                call = encode_exact_input(m_path, _ck(recip), deadline, amt, mino)
            ix = [Interaction(target=_ck(tin), value="0", call_data=encode_approve(router, amt), chain_id=cid),
                  Interaction(target=router, value="0", call_data=call, chain_id=cid)]
            return ExecutionPlan(intent_id=intent.app_id, interactions=ix, deadline=deadline,
                                 nonce=state.nonce, metadata={"solver": "pymsno-native", "chain_id": cid})
        except Exception:
            logger.exception("[pymsno-native] failed")
            return None

    def generate_plan(self, intent, state, snapshot=None):
        base = super().generate_plan(intent, state, snapshot)
        try:
            mine = self._py_improve(intent, state, snapshot, base)
            if mine is not None and getattr(mine, "interactions", None):
                return mine
        except Exception:
            pass
        return base


SOLVER_CLASS = _PymsnoNative
