"""Declarative base class shared by every ORM model."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Root of the ORM model hierarchy; its metadata describes the whole schema."""
