# models.py
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, Float, DateTime, Index

Base = declarative_base()

class Snapshot(Base):
    __tablename__ = "snapshots"
    id = Column(Integer, primary_key=True)
    symbol = Column(String(16), index=True, nullable=False)
    timeframe = Column(String(8), index=True, nullable=False)
    ts = Column(DateTime(timezone=True), index=True, nullable=False)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)

    __table_args__ = (
        Index("ix_symbol_tf_ts", "symbol", "timeframe", "ts"),
    )
