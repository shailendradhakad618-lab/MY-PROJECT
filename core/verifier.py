"""JARVIS verification layer.

Small, dependency-free verifier used by the JARVIS modular architecture.
It records whether an action appears to have completed and provides a
conservative result object for the executor/router.
"""

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class VerificationResult:
    success: bool
    message: str = ""
    evidence: Any = None


class Verifier:
    """Conservative post-action verifier."""

    def verify(
        self,
        action: Any = None,
        result: Any = None,
        check: Optional[Callable[[], bool]] = None,
    ) -> VerificationResult:
        if check is not None:
            try:
                ok = bool(check())
                return VerificationResult(
                    success=ok,
                    message="Verification passed." if ok else "Verification failed.",
                    evidence=ok,
                )
            except Exception as exc:
                return VerificationResult(
                    success=False,
                    message=f"Verification check failed: {exc}",
                )

        # Explicit boolean results are authoritative.
        if isinstance(result, bool):
            return VerificationResult(
                success=result,
                message="Action reported success." if result else "Action reported failure.",
                evidence=result,
            )

        # A result object/dict can expose a success flag.
        if isinstance(result, dict) and "success" in result:
            ok = bool(result.get("success"))
            return VerificationResult(
                success=ok,
                message=str(result.get("message", "")),
                evidence=result,
            )

        # No independent evidence: don't claim a false success.
        # For backwards compatibility, a non-None result is treated as
        # execution completed, while callers can supply `check` when
        # stronger verification is required.
        if result is not None:
            return VerificationResult(
                success=True,
                message="Action completed; no independent verification supplied.",
                evidence=result,
            )

        return VerificationResult(
            success=False,
            message="No execution result was supplied for verification.",
        )


def verify_action(action: Any = None, result: Any = None, check=None) -> VerificationResult:
    return Verifier().verify(action=action, result=result, check=check)
