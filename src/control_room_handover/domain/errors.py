"""Domain errors: the failures the scorecard and handover pipeline raise, in pure stdlib.

None of these carries an SDK type or a framework type: the domain fails on its own terms and a
driving adapter (the API, the CLI, the agent) maps the failure to a transport status. Failing
CLOSED is the rule throughout: an unknown feed, an empty feed set or a narration that will not
validate stops the handover rather than producing a brief on absent or unchecked data.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for every error the control-room domain raises."""


class UnknownFeedError(DomainError):
    """A feed was requested that the registry does not list. Fail closed, never invent one."""


class FeedsEmptyError(DomainError):
    """No feed snapshot was available, so a scorecard would be grounded in nothing."""


class FeedContractError(DomainError):
    """A feed row is missing a required field or carries an out-of-range value (fail closed)."""


class NarrationDiscardedError(DomainError):
    """The model narration failed schema validation or cited a figure the engine never produced.

    The handover service catches this and falls back to the deterministic summary; it is an error
    rather than a silent swap so the discard is testable and can be counted.
    """
