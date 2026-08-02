"""Native AWS Lambda runtime for City Commander Agent.

The package intentionally does not import :mod:`backend.main`; Lambda handlers use
API Gateway HTTP API events directly and share state through AWS services.
"""

__all__ = []
