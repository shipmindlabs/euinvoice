"""What a document is: an invoice, or the credit note that corrects one."""

from __future__ import annotations

from enum import Enum

__all__ = ["DocumentKind"]


class DocumentKind(Enum):
    """Whether a document bills a supply or corrects an earlier invoice."""

    INVOICE = "invoice"
    CREDIT_NOTE = "credit-note"
