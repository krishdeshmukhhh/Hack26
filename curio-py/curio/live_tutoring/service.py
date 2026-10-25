"""Independent tutoring session and injectable capture/recognition boundary."""

from dataclasses import dataclass

from curio.coaching_contract import AssessmentStatus

from .checker import (
    Unsupported,
    add,
    antiderivative,
    compose,
    derivative,
    format_polynomial,
    multiply,
    polynomial,
)


@dataclass(frozen=True)
class Feedback:
    status: AssessmentStatus
    message: str
    completion_kind: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "status", AssessmentStatus(self.status))


@dataclass(frozen=True)
class CompletionRecord:
    problem: str
    answer: str
    kind: str
    attempts: tuple["Attempt", ...]


@dataclass(frozen=True)
class Attempt:
    text: str
    feedback: Feedback


class TutoringService:
    def __init__(self, *, checker=polynomial, capture=None, recognize=None):
        self.checker = checker
        self.capture = capture
        self.recognize = recognize
        self.generation = 0
        self.problem = ""
        self.attempts = []
        self.pending = None
        self.substitution = None
        self.differential = None
        self.transformed = None
        self.primitive = None
        self.complete = False
        self.hint_level = 0
        self.integrand = None
        self.practice_problem = None
        self.unassisted = False
        self.completions = ()
        self._completion_recorded = False
        self.domain = "All real x (polynomial integrands and antiderivatives)."

    def start(self, problem):
        # Validate before replacing the current workspace.
        integrand = self.checker(problem, "x")
        self.cancel()
        self.problem = problem
        self.integrand = integrand
        self.attempts = []
        self.substitution = self.differential = self.transformed = self.primitive = None
        self.complete = False
        self.hint_level = 0
        self.practice_problem = None
        self.unassisted = False
        self._completion_recorded = False

    @property
    def completion_kind(self):
        if not self.complete:
            return None
        return "independent_demonstration" if self.unassisted else "guided_completion"

    @property
    def progress_message(self):
        guided = any(record.kind == "guided_completion" for record in self.completions)
        independent = any(record.kind == "independent_demonstration" for record in self.completions)
        if independent:
            return (
                "Independent understanding demonstrated on a related practice problem: "
                "final answer verified without in-app coaching. Broader mastery is not assessed."
            )
        if guided:
            return (
                "Guided completion recorded. "
                "Independent understanding has not yet been demonstrated."
            )
        return "No completed problem yet. Independent understanding has not yet been demonstrated."

    def start_practice(self):
        if not self.complete or self.practice_problem is None:
            raise Unsupported("Complete the current problem before starting practice")
        problem = self.practice_problem
        self.start(problem)
        self.unassisted = True

    def _offer_practice(self):
        # Translation preserves the substitution structure without exposing a solution.
        candidate = self.problem.replace("x", "(x+1)")
        try:
            related = self.checker(candidate, "x")
        except Unsupported:
            related = self.integrand
        if related == self.integrand:
            candidate = "2*x*(x^2+2)^2"
            if self.checker(candidate, "x") == self.integrand:
                candidate = "2*x*(x^2+3)^2"
        self.practice_problem = candidate
        outcome = (
            "Independent understanding demonstrated on this practice problem; "
            "no in-app coaching was provided. "
            if self.unassisted
            else "Guided completion; independent understanding has not yet been demonstrated. "
        )
        return (
            outcome + "Verified by differentiation. Related unassisted problem: integrate "
            f"{candidate} dx. Start practice when ready; no solution is shown."
        )

    def _assess_practice(self, text):
        if not text.startswith("F="):
            return Feedback(
                "needs_clarification", "Work recorded. Submit your final answer as F=...+C."
            )
        rhs = text[2:].strip()
        value, has_constant = antiderivative(rhs, checker=self.checker)
        if not has_constant:
            return Feedback("incorrect", "Final answer not verified. Try again.")
        if derivative(value) != self.integrand:
            return Feedback("incorrect", "Final answer not verified. Try again.")
        self.complete = True
        return Feedback("confirmed", self._offer_practice(), self.completion_kind)

    def cancel(self):
        self.generation += 1
        self.pending = None

    async def capture_equations(self):
        if self.capture is None or self.recognize is None:
            raise Unsupported("Capture and recognition callbacks are not configured")
        self.cancel()
        generation = self.generation
        images = await self.capture()
        if generation != self.generation:
            return None
        text = await self.recognize(images)
        if generation != self.generation:
            return None
        if not isinstance(text, str) or not text.strip() or len(text) > 512:
            raise Unsupported("Recognition must return one equation, at most 512 characters")
        self.pending = text
        return text

    def confirm_equation(self, edited_text):
        if self.pending is None:
            raise Unsupported("No recognized equation awaits confirmation")
        self.pending = None
        return self.submit(edited_text)

    def submit(self, text):
        if self.integrand is None:
            raise Unsupported("Enter a problem first")
        self.cancel()
        try:
            feedback = self._assess(text.strip())
        except (Unsupported, ValueError, ZeroDivisionError) as exc:
            feedback = Feedback("unsupported", str(exc))
        self.attempts.append(Attempt(text, feedback))
        if feedback.completion_kind is not None and not self._completion_recorded:
            self.completions += (
                CompletionRecord(
                    problem=self.problem,
                    answer=text,
                    kind=feedback.completion_kind,
                    attempts=tuple(self.attempts),
                ),
            )
            self._completion_recorded = True
        self.hint_level = 0
        return feedback

    def _assess(self, text):
        if self.unassisted:
            return self._assess_practice(text)
        parts = text.split("=")
        if len(parts) != 2:
            return Feedback(
                "needs_clarification",
                "Submit one equation: u=..., du=...*dx, I=..., or F=...+C",
            )
        lhs, rhs = (part.strip() for part in parts)
        if not lhs or not rhs:
            return Feedback("needs_clarification", "Enter both sides of the equation.")
        if lhs == "u":
            value = self.checker(rhs, "x")
            if not derivative(value):
                return Feedback(
                    "incorrect",
                    "A constant substitution cannot replace dx. Choose a changing expression.",
                )
            self.substitution = value
            self.differential = self.transformed = self.primitive = None
            self.complete = False
            return Feedback("confirmed", "Substitution recorded. What is du in terms of dx?")
        if self.substitution is None:
            return Feedback("needs_clarification", "First declare u as an expression in x.")
        if lhs == "du":
            if not rhs.endswith("*dx"):
                raise Unsupported("Write du=(derivative)*dx")
            value = self.checker(rhs[:-3], "x")
            if value != derivative(self.substitution):
                return Feedback(
                    "incorrect",
                    "The differential does not match u. Check the power rule and coefficient.",
                )
            self.differential = value
            return Feedback(
                "confirmed",
                "Differential verified. Rewrite the integrand using only u and du: I=...",
            )
        if self.differential is None:
            return Feedback("needs_clarification", "Verify du before changing variables.")
        if lhs == "I":
            value = self.checker(rhs, "u")
            if multiply(compose(value, self.substitution), self.differential) != self.integrand:
                return Feedback(
                    "incorrect",
                    "The rewritten integral changes the original integrand. "
                    "Check the factor from du.",
                )
            self.transformed = value
            self.primitive = None
            self.complete = False
            return Feedback(
                "confirmed", "Change of variables verified. Find an antiderivative: F=...+C"
            )
        if lhs != "F":
            raise Unsupported("Use u, du, I, or F on the left")
        if self.transformed is None:
            return Feedback("needs_clarification", "Rewrite I in u before integrating.")
        variable = "u" if "u" in rhs else "x"
        value, has_constant = antiderivative(rhs, variable, checker=self.checker)
        expected = self.transformed if variable == "u" else self.integrand
        if derivative(value) != expected:
            return Feedback(
                "incorrect",
                "Differentiating this answer does not recover the integrand. "
                "Check the power and coefficient.",
            )
        if not has_constant:
            return Feedback(
                "incorrect", "Include a free additive constant C for this indefinite integral."
            )
        if variable == "u":
            self.primitive = value
            return Feedback(
                "confirmed", "Antiderivative verified. Substitute back to x with F=...+C."
            )
        self.complete = True
        return Feedback("confirmed", self._offer_practice(), self.completion_kind)

    def help(self):
        if self.unassisted:
            return "Unassisted practice: submit your final answer as F=...+C when ready."
        self.hint_level = min(3, self.hint_level + 1)
        if self.substitution is None:
            return "Choose an inner polynomial for u; start by looking at a repeated power."
        if self.differential is None:
            target = "du=" + format_polynomial(derivative(self.substitution)) + "*dx"
            hint = "Differentiate your chosen u with respect to x."
            explanation = "The chain rule requires du=u'(x)*dx; retain every coefficient."
        elif self.transformed is None:
            hint = "Replace the x factors using u and du; check the coefficient multiplying du."
            explanation = "Find P(u) such that P(u(x))*u'(x) equals the original integrand."
            remainder = dict(self.integrand)
            result = {}
            degree = max(self.substitution)
            while remainder:
                power, residue = divmod(max(remainder) - max(self.differential), degree)
                if residue or not 0 <= power <= 32:
                    return "This substitution has no supported polynomial rewrite. Try another u."
                basis = multiply(compose({power: 1}, self.substitution), self.differential)
                coefficient = remainder[max(remainder)] / basis[max(basis)]
                result = add(result, {power: coefficient})
                remainder = add(remainder, multiply({0: -coefficient}, basis))
            target = "I=" + format_polynomial(result, "u")
        else:
            primitive = {p + 1: c / (p + 1) for p, c in self.transformed.items()}
            target = "F=" + format_polynomial(primitive, "u") + "+C"
            hint = "Use the power rule for integration, then substitute back."
            explanation = "Increase each power by one and divide its coefficient by the new power."
            if self.primitive is not None:
                target = "F=" + format_polynomial(compose(self.primitive, self.substitution)) + "+C"
        return (hint, explanation, target)[self.hint_level - 1]

    def check_understanding(self, differential):
        """Transfer check: student independently re-enters u'(x), without dx."""
        if self.unassisted:
            return Feedback("unsupported", "Understanding hints are unavailable during practice.")
        if self.substitution is None:
            return Feedback("unsupported", "Declare u first")
        try:
            correct = self.checker(differential, "x") == derivative(self.substitution)
        except Unsupported as exc:
            return Feedback("unsupported", str(exc))
        return Feedback(
            "confirmed" if correct else "incorrect",
            "Chain-rule factor verified." if correct else "Revisit the derivative of u.",
        )
