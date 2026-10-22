"""Source failure types shared by clients and pipelines."""


class SourceError(Exception):
    """A request failed after bounded retries."""


class SourceDisabled(SourceError):
    """The source rejected our credentials (401/403); no further requests this run."""


class RateLimited(SourceError):
    """The source asked us to wait longer than we are willing to within this run."""


class ResponseTooLarge(SourceError):
    pass
